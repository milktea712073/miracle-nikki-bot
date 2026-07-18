"""Raw-only integration coverage for the formal JoyBomb Wayback importer."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from crawler.joybomb_archive_crawler import (
    CdxIndexResult,
    CdxSnapshot,
    JoyBombArchiveNotice,
    parse_notice_id,
)
from database.announcement_identity import canonical_announcement_url
from database.database import get_connection
from database.raw_post_repository import RawPostRepository
from scripts.data.import_joybomb_archive import (
    JOYBOMB_ARCHIVE_SOURCE,
    import_joybomb_archive,
    notice_to_post,
)


def _snapshot(timestamp: str, original_url: str) -> CdxSnapshot:
    return CdxSnapshot(timestamp, original_url, "200", "text/html", timestamp)


def _notice(snapshot: CdxSnapshot, *, title: str = "JoyBomb Notice", images: list[str] | None = None) -> JoyBombArchiveNotice:
    notice_id = parse_notice_id(snapshot.original_url)
    assert notice_id is not None
    return JoyBombArchiveNotice(
        archive_timestamp=snapshot.timestamp,
        original_url=snapshot.original_url,
        archive_url=f"https://web.archive.org/web/{snapshot.timestamp}/{snapshot.original_url}",
        notice_id=notice_id,
        title=title,
        published_at="2018-01-02T00:00:00+00:00",
        content_html="<div class='notice-content'><p>Official notice body.</p></div>",
        content_text="Official notice body.",
        image_original_urls=images or ["https://nu3.joybomb.com.tw/images/one.jpg"],
        image_archive_urls=[],
        template_signature="joybomb_notice_v1",
        parse_warnings=[],
    )


def _index(snapshots: list[CdxSnapshot]) -> CdxIndexResult:
    return CdxIndexResult(snapshots=snapshots, query_failures={})


def test_joybomb_import_canonicalizes_variants_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb.db"
    desktop = _snapshot(
        "20170623052813",
        "http://nu3.joybomb.com.tw:80/notice/noticecontent?N=1&K=10061&lang=zh",
    )
    mobile = _snapshot(
        "20170903065128",
        "https://www.nu3.joybomb.com.tw/mobile/noticecontent?K=10061&N=1",
    )
    path = _snapshot(
        "20180101010101",
        "https://nu3.joybomb.com.tw/notice/noticecontent/2/10062/0/1?lang=zh",
    )
    snapshots = [desktop, mobile, path]
    parsed = [_notice(desktop), _notice(path, title="Path notice", images=["https://images.example/a.jpg", "https://images.example/b.jpg"])]

    first = import_joybomb_archive(
        database_path=database_path,
        index_fetcher=lambda **_kwargs: _index(snapshots),
        detail_crawler=lambda _snapshots, **_kwargs: parsed,
    )
    second = import_joybomb_archive(
        database_path=database_path,
        index_fetcher=lambda **_kwargs: _index(snapshots),
        detail_crawler=lambda _snapshots, **_kwargs: parsed,
    )

    assert first.discovered_notices == 2
    assert first.storage.inserted == 2
    assert first.raw_images_inserted == 3
    assert first.duplicate_urls == 1
    assert first.duplicate_identities == 1
    assert second.storage.inserted == 0
    assert second.storage.updated == 0
    assert second.storage.unchanged == 2

    repository = RawPostRepository(database_path)
    legacy = repository.get_raw_post_by_source_id("1:10061", source=JOYBOMB_ARCHIVE_SOURCE)
    later = repository.get_raw_post_by_source_id("2:10062", source=JOYBOMB_ARCHIVE_SOURCE)
    assert legacy is not None
    assert legacy["url"] == "https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10061"
    assert later is not None
    assert later["images"] == ["https://images.example/a.jpg", "https://images.example/b.jpg"]
    assert {row["notice_id"] for row in first.samples} == {"10061", "10062"}

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM raw_post_images").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM parse_drafts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        connection.close()


def test_joybomb_import_updates_changed_raw_content_without_duplicate_images(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-update.db"
    snapshot = _snapshot("20180101010101", "https://nu3.joybomb.com.tw/notice/noticecontent/1/10061/0")
    original = _notice(snapshot, images=["https://images.example/a.jpg", "https://images.example/a.jpg"])
    changed = replace(original, content_text="Corrected body.")

    first = import_joybomb_archive(
        database_path=database_path,
        index_fetcher=lambda **_kwargs: _index([snapshot]),
        detail_crawler=lambda _snapshots, **_kwargs: [original],
    )
    second = import_joybomb_archive(
        database_path=database_path,
        index_fetcher=lambda **_kwargs: _index([snapshot]),
        detail_crawler=lambda _snapshots, **_kwargs: [changed],
    )

    assert first.raw_images_inserted == 1
    assert second.storage.updated == 1
    assert second.raw_images_updated == 1
    row = RawPostRepository(database_path).get_raw_post_by_source_id("1:10061", source=JOYBOMB_ARCHIVE_SOURCE)
    assert row is not None
    assert row["content"].endswith("Corrected body.")
    assert row["images"] == ["https://images.example/a.jpg"]


def test_missing_html_is_skipped_and_never_creates_raw_or_queue_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-missing.db"
    snapshot = _snapshot("20180101010101", "https://nu3.joybomb.com.tw/notice/noticecontent/1/10061/0")
    failed = JoyBombArchiveNotice(
        archive_timestamp=snapshot.timestamp,
        original_url=snapshot.original_url,
        archive_url="https://archive.example/failed",
        notice_id="10061",
        title=None,
        published_at=None,
        content_html="",
        content_text="",
        image_original_urls=[],
        image_archive_urls=[],
        template_signature="request_failed",
        parse_warnings=["request_failed"],
    )

    result = import_joybomb_archive(
        database_path=database_path,
        index_fetcher=lambda **_kwargs: _index([snapshot]),
        detail_crawler=lambda _snapshots, **_kwargs: [failed],
    )

    assert result.missing_html == 1
    assert result.storage.inserted == 0
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
    finally:
        connection.close()


def test_notice_to_post_keeps_source_identity_and_optional_published_at() -> None:
    snapshot = _snapshot("20180101010101", "https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10061")
    notice = _notice(snapshot)
    post = notice_to_post(notice)
    assert post is not None
    assert post.source == JOYBOMB_ARCHIVE_SOURCE
    assert post.post_id == "1:10061"
    assert post.url == "https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10061"


def test_notice_to_post_uses_clean_body_without_repeating_title() -> None:
    snapshot = _snapshot("20180101010101", "https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10061")
    notice = _notice(snapshot, title="公告標題")
    post = notice_to_post(notice)

    assert post is not None
    assert post.content == "Official notice body."
    assert post.metadata is not None
    assert post.metadata["title"] == "公告標題"


def test_non_facebook_raw_urls_preserve_identity_query_parameters() -> None:
    assert canonical_announcement_url(
        "https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10061"
    ) == "https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10061"
