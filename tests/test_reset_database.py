from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from database.database import get_connection, init_database
from scripts.reset_database import reset_database


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def insert_sample_records(database_path: Path) -> None:
    connection = get_connection(database_path)
    try:
        announcement_id = connection.execute(
            "INSERT INTO announcements (publish_time, content, post_url) VALUES (?, ?, ?)",
            ("2026-07-12T00:00:00+00:00", "announcement", "https://example.test/posts/1"),
        ).lastrowid
        connection.execute(
            "INSERT INTO images (announcement_id, image_url) VALUES (?, ?)",
            (announcement_id, "https://example.test/image.jpg"),
        )
        raw_post_id = connection.execute(
            """
            INSERT INTO raw_posts (
                source, source_post_id, url, content, published_at, scraped_at, updated_at, parse_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "facebook",
                "post-1",
                "https://example.test/raw/1",
                "raw post",
                "2026-07-12T00:00:00+00:00",
                "2026-07-12T00:00:00+00:00",
                "2026-07-12T00:00:00+00:00",
                "pending",
            ),
        ).lastrowid
        connection.execute(
            "INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at) VALUES (?, ?, ?, ?)",
            (raw_post_id, "https://example.test/raw-image.jpg", 0, "2026-07-12T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO event_types (name) VALUES (?)", ("普通活動",)
        )
        connection.commit()
    finally:
        connection.close()


def test_reset_preserves_tables_and_clears_business_records(tmp_path: Path) -> None:
    database_path = tmp_path / "database.db"
    init_database(database_path)
    insert_sample_records(database_path)

    connection = get_connection(database_path)
    try:
        connection.execute("CREATE TABLE schema_version (version TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_version (version) VALUES ('1')")
        tables_before = table_names(connection)
        connection.commit()
    finally:
        connection.close()

    result = reset_database(database_path)

    connection = get_connection(database_path)
    try:
        assert table_names(connection) == tables_before
        for table_name in ("announcements", "images", "raw_posts", "raw_post_images", "event_types"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0] == 0
        assert connection.execute("SELECT version FROM schema_version").fetchone()[0] == "1"
    finally:
        connection.close()

    assert {"announcements", "raw_posts", "parse_drafts", "images"}.issubset(result.cleared_tables)


def test_reset_restarts_autoincrement_ids_at_one(tmp_path: Path) -> None:
    database_path = tmp_path / "database.db"
    init_database(database_path)
    insert_sample_records(database_path)

    reset_database(database_path)

    connection = get_connection(database_path)
    try:
        announcement_id = connection.execute(
            "INSERT INTO announcements (publish_time, content, post_url) VALUES (?, ?, ?)",
            ("2026-07-12T00:00:00+00:00", "new announcement", "https://example.test/posts/new"),
        ).lastrowid
    finally:
        connection.close()

    assert announcement_id == 1


def test_reset_warns_and_continues_when_expected_tables_are_missing(
    tmp_path: Path, caplog
) -> None:
    database_path = tmp_path / "database.db"
    connection = get_connection(database_path)
    try:
        connection.execute(
            "CREATE TABLE announcements (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO announcements (content) VALUES ('sample')")
        connection.commit()
    finally:
        connection.close()

    with caplog.at_level(logging.WARNING):
        result = reset_database(database_path)

    assert result.cleared_tables == ("announcements",)
    assert "raw_posts does not exist" in caplog.text
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 0
    finally:
        connection.close()
