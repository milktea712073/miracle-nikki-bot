"""Discord modal forms for editing reviewed parse-draft data."""

from __future__ import annotations

import asyncio

import discord

from bot.admin.checks import require_administrator
from bot.admin.review_data import get_draft_review_data
from database.review_repository import ReviewRepository


def _optional(value: str) -> str | None:
    return value.strip() or None


def _is_live2d(value: str) -> bool:
    return value.strip().lower() in {"y", "yes", "是", "true", "1"}


class ReviewDetailsModal(discord.ui.Modal):
    """Edit the non-list fields of a human review."""

    def __init__(self, draft_id: int, is_mansion: bool) -> None:
        self.draft_id = draft_id
        self.is_mansion = is_mansion
        data = get_draft_review_data(draft_id)
        review = data.review
        super().__init__(title="編輯草稿資料")
        self.event_name = discord.ui.TextInput(
            label="活動名稱",
            default=str(review["confirmed_event_name"] or ""),
            max_length=200,
        )
        self.official_series = discord.ui.TextInput(
            label="官方系列（可留空）",
            default=str(review["official_series"] or ""),
            required=False,
            max_length=200,
        )
        self.event_cost = discord.ui.TextInput(
            label="活動總花費（可留空）",
            default=str(review["event_cost_text"] or ""),
            required=False,
            max_length=200,
        )
        self.review_notes = discord.ui.TextInput(
            label="審核備註（可留空）",
            default=str(review["review_notes"] or ""),
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.add_item(self.event_name)
        self.add_item(self.official_series)
        self.add_item(self.event_cost)
        self.add_item(self.review_notes)
        if is_mansion:
            self.live2d_cost = discord.ui.TextInput(
                label="Live2D 花費（可留空）",
                default=str(review["live2d_cost_text"] or ""),
                required=False,
                max_length=200,
            )
            self.add_item(self.live2d_cost)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        values: dict[str, object] = {
            "confirmed_event_name": self.event_name.value.strip(),
            "official_series": _optional(self.official_series.value),
            "event_cost_text": _optional(self.event_cost.value),
            "review_notes": _optional(self.review_notes.value),
        }
        if self.is_mansion:
            values["live2d_cost_text"] = _optional(self.live2d_cost.value)
        await asyncio.to_thread(ReviewRepository().save_review, self.draft_id, **values)
        await interaction.response.send_message("已儲存草稿資料。", ephemeral=True)


class SuitEditModal(discord.ui.Modal):
    """Create or edit one review-suit including order and Live2D status."""

    def __init__(self, draft_id: int, suit_index: int | None = None) -> None:
        self.draft_id = draft_id
        self.suit_index = suit_index
        data = get_draft_review_data(draft_id)
        suits = list(data.review["suits"])
        existing = suits[suit_index] if suit_index is not None else None
        super().__init__(title="編輯套裝" if existing else "新增套裝")
        self.suit_name = discord.ui.TextInput(
            label="套裝名稱",
            default=str(existing["suit_name"]) if existing else "",
            max_length=200,
        )
        self.position = discord.ui.TextInput(
            label="顯示順序（從 1 開始）",
            default=str((suit_index or 0) + 1 if existing else len(suits) + 1),
            max_length=3,
        )
        self.live2d = discord.ui.TextInput(
            label="是否為 Live2D（是／否）",
            default="是" if existing and existing["is_live2d"] else "否",
            max_length=3,
        )
        self.cost = discord.ui.TextInput(
            label="單套花費（可留空）",
            default=str(existing["cost_text"] or "") if existing else "",
            required=False,
            max_length=200,
        )
        self.notes = discord.ui.TextInput(
            label="備註（可留空）",
            default=str(existing["notes"] or "") if existing else "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        for item in (self.suit_name, self.position, self.live2d, self.cost, self.notes):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        try:
            requested_position = int(self.position.value)
        except ValueError:
            await interaction.response.send_message("顯示順序必須是正整數。", ephemeral=True)
            return
        if requested_position < 1:
            await interaction.response.send_message("顯示順序必須從 1 開始。", ephemeral=True)
            return

        data = await asyncio.to_thread(get_draft_review_data, self.draft_id)
        suits = [dict(suit) for suit in data.review["suits"]]
        replacement = {
            "suit_name": self.suit_name.value.strip(),
            "is_live2d": _is_live2d(self.live2d.value),
            "cost_text": _optional(self.cost.value),
            "notes": _optional(self.notes.value),
        }
        if self.suit_index is None:
            suits.append(replacement)
            moved = suits.pop()
        else:
            if self.suit_index >= len(suits):
                await interaction.response.send_message("套裝資料已變更，請重新開啟編輯器。", ephemeral=True)
                return
            suits[self.suit_index] = replacement
            moved = suits.pop(self.suit_index)
        suits.insert(min(requested_position - 1, len(suits)), moved)
        await asyncio.to_thread(ReviewRepository().replace_review_suits, self.draft_id, suits)
        await interaction.response.send_message("已儲存套裝資料。", ephemeral=True)


class RejectModal(discord.ui.Modal):
    """Record a rejection reason and mark the draft as rejected."""

    def __init__(self, draft_id: int) -> None:
        self.draft_id = draft_id
        super().__init__(title="拒絕草稿")
        self.reason = discord.ui.TextInput(
            label="拒絕原因",
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        data = await asyncio.to_thread(get_draft_review_data, self.draft_id)
        old_notes = str(data.review["review_notes"] or "").strip()
        reason = self.reason.value.strip()
        notes = f"{old_notes}\n拒絕原因：{reason}".strip()
        repository = ReviewRepository()
        await asyncio.to_thread(repository.save_review, self.draft_id, review_notes=notes)
        await asyncio.to_thread(repository.update_draft_status, self.draft_id, "rejected")
        await interaction.response.send_message("草稿已拒絕，原因已保存。", ephemeral=True)
