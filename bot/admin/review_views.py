"""Discord views for reviewing, editing, and importing parse drafts."""

from __future__ import annotations

import asyncio
import logging

import discord

from bot.admin.checks import require_administrator
from bot.admin.review_data import (
    PERIOD_TYPE_LABELS,
    STATUS_LABELS,
    DraftReviewData,
    format_period,
    get_draft_review_data,
)
from bot.admin.review_modals import RejectModal, ReviewDetailsModal, SuitEditModal
from database.import_service import DraftImportError, import_parse_draft
from database.review_repository import ReviewRepository


LOGGER = logging.getLogger(__name__)
PINK = discord.Color.from_rgb(255, 183, 197)


def _value(value: object) -> str:
    return str(value) if value not in (None, "") else "未提供"


def create_draft_embed(data: DraftReviewData) -> discord.Embed:
    """Render parser output and editable review fields without changing them."""
    draft = data.draft
    review = data.review
    embed = discord.Embed(
        title=f"🌸 草稿審核 #{draft['id']}",
        description=_value(draft["title"]),
        color=PINK,
    )
    embed.add_field(name="Parser 辨識活動", value=_value(draft["event_name_candidate"]), inline=True)
    embed.add_field(name="審核活動名稱", value=_value(review["confirmed_event_name"]), inline=True)
    embed.add_field(
        name="草稿狀態",
        value=STATUS_LABELS.get(str(draft["status"]), str(draft["status"])),
        inline=True,
    )
    embed.add_field(
        name="活動時間",
        value=format_period(draft["start_at_candidate"], draft["end_at_candidate"]),
        inline=False,
    )
    embed.add_field(
        name="活動類型",
        value=PERIOD_TYPE_LABELS.get(
            str(draft["period_type_candidate"] or "unknown"), "未分類"
        ),
        inline=True,
    )
    embed.add_field(name="活動分類", value=data.event_type_name or "尚未選擇", inline=True)
    embed.add_field(
        name="取得方式", value=data.acquisition_method_name or "尚未選擇", inline=True
    )
    parser_suits = "\n".join(f"• {name}" for name in draft["suits"]) or "未辨識到套裝"
    review_suits = []
    for suit in review["suits"]:
        details = []
        if suit["is_live2d"]:
            details.append("Live2D")
        if suit["cost_text"]:
            details.append(str(suit["cost_text"]))
        suffix = f"（{'｜'.join(details)}）" if details else ""
        review_suits.append(f"• {suit['suit_name']}{suffix}")
    embed.add_field(name="Parser 找到的套裝", value=parser_suits[:1024], inline=False)
    embed.add_field(
        name="審核套裝",
        value=("\n".join(review_suits) or "尚未設定")[:1024],
        inline=False,
    )
    cost_lines = [f"活動總花費：{_value(review['event_cost_text'])}"]
    if review["live2d_cost_text"]:
        cost_lines.append(f"Live2D 花費：{review['live2d_cost_text']}")
    embed.add_field(name="花費", value="\n".join(cost_lines), inline=False)
    embed.add_field(name="官方系列", value=_value(review["official_series"]), inline=True)
    embed.add_field(name="審核備註", value=_value(review["review_notes"]), inline=False)
    if draft["parser_notes"]:
        embed.add_field(name="Parser 備註", value=str(draft["parser_notes"])[:1024], inline=False)
    return embed


