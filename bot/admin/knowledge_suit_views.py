"""Administrator controls attached directly to a suit information card."""

from __future__ import annotations

import asyncio

import discord

from bot.admin.checks import require_administrator
from bot.admin.knowledge_image_views import require_view_owner, send_image_preview
from bot.knowledge_formatting import format_cost_line
from database.knowledge_query_repository import KnowledgeQueryRepository, SuitEditContext, SuitEditEvent


PINK = discord.Color.from_rgb(255, 183, 197)
LIVE2D_EVENT_TYPES = {"故事套裝", "大閣"}


class SuitAdminView(discord.ui.View):
    """Shows the two administrator-only suit card controls."""

    def __init__(self, suit_id: int) -> None:
        super().__init__(timeout=900)
        self.suit_id = suit_id

    @discord.ui.button(label="✏️ 編輯套裝", style=discord.ButtonStyle.secondary)
    async def edit_suit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        context = await asyncio.to_thread(KnowledgeQueryRepository().get_suit_edit_context, self.suit_id)
        if context is None or not context.events:
            await interaction.response.send_message("找不到可編輯的套裝活動資料。", ephemeral=True)
            return
        if len(context.events) == 1:
            await interaction.response.send_modal(
                SuitRelationModal(context, context.events[0], interaction.message, interaction.message)
            )
            return
        await interaction.response.send_message(
            "請選擇要編輯的活動關聯：",
            view=SuitRelationSelectView(context, interaction.user.id, interaction.message),
            ephemeral=True,
        )

    @discord.ui.button(label="🖼️ 編輯圖片", style=discord.ButtonStyle.secondary)
    async def edit_images(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        context = await asyncio.to_thread(KnowledgeQueryRepository().get_suit_edit_context, self.suit_id)
        if context is None or not context.events:
            await interaction.response.send_message("找不到可用的活動圖片來源。", ephemeral=True)
            return
        if len(context.events) == 1:
            await show_suit_raw_images(interaction, context.suit_id, context.suit_name, context.events[0])
            return
        view = SuitImageEventSelectView(
            context.suit_id, context.suit_name, context.events, interaction.user.id
        )
        await interaction.response.send_message(
            "此套裝有多個所屬活動，請先選擇圖片來源活動：", view=view, ephemeral=True
        )
        view.message = await interaction.original_response()

    @discord.ui.button(label="✅ 標記已確認", style=discord.ButtonStyle.success)
    async def mark_verified(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await asyncio.to_thread(KnowledgeQueryRepository().mark_suit_verified, self.suit_id)
        await interaction.response.send_message("套裝已標記為已確認。", ephemeral=True)


def create_edit_embed(
    context: SuitEditContext, event: SuitEditEvent, saved: bool = False
) -> discord.Embed:
    """Render a compact, player-facing suit edit card without database columns."""
    cost_line = format_cost_line(event.acquisition_method, event.cost_text)
    embed = discord.Embed(
        title=f"✏️ 編輯套裝：{context.suit_name}",
        description=(
            f"📚 所屬活動：{event.name}\n\n"
            f"{cost_line or '🎁 取得方式：尚未整理'}"
        ),
        color=PINK,
    )
    if event.event_type in LIVE2D_EVENT_TYPES:
        embed.description += f"\n\n✨ Live2D：{'是' if context.is_live2d else '否'}"
    if saved:
        embed.set_footer(text="✅ 已儲存")
    return embed


async def refresh_edit_card(
    parent_message: discord.InteractionMessage,
    suit_id: int,
    event_id: int,
) -> None:
    """Rebuild the original edit card with the just-saved database values."""
    context = await asyncio.to_thread(KnowledgeQueryRepository().get_suit_edit_context, suit_id)
    if context is None or not context.events:
        return
    event = next((candidate for candidate in context.events if candidate.id == event_id), context.events[0])
    view = SuitEditSettingsView(context, event)
    view.message = parent_message
    await parent_message.edit(embed=create_edit_embed(context, event, saved=True), view=view)


class SuitEventContextSelect(discord.ui.Select):
    """Switch the event relationship whose cost and acquisition are edited."""

    def __init__(self, context: SuitEditContext) -> None:
        self.context = context
        super().__init__(
            placeholder="選擇要編輯的所屬活動",
            options=[discord.SelectOption(label=event.name[:100], value=str(event.id)) for event in context.events[:25]],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        event = next(event for event in self.context.events if event.id == int(self.values[0]))
        view = SuitEditSettingsView(self.context, event)
        view.message = interaction.message
        await interaction.response.edit_message(embed=create_edit_embed(self.context, event), view=view)


class AcquisitionMethodSelect(discord.ui.Select):
    """Persist an acquisition method without showing database identifiers."""

    def __init__(
        self,
        context: SuitEditContext,
        event: SuitEditEvent,
        parent_message: discord.InteractionMessage,
    ) -> None:
        self.context = context
        self.event = event
        self.parent_message = parent_message
        options = KnowledgeQueryRepository().get_acquisition_method_options()
        super().__init__(
            placeholder="選擇取得方式",
            options=[
                discord.SelectOption(label=name, value=str(method_id), default=method_id == event.acquisition_method_id)
                for method_id, name in options[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        await asyncio.to_thread(
            KnowledgeQueryRepository().update_suit_card_data,
            self.context.suit_id,
            self.event.id,
            int(self.values[0]),
            self.event.cost_text,
            self.context.is_live2d,
        )
        await interaction.response.defer()
        await refresh_edit_card(self.parent_message, self.context.suit_id, self.event.id)


class AcquisitionMethodView(discord.ui.View):
    """One-purpose acquisition-method selector."""

    def __init__(
        self,
        context: SuitEditContext,
        event: SuitEditEvent,
        parent_message: discord.InteractionMessage,
    ) -> None:
        super().__init__(timeout=300)
        self.add_item(AcquisitionMethodSelect(context, event, parent_message))


class SuitEditSettingsView(discord.ui.View):
    """Offer focused cost, acquisition, and permitted Live2D actions."""

    def __init__(self, context: SuitEditContext, event: SuitEditEvent) -> None:
        super().__init__(timeout=900)
        self.context = context
        self.event = event
        self.message: discord.InteractionMessage | None = None
        self.public_message: discord.Message | None = None
        if len(context.events) > 1:
            self.add_item(SuitEventContextSelect(context))
        if event.event_type not in LIVE2D_EVENT_TYPES:
            self.remove_item(self.edit_live2d)

    @discord.ui.button(label="💎 編輯花費", style=discord.ButtonStyle.primary, row=2)
    async def edit_cost(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.send_modal(SuitCostModal(self.context, self.event, self.message or interaction.message))

    @discord.ui.button(label="✏️ 校正套裝資訊", style=discord.ButtonStyle.primary, row=1)
    async def edit_relation(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.send_modal(
            SuitRelationModal(
                self.context,
                self.event,
                self.message or interaction.message,
                self.public_message,
            )
        )

    @discord.ui.button(label="🎁 編輯取得方式", style=discord.ButtonStyle.secondary, row=2)
    async def edit_acquisition(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        parent_message = self.message or interaction.message
        await interaction.response.edit_message(
            content="請選擇取得方式：",
            embed=None,
            view=AcquisitionMethodView(self.context, self.event, parent_message),
        )

    @discord.ui.button(label="✨ 設定 Live2D", style=discord.ButtonStyle.secondary, row=2)
    async def edit_live2d(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.send_modal(SuitLive2DModal(self.context, self.event, self.message or interaction.message))

    @discord.ui.button(label="⬅️ 返回套裝卡", style=discord.ButtonStyle.secondary, row=3)
    async def return_to_suit_card(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Return to the refreshed player-facing suit card without a new message."""
        if not await require_administrator(interaction):
            return
        repository = KnowledgeQueryRepository()
        suit = await asyncio.to_thread(repository.get_suit_by_name, self.context.suit_name)
        if suit is None:
            await interaction.response.edit_message(
                content="找不到套裝資料。", embed=None, view=None
            )
            return
        image_url = await asyncio.to_thread(repository.get_display_image_for_suit, suit.id)
        # Delayed import avoids a module-level circular dependency with bot.main.
        from bot.main import create_suit_embed

        await interaction.response.edit_message(
            content=None,
            embed=create_suit_embed(suit, image_url, show_missing_category=True),
            view=SuitAdminView(suit.id),
        )


class SuitRelationModal(discord.ui.Modal):
    """Edit the complete event-suit relation from the suit card."""

    def __init__(
        self,
        context: SuitEditContext,
        event: SuitEditEvent,
        parent_message: discord.Message | discord.InteractionMessage,
        public_message: discord.Message | None = None,
    ) -> None:
        self.context, self.event, self.parent_message = context, event, parent_message
        self.public_message = public_message
        super().__init__(title="校正套裝資訊")
        self.name = discord.ui.TextInput(label="套裝名稱", default=context.suit_name)
        self.event_type = discord.ui.TextInput(
            label="活動分類",
            default=event.event_type or "",
            required=False,
        )
        self.method = discord.ui.TextInput(label="取得方式", default=event.acquisition_method or "", required=False)
        raw_cost = event.cost_text or ""
        self.cost = discord.ui.TextInput(label="花費數量與貨幣／資源", default=raw_cost, required=False)
        for item in (self.name, self.event_type, self.method, self.cost):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await asyncio.to_thread(
                KnowledgeQueryRepository().save_event_suit_details,
                self.event.id,
                self.context.suit_id,
                name=str(self.name.value),
                event_type_name=str(self.event_type.value),
                acquisition_method=str(self.method.value) or None,
                cost_text=str(self.cost.value) or None,
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        if self.public_message is not None:
            repository = KnowledgeQueryRepository()
            suit = await asyncio.to_thread(repository.get_suit_by_name, str(self.name.value))
            if suit is not None:
                image_url = await asyncio.to_thread(repository.get_display_image_for_suit, suit.id)
                from bot.main import create_suit_embed

                await self.public_message.edit(
                    embed=create_suit_embed(suit, image_url, show_missing_category=True),
                    view=SuitAdminView(suit.id),
                )
                await interaction.response.send_message(
                    "套裝資料已儲存。",
                    view=ReturnSuitCardView(suit.id),
                    ephemeral=True,
                )
                return
        await interaction.response.send_message("套裝資料已儲存。", ephemeral=True)


class SuitRelationSelect(discord.ui.Select):
    """Choose one event relation, then immediately open its correction modal."""

    def __init__(
        self,
        context: SuitEditContext,
        owner_user_id: int,
        public_message: discord.Message | None,
    ) -> None:
        self.context, self.owner_user_id, self.public_message = context, owner_user_id, public_message
        super().__init__(
            placeholder="選擇活動關聯",
            options=[
                discord.SelectOption(label=event.name[:100], value=str(event.id))
                for event in context.events[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_user_id or not await require_administrator(interaction):
            return
        event = next(event for event in self.context.events if event.id == int(self.values[0]))
        await interaction.response.send_modal(
            SuitRelationModal(self.context, event, interaction.message, self.public_message)
        )


class SuitRelationSelectView(discord.ui.View):
    def __init__(
        self, context: SuitEditContext, owner_user_id: int, public_message: discord.Message | None
    ) -> None:
        super().__init__(timeout=300)
        self.add_item(SuitRelationSelect(context, owner_user_id, public_message))


class ReturnSuitCardView(discord.ui.View):
    """Offer one lightweight way back to the latest suit card after saving."""

    def __init__(self, suit_id: int) -> None:
        super().__init__(timeout=300)
        self.suit_id = suit_id

    @discord.ui.button(label="↩️ 返回套裝卡", style=discord.ButtonStyle.secondary)
    async def return_to_card(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        repository = KnowledgeQueryRepository()
        context = await asyncio.to_thread(repository.get_suit_edit_context, self.suit_id)
        if context is None:
            await interaction.response.edit_message(content="找不到套裝資料。", embed=None, view=None)
            return
        suit = await asyncio.to_thread(repository.get_suit_by_name, context.suit_name)
        if suit is None:
            await interaction.response.edit_message(content="找不到套裝資料。", embed=None, view=None)
            return
        image_url = await asyncio.to_thread(repository.get_display_image_for_suit, suit.id)
        from bot.main import create_suit_embed

        await interaction.response.edit_message(
            content=None,
            embed=create_suit_embed(suit, image_url, show_missing_category=True),
            view=SuitAdminView(suit.id),
        )


class SuitCostModal(discord.ui.Modal):
    """Edit a suit's single-suit cost only."""

    def __init__(
        self,
        context: SuitEditContext,
        event: SuitEditEvent,
        parent_message: discord.InteractionMessage,
    ) -> None:
        self.context = context
        self.event = event
        self.parent_message = parent_message
        super().__init__(title=f"編輯花費：{context.suit_name}")
        self.cost = discord.ui.TextInput(
            label="單套花費（可留空）",
            default=event.cost_text or "",
            required=False,
            max_length=200,
        )
        self.add_item(self.cost)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        await asyncio.to_thread(
            KnowledgeQueryRepository().update_suit_card_data,
            self.context.suit_id,
            self.event.id,
            self.event.acquisition_method_id,
            self.cost.value.strip() or None,
            self.context.is_live2d,
        )
        await interaction.response.defer()
        await refresh_edit_card(self.parent_message, self.context.suit_id, self.event.id)


class SuitLive2DModal(discord.ui.Modal):
    """Edit Live2D independently for an eligible story-suit event."""

    def __init__(
        self,
        context: SuitEditContext,
        event: SuitEditEvent,
        parent_message: discord.InteractionMessage,
    ) -> None:
        self.context = context
        self.event = event
        self.parent_message = parent_message
        super().__init__(title=f"設定 Live2D：{context.suit_name}")
        self.live2d = discord.ui.TextInput(
            label="是否為 Live2D（是／否）",
            default="是" if context.is_live2d else "否",
            max_length=3,
        )
        self.add_item(self.live2d)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        is_live2d = self.live2d.value.strip().lower() in {"是", "y", "yes", "true", "1"}
        try:
            await asyncio.to_thread(
                KnowledgeQueryRepository().update_suit_card_data,
                self.context.suit_id,
                self.event.id,
                self.event.acquisition_method_id,
                self.event.cost_text,
                is_live2d,
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.defer()
        await refresh_edit_card(self.parent_message, self.context.suit_id, self.event.id)


async def show_suit_raw_images(
    interaction: discord.Interaction, suit_id: int, suit_name: str, event: SuitEditEvent
) -> None:
    images = await asyncio.to_thread(KnowledgeQueryRepository().get_raw_images_for_event, event.id)
    await send_image_preview(interaction, suit_id, suit_name, event.name, images, replace_message=False)


class SuitImageEventSelect(discord.ui.Select):
    """Choose one event source before listing its raw announcement images."""

    def __init__(self, suit_id: int, suit_name: str, events: list[SuitEditEvent], owner_user_id: int) -> None:
        self.suit_id = suit_id
        self.suit_name = suit_name
        self.events = events
        self.owner_user_id = owner_user_id
        super().__init__(
            placeholder="選擇圖片來源活動",
            options=[discord.SelectOption(label=event.name[:100], value=str(event.id)) for event in events[:25]],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_view_owner(interaction, self.owner_user_id):
            return
        event = next(event for event in self.events if event.id == int(self.values[0]))
        images = await asyncio.to_thread(KnowledgeQueryRepository().get_raw_images_for_event, event.id)
        await send_image_preview(interaction, self.suit_id, self.suit_name, event.name, images, replace_message=True)


class SuitImageEventSelectView(discord.ui.View):
    def __init__(self, suit_id: int, suit_name: str, events: list[SuitEditEvent], owner_user_id: int) -> None:
        super().__init__(timeout=600)
        self.message: discord.InteractionMessage | None = None
        self.add_item(SuitImageEventSelect(suit_id, suit_name, events, owner_user_id))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
