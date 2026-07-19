"""Regression coverage for SQLite startup and short-lived connection behavior."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from datetime import datetime, timezone

import pytest
from bot import main as bot_main
from crawler.models import Post
from database import database as database_module
from database.database import get_connection, init_database
from database.knowledge_query_repository import KnowledgeQueryRepository
from database.raw_post_repository import RawPostRepository


def test_writer_waits_for_a_temporary_lock_then_succeeds(tmp_path) -> None:
    database_path = tmp_path / "locked.db"
    init_database(database_path)
    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def hold_write_lock() -> None:
        connection = get_connection(database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO event_types (name, is_active) VALUES (?, 1)",
                ("temporary lock",),
            )
            lock_acquired.set()
            assert release_lock.wait(timeout=5)
            connection.commit()
        finally:
            connection.close()

    holder = threading.Thread(target=hold_write_lock)
    holder.start()
    assert lock_acquired.wait(timeout=5)
    timer = threading.Timer(0.15, release_lock.set)
    timer.start()
    started_at = time.monotonic()
    waiting_connection = get_connection(database_path)
    try:
        waiting_connection.execute(
            "INSERT INTO event_types (name, is_active) VALUES (?, 1)",
            ("waited writer",),
        )
        waiting_connection.commit()
    finally:
        waiting_connection.close()
        timer.cancel()
        release_lock.set()
        holder.join(timeout=5)

    assert time.monotonic() - started_at >= 0.1
    connection = get_connection(database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM event_types WHERE name = ?", ("waited writer",)
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        connection.close()


def test_query_repository_connect_does_not_run_schema_initialization(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "query.db"
    init_database(database_path)
    repository = KnowledgeQueryRepository(database_path)

    def fail_if_called(*_args, **_kwargs) -> None:
        raise AssertionError("Repository connection unexpectedly initialized schema")

    monkeypatch.setattr(
        database_module, "initialize_knowledge_base_tables", fail_if_called
    )
    connection = repository._connect()
    try:
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    finally:
        connection.close()


def test_repository_rollback_releases_a_write_lock_after_an_error(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "rollback.db"
    init_database(database_path)
    repository = RawPostRepository(database_path)

    def fail_image_write(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated image write failure")

    monkeypatch.setattr(repository, "_insert_images", fail_image_write)
    with pytest.raises(RuntimeError, match="simulated image write failure"):
        repository.save_raw_post(
            Post(
                post_id="rollback-post",
                url="https://www.facebook.com/TwNikkiNikki/posts/rollback-post",
                content="content",
                published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
                images=["https://example.test/image.jpg"],
            )
        )

    next_connection = get_connection(database_path)
    try:
        next_connection.execute(
            "INSERT INTO event_types (name, is_active) VALUES (?, 1)",
            ("available after rollback",),
        )
        next_connection.commit()
        names = {
            row[0]
            for row in next_connection.execute(
                "SELECT name FROM event_types WHERE name IN (?, ?)",
                ("rolled back", "available after rollback"),
            )
        }
    finally:
        next_connection.close()

    assert names == {"available after rollback"}
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 0
    finally:
        connection.close()


def test_bot_startup_initializes_only_v2_announcement_state(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "announcement-state.db"
    from announcement.state_store import AnnouncementStateStore

    monkeypatch.setattr(bot_main, "AnnouncementStateStore", lambda: AnnouncementStateStore(database_path))

    async def fake_sync() -> list[object]:
        return []

    monkeypatch.setattr(bot_main.bot.tree, "sync", fake_sync)
    asyncio.run(bot_main.bot.setup_hook())

    connection = sqlite3.connect(database_path)
    try:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert {
        "announcements",
        "announcement_deliveries",
        "reminders",
    }.issubset(table_names)
    assert {"raw_posts", "announcement_jobs", "events", "suits"}.isdisjoint(table_names)
