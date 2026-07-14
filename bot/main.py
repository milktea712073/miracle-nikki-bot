"""Discord entry point for announcements, knowledge lookups, and review UI."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bot.admin.review_commands import register_admin_commands
from bot.admin.checks import is_administrator, is_administrator_channel
from bot.admin.knowledge_event_views import EventAdminView
from bot.admin.knowledge_suit_views import SuitAdminView
from bot.knowledge_formatting import format_cost_line, format_suit_cost_value
from crawler.facebook_crawler import fetch_latest_post, get_latest_posts
from crawler.models import Post
from database.database import announcement_exists, get_connection, insert_announcement, insert_images
from database.knowledge_query_repository import EventView, KnowledgeQueryRepository, SuitView
from database.raw_post_repository import RawPostRepository


LOGGER = logging.getLogger(__name__)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
EVENT_FORM_LABELS = {
    "故事套裝": "故事套裝（大閣）",
    "大閣": "故事套裝（大閣）",
    "婚紗": "婚紗（夢戀奇蹟）",
    "滿天繁星": "滿天繁星",
    "奇妙博物館": "奇妙博物館",
    "童話夢鄉": "童話夢鄉",
    "奇淵之嶼": "奇淵之嶼",
    "凝砂套裝": "凝砂套裝",
    "福袋": "福袋",
    "登入送": "登入送",
    "破曉之戰": "破曉之戰",
    "璀璨華光": "璀璨華光",
}
LARGE_EVENT_FORMS = {
    "故事套裝": "故事套裝（大閣）",
    "大閣": "故事套裝（大閣）",
    "婚紗": "婚紗（夢戀奇蹟）",
    "滿天繁星": "滿天繁星",
    "奇妙博物館": "奇妙博物館",
    "童話夢鄉": "童話夢鄉",
    "破曉之戰": "破曉之戰",
}
PERIOD_RECORD_LABELS = {
    "debut": "首次",
    "rerun": "復刻",
    "wish_gate": "心願之門",
    "return": "回歸",
    "unknown": "活動",
}


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries from a local .env file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

load_dotenv(PROJECT_ROOT / ".env")
def load_channel_ids(env_name: str) -> list[int]:
    return [
        int(channel_id.strip())
        for channel_id in os.getenv(env_name, "").split(",")
        if channel_id.strip()
    ]
    


ANNOUNCEMENT_CHANNEL_IDS = load_channel_ids("ANNOUNCEMENT_CHANNEL_IDS")
QUERY_CHANNEL_IDS = load_channel_ids("QUERY_CHANNEL_IDS")
ADMIN_CHANNEL_IDS = load_channel_ids("ADMIN_CHANNEL_IDS")


def is_query_channel(channel_id: int | None) -> bool:
    """Allow queries only in explicitly configured query or admin channels."""
    allowed_channel_ids = set(QUERY_CHANNEL_IDS) | set(ADMIN_CHANNEL_IDS)
    return channel_id is not None and channel_id in allowed_channel_ids


async def require_query_channel(interaction: discord.Interaction) -> bool:
    """Reject a knowledge query before Discord defers the interaction."""
    if is_query_channel(interaction.channel_id):
        return True
    await interaction.response.send_message(
        "請到指定的查詢頻道使用此指令。", ephemeral=True
    )
    return False


class MiracleNikkiBot(commands.Bot):
    """Discord client that synchronizes its global application commands."""

    async def setup_hook(self) -> None:
        synced_commands = await self.tree.sync()
        LOGGER.info("已同步 %s 個 Slash Commands。", len(synced_commands))


intents = discord.Intents.default()
intents.message_content = True
bot = MiracleNikkiBot(command_prefix="!", intents=intents)


def create_embed(post: dict[str, object]) -> discord.Embed:
    """Create the existing latest-announcement embed."""
    image_urls = post.get("image_urls") or post.get("images") or []
    embed = discord.Embed(
        title="🌸 奇蹟暖暖最新公告",
        description=(
            f"📅 發布時間\n{post.get('publish_time') or '未提供'}\n\n"
            f"📝 公告內容\n{post.get('content', '')}"
        ),
        color=discord.Color.from_rgb(255, 183, 197),
    )
    if image_urls:
        embed.set_image(url=str(image_urls[0]))
    return embed


async def send_post(destination: discord.abc.Messageable, post: dict[str, object]) -> None:
    """Send the latest post and any additional announcement images."""
    image_urls = post.get("image_urls") or post.get("images") or []
    await destination.send(embed=create_embed(post))
    for image_url in image_urls[1:]:
        await destination.send(str(image_url))


async def send_announcement_post(post: dict[str, object]) -> None:
    """Send an automatic announcement only to configured announcement channels."""
    if not ANNOUNCEMENT_CHANNEL_IDS:
        LOGGER.warning("ANNOUNCEMENT_CHANNEL_IDS is not configured; announcement was not sent.")
        return
    for channel_id in ANNOUNCEMENT_CHANNEL_IDS:
        channel = bot.get_channel(channel_id)
        if channel is None:
            LOGGER.warning("Configured announcement channel %s is unavailable.", channel_id)
            continue
        await send_post(channel, post)


def announcement_payload_from_post(post: Post) -> dict[str, object]:
    """Create an announcement payload without inventing a Facebook publication time."""
    return {
        "publish_time": (
            post.published_at.strftime("%Y/%m/%d %H:%M")
            if post.published_at is not None
            else None
        ),
        "content": post.content,
        "image_urls": post.images,
        "post_url": post.url,
    }


def format_date(value: str | None) -> str | None:
    """Format a stored timestamp as a Taiwan-facing calendar date."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(TAIPEI_TIMEZONE)
        return parsed.strftime("%Y/%m/%d")
    except ValueError:
        return value.replace("T", " ")[:10].replace("-", "/")


