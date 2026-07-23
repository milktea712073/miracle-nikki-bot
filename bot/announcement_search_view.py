"""Discord rendering for complete historical-announcement search results."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import discord

from announcement.search import valid_image_urls
from announcement.search_models import AnnouncementSearchResult

LOGGER = logging.getLogger(__name__)
SEARCH_VIEW_TIMEOUT_SECONDS = 300
MAX_EMBED_DESCRIPTION_LENGTH = 4096
MAX_EMBED_TITLE_LENGTH = 256
MAX_EMBEDS_PER_MESSAGE = 10
MAX_EMBED_TEXT_PER_MESSAGE = 5800
BODY_CHUNK_LENGTH = 3400
REGION_LABELS = {"tw": "台服", "cn": "陸服"}


@dataclass(slots=True)
class AnnouncementMessagePayload:
    """One Discord message for a single announcement's complete content."""

    embeds: list[discord.Embed]
    view: AnnouncementImageView | None = None


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _format_date(value: str | None) -> str:
    if not value:
        return "日期未提供"
    return value.replace("T", " ").replace("+00:00", " UTC")


def _split_oversized_text(value: str, maximum: int) -> list[str]:
    """Split a paragraph at punctuation before using a safe character boundary."""
    if len(value) <= maximum:
        return [value]
    # Keep whitespace that follows an ASCII sentence delimiter.  Otherwise a
    # split at "one. Two" could rejoin as "one.Two" in adjacent embeds.
    units = re.findall(r".*?[。！？!?；;](?:\s+|$)|.+$", value, flags=re.DOTALL)
    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > maximum:
            chunks.append(current)
            current = ""
        while len(unit) > maximum:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(unit[:maximum])
            unit = unit[maximum:]
        current += unit
    if current:
        chunks.append(current)
    return chunks


def split_announcement_content(content: str, *, maximum: int = BODY_CHUNK_LENGTH) -> list[str]:
    """Preserve paragraphs and punctuation where possible while fitting embeds."""
    normalized = content.strip()
    if not normalized:
        return []
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", normalized) if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for paragraph_chunk in _split_oversized_text(paragraph, maximum):
            separator = "\n\n" if current else ""
            if current and len(current) + len(separator) + len(paragraph_chunk) > maximum:
                chunks.append(current)
                current = paragraph_chunk
            else:
                current += separator + paragraph_chunk
    if current:
        chunks.append(current)
    return chunks


def _embed_text_size(embed: discord.Embed) -> int:
    return len(embed.title or "") + len(embed.description or "") + len(embed.footer.text or "")


def _group_embeds_for_messages(embeds: list[discord.Embed]) -> list[list[discord.Embed]]:
    """Respect Discord's ten-embed cap and a conservative text budget."""
    groups: list[list[discord.Embed]] = []
    current: list[discord.Embed] = []
    current_size = 0
    for embed in embeds:
        embed_size = _embed_text_size(embed)
        if current and (len(current) >= MAX_EMBEDS_PER_MESSAGE or current_size + embed_size > MAX_EMBED_TEXT_PER_MESSAGE):
            groups.append(current)
            current, current_size = [], 0
        current.append(embed)
        current_size += embed_size
    if current:
        groups.append(current)
    return groups


def _copy_embed(embed: discord.Embed) -> discord.Embed:
    return discord.Embed.from_dict(embed.to_dict())


def _primary_footer(content_message_index: int, content_message_total: int, image_index: int, image_total: int) -> str:
    return f"內容 {content_message_index} / {content_message_total}｜圖片 {image_index if image_total else 0} / {image_total}"


