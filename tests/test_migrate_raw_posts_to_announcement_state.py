"""Migration tests for copied legacy raw announcements in v2 state storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from announcement.history_archive import ArchivedRawPost, HistoricalRawArchive
from announcement.history_search import AnnouncementHistorySearchService
from scripts.migrations.migrate_raw_posts_to_announcement_state import main, read_legacy_archive


def create_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE raw_posts (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                source_post_id TEXT NOT NULL,
                url TEXT NOT NULL,
                content TEXT NOT NULL,
                published_at TEXT,
                scraped_at TEXT,
                updated_at TEXT,
                parse_status TEXT,
                parse_error TEXT,
                content_hash TEXT,
                metadata_json TEXT
            );
            CREATE TABLE raw_post_images (
                id INTEGER PRIMARY KEY,
                raw_post_id INTEGER NOT NULL,
                image_url TEXT NOT NULL,
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO raw_posts (id, source, source_post_id, url, content, published_at, scraped_at,
                                   updated_at, parse_status, parse_error, content_hash, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "facebook", "post-1", "https://www.facebook.com/post-1", "first body", "2024-01-01", "s1", "u1", "done", None, "h1", '{"title":"First"}'),
                (2, "joybomb_archive", "notice-2", "https://joybomb.example/2", "second body", "2023-01-01", "s2", "u2", "done", None, "h2", '{"title":"Second"}'),
            ],
        )
        connection.executemany(
            "INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at) VALUES (?, ?, ?, ?)",
            [
                (1, "https://images.example/first-b.png", 1, "i1"),
                (1, "https://images.example/first-a.png", 0, "i2"),
                (1, "https://images.example/first-a.png", 2, "i3"),
                (2, "https://images.example/second.png", 0, "i4"),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def state_counts(path: Path) -> tuple[int, int, int]:
    connection = sqlite3.connect(path)
    try:
        return tuple(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("raw_posts", "raw_post_images", "announcement_deliveries")
        )
    finally:
        connection.close()


def test_dry_run_reads_legacy_database_without_creating_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    legacy_path = tmp_path / "database.db"
    state_path = tmp_path / "announcement_state.db"
    create_legacy_database(legacy_path)

    assert main(["--legacy-database", str(legacy_path), "--state-database", str(state_path), "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "Legacy raw_posts: 2" in output
    assert "Would insert raw_posts: 2" in output
    assert "Dry run only" in output
    assert state_path.exists() is False


def test_migration_is_idempotent_preserves_images_and_never_creates_delivery(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    legacy_path = tmp_path / "database.db"
    state_path = tmp_path / "announcement_state.db"
    create_legacy_database(legacy_path)

    assert main(["--legacy-database", str(legacy_path), "--state-database", str(state_path)]) == 0
    first_output = capsys.readouterr().out
    assert "insert raw_posts: 2" in first_output
    assert state_counts(state_path) == (2, 3, 0)

    connection = sqlite3.connect(state_path)
    try:
        images = [
            row[0]
            for row in connection.execute(
                """
                SELECT i.image_url FROM raw_post_images i
                JOIN raw_posts r ON r.id = i.raw_post_id
                WHERE r.source_post_id = 'post-1'
                ORDER BY i.position, i.id
                """
            )
        ]
        assert images == ["https://images.example/first-a.png", "https://images.example/first-b.png"]
        legacy_rows = connection.execute("SELECT COUNT(*) FROM raw_posts WHERE legacy_raw_post_id IN (1, 2)").fetchone()[0]
        assert legacy_rows == 2
    finally:
        connection.close()

    assert main(["--legacy-database", str(legacy_path), "--state-database", str(state_path)]) == 0
    second_output = capsys.readouterr().out
    assert "insert raw_posts: 0" in second_output
    assert "Existing/skip raw_posts: 2" in second_output
    assert state_counts(state_path) == (2, 3, 0)
    legacy_path.unlink()
    assert AnnouncementHistorySearchService(state_database_path=state_path).search("first").results[0].source_kind == "raw_post"


def test_archive_rolls_back_if_one_batch_row_conflicts(tmp_path: Path) -> None:
    archive = HistoricalRawArchive(tmp_path / "announcement_state.db")
    first = ArchivedRawPost(1, "facebook", "a", "https://example.test/a", "a", None, None, None, None, None, None, None)
    conflicting = ArchivedRawPost(1, "facebook", "b", "https://example.test/b", "b", None, None, None, None, None, None, None)

    with pytest.raises(sqlite3.IntegrityError):
        archive.synchronize((first, conflicting), (), migrated_at="test")

    connection = sqlite3.connect(tmp_path / "announcement_state.db")
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 0
    finally:
        connection.close()


def test_reader_opens_source_in_read_only_mode_and_keeps_all_metadata(tmp_path: Path) -> None:
    legacy_path = tmp_path / "database.db"
    create_legacy_database(legacy_path)

    posts, images = read_legacy_archive(legacy_path)

    assert posts[0].metadata_json == '{"title":"First"}'
    assert posts[0].content_hash == "h1"
    assert [image.position for image in images if image.legacy_raw_post_id == 1] == [0, 1, 2]
