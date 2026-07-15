from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crawler.models import Post
from database.database import get_connection, init_database
from database.raw_post_repository import RawPostBatchResult, RawPostRepository
from scripts.data.fetch_raw_posts import FetchRawPostsResult, fetch_and_save_raw_posts
from scripts.data.fetch_website_posts import FetchWebsitePostsResult
from scripts.data.parse_raw_posts import ParseRawPostsResult, parse_pending_raw_posts
from scripts.data.rebuild_database import RebuildResult, main, rebuild_database
from scripts.data.reset_database import ResetResult


def sample_post() -> Post:
    return Post(
        post_id="rebuild-post",
        url="https://example.test/rebuild-post",
        content="【全新】測試活動\n2026/07/13 05:00 - 2026/07/19 23:59",
        published_at=datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc),
        images=[],
    )


def fake_result() -> RebuildResult:
    return RebuildResult(
        ResetResult((), (), True),
        FetchRawPostsResult(1, RawPostBatchResult(inserted=1)),
        ParseRawPostsResult(1, 1, 0, 0, 0),
        1,
        0,
    )


def test_rebuild_requires_exact_yes_before_running() -> None:
    calls: list[int] = []

    exit_code = main(["--limit", "7"], input_fn=lambda _: "yes", runner=lambda limit: calls.append(limit) or fake_result())

    assert exit_code == 0
    assert calls == []


def test_rebuild_runs_reset_fetch_parse_in_order_and_passes_limit(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, int | None]] = []
    monkeypatch.setattr("scripts.data.rebuild_database.count_knowledge_records", lambda _: (2, 3))

    result = rebuild_database(
        50,
        tmp_path / "rebuild.db",
        resetter=lambda _: calls.append(("reset", None)) or ResetResult((), (), True),
        fetcher=lambda limit, _: calls.append(("fetch", limit)) or FetchRawPostsResult(2, RawPostBatchResult(inserted=2)),
        parser=lambda limit, _: calls.append(("parse", limit)) or ParseRawPostsResult(2, 2, 0, 0, 1),
    )

    assert calls == [("reset", None), ("fetch", 50), ("parse", 50)]
    assert result.event_count == 2
    assert result.suit_count == 3


def test_rebuild_include_website_fetches_both_sources_without_queue_enqueue(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, int | None]] = []
    monkeypatch.setattr("scripts.data.rebuild_database.count_knowledge_records", lambda _: (2, 3))

    result = rebuild_database(
        10,
        tmp_path / "rebuild-website.db",
        resetter=lambda _: calls.append(("reset", None)) or ResetResult((), (), True),
        fetcher=lambda limit, _: calls.append(("facebook", limit)) or FetchRawPostsResult(10, RawPostBatchResult(inserted=10)),
        website_fetcher=lambda limit, _: calls.append(("website", limit)) or FetchWebsitePostsResult(10, 0, RawPostBatchResult(inserted=10)),
        parser=lambda limit, _: calls.append(("parse", limit)) or ParseRawPostsResult(20, 20, 0, 0, 0),
        include_website=True,
    )

    assert calls == [("reset", None), ("facebook", 10), ("website", 10), ("parse", 20)]
    assert result.website_fetch is not None
    assert result.website_fetch.storage.inserted == 10


def test_reset_failure_stops_fetch_and_parse(tmp_path: Path) -> None:
    calls: list[str] = []

    with pytest.raises(RuntimeError, match="reset"):
        rebuild_database(
            1,
            tmp_path / "reset-failure.db",
            resetter=lambda _: (_ for _ in ()).throw(RuntimeError("reset failed")),
            fetcher=lambda *_: calls.append("fetch") or FetchRawPostsResult(0, RawPostBatchResult()),
            parser=lambda *_: calls.append("parse") or ParseRawPostsResult(0, 0, 0, 0, 0),
        )
    assert calls == []


def test_fetch_failure_stops_parse(tmp_path: Path) -> None:
    calls: list[str] = []

    with pytest.raises(RuntimeError, match="fetch"):
        rebuild_database(
            1,
            tmp_path / "fetch-failure.db",
            resetter=lambda _: ResetResult((), (), True),
            fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("fetch failed")),
            parser=lambda *_: calls.append("parse") or ParseRawPostsResult(0, 0, 0, 0, 0),
        )
    assert calls == []


def test_parse_failure_keeps_raw_posts(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "parse-failure.db"
    RawPostRepository(database_path).save_raw_post(sample_post())
    monkeypatch.setattr("scripts.data.parse_raw_posts.parse_announcement", lambda _: (_ for _ in ()).throw(RuntimeError("bad parser")))

    result = parse_pending_raw_posts(1, database_path)

    assert result.failed == 1
    assert RawPostRepository(database_path).get_raw_post_by_source_id("rebuild-post") is not None


def test_fetch_core_passes_limit_to_crawler_and_does_not_send_discord(tmp_path: Path) -> None:
    limits: list[int] = []

    result = fetch_and_save_raw_posts(
        12,
        tmp_path / "fetch.db",
        crawler=lambda limit: limits.append(limit) or [sample_post()],
    )

    assert limits == [12]
    assert result.fetched_count == 1
    assert result.storage.inserted == 1


def test_database_locked_message_is_friendly(capsys) -> None:
    exit_code = main(
        [],
        input_fn=lambda _: "YES",
        runner=lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    assert exit_code == 1
    assert "Database is locked" in capsys.readouterr().out


def test_reset_announcements_requires_second_exact_confirmation() -> None:
    calls: list[int] = []
    answers = iter(("YES", "NO"))

    exit_code = main(
        ["--reset-announcements"],
        input_fn=lambda _: next(answers),
        runner=lambda limit: calls.append(limit) or fake_result(),
    )

    assert exit_code == 0
    assert calls == []


def test_existing_script_cores_can_run_independently(tmp_path: Path) -> None:
    database_path = tmp_path / "standalone.db"
    init_database(database_path)
    fetched = fetch_and_save_raw_posts(1, database_path, crawler=lambda _: [sample_post()])
    parsed = parse_pending_raw_posts(1, database_path)
    connection = get_connection(database_path)
    try:
        raw_count = connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0]
    finally:
        connection.close()

    assert fetched.fetched_count == 1
    assert parsed.succeeded == 1
    assert raw_count == 1
