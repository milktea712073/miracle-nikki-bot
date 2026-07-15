from __future__ import annotations

import sqlite3
from pathlib import Path

from database.database import get_connection, init_database
from database.knowledge_repository import KnowledgeRepository


def test_same_name_different_source_raw_posts_create_distinct_events(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "event-source-identity.db"
    repository = KnowledgeRepository(database_path)
    connection = repository.connect()
    try:
        connection.execute("BEGIN")
        first_event_id = repository.upsert_auto_event(
            connection, "Same Event", None, "first source", 101
        )
        second_event_id = repository.upsert_auto_event(
            connection, "Same Event", None, "second source", 202
        )
        connection.commit()

        assert first_event_id != second_event_id
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    finally:
        connection.close()


def test_same_source_raw_post_updates_the_same_event(tmp_path: Path) -> None:
    database_path = tmp_path / "same-raw-post.db"
    repository = KnowledgeRepository(database_path)
    connection = repository.connect()
    try:
        connection.execute("BEGIN")
        first_event_id = repository.upsert_auto_event(
            connection, "Original Name", None, "first parser value", 101
        )
        connection.commit()

        connection.execute("BEGIN")
        second_event_id = repository.upsert_auto_event(
            connection, "Updated Name", None, "updated parser value", 101
        )
        connection.commit()

        assert first_event_id == second_event_id
        row = connection.execute(
            "SELECT name, description, source_raw_post_id FROM events WHERE id = ?",
            (first_event_id,),
        ).fetchone()
        assert row == ("Original Name", "updated parser value", 101)
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    finally:
        connection.close()


def test_manual_events_without_a_source_raw_post_do_not_auto_merge(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "manual-events.db"
    repository = KnowledgeRepository(database_path)
    connection = repository.connect()
    try:
        connection.execute("BEGIN")
        first_event_id = repository.create_event(
            connection, "Manual Event", None, None, None
        )
        second_event_id = repository.create_event(
            connection, "Manual Event", None, None, None
        )
        connection.commit()

        assert first_event_id != second_event_id
        rows = connection.execute(
            "SELECT source_raw_post_id FROM events WHERE name = ? ORDER BY id",
            ("Manual Event",),
        ).fetchall()
        assert rows == [(None,), (None,)]
    finally:
        connection.close()


def test_legacy_events_name_unique_constraint_is_migrated(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-events.db"
    legacy_connection = sqlite3.connect(database_path)
    try:
        legacy_connection.executescript(
            """
            CREATE TABLE event_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                official_series TEXT,
                event_type_id INTEGER,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (event_type_id) REFERENCES event_types(id)
            );
            CREATE TABLE event_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                period_type TEXT NOT NULL,
                start_at TEXT,
                end_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );
            INSERT INTO events (name, created_at, updated_at)
            VALUES ('Legacy Event', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            INSERT INTO event_periods (event_id, period_type, created_at)
            VALUES (1, 'debut', '2026-01-01T00:00:00+00:00');
            """
        )
        legacy_connection.commit()
    finally:
        legacy_connection.close()

    init_database(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute(
            "INSERT INTO events (name, created_at, updated_at) VALUES (?, ?, ?)",
            ("Legacy Event", "2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
        )
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE name = ?", ("Legacy Event",)
        ).fetchone()[0] == 2
        assert connection.execute("SELECT event_id FROM event_periods").fetchone() == (1,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