class DraftReviewView(discord.ui.View):
    """Primary actions for one administrative draft-review session."""

    def __init__(self, draft_id: int, allow_import: bool = True) -> None:
        super().__init__(timeout=900)
        self.draft_id = draft_id
        self.allow_import = allow_import
        if not allow_import:
            self.remove_item(self.import_draft)

    async def _data(self) -> DraftReviewData:
        return await asyncio.to_thread(get_draft_review_data, self.draft_id)

    @discord.ui.button(label="重新整理", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        data = await self._data()
        await interaction.response.edit_message(
            embed=create_draft_embed(data),
            view=DraftReviewView(self.draft_id, allow_import=self.allow_import),
        )

    @discord.ui.button(label="編輯草稿", style=discord.ButtonStyle.primary, row=0)
    async def edit_details(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        data = await self._data()
        await interaction.response.send_modal(
            ReviewDetailsModal(self.draft_id, data.event_type_name == "大閣")
        )

    @discord.ui.button(label="活動分類", style=discord.ButtonStyle.secondary, row=0)
    async def choose_event_type(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.edit_message(
            content="請選擇活動分類：",
            embed=None,
            view=ReferenceSelectView(self.draft_id, "event_types"),
        )

    @discord.ui.button(label="取得方式", style=discord.ButtonStyle.secondary, row=0)
    async def choose_acquisition_method(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.edit_message(
            content="請選擇取得方式：",
            embed=None,
            view=ReferenceSelectView(self.draft_id, "acquisition_methods"),
        )

    @discord.ui.button(label="編輯套裝", style=discord.ButtonStyle.secondary, row=1)
    async def edit_suits(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        data = await self._data()
        await interaction.response.edit_message(
            content=None,
            embed=create_suit_embed(self.draft_id, data),
            view=SuitEditorView(self.draft_id, data),
        )

    @discord.ui.button(label="標記已確認", style=discord.ButtonStyle.success, row=1)
    async def import_draft(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        try:
            await asyncio.to_thread(ReviewRepository().validate_review_ready, self.draft_id)
        except ValueError:
            await interaction.response.send_message(
                "尚未完成：活動名稱、活動分類、取得方式及至少一套套裝都必須填寫。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "草稿驗證通過。確定要匯入正式 Knowledge Base 嗎？",
            view=ConfirmImportView(self.draft_id),
            ephemeral=True,
        )

    @discord.ui.button(label="拒絕", style=discord.ButtonStyle.danger, row=1)
    async def reject_draft(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.send_modal(RejectModal(self.draft_id))

    @discord.ui.button(label="忽略", style=discord.ButtonStyle.secondary, row=1)
    async def ignore_draft(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.send_message(
            "確定要忽略此草稿嗎？這不會匯入正式資料。",
            view=ConfirmIgnoreView(self.draft_id),
            ephemeral=True,
        )


class ReferenceSelect(discord.ui.Select):
    """Persist one selected reference-data id to the existing review record."""

    def __init__(self, draft_id: int, table: str) -> None:
        self.draft_id = draft_id
        self.table = table
        options = ReviewRepository().get_reference_options(table)
        label = "活動分類" if table == "event_types" else "取得方式"
        super().__init__(
            placeholder=f"選擇{label}",
            options=[discord.SelectOption(label=name, value=str(option_id)) for option_id, name in options],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        field_name = "event_type_id" if self.table == "event_types" else "acquisition_method_id"
        await asyncio.to_thread(
            ReviewRepository().save_review,
            self.draft_id,
            **{field_name: int(self.values[0])},
        )
        data = await asyncio.to_thread(get_draft_review_data, self.draft_id)
        await interaction.response.edit_message(
            content=None,
            embed=create_draft_embed(data),
            view=DraftReviewView(self.draft_id),
        )


class ReferenceSelectView(discord.ui.View):
    """A one-selection view for event type or acquisition method."""

    def __init__(self, draft_id: int, table: str) -> None:
        super().__init__(timeout=300)
        self.add_item(ReferenceSelect(draft_id, table))


def create_suit_embed(draft_id: int, data: DraftReviewData) -> discord.Embed:
    """Show a compact list for the dedicated suit editor."""
    lines = []
    for position, suit in enumerate(data.review["suits"], 1):
        live2d = " Live2D" if suit["is_live2d"] else ""
        cost = f"｜{suit['cost_text']}" if suit["cost_text"] else ""
        lines.append(f"{position}. {suit['suit_name']}{live2d}{cost}")
    return discord.Embed(
        title=f"🌸 草稿 #{draft_id} 的套裝",
        description="\n".join(lines) or "目前沒有套裝。",
        color=PINK,
    )


class SuitEditSelect(discord.ui.Select):
    """Select a suit and open its five-field edit modal."""

    def __init__(self, draft_id: int, suits: list[dict[str, object]]) -> None:
        self.draft_id = draft_id
        super().__init__(
            placeholder="選擇要修改或排序的套裝",
            options=[
                discord.SelectOption(label=str(suit["suit_name"])[:100], value=str(index))
                for index, suit in enumerate(suits[:25])
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.send_modal(SuitEditModal(self.draft_id, int(self.values[0])))


class SuitDeleteSelect(discord.ui.Select):
    """Select a suit and ask for a confirmation before deleting it."""

    def __init__(self, draft_id: int, suits: list[dict[str, object]]) -> None:
        self.draft_id = draft_id
        super().__init__(
            placeholder="選擇要刪除的套裝",
            options=[
                discord.SelectOption(label=str(suit["suit_name"])[:100], value=str(index))
                for index, suit in enumerate(suits[:25])
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        data = await asyncio.to_thread(get_draft_review_data, self.draft_id)
        index = int(self.values[0])
        suits = list(data.review["suits"])
        if index >= len(suits):
            await interaction.response.send_message("套裝資料已變更，請重新開啟編輯器。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"確定刪除套裝「{suits[index]['suit_name']}」嗎？",
            view=ConfirmDeleteSuitView(self.draft_id, index),
            ephemeral=True,
        )


class SuitEditorView(discord.ui.View):
    """Offer explicit add, edit/reorder, and delete controls for review suits."""

    def __init__(self, draft_id: int, data: DraftReviewData) -> None:
        super().__init__(timeout=900)
        self.draft_id = draft_id
        suits = list(data.review["suits"])
        if suits:
            self.add_item(SuitEditSelect(draft_id, suits))
            self.add_item(SuitDeleteSelect(draft_id, suits))

    @discord.ui.button(label="新增套裝", style=discord.ButtonStyle.primary, row=2)
    async def add_suit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.send_modal(SuitEditModal(self.draft_id))

    @discord.ui.button(label="返回草稿", style=discord.ButtonStyle.secondary, row=2)
    async def return_to_draft(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        data = await asyncio.to_thread(get_draft_review_data, self.draft_id)
        await interaction.response.edit_message(
            embed=create_draft_embed(data), view=DraftReviewView(self.draft_id)
        )


class ConfirmDeleteSuitView(discord.ui.View):
    """Avoid deleting a suit on a single select interaction."""

    def __init__(self, draft_id: int, suit_index: int) -> None:
        super().__init__(timeout=120)
        self.draft_id = draft_id
        self.suit_index = suit_index

    @discord.ui.button(label="確認刪除", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        data = await asyncio.to_thread(get_draft_review_data, self.draft_id)
        suits = [dict(suit) for suit in data.review["suits"]]
        if self.suit_index >= len(suits):
            await interaction.response.edit_message(content="套裝資料已變更，未執行刪除。", view=None)
            return
        deleted_name = suits.pop(self.suit_index)["suit_name"]
        await asyncio.to_thread(ReviewRepository().replace_review_suits, self.draft_id, suits)
        await interaction.response.edit_message(content=f"已刪除套裝「{deleted_name}」。", view=None)


class ConfirmImportView(discord.ui.View):
    """Second confirmation before the irreversible knowledge-base import step."""

    def __init__(self, draft_id: int) -> None:
        super().__init__(timeout=180)
        self.draft_id = draft_id

    @discord.ui.button(label="確認已確認", style=discord.ButtonStyle.success)
    async def confirm_import(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        repository = ReviewRepository()
        try:
            await asyncio.to_thread(repository.update_draft_status, self.draft_id, "approved")
            result = await asyncio.to_thread(import_parse_draft, self.draft_id)
        except (DraftImportError, ValueError) as error:
            LOGGER.warning("草稿 #%s 匯入遭拒：%s", self.draft_id, error)
            await interaction.followup.send(f"無法匯入：{error}", ephemeral=True)
        except Exception:
            LOGGER.exception("草稿 #%s 匯入失敗。", self.draft_id)
            await interaction.followup.send("匯入時發生未預期錯誤，資料未完成匯入。", ephemeral=True)
        else:
            await interaction.followup.send(
                f"已匯入正式資料：活動 #{result.event_id}，套裝 {len(result.suit_ids)} 套。",
                ephemeral=True,
            )


class ConfirmIgnoreView(discord.ui.View):
    """Second confirmation before marking a draft ignored."""

    def __init__(self, draft_id: int) -> None:
        super().__init__(timeout=120)
        self.draft_id = draft_id

    @discord.ui.button(label="確認忽略", style=discord.ButtonStyle.danger)
    async def confirm_ignore(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_administrator(interaction):
            return
        await asyncio.to_thread(ReviewRepository().update_draft_status, self.draft_id, "ignored")
        await interaction.response.edit_message(content="草稿已忽略，未匯入正式資料。", view=None)
