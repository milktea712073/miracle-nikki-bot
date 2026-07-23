"""Discord runtime configuration stays environment-driven in every deployment."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import bot.main as bot_main


class FakeCommandTree:
    def __init__(self) -> None:
        self.copied_to: list[object] = []
        self.synced_to: list[object | None] = []

    def copy_global_to(self, *, guild: object) -> None:
        self.copied_to.append(guild)

    async def sync(self, *, guild: object | None = None) -> list[str]:
        self.synced_to.append(guild)
        return ["command"]


def test_optional_guild_id_is_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("GUILD_ID", "123456789012345678")

    assert bot_main.load_optional_snowflake("GUILD_ID") == 123456789012345678


def test_invalid_discord_runtime_settings_fail_fast(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_MESSAGE_CONTENT_INTENT", "sometimes")
    with pytest.raises(RuntimeError, match="DISCORD_MESSAGE_CONTENT_INTENT"):
        bot_main.load_boolean("DISCORD_MESSAGE_CONTENT_INTENT", default=True)

    monkeypatch.setenv("DISCORD_EMBEDS_PER_MESSAGE", "11")
    with pytest.raises(RuntimeError, match="DISCORD_EMBEDS_PER_MESSAGE"):
        bot_main.load_bounded_integer("DISCORD_EMBEDS_PER_MESSAGE", 10, 1, 10)


def test_development_guild_sync_does_not_sync_global_commands(monkeypatch) -> None:
    tree = FakeCommandTree()
    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: None)
    monkeypatch.setattr(bot_main, "APP_ENV", "development")
    monkeypatch.setattr(bot_main, "GUILD_ID", 123456789012345678)

    asyncio.run(bot_main.MiracleNikkiBot.setup_hook(SimpleNamespace(tree=tree)))

    assert len(tree.copied_to) == 1
    assert tree.copied_to[0].id == 123456789012345678
    assert tree.synced_to == tree.copied_to


def test_production_without_guild_id_preserves_global_sync(monkeypatch) -> None:
    tree = FakeCommandTree()
    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: None)
    monkeypatch.setattr(bot_main, "APP_ENV", "production")
    monkeypatch.setattr(bot_main, "GUILD_ID", None)

    asyncio.run(bot_main.MiracleNikkiBot.setup_hook(SimpleNamespace(tree=tree)))

    assert tree.copied_to == []
    assert tree.synced_to == [None]


def test_disabled_pipeline_keeps_discord_command_setup_without_initializing_state(monkeypatch) -> None:
    tree = FakeCommandTree()

    def state_store_should_not_run() -> None:
        raise AssertionError("announcement state must not initialize when disabled")

    monkeypatch.setattr(bot_main, "AnnouncementStateStore", state_store_should_not_run)
    monkeypatch.setattr(bot_main, "ENABLE_ANNOUNCEMENT_PIPELINE", False)
    monkeypatch.setattr(bot_main, "GUILD_ID", None)

    asyncio.run(bot_main.MiracleNikkiBot.setup_hook(SimpleNamespace(tree=tree)))

    assert tree.synced_to == [None]
