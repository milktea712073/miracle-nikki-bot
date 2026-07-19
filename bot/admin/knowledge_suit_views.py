"""Administrator controls attached directly to a suit information card."""

from __future__ import annotations

import asyncio

import discord

from bot.admin.checks import require_administrator
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
        if context is None:
            await interaction.response.send_message("找不到可編輯的套裝資料。", ephemeral=True)
            return
        urls = await asyncio.to_thread(KnowledgeQueryRepository().get_suit_image_urls, context.suit_id)
        view = SuitImageManagementView(
            context.suit_id, context.suit_name, urls, interaction.user.id, interaction.message
        )
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


def create_suit_image_embed(suit_name: str, urls: list[str], index: int) -> discord.Embed:
    """Build the current SuitImages browser page without referring to raw posts."""
    total = len(urls)
    description = f"套裝：{suit_name}\n圖片：【{index + 1 if total else 0} / {total}】"
    embed = discord.Embed(title="🖼️ 編輯套裝圖片", description=description)
    if total:
        embed.set_image(url=urls[index])
    else:
        embed.add_field(name="圖片預覽", value="目前沒有圖片。可直接上傳第一張圖片。", inline=False)
    return embed


class SuitImageManagementView(discord.ui.View):
    """Page through Suit-owned images and replace the selected page by upload."""

    def __init__(
        self,
        suit_id: int,
        suit_name: str,
        urls: list[str],
        owner_user_id: int,
        public_message: discord.Message | discord.InteractionMessage | None,
    ) -> None:
        super().__init__(timeout=900)
        self.suit_id = suit_id
        self.suit_name = suit_name
        self.urls = urls
        self.owner_user_id = owner_user_id
        self.public_message = public_message
        self.index = 0
        self.message: discord.InteractionMessage | None = None
        self._update_navigation()

    def _update_navigation(self) -> None:
        self.previous.disabled = self.index <= 0 or not self.urls
        self.next.disabled = not self.urls or self.index >= len(self.urls) - 1

    def embed(self) -> discord.Embed:
        return create_suit_image_embed(self.suit_name, self.urls, self.index)

    async def _require_owner(self, interaction: discord.Interaction) -> bool:
        if not await require_administrator(interaction):
            return False
        if interaction.user.id == self.owner_user_id:
            return True
        await interaction.response.send_message("這不是你的圖片管理介面。", ephemeral=True)
        return False

    @discord.ui.button(label="⬅️ 上一張", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        self.index -= 1
        self._update_navigation()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="➡️ 下一張", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        self.index += 1
        self._update_navigation()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="📝 編輯圖片", style=discord.ButtonStyle.primary)
    async def upload(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._require_owner(interaction):
            return
        await interaction.response.send_message("請於 5 分鐘內上傳圖片，輸入「取消」可放棄。", ephemeral=True)
        try:
            message = await interaction.client.wait_for(
                "message",
                timeout=300,
                check=lambda candidate: (
                    candidate.author.id == self.owner_user_id
                    and candidate.channel.id == interaction.channel_id
                    and (bool(candidate.attachments) or candidate.content.strip() == "取消")
                ),
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("等待上傳已逾時，已取消。", ephemeral=True)
            return
        if message.content.strip() == "取消":
            await interaction.followup.send("已取消圖片上傳。", ephemeral=True)
            return

        image_url = message.attachments[0].url
        current_urls = await asyncio.to_thread(KnowledgeQueryRepository().get_suit_image_urls, self.suit_id)
        if current_urls:
            current_urls[min(self.index, len(current_urls) - 1)] = image_url
        else:
            current_urls = [image_url]
            self.index = 0
        await asyncio.to_thread(KnowledgeQueryRepository().save_suit_images, self.suit_id, current_urls)
        self.urls = await asyncio.to_thread(KnowledgeQueryRepository().get_suit_image_urls, self.suit_id)
        self.index = min(self.index, len(self.urls) - 1)
        self._update_navigation()
        if self.message is not None:
            await self.message.edit(embed=self.embed(), view=self)
        await self._refresh_public_card()
        await interaction.followup.send("圖片已更新。", ephemeral=True)

    async def _refresh_public_card(self) -> None:
        repository = KnowledgeQueryRepository()
        suit = await asyncio.to_thread(repository.get_suit_by_name, self.suit_name)
        if suit is not None and self.public_message is not None:
            image_url = await asyncio.to_thread(repository.get_display_image_for_suit, suit.id)
            from bot.main import create_suit_embed

            await self.public_message.edit(
                embed=create_suit_embed(suit, image_url, show_missing_category=True),
                view=SuitAdminView(suit.id),
            )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

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
            placeholder="例如：扭蛋／大閣／體力套／童話夢鄉"
        )
        self.method = discord.ui.TextInput(label="取得方式", default=event.acquisition_method or "", required=False,placeholder="例如：花鑽／免費／儲值／聯盟／體力")
        raw_cost = event.cost_text or ""
        self.cost = discord.ui.TextInput(label="花費數量", default=raw_cost, required=False)
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
