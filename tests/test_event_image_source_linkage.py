"""Regression coverage for event image lookup by source raw-post identity."""

from __future__ import annotations

from pathlib import Path

from database.database import get_connection, init_database
from database.knowledge_query_repository import KnowledgeQueryRepository


def _insert_raw_post(connection, source_post_id: str, image_urls: list[str]) -> int:
    raw_post_id = connection.execute(
        """
        INSERT INTO raw_posts (source, source_post_id, url, content, scraped_at, updated_at)
        VALUES ('facebook', ?, ?, 'same event name appears here',
                '2026-07-17T00:00:00+00:00', '2026-07-17T00:00:00+00:00')
        """,
        (source_post_id, f"https://example.test/posts/{source_post_id}"),
    ).lastrowid
    connection.executemany(
        """
        INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at)
        VALUES (?, ?, ?, '2026-07-17T00:00:00+00:00')
        """,
        [(raw_post_id, url, position) for position, url in enumerate(image_urls)],
    )
    return int(raw_post_id)


def _insert_event(connection, name: str, source_raw_post_id: int | None) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO events (name, source_raw_post_id, created_at, updated_at)
            VALUES (?, ?, '2026-07-17T00:00:00+00:00', '2026-07-17T00:00:00+00:00')
            """,
            (name, source_raw_post_id),
        ).lastrowid
    )


def _event_images(database_path: Path, event_id: int) -> list[str]:
    return [item.image_url for item in KnowledgeQueryRepository(database_path).get_raw_images_for_event(event_id)]


def test_event_images_only_use_its_source_raw_post(tmp_path: Path) -> None:
    database_path = tmp_path / "event-images.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        first_raw_id = _insert_raw_post(connection, "first", ["https://images.test/first-1.jpg", "https://images.test/first-2.jpg"])
        _insert_raw_post(connection, "second", ["https://images.test/second.jpg"])
        event_id = _insert_event(connection, "Same event", first_raw_id)
        connection.commit()
    finally:
        connection.close()

    assert _event_images(database_path, event_id) == [
        "https://images.test/first-1.jpg",
        "https://images.test/first-2.jpg",
    ]


def test_same_named_events_do_not_share_images(tmp_path: Path) -> None:
    database_path = tmp_path / "same-name-events.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        first_raw_id = _insert_raw_post(connection, "first", ["https://images.test/first.jpg"])
        second_raw_id = _insert_raw_post(connection, "second", ["https://images.test/second.jpg"])
        first_event_id = _insert_event(connection, "Recurring event", first_raw_id)
        second_event_id = _insert_event(connection, "Recurring event", second_raw_id)
        connection.commit()
    finally:
        connection.close()

    assert _event_images(database_path, first_event_id) == ["https://images.test/first.jpg"]
    assert _event_images(database_path, second_event_id) == ["https://images.test/second.jpg"]


def test_event_without_source_raw_post_has_no_fallback_images(tmp_path: Path) -> None:
    database_path = tmp_path / "null-source.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        _insert_raw_post(connection, "matching-content", ["https://images.test/should-not-leak.jpg"])
        event_id = _insert_event(connection, "same event name", None)
        connection.commit()
    finally:
        connection.close()

    assert _event_images(database_path, event_id) == []


def test_multiple_section_events_can_share_their_one_raw_post_images(tmp_path: Path) -> None:
    database_path = tmp_path / "section-events.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        raw_post_id = _insert_raw_post(connection, "notice-1", ["https://images.test/notice-1.jpg"])
        first_event_id = _insert_event(connection, "Section one", raw_post_id)
        second_event_id = _insert_event(connection, "Section two", raw_post_id)
        connection.commit()
    finally:
        connection.close()

    assert _event_images(database_path, first_event_id) == ["https://images.test/notice-1.jpg"]
    assert _event_images(database_path, second_event_id) == ["https://images.test/notice-1.jpg"]
