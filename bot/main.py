"""Discord entry point for official announcements and historical notice search."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
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
from bot.announcement_search_view import (
    AnnouncementSearchResultView,
    build_announcement_message_payloads,
    send_announcement_payloads,
)
from crawler.cn_official_crawler import fetch_recent_announcements as fetch_cn_official_announcements
from crawler.tw_official_crawler import fetch_recent_announcements as fetch_tw_official_announcements
from bot.presence import start_presence_rotation

LOGGER = logging.getLogger(__name__)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")


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



TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS = load_channel_ids("TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS")
CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS = load_channel_ids("CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS")
QUERY_CHANNEL_IDS = load_channel_ids("QUERY_CHANNEL_IDS")
ADMIN_CHANNEL_IDS = load_channel_ids("ADMIN_CHANNEL_IDS")
APP_ENV = os.getenv("APP_ENV", "production").strip() or "production"
GUILD_ID = load_optional_snowflake("GUILD_ID")
DISCORD_COMMAND_PREFIX = os.getenv("DISCORD_COMMAND_PREFIX", "!") or "!"
DISCORD_MESSAGE_CONTENT_INTENT = load_boolean("DISCORD_MESSAGE_CONTENT_INTENT", default=True)
ENABLE_ANNOUNCEMENT_PIPELINE = load_boolean("ENABLE_ANNOUNCEMENT_PIPELINE", default=True)

MAX_AUTO_ANNOUNCEMENTS_PER_CYCLE = 3
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
official_initial_poll_complete = asyncio.Event()
v2_delivery_recovered = False


def is_query_channel(channel_id: int | None) -> bool:
    """Allow queries only in explicitly configured query or admin channels."""
    allowed_channel_ids = set(QUERY_CHANNEL_IDS) | set(ADMIN_CHANNEL_IDS)
    return channel_id is not None and channel_id in allowed_channel_ids


async def require_query_channel(interaction: discord.Interaction) -> bool:
    """Reject an announcement search outside configured query channels."""
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


@bot.event
async def on_ready() -> None:
    start_presence_rotation(bot)
    LOGGER.info("%s 已登入 Discord。", bot.user)
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
                seen_initialized = await asyncio.to_thread(
                    state.has_official_seen_announcements,
                    source,
                )
                if not seen_initialized:
                    LOGGER.warning(
                        "%s seen state is not initialized; no announcements were queued. "
                        "Run initialize_official_baseline.py first.",
                        label,
                    )
                    continue
                queued = 0
                for announcement in _official_announcements_oldest_first(announcements):
                    registered = await asyncio.to_thread(
                        state.register_official_if_unseen,
                        announcement,
                        channel_ids,
                    )
                    queued += int(registered)
                if announcements:
                    await asyncio.to_thread(
                        state.set_official_baseline,
                        source,
                        announcements[0].external_id,
                    )
                LOGGER.info(
                    "%s poll completed fetched=%s queued=%s baseline=%s",
                    label, len(announcements), queued, baseline,
                )
            except Exception:
                LOGGER.exception("%s poll failed; other official sources remain available.", label)
    finally:
        official_initial_poll_complete.set()


def _official_announcements_oldest_first(announcements: list[Announcement]) -> list[Announcement]:
    """Order one official list for delivery without treating IDs as chronology.

    Crawlers return the website's current list order. Publishing timestamps order
    ordinary cases from oldest to newest; an original list index keeps equal or
    missing timestamps deterministic without any numeric external-ID comparison.
    """
    def sort_key(item: tuple[int, Announcement]) -> tuple[bool, float, int]:
        index, announcement = item
        published_at = announcement.published_at
        if published_at is None:
            return True, 0.0, index
        if published_at.tzinfo is None:
            return False, published_at.replace(tzinfo=TAIPEI_TIMEZONE).timestamp(), index
        return False, published_at.timestamp(), index

    return [announcement for _, announcement in sorted(enumerate(announcements), key=sort_key)]


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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(".env 缺少 DISCORD_TOKEN。")
    bot.run(token)


if __name__ == "__main__":
    main()
