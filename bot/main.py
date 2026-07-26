"""Discord entry point for the active v2 shell and retained legacy code.

The Facebook polling, Knowledge query callbacks, and administration views below
are intentionally retained for historical recovery only. They are not
registered or scheduled by the normal bot startup path.
"""

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

from announcement.dispatcher import dispatch_delivery
from announcement.history_search import AnnouncementHistorySearchService
from announcement.models import Announcement, CN_OFFICIAL, TW_OFFICIAL
from announcement.search import keyword_search_variants
from announcement.state_store import AnnouncementStateStore
from bot.admin.checks import is_administrator, is_administrator_channel
from bot.ambient_nikki import AmbientNikkiService, AmbientNikkiSettings
from bot.ambient_nikki.service import display_target
from bot.announcement_search_view import (
    AnnouncementSearchResultView,
    build_announcement_message_payloads,
    send_announcement_payloads,
)
from bot.admin.knowledge_event_views import EventAdminView
from bot.admin.knowledge_suit_views import SuitAdminView
from bot.knowledge_formatting import format_cost_line, format_suit_cost_value
from crawler.facebook_crawler import get_latest_posts
from crawler.models import Post
from crawler.cn_official_crawler import fetch_recent_announcements as fetch_cn_official_announcements
from crawler.tw_official_crawler import fetch_recent_announcements as fetch_tw_official_announcements
from database.announcement_job_repository import AnnouncementJob, AnnouncementJobRepository
from database.knowledge_query_repository import EventView, KnowledgeQueryRepository, SuitView
from scripts.data.fetch_raw_posts import fetch_and_save_raw_posts
from bot.presence import start_presence_rotation

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