class AnnouncementImageView(discord.ui.View):
    """Own only one announcement's image index and edits only that message's first embed."""

    def __init__(self, *, owner_user_id: int, image_urls: tuple[str, ...], primary_embed: discord.Embed, body_embeds: list[discord.Embed], content_message_index: int, content_message_total: int) -> None:
        super().__init__(timeout=SEARCH_VIEW_TIMEOUT_SECONDS)
        self.owner_user_id = owner_user_id
        self.image_urls = image_urls
        self.primary_embed = primary_embed
        self.body_embeds = body_embeds
        self.content_message_index = content_message_index
        self.content_message_total = content_message_total
        self.image_index = 0
        self.message: discord.Message | discord.WebhookMessage | None = None
        self._update_navigation()

    def _update_navigation(self) -> None:
        self.previous_image.disabled = self.image_index <= 0
        self.next_image.disabled = self.image_index >= len(self.image_urls) - 1

    def embeds(self) -> list[discord.Embed]:
        primary = _copy_embed(self.primary_embed)
        primary.set_image(url=self.image_urls[self.image_index])
        primary.set_footer(text=_primary_footer(self.content_message_index, self.content_message_total, self.image_index + 1, len(self.image_urls)))
        return [primary, *self.body_embeds]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_user_id:
            return True
        await interaction.response.send_message("只有執行這次搜尋的使用者可以操作。", ephemeral=True)
        return False

    async def _refresh(self, interaction: discord.Interaction) -> None:
        self._update_navigation()
        try:
            await interaction.response.edit_message(embeds=self.embeds(), view=self)
        except Exception:
            LOGGER.exception("Failed to update announcement-search image page.")
            if not interaction.response.is_done():
                await interaction.response.send_message("更新公告圖片時發生錯誤，請稍後再試。", ephemeral=True)

    @discord.ui.button(label="◀ 上一張", style=discord.ButtonStyle.secondary, row=0)
    async def previous_image(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.image_index > 0:
            self.image_index -= 1
        await self._refresh(interaction)

    @discord.ui.button(label="下一張 ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_image(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.image_index < len(self.image_urls) - 1:
            self.image_index += 1
        await self._refresh(interaction)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(embeds=self.embeds(), view=self)
        except discord.NotFound:
            pass
        except discord.HTTPException:
            LOGGER.exception("Failed to disable timed-out announcement-search image controls.")


def build_announcement_message_payloads(result: AnnouncementSearchResult, *, owner_user_id: int) -> list[AnnouncementMessagePayload]:
    """Render one complete announcement into one or more Discord-safe messages."""
    source = REGION_LABELS.get(result.region, result.source)
    header = f"**{source}｜{_format_date(result.published_at)}**\n\n🔗 [查看官方公告]({result.canonical_url})"
    first_chunk_limit = max(1, min(BODY_CHUNK_LENGTH, MAX_EMBED_DESCRIPTION_LENGTH - len(header) - 2))
    content_chunks = split_announcement_content(result.content_text, maximum=first_chunk_limit) or ["（公告未提供正文）"]
    embeds = [discord.Embed(title=_truncate(result.title or "未命名公告", MAX_EMBED_TITLE_LENGTH), description=f"{header}\n\n{content_chunks[0]}", color=discord.Color.from_rgb(255, 183, 197))]
    total_chunks = len(content_chunks)
    for index, chunk in enumerate(content_chunks[1:], start=2):
        embeds.append(discord.Embed(title=f"公告內容 {index} / {total_chunks}", description=chunk, color=discord.Color.from_rgb(255, 183, 197)))

    groups = _group_embeds_for_messages(embeds)
    image_urls = valid_image_urls(result.image_urls)
    payloads: list[AnnouncementMessagePayload] = []
    for message_index, group in enumerate(groups, start=1):
        primary = group[0]
        if message_index == 1:
            primary.set_footer(text=_primary_footer(message_index, len(groups), 1, len(image_urls)))
            if image_urls:
                primary.set_image(url=image_urls[0])
        else:
            primary.set_footer(text=f"內容 {message_index} / {len(groups)}")
        payloads.append(AnnouncementMessagePayload(embeds=group))
    if len(image_urls) > 1:
        first_payload = payloads[0]
        first_payload.view = AnnouncementImageView(owner_user_id=owner_user_id, image_urls=image_urls, primary_embed=first_payload.embeds[0], body_embeds=first_payload.embeds[1:], content_message_index=1, content_message_total=len(payloads))
        first_payload.embeds = first_payload.view.embeds()
    return payloads
