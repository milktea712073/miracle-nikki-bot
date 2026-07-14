"""Administrator controls attached directly to a suit information card."""

from __future__ import annotations

import asyncio

import discord

from bot.admin.checks import require_administrator
from bot.admin.knowledge_image_views import require_view_owner, send_image_preview
from database.knowledge_query_repository import KnowledgeQueryRepository, SuitEditContext, SuitEditEvent


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
        super().__init__(title="編輯套裝資訊")
        self.name = discord.ui.TextInput(label="套裝名稱", default=context.suit_name)
        self.event_type = discord.ui.TextInput(
            label="活動分類",
            default=event.event_type or "",
            required=False,
            placeholder="例如：普通活動／故事套裝／體力套／登入送"
        )
        self.method = discord.ui.TextInput(label="取得方式", default=event.acquisition_method or "", required=False,placeholder="例如：花鑽／免費／儲值／聯盟／體力")
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
