"""Authorization checks for Discord administration interactions."""

from __future__ import annotations

import os
import logging

import discord


LOGGER = logging.getLogger(__name__)


def _configured_ids(variable_name: str) -> set[int]:
    """Read a comma-separated set of Discord snowflakes from the environment."""
    values: set[int] = set()
    for raw_value in os.getenv(variable_name, "").split(","):
        value = raw_value.strip()
        if value.isdigit():
            values.add(int(value))
    return values


def is_administrator_channel(channel_id: int | None) -> bool:
    """Return whether a channel is configured for administrator operations."""
    channel_ids = _configured_ids("ADMIN_CHANNEL_IDS")
    if not channel_ids:
        LOGGER.warning("ADMIN_CHANNEL_IDS is not configured; administrator actions are disabled.")
        return False
    return channel_id is not None and channel_id in channel_ids


def is_administrator(interaction: discord.Interaction) -> bool:
    """Return whether the interaction user is authorized to manage drafts."""
    if interaction.user.id in _configured_ids("DISCORD_ADMIN_USER_IDS"):
        return True

    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True

    allowed_role_ids = _configured_ids("DISCORD_ADMIN_ROLE_IDS")
    return any(role.id in allowed_role_ids for role in member.roles)


async def require_administrator(interaction: discord.Interaction) -> bool:
    """Require both an administrator identity and an administrator channel."""
    if not is_administrator_channel(getattr(interaction, "channel_id", None)):
        message = "請到指定的管理頻道進行編輯。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False
    if is_administrator(interaction):
        return True
    message = "你沒有使用草稿管理功能的權限。"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
    return False
