"""Administrator image preview and assignment views backed by raw post images."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import discord

from bot.admin.checks import require_administrator
from database.knowledge_query_repository import (
    KnowledgeQueryRepository,
    RawPostImageView,
    SuitImageCandidate,
)


PINK = discord.Color.from_rgb(255, 183, 197)


async def require_view_owner(interaction: discord.Interaction, owner_user_id: int) -> bool:
    """Require both administrator access and ownership of an ephemeral UI session."""
    if not await require_administrator(interaction):
        return False
    if interaction.user.id == owner_user_id:
        return True
    await interaction.response.send_message("這不是你的圖片管理介面。", ephemeral=True)
    return False


def is_previewable_url(image_url: str) -> bool:
    """Reject malformed URLs before Discord is asked to render an image."""
    parsed = urlparse(image_url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def create_image_preview_embed(
    suit_name: str,
    event_name: str,
    images: list[RawPostImageView],
    index: int,
    assigned: bool = False,
) -> discord.Embed:
    """Build one image-browser page with the selected raw image preview."""
    image = images[index]
    description = (
        f"套裝：{suit_name}\n"
        f"圖片：{index + 1} / {len(images)}\n"
        f"來源活動：{event_name}"
    )
    if assigned:
        description += "\n\n✅ 已指定為此套裝的主圖片。"
    embed = discord.Embed(title="🌸 選擇套裝圖片", description=description, color=PINK)
    if is_previewable_url(image.image_url):
        embed.set_image(url=image.image_url)
    else:
        embed.add_field(name="圖片預覽", value="此圖片目前無法預覽。", inline=False)
    return embed


class ImagePreviewView(discord.ui.View):
    """Browse raw images one at a time and assign the current one as primary."""

    def __init__(
        self,
        suit_id: int,
        suit_name: str,
        event_name: str,
        images: list[RawPostImageView],
        owner_user_id: int,
        index: int = 0,
    ) -> None:
        super().__init__(timeout=900)
        self.suit_id = suit_id
        self.suit_name = suit_name
        self.event_name = event_name
        self.images = images
        self.owner_user_id = owner_user_id
        self.index = index
        self.message: discord.InteractionMessage | None = None
        self.previous.disabled = index == 0
        self.next.disabled = index >= len(images) - 1

    def embed(self, assigned: bool = False) -> discord.Embed:
        return create_image_preview_embed(
            self.suit_name, self.event_name, self.images, self.index, assigned
        )

    async def _edit(self, interaction: discord.Interaction, assigned: bool = False) -> None:
        await interaction.response.edit_message(embed=self.embed(assigned), view=self)

    @discord.ui.button(label="◀️ 上一張", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_view_owner(interaction, self.owner_user_id):
            return
        self.index -= 1
        self.previous.disabled = self.index == 0
        self.next.disabled = False
        await self._edit(interaction)

    @discord.ui.button(label="▶️ 下一張", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_view_owner(interaction, self.owner_user_id):
            return
        self.index += 1
        self.previous.disabled = False
        self.next.disabled = self.index >= len(self.images) - 1
        await self._edit(interaction)

    @discord.ui.button(label="✅ 設為主圖", style=discord.ButtonStyle.success)
    async def set_primary(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_view_owner(interaction, self.owner_user_id):
            return
        image = self.images[self.index]
        await asyncio.to_thread(
            KnowledgeQueryRepository().assign_primary_image_to_suit,
            self.suit_id,
            image.id,
        )
        await interaction.response.edit_message(
            content=f"已將圖片 {self.index + 1} 設為「{self.suit_name}」的主圖片。",
            embed=self.embed(assigned=True),
            view=self,
        )

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_view_owner(interaction, self.owner_user_id):
            return
        await interaction.response.edit_message(content="已取消圖片指定。", embed=None, view=None)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def send_image_preview(
    interaction: discord.Interaction,
    suit_id: int,
    suit_name: str,
    event_name: str,
    images: list[RawPostImageView],
    *,
    replace_message: bool,
) -> None:
    """Open the preview browser from either a button or a select interaction."""
    if not images:
        message = "此活動沒有可用圖片。"
        if replace_message:
            await interaction.response.edit_message(content=message, embed=None, view=None)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return
    view = ImagePreviewView(
        suit_id=suit_id,
        suit_name=suit_name,
        event_name=event_name,
        images=images,
        owner_user_id=interaction.user.id,
    )
    if replace_message:
        view.message = interaction.message
        await interaction.response.edit_message(embed=view.embed(), view=view)
    else:
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


class EventSuitSelect(discord.ui.Select):
    """Choose the event suit that will receive the selected preview image."""

    def __init__(
        self, event_id: int, event_name: str, suits: list[SuitImageCandidate], owner_user_id: int
    ) -> None:
        self.event_id = event_id
        self.event_name = event_name
        self.suits = suits
        self.owner_user_id = owner_user_id
        super().__init__(
            placeholder="選擇要指定圖片的套裝",
            options=[discord.SelectOption(label=suit.name[:100], value=str(suit.id)) for suit in suits[:25]],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_view_owner(interaction, self.owner_user_id):
            return
        suit = next(suit for suit in self.suits if suit.id == int(self.values[0]))
        images = await asyncio.to_thread(
            KnowledgeQueryRepository().get_raw_images_for_event, self.event_id
        )
        await send_image_preview(
            interaction,
            suit.id,
            suit.name,
            self.event_name,
            images,
            replace_message=True,
        )


class EventSuitSelectionView(discord.ui.View):
    """First step for event-card assignment: select a suit, then preview images."""

    def __init__(
        self, event_id: int, event_name: str, suits: list[SuitImageCandidate], owner_user_id: int
    ) -> None:
        super().__init__(timeout=900)
        self.message: discord.InteractionMessage | None = None
        self.add_item(EventSuitSelect(event_id, event_name, suits, owner_user_id))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class EventImageManagementView(discord.ui.View):
    """Expose event image assignment by selecting a suit before browsing previews."""

    def __init__(self, event_id: int, event_name: str) -> None:
        super().__init__(timeout=900)
        self.event_id = event_id
        self.event_name = event_name

    @discord.ui.button(label="🖼️ 編輯圖片", style=discord.ButtonStyle.secondary)
    async def edit_images(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await open_event_image_management(interaction, self.event_id, self.event_name)


async def open_event_image_management(
    interaction: discord.Interaction, event_id: int, event_name: str
) -> None:
    """Open the event image assignment flow from any administrator view."""
    repository = KnowledgeQueryRepository()
    images, suits = await asyncio.gather(
        asyncio.to_thread(repository.get_raw_images_for_event, event_id),
        asyncio.to_thread(repository.get_event_suits_for_image_assignment, event_id),
    )
    if not images:
        await interaction.response.send_message("此活動沒有可用圖片。", ephemeral=True)
        return
    if not suits:
        await interaction.response.send_message("此活動沒有可指定圖片的套裝。", ephemeral=True)
        return
    view = EventSuitSelectionView(event_id, event_name, suits, interaction.user.id)
    await interaction.response.send_message(
        "請先選擇要指定圖片的套裝：", view=view, ephemeral=True
    )
    view.message = await interaction.original_response()
