"""Compact two-level administrator editing for event information cards."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import discord

from bot.admin.checks import require_administrator
from database.knowledge_query_repository import EventEditContext, KnowledgeQueryRepository


@dataclass(frozen=True, slots=True)
class EventEditSession:
    guild_id: int | None
    channel_id: int
    message_id: int
    event_id: int
    owner_user_id: int


class EventAdminView(discord.ui.View):
    """Only the two requested controls appear on an administrator's public card."""

    def __init__(self, event_id: int, event_name: str) -> None:
        super().__init__(timeout=900)
        self.event_id, self.event_name = event_id, event_name

    @discord.ui.button(label="✏️ 編輯", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        if interaction.message is None or interaction.channel_id is None:
            await interaction.response.send_message("找不到原活動資料卡。", ephemeral=True)
            return
        context = await asyncio.to_thread(KnowledgeQueryRepository().get_event_edit_context, self.event_id)
        if context is None:
            await interaction.response.send_message("找不到活動資料。", ephemeral=True)
            return
        suit_names = await asyncio.to_thread(
            KnowledgeQueryRepository().get_event_suit_names, self.event_id
        )
        session = EventEditSession(
            interaction.guild_id,
            interaction.channel_id,
            interaction.message.id,
            self.event_id,
            interaction.user.id,
        )
        await interaction.response.send_modal(
            EventInfoModal(context, suit_names, session, None)
        )

    @discord.ui.button(label="✅ 標記已確認", style=discord.ButtonStyle.success)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await asyncio.to_thread(KnowledgeQueryRepository().mark_event_verified, self.event_id)
        await interaction.response.send_message("活動已標記為已確認。", ephemeral=True)


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


def format_edit_time(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("T", " ").replace("+08:00", "")[:16]


async def refresh_public_card(interaction: discord.Interaction, session: EventEditSession) -> bool:
    """Refresh the originating public card, or send one replacement when missing."""
    repository = KnowledgeQueryRepository()
    event = await asyncio.to_thread(repository.get_event_by_id, session.event_id)
    if event is None:
        return False
    image_url = await asyncio.to_thread(repository.get_announcement_image_for_event, event.name)
    from bot.main import add_auto_status_notice, create_event_embed

    embed = create_event_embed(event, image_url)
    add_auto_status_notice(embed, event.data_status, True)
    try:
        channel = interaction.client.get_channel(session.channel_id) or await interaction.client.fetch_channel(session.channel_id)
        message = await channel.fetch_message(session.message_id)
        await message.edit(embed=embed, view=EventAdminView(event.id, event.name))
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        await interaction.channel.send(embed=embed, view=EventAdminView(event.id, event.name))
        return False


# Backward-compatible test/helper name used by the existing management tests.
complete_event_edit = refresh_public_card
