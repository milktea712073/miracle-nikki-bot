"""Authorization checks for Discord administration interactions."""

from __future__ import annotations

import os

import discord


def _configured_ids(variable_name: str) -> set[int]:
    """Read a comma-separated set of Discord snowflakes from the environment."""
    values: set[int] = set()
    for raw_value in os.getenv(variable_name, "").split(","):
        value = raw_value.strip()
        if value.isdigit():
            values.add(int(value))
    return values


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
    """Send a private denial response when the user is not an administrator."""
    if is_administrator(interaction):
        return True
    message = "你沒有使用草稿管理功能的權限。"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
    return False
