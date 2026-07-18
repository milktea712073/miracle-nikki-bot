from __future__ import annotations

import json
from pathlib import Path

from crawler.models import Post
from database.database import get_connection, init_database
from database.raw_post_repository import RawPostRepository
from scripts.data.refresh_joybomb_raw_content import refresh_joybomb_raw_content


def _save_joybomb_raw(database_path: Path, post_id: str, content: str, *, content_html: str | None) -> int:
    metadata = {
        "archive_timestamp": "20190821182603",
        "original_url": f"https://nu3.joybomb.com.tw/notice/noticecontent/1/{post_id}/0",
        "title": "正文標題",
    }
    if content_html is not None:
        metadata["content_html"] = content_html
    return RawPostRepository(database_path).save_raw_post(
        Post(
            post_id=f"1:{post_id}",
            url=metadata["original_url"],
            content=content,
            published_at=None,
            images=["https://images.example/one.jpg"],
            source="joybomb_archive",
            metadata=metadata,
        ),
        enqueue_announcement=False,
    ).raw_post_id


def test_refresh_rebuilds_clean_body_without_changing_row_metadata_or_jobs(tmp_path: Path) -> None:
    database_path = tmp_path / "refresh.db"
    raw_post_id = _save_joybomb_raw(
        database_path,
        "10101",
        "正文標題\n正文標題\n2019.08.21\n活動一、正文",
        content_html=(
            "<div class='content_bg'><h1>正文標題</h1><span>2019.08.21</span>"
            "<p>活動一、正文</p><a>返回公告列表</a></div>"
        ),
    )
    connection = get_connection(database_path)
    try:
        before = connection.execute(
            "SELECT source_post_id, url, published_at, metadata_json FROM raw_posts WHERE id = ?", (raw_post_id,)
        ).fetchone()
    finally:
        connection.close()

    result = refresh_joybomb_raw_content(database_path)

    assert result.scanned == result.changed == 1
    connection = get_connection(database_path)
    try:
        after = connection.execute(
            "SELECT id, source_post_id, url, content, published_at, metadata_json FROM raw_posts WHERE id = ?",
            (raw_post_id,),
        ).fetchone()
        assert after[0] == raw_post_id
        assert after[1:3] == before[:2]
        assert after[3] == "活動一、正文"
        assert after[4:] == before[2:]
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        connection.close()


def test_refresh_skips_missing_html_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "refresh-idempotent.db"
    raw_post_id = _save_joybomb_raw(database_path, "10102", "保留原文", content_html=None)

    missing = refresh_joybomb_raw_content(database_path)
    assert missing.content_html_missing == 1
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT content FROM raw_posts WHERE id = ?", (raw_post_id,)).fetchone()[0] == "保留原文"
    finally:
        connection.close()

    html = "<div class='content_bg'><h1>正文標題</h1><p>乾淨正文</p></div>"
    metadata = {
        "archive_timestamp": "20190821182603",
        "original_url": "https://nu3.joybomb.com.tw/notice/noticecontent/1/10102/0",
        "title": "正文標題",
        "content_html": html,
    }
    connection = get_connection(database_path)
    try:
        connection.execute("UPDATE raw_posts SET metadata_json = ? WHERE id = ?", (json.dumps(metadata), raw_post_id))
        connection.commit()
    finally:
        connection.close()

    first = refresh_joybomb_raw_content(database_path)
    second = refresh_joybomb_raw_content(database_path)
    assert first.changed == 1
    assert second.changed == 0
    assert second.unchanged == 1


def test_refresh_dry_run_does_not_write_raw_or_derived_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "refresh-dry-run.db"
    raw_post_id = _save_joybomb_raw(
        database_path,
        "10103",
        "舊正文",
        content_html="<div class='content_bg'><p>新正文</p></div>",
    )

    result = refresh_joybomb_raw_content(database_path, dry_run=True)

    assert result.changed == 1
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT content FROM raw_posts WHERE id = ?", (raw_post_id,)).fetchone()[0] == "舊正文"
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM parse_drafts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        connection.close()
