"""Slash commands that expose the administrative review interface."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from bot.admin.checks import require_administrator
from bot.admin.review_data import STATUS_LABELS, get_draft_review_data, list_pending_drafts
from bot.admin.review_views import DraftReviewView, create_draft_embed


LOGGER = logging.getLogger(__name__)


class PendingDraftSelect(discord.ui.Select):
    """Open a selected pending draft from the review-list message."""

    def __init__(self, draft_ids: list[int], labels: list[str], descriptions: list[str]) -> None:
        self.draft_ids = draft_ids
        super().__init__(
            placeholder="選擇要審核的草稿",
            options=[
                discord.SelectOption(
                    label=label[:100], value=str(draft_id), description=description[:100]
                )
                for draft_id, label, description in zip(draft_ids, labels, descriptions, strict=True)
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        draft_id = int(self.values[0])
        try:
            data = await asyncio.to_thread(get_draft_review_data, draft_id)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.edit_message(
            content=None,
            embed=create_draft_embed(data),
            view=DraftReviewView(draft_id),
        )


class PendingDraftListView(discord.ui.View):
    """A short, selectable list of pending drafts."""

    def __init__(self, drafts: list[object]) -> None:
        super().__init__(timeout=900)
        draft_ids = [int(data.draft["id"]) for data in drafts]
        labels = [
            f"#{data.draft['id']} {data.draft['title'] or data.draft['event_name_candidate'] or '未命名草稿'}"
            for data in drafts
        ]
        descriptions = [
            f"活動：{data.draft['event_name_candidate'] or '未辨識'}｜"
            f"{STATUS_LABELS.get(str(data.draft['status']), data.draft['status'])}"
            for data in drafts
        ]
        self.add_item(PendingDraftSelect(draft_ids, labels, descriptions))


def register_admin_commands(bot: discord.Client) -> None:
    """Register the three administrator-only slash commands on the bot tree."""

    @bot.tree.command(name="審核列表", description="列出待審核的公告草稿")
    async def review_list(interaction: discord.Interaction) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            drafts = await asyncio.to_thread(list_pending_drafts, 10)
        except Exception:
            LOGGER.exception("讀取待審核草稿失敗。")
            await interaction.followup.send("讀取待審核草稿時發生錯誤。", ephemeral=True)
            return
        if not drafts:
            await interaction.followup.send("目前沒有待審核草稿。", ephemeral=True)
            return
        lines = [
            f"#{data.draft['id']} {data.draft['title'] or data.draft['event_name_candidate'] or '未命名草稿'}"
            for data in drafts
        ]
        embed = discord.Embed(
            title="🌸 待審核草稿",
            description="\n".join(lines),
            color=discord.Color.from_rgb(255, 183, 197),
        )
        await interaction.followup.send(embed=embed, view=PendingDraftListView(drafts), ephemeral=True)

    @bot.tree.command(name="審核", description="開啟草稿審核與正式資料匯入流程")
    @app_commands.rename(draft_id="草稿id")
    @app_commands.describe(draft_id="要審核的草稿 ID")
    async def review_draft(interaction: discord.Interaction, draft_id: int) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await asyncio.to_thread(get_draft_review_data, draft_id)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            LOGGER.exception("開啟草稿 #%s 審核失敗。", draft_id)
            await interaction.followup.send("開啟草稿時發生錯誤。", ephemeral=True)
            return
        await interaction.followup.send(
            embed=create_draft_embed(data), view=DraftReviewView(draft_id), ephemeral=True
        )

    @bot.tree.command(name="編輯草稿", description="編輯草稿資料，但不執行正式資料匯入")
    @app_commands.rename(draft_id="草稿id")
    @app_commands.describe(draft_id="要編輯的草稿 ID")
    async def edit_draft(interaction: discord.Interaction, draft_id: int) -> None:
        if not await require_administrator(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await asyncio.to_thread(get_draft_review_data, draft_id)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            LOGGER.exception("開啟草稿 #%s 編輯失敗。", draft_id)
            await interaction.followup.send("開啟草稿時發生錯誤。", ephemeral=True)
            return
        await interaction.followup.send(
            embed=create_draft_embed(data),
            view=DraftReviewView(draft_id, allow_import=False),
            ephemeral=True,
        )