def truncate(text: str, limit: int = 1024) -> str:
    """Keep embed fields within Discord's field-size limit."""
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def format_activity_records(periods: list[object]) -> list[str]:
    """Render valid availability records from oldest to newest."""
    records: list[str] = []
    seen: set[tuple[str, str]] = set()
    for period in sorted(periods, key=lambda item: str(getattr(item, "start_at", "") or "")):
        date = format_date(getattr(period, "start_at", None))
        if not date:
            continue
        period_type = str(getattr(period, "period_type", "unknown"))
        key = (period_type, date)
        if key in seen:
            continue
        seen.add(key)
        records.append(f"{PERIOD_RECORD_LABELS.get(period_type, '活動')}　{date}")
    return records


def create_event_embed(event: EventView, image_url: str | None = None) -> discord.Embed:
    """Build a concise event card centred on category, dates, and suits."""
    embed = discord.Embed(title=f"🌸 {event.name}", color=discord.Color.from_rgb(255, 183, 197))
    lines: list[str] = []
    if event.event_type:
        lines.append(f"活動分類：{event.event_type}")
    dated_periods = [period for period in event.periods if period.start_at]
    if dated_periods:
        latest = dated_periods[-1]
        start = format_date(latest.start_at) or "未提供"
        end = format_date(latest.end_at) or "未提供"
        lines.append(f"活動期間：{start}～{end}")
    common_method = None
    methods = {suit.acquisition_method for suit in event.suits if suit.acquisition_method}
    if len(methods) == 1:
        common_method = methods.pop()
        lines.append(f"取得方式：{common_method}")
    elif methods:
        lines.append(f"取得方式：{'、'.join(sorted(str(method) for method in methods))}")
    appearance_icons = {"debut": "🆕", "rerun": "🔁", "return": "↩️", "unknown": ""}
    suit_lines = [f"{appearance_icons.get(suit.appearance_status, '')} {suit.name}".strip() for suit in event.suits]
    if suit_lines:
        lines.append(f"套裝：{'、'.join(suit_lines)}")
    if event.event_total_cost:
        lines.append(f"全收花費：{event.event_total_cost}")
    if event.description:
        lines.append(f"備註：{event.description}")
    embed.description = truncate("\n".join(lines), 4096) if lines else None
    if image_url:
        embed.set_image(url=image_url)
    return embed


def create_suit_embed(
    suit: SuitView, image_url: str | None = None, *, show_missing_category: bool = False
) -> discord.Embed:
    """Build a compact suit card from its latest event relation."""
    embed = discord.Embed(title=f"👗 {suit.name}", color=discord.Color.from_rgb(255, 183, 197))
    lines = ["✨ Live2D"] if suit.is_live2d else []
    if suit.events:
        event = suit.events[0]
        lines.append(f"📚 所屬活動：{event.event_name}")
        if event.event_type:
            lines.append(f"🏷️ 活動分類：{event.event_type}")
        elif show_missing_category:
            lines.append("🏷️ 活動分類：尚未設定")
        dated = [period for period in event.periods if period.start_at]
        if dated:
            latest = dated[-1]
            start = format_date(latest.start_at) or "未提供"
            end = format_date(latest.end_at) or "未提供"
            lines.append(f"📅 活動期間：{start}～{end}")
        cost_value = format_suit_cost_value(event.acquisition_method, event.cost_text)
        if cost_value:
            lines.append(f"💎 花費：{cost_value}")
    embed.description = truncate("\n".join(lines), 4096) if lines else None
    if image_url:
        embed.set_image(url=image_url)
    return embed


def create_suit_response_view(suit_id: int, is_admin: bool) -> SuitAdminView | None:
    """Only attach the management controls to an administrator's suit response."""
    return SuitAdminView(suit_id) if is_admin else None