def load_optional_snowflake(env_name: str) -> int | None:
    """Return an optional Discord snowflake configured in the environment."""
    value = os.getenv(env_name, "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    raise RuntimeError(f"{env_name} must be a Discord snowflake or left empty.")


def load_boolean(env_name: str, default: bool) -> bool:
    """Read a conventional boolean environment value with a compatible default."""
    value = os.getenv(env_name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{env_name} must be true or false when configured.")


def load_bounded_integer(env_name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an integer environment value while preserving Discord API limits."""
    value = os.getenv(env_name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise RuntimeError(f"{env_name} must be an integer.") from error
    if not minimum <= parsed <= maximum:
        raise RuntimeError(f"{env_name} must be between {minimum} and {maximum}.")
    return parsed



ANNOUNCEMENT_CHANNEL_IDS = load_channel_ids("ANNOUNCEMENT_CHANNEL_IDS")
TW_ANNOUNCEMENT_CHANNEL_IDS = load_channel_ids("TW_ANNOUNCEMENT_CHANNEL_IDS") or ANNOUNCEMENT_CHANNEL_IDS
TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS = (
    load_channel_ids("TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS") or TW_ANNOUNCEMENT_CHANNEL_IDS
)
CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS = load_channel_ids("CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS")
QUERY_CHANNEL_IDS = load_channel_ids("QUERY_CHANNEL_IDS")
ADMIN_CHANNEL_IDS = load_channel_ids("ADMIN_CHANNEL_IDS")
APP_ENV = os.getenv("APP_ENV", "production").strip() or "production"
GUILD_ID = load_optional_snowflake("GUILD_ID")
DISCORD_COMMAND_PREFIX = os.getenv("DISCORD_COMMAND_PREFIX", "!") or "!"
DISCORD_MESSAGE_CONTENT_INTENT = load_boolean("DISCORD_MESSAGE_CONTENT_INTENT", default=True)
ENABLE_ANNOUNCEMENT_PIPELINE = load_boolean("ENABLE_ANNOUNCEMENT_PIPELINE", default=True)
AMBIENT_NIKKI_SETTINGS = AmbientNikkiSettings.from_environment()
AMBIENT_NIKKI_SERVICE = AmbientNikkiService(AMBIENT_NIKKI_SETTINGS)

MAX_AUTO_ANNOUNCEMENTS_PER_CYCLE = 3
FACEBOOK_POLL_INTERVAL_MINUTES = 5
FACEBOOK_POLL_LIMIT = 10
OFFICIAL_POLL_INTERVAL_MINUTES = 5
OFFICIAL_POLL_LIMIT = 20
DISCORD_EMBEDS_PER_MESSAGE = load_bounded_integer(
    "DISCORD_EMBEDS_PER_MESSAGE", default=10, minimum=1, maximum=10
)
ANNOUNCEMENT_SEARCH_SOURCES = {
    "all": None,
    "tw": TW_OFFICIAL,
    "cn": CN_OFFICIAL,
}
facebook_initial_poll_complete = asyncio.Event()
tw_initial_poll_complete = asyncio.Event()
official_initial_poll_complete = asyncio.Event()
v2_delivery_recovered = False


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
    """Discord client that synchronizes globally or to the configured development guild."""

    async def setup_hook(self) -> None:
        if ENABLE_ANNOUNCEMENT_PIPELINE:
            await asyncio.to_thread(AnnouncementStateStore)
            LOGGER.info("v2 announcement state initialized with WAL and a 30-second busy timeout.")
        else:
            LOGGER.info("[%s] Announcement Pipeline is disabled by ENABLE_ANNOUNCEMENT_PIPELINE.", APP_ENV)
        if GUILD_ID is None:
            synced_commands = await self.tree.sync()
            LOGGER.info("[%s] 已全域同步 %s 個 Slash Commands。", APP_ENV, len(synced_commands))
            return

        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced_commands = await self.tree.sync(guild=guild)
        LOGGER.info(
            "[%s] 已同步 %s 個 Slash Commands 至 Guild %s。",
            APP_ENV,
            len(synced_commands),
            GUILD_ID,
        )


intents = discord.Intents.default()
intents.message_content = DISCORD_MESSAGE_CONTENT_INTENT
bot = MiracleNikkiBot(command_prefix=DISCORD_COMMAND_PREFIX, intents=intents)
ambient_nikki_message_lock = asyncio.Lock()


def create_embed(post: dict[str, object]) -> discord.Embed:
    """Create the existing latest-announcement embed."""
    image_urls = post.get("image_urls") or post.get("images") or []
    lines = [f"📝 公告內容\n{post.get('content', '')}"]
    if post.get("publish_time"):
        lines.append(f"📅 發布時間：{post['publish_time']}")
    if post.get("post_url"):
        lines.append(f"🔗 [原文連結]({post['post_url']})")
    embed = discord.Embed(
        title=str(post.get("title") or "🌸 奇蹟暖暖最新公告"),
        description="\n\n".join(lines),
        color=discord.Color.from_rgb(255, 183, 197),
    )
    if image_urls:
        embed.set_image(url=str(image_urls[0]))
    return embed


def announcement_embed_batches(post: dict[str, object]) -> list[list[discord.Embed]]:
    """Keep the main card separate and batch remaining images per message."""
    image_urls = [
        image_url
        for image_url in (post.get("image_urls") or post.get("images") or [])
        if isinstance(image_url, str) and image_url
    ]
    main_embed = create_embed({**post, "image_urls": image_urls})
    remaining_embeds: list[discord.Embed] = []
    for image_url in image_urls[1:]:
        image_embed = discord.Embed(color=discord.Color.from_rgb(255, 183, 197))
        image_embed.set_image(url=image_url)
        remaining_embeds.append(image_embed)
    batches = [[main_embed]]
    batches.extend(
        remaining_embeds[index : index + DISCORD_EMBEDS_PER_MESSAGE]
        for index in range(0, len(remaining_embeds), DISCORD_EMBEDS_PER_MESSAGE)
    )
    return batches


async def send_post(destination: discord.abc.Messageable, post: dict[str, object]) -> list[int | str]:
    """Send one announcement as ordered embed batches, including every image."""
    message_ids: list[int | str] = []
    for embeds in announcement_embed_batches(post):
        message = await destination.send(embeds=embeds)
        message_id = getattr(message, "id", None)
        if message_id is not None:
            message_ids.append(message_id)
    return message_ids


async def resolve_announcement_channel(channel_id: int) -> discord.abc.Messageable:
    """Resolve one configured announcement destination without exposing credentials."""
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException as error:
            raise RuntimeError(f"Configured announcement channel {channel_id} is unavailable") from error
    if not hasattr(channel, "send"):
        raise RuntimeError(f"Configured announcement channel {channel_id} is not messageable")
    return channel


async def send_announcement_post(post: dict[str, object]) -> None:
    """Send an automatic announcement only to configured announcement channels."""
    if not ANNOUNCEMENT_CHANNEL_IDS:
        raise RuntimeError("ANNOUNCEMENT_CHANNEL_IDS is not configured")
    for channel_id in ANNOUNCEMENT_CHANNEL_IDS:
        channel = await resolve_announcement_channel(channel_id)
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


def announcement_payload_from_job(job: AnnouncementJob) -> dict[str, object]:
    """Build the existing announcement card payload from durable raw storage."""
    publish_time = None
    if job.published_at:
        try:
            publish_time = datetime.fromisoformat(job.published_at).strftime("%Y/%m/%d %H:%M")
        except ValueError:
            publish_time = job.published_at
    return {
        "publish_time": publish_time,
        "content": job.content,
        "image_urls": job.images,
        "post_url": job.post_url,
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
    if event.entity_type == "series":
        lines: list[str] = []
        if event.event_type:
            lines.append(f"📚 分類：{event.event_type}")
        if event.event_total_cost:
            lines.append(f"💎 花費：{event.event_total_cost} 鑽")
        labels = {"main": "👑 主套", "minor": "🎀 小套", "live2d": "✨ Live2D"}
        for content_type in ("main", "minor", "live2d"):
            names = [suit.name for suit in event.suits if suit.content_type == content_type]
            if names:
                lines.append(f"{labels[content_type]}：\n" + "\n".join(names))
        if image_url:
            lines.append("🖼️ 圖片")
        if event.series_periods:
            lines.append("📅 檔期：\n" + "\n".join(event.series_periods))
        if event.description:
            lines.append(f"📝 備註：{event.description}")
        embed.description = truncate("\n".join(lines), 4096) if lines else None
        return embed
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
    series_events = [event for event in suit.events if event.series_name]
    regular_events = [event for event in suit.events if not event.series_name]
    if series_events:
        series_names = list(dict.fromkeys(event.series_name for event in series_events if event.series_name))
        lines.append(f"🏛️ 所屬系列：{'、'.join(series_names)}")
        category = next((event.event_type for event in series_events if event.event_type), None)
        if category:
            lines.append(f"🏷️ 活動分類：{category}")
        elif show_missing_category:
            lines.append("🏷️ 活動分類：尚未設定")
    if regular_events:
        event = regular_events[0]
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
    event_id: int, event_name: str, is_admin: bool, *, entity_type: str = "event"
) -> EventAdminView | None:
    """Only attach event management controls to an administrator response."""
    return EventAdminView(event_id, event_name, entity_type=entity_type) if is_admin else None


async def event_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    try:
        options = await asyncio.to_thread(
            KnowledgeQueryRepository().search_activity_options, current
        )
    except Exception:
        LOGGER.exception("讀取活動名稱提示失敗。")
        return []
    return [
        app_commands.Choice(
            name=truncate(f"{name}（{format_date(start_at) or '日期未提供'}）", 100),
            value=str(event_id),
        )
        for event_id, name, start_at in options
    ]


async def suit_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    try:
        names = await asyncio.to_thread(KnowledgeQueryRepository().search_suit_names, current)
    except Exception:
        LOGGER.exception("讀取套裝名稱提示失敗。")
        return []
    return [app_commands.Choice(name=name, value=name) for name in names]


@bot.tree.command(name="公告搜尋", description="搜尋已保存的台服與陸服官方公告")
@app_commands.rename(keyword="關鍵字", source="公告來源")
@app_commands.describe(keyword="搜尋公告標題與正文", source="選擇全部、台服或陸服公告")
@app_commands.choices(
    source=[
        app_commands.Choice(name="全部", value="all"),
        app_commands.Choice(name="台服", value="tw"),
        app_commands.Choice(name="陸服", value="cn"),
    ]
)
async def announcement_search_command(
    interaction: discord.Interaction,
    keyword: str,
    source: str = "all",
) -> None:
    """Search persisted official notices without invoking the announcement pipeline."""
    try:
        await interaction.response.defer(thinking=True)
    except Exception:
        LOGGER.exception("Unable to acknowledge announcement search interaction.")
        return
    if not is_query_channel(interaction.channel_id):
        await interaction.followup.send("請到指定的查詢頻道使用此指令。", ephemeral=True)
        return
    normalized_keyword = keyword.strip()
    if not normalized_keyword:
        await interaction.followup.send("請輸入公告搜尋關鍵字。", ephemeral=True)
        return
    source_filter = ANNOUNCEMENT_SEARCH_SOURCES.get(source)
    if source not in ANNOUNCEMENT_SEARCH_SOURCES:
        await interaction.followup.send("請選擇有效的公告伺服器篩選條件。", ephemeral=True)
        return

    try:
        search_page = await asyncio.to_thread(
            AnnouncementHistorySearchService().search,
            normalized_keyword,
            source=source_filter,
            limit=None,
        )
    except Exception:
        LOGGER.exception("公告搜尋失敗 keyword=%r source=%r", normalized_keyword, source)
        await interaction.followup.send("公告搜尋時發生錯誤，請稍後再試。", ephemeral=True)
        return

    if not search_page.results:
        await interaction.followup.send(
            f"找不到包含「{normalized_keyword}」的公告。",
            ephemeral=True,
        )
        return
    highlight_terms = keyword_search_variants(normalized_keyword)
    if len(search_page.results) == 1:
        result = search_page.results[0]
        try:
            payloads = build_announcement_message_payloads(
                result,
                owner_user_id=interaction.user.id,
                highlight_terms=highlight_terms,
            )
            await send_announcement_payloads(interaction, payloads, ephemeral=False)
        except Exception:
            LOGGER.exception(
                "Announcement-search single-result rendering failed keyword=%r source_filter=%r "
                "source_kind=%s notice_source=%s external_id=%s record_id=%s",
                normalized_keyword,
                source,
                result.source_kind,
                result.source,
                result.external_id,
                result.source_record_id,
            )
            try:
                await interaction.followup.send("公告搜尋結果呈現失敗，請稍後再試。", ephemeral=True)
            except Exception:
                LOGGER.exception("Unable to report announcement-search rendering failure.")
        return

    view = AnnouncementSearchResultView(
        results=search_page.results,
        owner_user_id=interaction.user.id,
        keyword=normalized_keyword,
        source_filter=source,
        highlight_terms=highlight_terms,
    )
    try:
        message = await interaction.followup.send(
            embed=view.embed(),
            view=view,
            wait=True,
        )
        view.message = message
    except Exception:
        LOGGER.exception(
            "Announcement-search result-list rendering failed keyword=%r source_filter=%r result_count=%d",
            normalized_keyword,
            source,
            len(search_page.results),
        )
        try:
            await interaction.followup.send("公告搜尋結果呈現失敗，請稍後再試。", ephemeral=True)
        except Exception:
            LOGGER.exception("Unable to report announcement-search result-list rendering failure.")


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
        if name.isdecimal() or name.startswith("series:"):
            event = await asyncio.to_thread(repository.get_activity_by_reference, name)
        else:
            matches = await asyncio.to_thread(repository.get_activities_by_name, name)
            if len(matches) > 1:
                await interaction.followup.send(
                    "找到多筆同名活動，請從自動完成選擇指定檔期。",
                    ephemeral=True,
                )
                return
            event = matches[0] if matches else None
        image_url = await asyncio.to_thread(repository.get_announcement_image_for_event_id, event.id) if event else None
    except Exception:
        LOGGER.exception("查詢活動失敗：%s", name)
        await interaction.followup.send("查詢活動時發生錯誤，請稍後再試。", ephemeral=True)
        return
    if event is None:
        await interaction.followup.send(f"找不到已匯入的活動「{name}」。", ephemeral=True)
        return
    can_manage = is_administrator(interaction) and is_administrator_channel(interaction.channel_id)
    view = create_event_response_view(
        event.id, event.name, can_manage, entity_type=event.entity_type
    )
    embed = create_event_embed(event, image_url)
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
    if view is None:
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(embed=embed, view=view)


# Keep the legacy callback objects available for future restoration, but do not
# register Knowledge commands in the v2 application command tree.
bot.tree.remove_command("活動")
bot.tree.remove_command("套裝")


async def handle_ambient_nikki_message(message: discord.Message) -> None:
    """Occasionally cast a cosmetic skill without interpreting player content."""
    service = AMBIENT_NIKKI_SERVICE
    author = getattr(message, "author", None)
    guild = getattr(message, "guild", None)
    channel = getattr(message, "channel", None)
    if author is None or guild is None or channel is None:
        return
    message_type = getattr(message, "type", discord.MessageType.default)
    message_type_name = getattr(message_type, "name", str(message_type))
    author_is_bot = bool(getattr(author, "bot", False))
    is_webhook = getattr(message, "webhook_id", None) is not None
    is_system = bool(getattr(message, "is_system", lambda: False)())
    LOGGER.debug(
        "ambient_nikki received: author_bot=%s webhook_id=%s guild_id=%s channel_id=%s "
        "message_type=%s enabled=%s allowed_channel_ids=%s",
        author_is_bot,
        is_webhook,
        getattr(guild, "id", None),
        getattr(channel, "id", None),
        message_type_name,
        service.settings.enabled,
        sorted(service.settings.channel_ids),
    )
    if message_type != discord.MessageType.default:
        LOGGER.debug("Ambient Nikki skipped: message_type")
        return
    skip_reason = service.skip_reason(
        guild_id=getattr(guild, "id", None),
        channel_id=getattr(channel, "id", None),
        author_is_bot=author_is_bot,
        is_webhook=is_webhook,
        is_system=is_system,
    )
    if skip_reason is not None:
        LOGGER.debug("Ambient Nikki skipped: %s", skip_reason)
        return

    async with ambient_nikki_message_lock:
        now = datetime.now(TAIPEI_TIMEZONE)
        response, skip_reason = service.decide(
            guild_id=guild.id,
            channel_id=channel.id,
            target=display_target(author),
            now=now,
        )
        if response is None:
            LOGGER.debug("Ambient Nikki skipped: %s", skip_reason)
            return
        try:
<<<<<<< Updated upstream
            await message.reply(f"🌸 小暖：{response.line}", mention_author=False)
=======
            await message.reply(
                response.text,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
>>>>>>> Stashed changes
        except discord.DiscordException:
            LOGGER.exception("Ambient Nikki reply failed; cooldown and daily count were not recorded.")
            return
        service.record_success(guild_id=guild.id, now=now)
        LOGGER.debug("Ambient Nikki event sent.")


@bot.event
async def on_message(message: discord.Message) -> None:
    """Run optional ambient replies while preserving Prefix Command dispatch."""
    try:
        await handle_ambient_nikki_message(message)
    except Exception:
        LOGGER.exception("Ambient Nikki message handling failed.")
    await bot.process_commands(message)


@bot.event
async def on_ready() -> None:
    start_presence_rotation(bot)
    LOGGER.info("%s 已登入 Discord。", bot.user)
    settings = AMBIENT_NIKKI_SERVICE.settings
    LOGGER.info(
        "Ambient Nikki config: enabled=%s trigger_rate=%s sleep_trigger_rate=%s cooldown_minutes=%s channel_ids=%s",
        settings.enabled,
        settings.trigger_rate,
        settings.sleep_trigger_rate,
        settings.cooldown_minutes,
        sorted(settings.channel_ids),
    )
    if not ENABLE_ANNOUNCEMENT_PIPELINE:
        LOGGER.info("[%s] Official announcement polling and delivery are disabled.", APP_ENV)
        return
    if not poll_official_announcements.is_running():
        poll_official_announcements.start()
    if not process_v2_announcement_deliveries.is_running():
        process_v2_announcement_deliveries.start()


@tasks.loop(minutes=OFFICIAL_POLL_INTERVAL_MINUTES)
async def poll_official_announcements() -> None:
    """Poll official Taiwan and China sources into v2 state, without legacy storage."""
    if not ENABLE_ANNOUNCEMENT_PIPELINE:
        LOGGER.info("Official announcement poll skipped because the pipeline is disabled.")
        official_initial_poll_complete.set()
        return
    state = AnnouncementStateStore()
    sources = (
        ("TW official", TW_OFFICIAL, fetch_tw_official_announcements, TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS),
        ("CN official", CN_OFFICIAL, fetch_cn_official_announcements, CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS),
    )
    try:
        for label, source, crawler, channel_ids in sources:
            if not channel_ids:
                LOGGER.warning("%s announcement channels are not configured; source poll skipped.", label)
                continue
            try:
                announcements = await asyncio.to_thread(crawler, OFFICIAL_POLL_LIMIT)
                baseline = await asyncio.to_thread(state.get_official_baseline, source)
                if baseline is None:
                    LOGGER.warning(
                        "%s baseline is not initialized; no announcements were queued. "
                        "Run initialize_official_baseline.py first.",
                        label,
                    )
                    continue
                new_announcements = _announcements_before_official_baseline(announcements, baseline)
                if new_announcements is None:
                    LOGGER.warning(
                        "%s baseline was not found in the fetched official list; "
                        "no announcements were queued and the baseline was left unchanged "
                        "source=%s baseline=%s fetched=%s",
                        label,
                        source,
                        baseline,
                        len(announcements),
                    )
                    continue
                for announcement in reversed(new_announcements):
                    await asyncio.to_thread(state.register, announcement, channel_ids)
                if new_announcements:
                    await asyncio.to_thread(
                        state.set_official_baseline,
                        source,
                        announcements[0].external_id,
                    )
                LOGGER.info(
                    "%s poll completed fetched=%s queued=%s baseline=%s",
                    label, len(announcements), len(new_announcements), baseline,
                )
            except Exception:
                LOGGER.exception("%s poll failed; other official sources remain available.", label)
    finally:
        official_initial_poll_complete.set()


def _announcements_before_official_baseline(
    announcements: list[Announcement],
    baseline_external_id: str,
) -> list[Announcement] | None:
    """Return latest-first notices before a source-list baseline anchor.

    Official article IDs are identifiers, not a reliable chronological sequence.
    Returning ``None`` distinguishes a missing anchor from a valid empty update
    and lets the caller fail closed without advancing the baseline.
    """
    for index, announcement in enumerate(announcements):
        if announcement.external_id == baseline_external_id:
            return announcements[:index]
    return None


@tasks.loop(minutes=FACEBOOK_POLL_INTERVAL_MINUTES)
async def poll_tw_announcements() -> None:
    """DEPRECATED: retained Facebook-to-v2-state poller; never auto-scheduled."""
    if not TW_ANNOUNCEMENT_CHANNEL_IDS:
        LOGGER.error("TW_ANNOUNCEMENT_CHANNEL_IDS or ANNOUNCEMENT_CHANNEL_IDS is not configured.")
        tw_initial_poll_complete.set()
        return
    try:
        posts = await asyncio.to_thread(get_latest_posts, FACEBOOK_POLL_LIMIT)
        state = AnnouncementStateStore()
        for post in posts:
            state.register(Announcement.from_facebook_post(post), TW_ANNOUNCEMENT_CHANNEL_IDS)
        LOGGER.info("v2 Taiwan Facebook poll completed fetched=%s", len(posts))
        if len(posts) < FACEBOOK_POLL_LIMIT:
            LOGGER.warning(
                "Facebook exposed %s post(s), fewer than poll limit %s.",
                len(posts),
                FACEBOOK_POLL_LIMIT,
            )
    except Exception:
        LOGGER.exception("v2 Taiwan Facebook poll failed; pending v2 deliveries remain retryable.")
    finally:
        tw_initial_poll_complete.set()


@tasks.loop(minutes=1)
async def process_v2_announcement_deliveries() -> None:
    """Deliver only persisted official-site announcements through the existing dispatcher."""
    global v2_delivery_recovered
    if not ENABLE_ANNOUNCEMENT_PIPELINE:
        LOGGER.info("Official announcement delivery skipped because the pipeline is disabled.")
        return
    await official_initial_poll_complete.wait()
    state = AnnouncementStateStore()
    if not v2_delivery_recovered:
        recovered = await asyncio.to_thread(state.recover_interrupted_deliveries)
        if recovered:
            LOGGER.warning("Recovered %s interrupted v2 announcement delivery(s).", recovered)
        v2_delivery_recovered = True
    delivery_limit = MAX_AUTO_ANNOUNCEMENTS_PER_CYCLE * max(
        1, len(TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS) + len(CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS)
    )
    deliveries = await asyncio.to_thread(
        state.claim_deliveries, delivery_limit, sources=(TW_OFFICIAL, CN_OFFICIAL)
    )
    for delivery in deliveries:
        try:
            message_ids = await dispatch_delivery(delivery, resolve_announcement_channel, send_post)
            await asyncio.to_thread(state.mark_delivery_sent, delivery.delivery_id, message_ids)
            LOGGER.info(
                "v2 announcement delivery sent source=%s external_id=%s channel=%s",
                delivery.announcement.source,
                delivery.announcement.external_id,
                delivery.channel_id,
            )
        except Exception as error:
            await asyncio.to_thread(state.mark_delivery_failed, delivery.delivery_id, str(error))
            LOGGER.exception(
                "v2 announcement delivery failed source=%s external_id=%s channel=%s",
                delivery.announcement.source,
                delivery.announcement.external_id,
                delivery.channel_id,
            )


@tasks.loop(minutes=FACEBOOK_POLL_INTERVAL_MINUTES)
async def poll_facebook_posts() -> None:
    """DEPRECATED: retained Facebook raw-archive poller; never auto-scheduled."""
    try:
        result = await asyncio.to_thread(
            fetch_and_save_raw_posts,
            FACEBOOK_POLL_LIMIT,
            enqueue_announcements=True,
        )
        storage = result.storage
        LOGGER.info(
            "Facebook poll completed fetched=%s inserted=%s updated=%s unchanged=%s failed=%s",
            result.fetched_count,
            storage.inserted,
            storage.updated,
            storage.unchanged,
            storage.failed,
        )
        if result.fetched_count < FACEBOOK_POLL_LIMIT:
            LOGGER.warning(
                "Facebook exposed %s post(s), fewer than poll limit %s.",
                result.fetched_count,
                FACEBOOK_POLL_LIMIT,
            )
    except Exception:
        LOGGER.exception("Facebook poll failed; the announcement queue will continue running.")
    finally:
        facebook_initial_poll_complete.set()


@tasks.loop(minutes=5)
async def process_announcement_queue() -> None:
    """DEPRECATED: retained legacy Queue worker; never auto-scheduled."""
    if poll_facebook_posts.is_running():
        await facebook_initial_poll_complete.wait()
    repository = AnnouncementJobRepository()
    recovered = await asyncio.to_thread(repository.recover_interrupted_jobs)
    if recovered:
        LOGGER.warning("Recovered %s interrupted announcement job(s).", recovered)
    jobs = await asyncio.to_thread(repository.claim_jobs, MAX_AUTO_ANNOUNCEMENTS_PER_CYCLE)
    if not jobs:
        LOGGER.info("Announcement queue has no pending jobs.")
        return
    for job in jobs:
        try:
            await send_announcement_post(announcement_payload_from_job(job))
            await asyncio.to_thread(repository.mark_sent, job.id)
            LOGGER.info("Announcement job %s sent for %s", job.id, job.post_url)
        except Exception as error:
            await asyncio.to_thread(repository.mark_failed, job.id, str(error))
            LOGGER.exception("Announcement job %s failed for %s", job.id, job.post_url)


# Compatibility alias for existing scheduler tests and local integrations.
check_new_post = process_announcement_queue


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(".env 缺少 DISCORD_TOKEN。")
    bot.run(token)


if __name__ == "__main__":
    main()
