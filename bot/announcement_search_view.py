"""Discord rendering for complete historical-announcement search results."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

import discord

from announcement.search import valid_image_urls
from announcement.search_models import AnnouncementSearchResult

LOGGER = logging.getLogger(__name__)
SEARCH_VIEW_TIMEOUT_SECONDS = 300
SEARCH_RESULTS_PER_PAGE = 10
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


def _result_title(result: AnnouncementSearchResult, limit: int = 100) -> str:
    return _truncate(result.title.strip() or "未命名公告", limit)


def _result_source_label(result: AnnouncementSearchResult) -> str:
    return REGION_LABELS.get(result.region, result.source)


def _result_date_label(result: AnnouncementSearchResult) -> str:
    if not result.published_at:
        return "日期未提供"
    return result.published_at[:10].replace("-", "/")


def highlight_search_terms(
    text: str,
    keyword: str,
    matched_terms: Iterable[str],
) -> str:
    """Add Discord bold markers to literal matched terms without touching protected Markdown."""
    terms: list[str] = []
    for candidate in (keyword, *matched_terms):
        normalized = candidate.strip()
        if normalized and normalized not in terms:
            terms.append(normalized)
    if not text or not terms:
        return text

    # Existing bold spans and URLs must remain byte-for-byte intact.  Inline
    # code is protected as well because Markdown inside it is literal content.
    protected_pattern = re.compile(r"(\*\*.*?\*\*|`[^`]*`|https?://[^\s]+)", re.DOTALL)
    term_pattern = re.compile(
        "(" + "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True)) + ")",
        re.IGNORECASE,
    )
    parts: list[str] = []
    cursor = 0
    for protected in protected_pattern.finditer(text):
        parts.append(term_pattern.sub(r"**\1**", text[cursor : protected.start()]))
        parts.append(protected.group(0))
        cursor = protected.end()
    parts.append(term_pattern.sub(r"**\1**", text[cursor:]))
    return "".join(parts)


def build_search_results_embed(
    results: tuple[AnnouncementSearchResult, ...],
    *,
    keyword: str,
    page_index: int = 0,
    page_size: int = SEARCH_RESULTS_PER_PAGE,
) -> discord.Embed:
    """Build the compact public result list for a multi-result search."""
    total_results = len(results)
    total_pages = max(1, (total_results + page_size - 1) // page_size)
    current_page = min(max(page_index, 0), total_pages - 1)
    start_index = current_page * page_size
    page_results = results[start_index : start_index + page_size]
    lines = [f"關鍵字：{keyword}", f"第 {current_page + 1} / {total_pages} 頁", ""]
    region_totals = {
        region: sum(1 for result in results if result.region == region)
        for region in REGION_LABELS
    }
    displayed_regions: set[str | None] = set()
    for index, result in enumerate(page_results, start=start_index + 1):
        if result.region not in displayed_regions:
            if displayed_regions:
                lines.append("")
            displayed_regions.add(result.region)
            if result.region in REGION_LABELS:
                flag = "🇹🇼" if result.region == "tw" else "🇨🇳"
                lines.append(f"{flag} {REGION_LABELS[result.region]}（{region_totals[result.region]}）")
                lines.append("────────────")
            else:
                lines.append(_result_source_label(result))
                lines.append("────────────")
        lines.append(f"{index}. **{_result_title(result, 180)}**")
        lines.append(f"   {_result_date_label(result)}")
    lines.append("請從下方選擇要查看的公告。")
    embed = discord.Embed(
        title=f"🔎 找到 {total_results} 筆公告",
        description="\n".join(lines)[:MAX_EMBED_DESCRIPTION_LENGTH],
        color=discord.Color.from_rgb(255, 183, 197),
    )
    embed.set_footer(text="依發布時間由新到舊・台服優先顯示")
    return embed


async def send_announcement_payloads(
    interaction: discord.Interaction,
    payloads: list[AnnouncementMessagePayload],
    *,
    ephemeral: bool,
) -> list[discord.Message | discord.WebhookMessage | None]:
    """Send complete-notice payloads without passing ``view=None`` to discord.py."""
    messages: list[discord.Message | discord.WebhookMessage | None] = []
    for payload in payloads:
        send_kwargs: dict[str, object] = {"embeds": payload.embeds, "wait": True}
        if ephemeral:
            send_kwargs["ephemeral"] = True
        if payload.view is not None:
            send_kwargs["view"] = payload.view
        message = await interaction.followup.send(**send_kwargs)
        if payload.view is not None and message is not None:
            payload.view.message = message
        messages.append(message)
    return messages


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


class AnnouncementSearchResultSelect(discord.ui.Select):
    """Select one compact search-list entry and reveal its complete notice privately."""

    def __init__(self, parent: AnnouncementSearchResultView) -> None:
        self.parent_view = parent
        super().__init__(
            placeholder="選擇公告",
            min_values=1,
            max_values=1,
            options=parent.select_options(),
        )

    def refresh_options(self) -> None:
        self.options = self.parent_view.select_options()

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_index = int(self.values[0])
        result = self.parent_view.results[selected_index]
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            payloads = build_announcement_message_payloads(
                result,
                owner_user_id=self.parent_view.owner_user_id,
                highlight_terms=self.parent_view.highlight_terms,
            )
            await send_announcement_payloads(interaction, payloads, ephemeral=True)
        except Exception:
            LOGGER.exception(
                "Announcement-search selection rendering failed keyword=%r source_filter=%r "
                "owner_user_id=%s selected_index=%s source_kind=%s notice_source=%s "
                "external_id=%s record_id=%s",
                self.parent_view.keyword,
                self.parent_view.source_filter,
                self.parent_view.owner_user_id,
                selected_index,
                result.source_kind,
                result.source,
                result.external_id,
                result.source_record_id,
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("公告內容顯示失敗，請稍後再試。", ephemeral=True)
                else:
                    await interaction.response.send_message("公告內容顯示失敗，請稍後再試。", ephemeral=True)
            except Exception:
                LOGGER.exception("Unable to report announcement-search selection rendering failure.")


class AnnouncementSearchResultView(discord.ui.View):
    """Public, owner-bound search result list with ten-result pages."""

    def __init__(
        self,
        *,
        results: tuple[AnnouncementSearchResult, ...],
        owner_user_id: int,
        keyword: str,
        source_filter: str,
        highlight_terms: tuple[str, ...] = (),
    ) -> None:
        super().__init__(timeout=SEARCH_VIEW_TIMEOUT_SECONDS)
        self.results = results
        self.owner_user_id = owner_user_id
        self.keyword = keyword
        self.source_filter = source_filter
        self.highlight_terms = highlight_terms
        self.page_index = 0
        self.message: discord.Message | discord.WebhookMessage | None = None
        self.result_select = AnnouncementSearchResultSelect(self)
        self.previous_page_button = discord.ui.Button(
            label="◀ 上一頁", style=discord.ButtonStyle.secondary, row=1
        )
        self.next_page_button = discord.ui.Button(
            label="下一頁 ▶", style=discord.ButtonStyle.secondary, row=1
        )
        self.previous_page_button.callback = self._previous_page
        self.next_page_button.callback = self._next_page
        self.add_item(self.result_select)
        self.add_item(self.previous_page_button)
        self.add_item(self.next_page_button)
        self._update_navigation()

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.results) + SEARCH_RESULTS_PER_PAGE - 1) // SEARCH_RESULTS_PER_PAGE)

    def select_options(self) -> list[discord.SelectOption]:
        start_index = self.page_index * SEARCH_RESULTS_PER_PAGE
        return [
            discord.SelectOption(
                label=_truncate(f"{index + 1}. {_result_title(result, 95)}", 100),
                description=_truncate(
                    f"{_result_date_label(result)}・{_result_source_label(result)}", 100
                ),
                value=str(index),
            )
            for index, result in enumerate(
                self.results[start_index : start_index + SEARCH_RESULTS_PER_PAGE],
                start=start_index,
            )
        ]

    def embed(self) -> discord.Embed:
        return build_search_results_embed(
            self.results,
            keyword=self.keyword,
            page_index=self.page_index,
        )

    def _update_navigation(self) -> None:
        self.previous_page_button.disabled = self.page_index <= 0
        self.next_page_button.disabled = self.page_index >= self.total_pages - 1
        self.result_select.disabled = not self.results
        self.result_select.refresh_options()

    async def _change_page(self, interaction: discord.Interaction, delta: int) -> None:
        self.page_index = min(max(self.page_index + delta, 0), self.total_pages - 1)
        self._update_navigation()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _previous_page(self, interaction: discord.Interaction) -> None:
        await self._change_page(interaction, -1)

    async def _next_page(self, interaction: discord.Interaction) -> None:
        await self._change_page(interaction, 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_user_id:
            return True
        try:
            await interaction.response.send_message(
                "這不是你的搜尋結果，請自行使用 /公告搜尋。",
                ephemeral=True,
            )
        except Exception:
            LOGGER.exception("Unable to reject another user's announcement-search selection.")
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except discord.NotFound:
            pass
        except discord.HTTPException:
            LOGGER.exception("Failed to disable timed-out announcement-search result selector.")


def build_announcement_message_payloads(
    result: AnnouncementSearchResult,
    *,
    owner_user_id: int,
    highlight_terms: tuple[str, ...] = (),
) -> list[AnnouncementMessagePayload]:
    """Render one complete announcement into one or more Discord-safe messages."""
    source = REGION_LABELS.get(result.region, result.source)
    header = f"**{source}｜{_format_date(result.published_at)}**\n\n🔗 [查看官方公告]({result.canonical_url})"
    first_chunk_limit = max(1, min(BODY_CHUNK_LENGTH, MAX_EMBED_DESCRIPTION_LENGTH - len(header) - 2))
    highlighted_content = highlight_search_terms(result.content_text, "", highlight_terms)
    content_chunks = split_announcement_content(highlighted_content, maximum=first_chunk_limit) or ["（公告未提供正文）"]
    display_title = highlight_search_terms(
        _truncate(result.title or "未命名公告", MAX_EMBED_TITLE_LENGTH),
        "",
        highlight_terms,
    )
    embeds = [discord.Embed(title=display_title, description=f"{header}\n\n{content_chunks[0]}", color=discord.Color.from_rgb(255, 183, 197))]
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
