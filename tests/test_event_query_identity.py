from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import bot.main as bot_main
from database.database import get_connection, init_database
from database.knowledge_query_repository import KnowledgeQueryRepository


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False

    async def defer(self, **_kwargs: object) -> None:
        self.deferred = True


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def send(self, *args: object, **kwargs: object) -> None:
        self.messages.append((args, kwargs))


class FakeInteraction:
    def __init__(self) -> None:
        self.channel_id = 1
        self.user = SimpleNamespace(id=1)
        self.response = FakeResponse()
        self.followup = FakeFollowup()


def seed_events(database_path: Path) -> tuple[int, int, int]:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        duplicate_ids: list[int] = []
        for source_raw_post_id, start_at in (
            (101, "2026-05-01T05:00:00+08:00"),
            (202, "2026-06-01T05:00:00+08:00"),
        ):
            event_id = int(
                connection.execute(
                    """
                    INSERT INTO events (
                        name, content_type, source_raw_post_id, created_at, updated_at
                    ) VALUES ('同名活動', 'event', ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                    """,
                    (source_raw_post_id,),
                ).lastrowid
            )
            connection.execute(
                """
                INSERT INTO event_periods (event_id, period_type, start_at, end_at, created_at)
                VALUES (?, 'debut', ?, ?, '2026-01-01T00:00:00+00:00')
                """,
                (event_id, start_at, start_at.replace("05:00", "23:59")),
            )
            duplicate_ids.append(event_id)
        unique_id = int(
            connection.execute(
                """
                INSERT INTO events (name, content_type, created_at, updated_at)
                VALUES ('唯一活動', 'event', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            ).lastrowid
        )
        connection.commit()
        return duplicate_ids[0], duplicate_ids[1], unique_id
    finally:
        connection.close()


def configure_event_query(monkeypatch, repository: KnowledgeQueryRepository) -> None:
    async def allow_query(_interaction: object) -> bool:
        return True

    monkeypatch.setattr(bot_main, "KnowledgeQueryRepository", lambda: repository)
    monkeypatch.setattr(bot_main, "require_query_channel", allow_query)
    monkeypatch.setattr(bot_main, "is_administrator", lambda _interaction: False)
    monkeypatch.setattr(bot_main, "is_administrator_channel", lambda _channel_id: False)


def test_event_autocomplete_uses_distinct_event_ids_for_same_named_events(
    monkeypatch, tmp_path: Path
) -> None:
    first_id, second_id, _ = seed_events(tmp_path / "events.db")
    repository = KnowledgeQueryRepository(tmp_path / "events.db")
    configure_event_query(monkeypatch, repository)

    choices = asyncio.run(bot_main.event_name_autocomplete(FakeInteraction(), "同名"))

    assert {choice.value for choice in choices} == {str(first_id), str(second_id)}
    assert len({choice.value for choice in choices}) == 2


def test_selected_event_id_loads_the_matching_event_card(monkeypatch, tmp_path: Path) -> None:
    first_id, second_id, _ = seed_events(tmp_path / "events.db")
    repository = KnowledgeQueryRepository(tmp_path / "events.db")
    configure_event_query(monkeypatch, repository)

    first_interaction = FakeInteraction()
    second_interaction = FakeInteraction()
    asyncio.run(bot_main.event_command.callback(first_interaction, str(first_id)))
    asyncio.run(bot_main.event_command.callback(second_interaction, str(second_id)))

    first_embed = first_interaction.followup.messages[0][1]["embed"]
    second_embed = second_interaction.followup.messages[0][1]["embed"]
    assert "2026/05/01" in first_embed.description
    assert "2026/06/01" in second_embed.description


def test_direct_duplicate_event_name_does_not_silently_select_one(
    monkeypatch, tmp_path: Path
) -> None:
    seed_events(tmp_path / "events.db")
    repository = KnowledgeQueryRepository(tmp_path / "events.db")
    configure_event_query(monkeypatch, repository)
    interaction = FakeInteraction()

    asyncio.run(bot_main.event_command.callback(interaction, "同名活動"))

    assert interaction.response.deferred is True
    assert interaction.followup.messages == [
        (("找到多筆同名活動，請從自動完成選擇指定檔期。",), {"ephemeral": True})
    ]


def test_direct_unique_event_name_keeps_existing_lookup_behavior(
    monkeypatch, tmp_path: Path
) -> None:
    _, _, unique_id = seed_events(tmp_path / "events.db")
    repository = KnowledgeQueryRepository(tmp_path / "events.db")
    configure_event_query(monkeypatch, repository)
    interaction = FakeInteraction()

    asyncio.run(bot_main.event_command.callback(interaction, "唯一活動"))

    embed = interaction.followup.messages[0][1]["embed"]
    assert embed.title == "🌸 唯一活動"
    assert repository.get_event_by_name("唯一活動").id == unique_id
