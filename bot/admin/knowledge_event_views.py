"""Compact two-level administrator editing for event information cards."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import discord

from bot.admin.checks import require_administrator
from database.knowledge_query_repository import (
    EventEditContext,
    KnowledgeQueryRepository,
    SeriesEditContext,
)


@dataclass(frozen=True, slots=True)
class EventEditSession:
    guild_id: int | None
    channel_id: int
    message_id: int
    event_id: int
    owner_user_id: int
    entity_type: str = "event"
    series_id: int | None = None


class EventAdminView(discord.ui.View):
    """Administrator controls for a normal event or a fixed Series card."""

    def __init__(self, event_id: int, event_name: str, *, entity_type: str = "event") -> None:
        super().__init__(timeout=900)
        self.event_id, self.event_name, self.entity_type = event_id, event_name, entity_type
        if entity_type == "series":
            self.edit.label = "✏️ 編輯資訊"
            suits_button = discord.ui.Button(label="👗 編輯套裝", style=discord.ButtonStyle.secondary)
            suits_button.callback = self.edit_series_suits
            periods_button = discord.ui.Button(label="📅 編輯檔期", style=discord.ButtonStyle.secondary)
            periods_button.callback = self.edit_series_periods
            self.add_item(suits_button)
            self.add_item(periods_button)

    @discord.ui.button(label="✏️ 編輯", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        if interaction.message is None or interaction.channel_id is None:
            await interaction.response.send_message("找不到原活動資料卡。", ephemeral=True)
            return
        repository = KnowledgeQueryRepository()
        context = await asyncio.to_thread(
            repository.get_series_edit_context_for_event if self.entity_type == "series" else repository.get_event_edit_context,
            self.event_id,
        )
        if context is None:
            await interaction.response.send_message("找不到活動資料。", ephemeral=True)
            return
        session = EventEditSession(
            interaction.guild_id,
            interaction.channel_id,
            interaction.message.id,
            self.event_id,
            interaction.user.id,
            self.entity_type,
            context.series_id if isinstance(context, SeriesEditContext) else None,
        )
        if isinstance(context, SeriesEditContext):
            await interaction.response.send_modal(SeriesInfoModal(context, session))
            return
        suit_names = await asyncio.to_thread(repository.get_event_suit_names, self.event_id)
        await interaction.response.send_modal(EventInfoModal(context, suit_names, session, None))

    async def edit_series_suits(self, interaction: discord.Interaction) -> None:
        context, session = await self._get_series_context(interaction)
        if context is not None and session is not None:
            await interaction.response.send_modal(SeriesSuitsModal(context, session))

    async def edit_series_periods(self, interaction: discord.Interaction) -> None:
        context, session = await self._get_series_context(interaction)
        if context is not None and session is not None:
            await interaction.response.send_modal(SeriesPeriodsModal(context, session))

    async def _get_series_context(
        self, interaction: discord.Interaction
    ) -> tuple[SeriesEditContext | None, EventEditSession | None]:
        if not await require_administrator(interaction):
            return None, None
        if interaction.message is None or interaction.channel_id is None:
            await interaction.response.send_message("找不到原活動資料卡。", ephemeral=True)
            return None, None
        context = await asyncio.to_thread(KnowledgeQueryRepository().get_series_edit_context_for_event, self.event_id)
        if context is None:
            await interaction.response.send_message("找不到固定系列資料。", ephemeral=True)
            return None, None
        return context, EventEditSession(
            interaction.guild_id, interaction.channel_id, interaction.message.id,
            self.event_id, interaction.user.id, "series", context.series_id,
        )


class EventInfoModal(discord.ui.Modal):
    def __init__(
        self,
        context: EventEditContext,
        suit_names: list[str],
        session: EventEditSession,
        menu_message: discord.Message | None,
    ) -> None:
        self.context, self.session, self.menu_message = context, session, menu_message
        super().__init__(title="活動資訊")
        self.category = discord.ui.TextInput(label="活動分類", default=context.event_type_name or "", placeholder="例如：扭蛋" ,required=False,)
        self.start = discord.ui.TextInput(label="開始（YYYY-MM-DD HH:mm）", default=format_edit_time(context.start_at))
        self.end = discord.ui.TextInput(label="結束（YYYY-MM-DD HH:mm）", default=format_edit_time(context.end_at))
        self.notes = discord.ui.TextInput(label="備註（可選）", default=context.notes or "", required=False, style=discord.TextStyle.paragraph)
        self.suits = discord.ui.TextInput(
            label="套裝名稱",
            default=", ".join(suit_names)[:4_000],
            placeholder="以逗號分隔套裝名稱",
            required=False,
            max_length=4_000,
        )
        for item in (self.category, self.start, self.end, self.notes, self.suits):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            repository = KnowledgeQueryRepository()
            await asyncio.to_thread(
                repository.save_event_info,
                self.session.event_id,
                str(self.category.value),
                str(self.start.value),
                str(self.end.value),
                str(self.notes.value) or None,
            )
            await asyncio.to_thread(
                repository.synchronize_event_suits,
                self.session.event_id,
                str(self.suits.value).replace("，", ",").split(","),
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await refresh_public_card(interaction, self.session)
        await interaction.response.send_message("活動資訊已儲存。", ephemeral=True)


class SeriesInfoModal(discord.ui.Modal):
    """Edit the four fixed-Series fields that are not contents or periods."""

    def __init__(self, context: SeriesEditContext, session: EventEditSession) -> None:
        self.session = session
        super().__init__(title="編輯固定系列資訊")
        self.name = discord.ui.TextInput(label="系列名稱", default=context.name)
        self.category = discord.ui.TextInput(label="分類", default=context.category)
        self.diamond_cost = discord.ui.TextInput(
            label="鑽石花費", default=context.diamond_cost or "", required=False
        )
        self.notes = discord.ui.TextInput(
            label="備註", default=context.notes or "", required=False,
            style=discord.TextStyle.paragraph,
        )
        for item in (self.name, self.category, self.diamond_cost, self.notes):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await asyncio.to_thread(
                KnowledgeQueryRepository().save_series_info,
                self.session.series_id,
                name=str(self.name.value), category=str(self.category.value),
                diamond_cost=str(self.diamond_cost.value), notes=str(self.notes.value),
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await refresh_public_card(interaction, self.session)
        await interaction.response.send_message("固定系列資訊已儲存。", ephemeral=True)


class SeriesSuitsModal(discord.ui.Modal):
    """Edit the visible main and Live2D Series contents without touching minor data."""

    def __init__(self, context: SeriesEditContext, session: EventEditSession) -> None:
        self.session = session
        super().__init__(title="編輯固定系列套裝")
        by_type = {content_type: [] for content_type in ("main", "minor", "live2d")}
        for name, content_type in context.contents:
            if content_type in by_type:
                by_type[content_type].append(name)
        self.main = discord.ui.TextInput(
            label="主套", default="\n".join(by_type["main"])[:4_000], required=False,
            max_length=4_000, style=discord.TextStyle.paragraph,
        )
        self.minor = discord.ui.TextInput(
            label="小套", default="\n".join(by_type["minor"])[:4_000], required=False,
            max_length=4_000, style=discord.TextStyle.paragraph,
        )
        self.live2d = discord.ui.TextInput(
            label="Live2D", default="\n".join(by_type["live2d"])[:4_000], required=False,
            max_length=4_000, style=discord.TextStyle.paragraph,
        )
        for item in (self.main, self.minor, self.live2d):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await asyncio.to_thread(
                KnowledgeQueryRepository().save_series_contents,
                self.session.series_id,
                main=str(self.main.value).splitlines(),
                minor=str(self.minor.value).splitlines(),
                live2d=str(self.live2d.value).splitlines(),
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await refresh_public_card(interaction, self.session)
        await interaction.response.send_message("固定系列套裝已儲存。", ephemeral=True)


class SeriesPeriodsModal(discord.ui.Modal):
    """Edit the ordered, display-only fixed-Series period labels."""

    def __init__(self, context: SeriesEditContext, session: EventEditSession) -> None:
        self.session = session
        super().__init__(title="編輯固定系列檔期")
        self.periods = discord.ui.TextInput(
            label="檔期", default="\n".join(context.periods)[:4_000], required=False,
            max_length=4_000, style=discord.TextStyle.paragraph,
        )
        self.add_item(self.periods)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(
            KnowledgeQueryRepository().save_series_periods,
                self.session.series_id, str(self.periods.value).splitlines(),
        )
        await refresh_public_card(interaction, self.session)
        await interaction.response.send_message("固定系列檔期已儲存。", ephemeral=True)


def format_edit_time(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("T", " ").replace("+08:00", "")[:16]


async def refresh_public_card(interaction: discord.Interaction, session: EventEditSession) -> bool:
    """Refresh the originating public card, or send one replacement when missing."""
    repository = KnowledgeQueryRepository()
    event = await asyncio.to_thread(
        repository.get_event_by_id,
        session.event_id,
    )
    if event is None:
        return False
    image_url = await asyncio.to_thread(repository.get_announcement_image_for_event_id, event.id)
    from bot.main import create_event_embed

    embed = create_event_embed(event, image_url)
    try:
        channel = interaction.client.get_channel(session.channel_id) or await interaction.client.fetch_channel(session.channel_id)
        message = await channel.fetch_message(session.message_id)
        await message.edit(embed=embed, view=EventAdminView(event.id, event.name, entity_type=event.entity_type))
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        await interaction.channel.send(
            embed=embed, view=EventAdminView(event.id, event.name, entity_type=event.entity_type)
        )
        return False


# Backward-compatible test/helper name used by the existing management tests.
complete_event_edit = refresh_public_card