def create_event_response_view(
    event_id: int, event_name: str, is_admin: bool
) -> EventAdminView | None:
    """Only attach event management controls to an administrator response."""
    return EventAdminView(event_id, event_name) if is_admin else None


def add_auto_status_notice(embed: discord.Embed, data_status: str, is_admin: bool) -> None:
    """Show provenance only to administrators; players see the normal card."""
    if is_admin and data_status == "auto":
        embed.set_footer(text="自動建立，尚未確認")


async def event_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    try:
        names = await asyncio.to_thread(KnowledgeQueryRepository().search_event_names, current)
    except Exception:
        LOGGER.exception("讀取活動名稱提示失敗。")
        return []
    return [app_commands.Choice(name=name, value=name) for name in names]


async def suit_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    try:
        names = await asyncio.to_thread(KnowledgeQueryRepository().search_suit_names, current)
    except Exception:
        LOGGER.exception("讀取套裝名稱提示失敗。")
        return []
    return [app_commands.Choice(name=name, value=name) for name in names]


@bot.tree.command(name="活動", description="查詢已確認匯入的活動資料")
@app_commands.rename(name="名稱")
@app_commands.describe(name="活動名稱")
@app_commands.autocomplete(name=event_name_autocomplete)
async def event_command(interaction: discord.Interaction, name: str) -> None:
    if not await require_query_channel(interaction):
        return
    await interaction.response.defer(thinking=True)
    repository = KnowledgeQueryRepository()
    try:
        event = await asyncio.to_thread(repository.get_event_by_name, name)
        image_url = await asyncio.to_thread(repository.get_announcement_image_for_event, name)
    except Exception:
        LOGGER.exception("查詢活動失敗：%s", name)
        await interaction.followup.send("查詢活動時發生錯誤，請稍後再試。", ephemeral=True)
        return
    if event is None:
        await interaction.followup.send(f"找不到已匯入的活動「{name}」。", ephemeral=True)
        return
    can_manage = is_administrator(interaction) and is_administrator_channel(interaction.channel_id)
    view = create_event_response_view(event.id, event.name, can_manage)
    embed = create_event_embed(event, image_url)
    add_auto_status_notice(embed, event.data_status, can_manage)
    if view is None:
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="套裝", description="查詢已確認匯入的套裝資料")
@app_commands.rename(name="名稱")
@app_commands.describe(name="套裝名稱")
@app_commands.autocomplete(name=suit_name_autocomplete)
async def suit_command(interaction: discord.Interaction, name: str) -> None:
    if not await require_query_channel(interaction):
        return
    await interaction.response.defer(thinking=True)
    repository = KnowledgeQueryRepository()
    try:
        suit = await asyncio.to_thread(repository.get_suit_by_name, name)
    except Exception:
        LOGGER.exception("查詢套裝失敗：%s", name)
        await interaction.followup.send("查詢套裝時發生錯誤，請稍後再試。", ephemeral=True)
        return
    if suit is None:
        await interaction.followup.send(f"找不到已匯入的套裝「{name}」。", ephemeral=True)
        return
    image_url = await asyncio.to_thread(repository.get_display_image_for_suit, suit.id)
    can_manage = is_administrator(interaction) and is_administrator_channel(interaction.channel_id)
    view = create_suit_response_view(suit.id, can_manage)
    embed = create_suit_embed(
        suit, image_url, show_missing_category=can_manage
    )
    add_auto_status_notice(embed, suit.data_status, can_manage)
    if view is None:
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(embed=embed, view=view)


@bot.event
async def on_ready() -> None:
    LOGGER.info("%s 已登入 Discord。", bot.user)
    if not check_new_post.is_running():
        check_new_post.start()


@tasks.loop(minutes=5)
async def check_new_post() -> None:
    """Keep the existing scheduled latest-post notification behavior."""
    latest_posts = await asyncio.to_thread(get_latest_posts, 1)
    post_model = latest_posts[0]
    await asyncio.to_thread(RawPostRepository().save_raw_post, post_model)
    post = announcement_payload_from_post(post_model)
    connection = get_connection()
    try:
        if announcement_exists(connection, str(post["post_url"])):
            return
        announcement_id = insert_announcement(
            connection,
            str(post["publish_time"] or ""),
            str(post["content"]),
            str(post["post_url"]),
        )
        image_urls = post.get("image_urls") or post.get("images") or []
        insert_images(connection, announcement_id, [str(url) for url in image_urls])
        await send_announcement_post(post)
    finally:
        connection.close()


@bot.command(name="latest")
async def latest(ctx: commands.Context[MiracleNikkiBot]) -> None:
    post = await asyncio.to_thread(fetch_latest_post)
    await send_post(ctx, post)


register_admin_commands(bot)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(".env 缺少 DISCORD_TOKEN。")
    bot.run(token)


if __name__ == "__main__":
    main()
