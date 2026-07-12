"""Compact two-level administrator editing for event information cards."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import discord

from bot.admin.checks import require_administrator
from database.knowledge_query_repository import EventEditContext, KnowledgeQueryRepository


PINK = discord.Color.from_rgb(255, 183, 197)
APPEARANCE_LABELS = {"debut": "首發", "rerun": "復刻", "return": "回歸", "unknown": "未知"}


@dataclass(frozen=True, slots=True)
class EventEditSession:
    guild_id: int | None
    channel_id: int
    message_id: int
    event_id: int
    owner_user_id: int


async def require_session_owner(interaction: discord.Interaction, session: EventEditSession) -> bool:
    if not await require_administrator(interaction):
        return False
    if interaction.user.id == session.owner_user_id:
        return True
    await interaction.response.send_message("此編輯介面屬於其他管理員。", ephemeral=True)
    return False


def menu_embed(event_name: str, section: str | None = None) -> discord.Embed:
    embed = discord.Embed(title=f"✏️ 編輯：{event_name}", color=PINK)
    if section:
        embed.set_footer(text=f"✅ {section}已儲存")
    return embed


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
        session = EventEditSession(interaction.guild_id, interaction.channel_id, interaction.message.id, self.event_id, interaction.user.id)
        view = EventEditMenuView(session)
        await interaction.response.send_message(embed=menu_embed(context.name), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @discord.ui.button(label="✅ 標記已確認", style=discord.ButtonStyle.success)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await asyncio.to_thread(KnowledgeQueryRepository().mark_event_verified, self.event_id)
        await interaction.response.send_message("活動已標記為已確認。", ephemeral=True)


class EventEditMenuView(discord.ui.View):
    """First editing level: only event information and suit information."""

    def __init__(self, session: EventEditSession) -> None:
        super().__init__(timeout=900)
        self.session = session
        self.message: discord.Message | discord.InteractionMessage | None = None

    @discord.ui.button(label="1️⃣ 活動資訊", style=discord.ButtonStyle.secondary)
    async def event_info(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_session_owner(interaction, self.session):
            return
        context = await asyncio.to_thread(KnowledgeQueryRepository().get_event_edit_context, self.session.event_id)
        if context is None:
            await interaction.response.send_message("找不到活動資料。", ephemeral=True)
            return
        await interaction.response.send_modal(EventInfoModal(context, self.session, self.message))

    @discord.ui.button(label="2️⃣ 完成編輯", style=discord.ButtonStyle.success)
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_session_owner(interaction, self.session):
            return
        await refresh_public_card(interaction, self.session)
        await interaction.response.edit_message(content="編輯完成，資料卡已更新。", embed=None, view=None)

    @discord.ui.button(label="3️⃣ 取消", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_session_owner(interaction, self.session):
            return
        await interaction.response.edit_message(content="已取消編輯；已儲存的修改仍會保留。", embed=None, view=None)


async def open_suit_menu(interaction: discord.Interaction, session: EventEditSession) -> None:
    """Build the suit action list fresh from event_suits for every entry."""
    repository = KnowledgeQueryRepository()
    names = await asyncio.to_thread(repository.get_event_suit_names, session.event_id)
    view = SuitMenuView(session, names)
    await interaction.response.edit_message(content="選擇要校正的套裝或操作：", embed=None, view=view)


class SuitMenuSelect(discord.ui.Select):
    def __init__(self, session: EventEditSession, names: list[str]) -> None:
        self.session = session
        self.names = names
        options = [discord.SelectOption(label=f"{index}. {name}"[:100], value=f"suit:{name}") for index, name in enumerate(names, 1)]
        options.extend([
            discord.SelectOption(label="新增套裝", value="new"),
            discord.SelectOption(label="批次校正", value="batch"),
            discord.SelectOption(label="返回", value="back"),
        ])
        super().__init__(placeholder="選擇套裝或操作", options=options[:25])

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_session_owner(interaction, self.session):
            return
        value = self.values[0]
        repository = KnowledgeQueryRepository()
        if value == "back":
            context = await asyncio.to_thread(repository.get_event_edit_context, self.session.event_id)
            if context is not None:
                view = EventEditMenuView(self.session)
                view.message = interaction.message
                await interaction.response.edit_message(embed=menu_embed(context.name), content=None, view=view)
            return
        if value == "batch":
            names = await asyncio.to_thread(repository.get_event_suit_names, self.session.event_id)
            await interaction.response.send_modal(EventSuitCorrectionModal(self.session, names, interaction.message))
            return
        if value == "new":
            await interaction.response.send_modal(EventSuitModal(self.session, None, None, interaction.message))
            return
        name = value.removeprefix("suit:")
        details = await asyncio.to_thread(repository.get_event_suit_details_by_name, self.session.event_id, name)
        if details is None:
            await interaction.response.send_message("套裝資料已變更，請重新開啟。", ephemeral=True)
            return
        await interaction.response.send_modal(EventSuitModal(self.session, int(details["suit_id"]), details, interaction.message))


class SuitMenuView(discord.ui.View):
    def __init__(self, session: EventEditSession, names: list[str]) -> None:
        super().__init__(timeout=600)
        self.add_item(SuitMenuSelect(session, names))


class EventInfoModal(discord.ui.Modal):
    def __init__(self, context: EventEditContext, session: EventEditSession, menu_message: discord.Message | None) -> None:
        self.context, self.session, self.menu_message = context, session, menu_message
        super().__init__(title="活動資訊")
        self.category = discord.ui.TextInput(label="活動分類", default=context.event_type_name or "", placeholder="例如：扭蛋")
        self.start = discord.ui.TextInput(label="開始（YYYY-MM-DD HH:mm）", default=format_edit_time(context.start_at))
        self.end = discord.ui.TextInput(label="結束（YYYY-MM-DD HH:mm）", default=format_edit_time(context.end_at))
        self.notes = discord.ui.TextInput(label="備註（可選）", default=context.notes or "", required=False, style=discord.TextStyle.paragraph)
        for item in (self.category, self.start, self.end, self.notes):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await asyncio.to_thread(KnowledgeQueryRepository().save_event_info, self.session.event_id, str(self.category.value), str(self.start.value), str(self.end.value), str(self.notes.value) or None)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await refresh_public_card(interaction, self.session)
        await interaction.response.send_message("活動資訊已儲存。", ephemeral=True)


class EventSuitModal(discord.ui.Modal):
    def __init__(self, session: EventEditSession, suit_id: int | None, details: dict[str, object] | None, menu_message: discord.Message | None) -> None:
        self.session, self.suit_id, self.menu_message = session, suit_id, menu_message
        details = details or {}
        super().__init__(title="新增套裝" if suit_id is None else "校正套裝")
        self.name = discord.ui.TextInput(label="名稱", default=str(details.get("name") or ""))
        self.appearance = discord.ui.TextInput(label="登場狀態（debut/rerun/return/unknown）", default=str(details.get("appearance_status") or "unknown"))
        self.method = discord.ui.TextInput(label="取得方式", default=str(details.get("acquisition_method") or ""), required=False)
        self.cost = discord.ui.TextInput(label="花費", default=str(details.get("cost_text") or ""), required=False)
        for item in (self.name, self.appearance, self.method, self.cost):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await asyncio.to_thread(KnowledgeQueryRepository().save_event_suit_details, self.session.event_id, self.suit_id, name=str(self.name.value), appearance_status=str(self.appearance.value).strip(), acquisition_method=str(self.method.value) or None, cost_text=str(self.cost.value) or None)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await refresh_public_card(interaction, self.session)
        await interaction.response.send_message("套裝資訊已儲存。", ephemeral=True)


class EventSuitCorrectionModal(discord.ui.Modal):
    def __init__(self, session: EventEditSession, names: list[str], menu_message: discord.Message | None) -> None:
        self.session, self.menu_message = session, menu_message
        super().__init__(title="批次校正套裝")
        self.suits = discord.ui.TextInput(label="套裝", placeholder="每行一個套裝名稱\n例如：\n逐風之翎\n灼火之翼", default="\n".join(names)[:4000], required=False, style=discord.TextStyle.paragraph, max_length=4000)
        self.add_item(self.suits)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(KnowledgeQueryRepository().synchronize_event_suits, self.session.event_id, str(self.suits.value).splitlines())
        await refresh_public_card(interaction, self.session)
        await interaction.response.send_message("套裝清單已批次校正。", ephemeral=True)


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
