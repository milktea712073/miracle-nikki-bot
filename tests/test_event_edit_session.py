from __future__ import annotations

import asyncio
from pathlib import Path

from bot.admin.knowledge_event_views import EventEditSession, complete_event_edit
from database.database import get_connection, init_database
from database.knowledge_query_repository import KnowledgeQueryRepository


class FakeMessage:
    def __init__(self) -> None:
        self.edits: list[dict[str, object]] = []

    async def edit(self, **kwargs: object) -> None:
        self.edits.append(kwargs)


class FakeChannel:
    def __init__(self, message: FakeMessage | None, fail_fetch: bool = False) -> None:
        self.message = message
        self.fail_fetch = fail_fetch
        self.sent: list[dict[str, object]] = []

    async def fetch_message(self, message_id: int) -> FakeMessage:
        if self.fail_fetch:
            raise AttributeError("message missing")
        assert message_id == 30
        assert self.message is not None
        return self.message

    async def send(self, **kwargs: object) -> None:
        self.sent.append(kwargs)


class FakeClient:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel = channel

    def get_channel(self, channel_id: int) -> FakeChannel:
        assert channel_id == 20
        return self.channel


class FakeInteraction:
    def __init__(self, channel: FakeChannel) -> None:
        self.client = FakeClient(channel)
        self.channel = channel


def seed_event(database_path: Path) -> int:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        event_id = connection.execute(
            "INSERT INTO events (name, created_at, updated_at) VALUES ('原活動', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        ).lastrowid
        connection.commit()
        return int(event_id)
    finally:
        connection.close()


def test_complete_edit_reads_latest_data_and_edits_original_card_once(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "session.db"
    event_id = seed_event(database_path)
    repository = KnowledgeQueryRepository(database_path)
    repository.update_event_management(
        event_id, name="最新活動", content_type="event", event_status=None,
        official_series=None, notes=None, start_at=None, end_at=None, is_visible=True,
    )
    monkeypatch.setattr("bot.admin.knowledge_event_views.KnowledgeQueryRepository", lambda: KnowledgeQueryRepository(database_path))
    source = FakeMessage()
    channel = FakeChannel(source)
    session = EventEditSession(10, 20, 30, event_id, 40)

    updated = asyncio.run(complete_event_edit(FakeInteraction(channel), session))

    assert updated is True
    assert len(source.edits) == 1
    assert source.edits[0]["embed"].title == "🌸 最新活動"
    assert channel.sent == []


def test_complete_edit_falls_back_to_one_new_card_when_original_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "fallback.db"
    event_id = seed_event(database_path)
    monkeypatch.setattr("bot.admin.knowledge_event_views.KnowledgeQueryRepository", lambda: KnowledgeQueryRepository(database_path))
    channel = FakeChannel(None, fail_fetch=True)
    session = EventEditSession(10, 20, 30, event_id, 40)

    updated = asyncio.run(complete_event_edit(FakeInteraction(channel), session))

    assert updated is False
    assert len(channel.sent) == 1


def test_section_database_save_does_not_edit_public_card(tmp_path: Path) -> None:
    database_path = tmp_path / "section.db"
    event_id = seed_event(database_path)
    public_card = FakeMessage()

    KnowledgeQueryRepository(database_path).synchronize_event_suits(event_id, ["校正套裝"])

    assert public_card.edits == []
    assert KnowledgeQueryRepository(database_path).get_event_suit_names(event_id) == ["校正套裝"]


def test_session_keeps_only_message_reference_identifiers() -> None:
    session = EventEditSession(10, 20, 30, 40, 50)

    assert (session.guild_id, session.channel_id, session.message_id, session.event_id) == (10, 20, 30, 40)
