"""Regression coverage for the read-only JoyBomb draft HTML export."""

from __future__ import annotations

from pathlib import Path

from content.section_splitter import split_notice_sections
from crawler.models import Post
from database.database import get_connection, init_database
from database.parse_draft_repository import ParseDraftRepository
from database.raw_post_repository import RawPostRepository
from parser.models import ParseDraft, SuitCandidate
from scripts.data.parse_raw_posts import parse_pending_raw_posts
from scripts.diagnostic.export_joybomb_draft_report import export_report


def _save_joybomb_raw(database_path: Path, post_id: str, content: str, title: str) -> int:
    return RawPostRepository(database_path).save_raw_post(
        Post(
            post_id=post_id,
            url=f"https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K={post_id}",
            content=content,
            published_at=None,
            images=[],
            source="joybomb_archive",
            metadata={
                "title": title,
                "section": "1",
                "notice_id": post_id,
                "archive_url": f"https://web.archive.org/web/20200101000000/https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K={post_id}",
            },
        ),
        enqueue_announcement=False,
    ).raw_post_id


def test_report_escapes_source_text_and_handles_empty_candidates(tmp_path: Path) -> None:
    database_path = tmp_path / "report.db"
    raw_id = _save_joybomb_raw(
        database_path,
        "10001",
        "【活動一】<script>alert('raw')</script>",
        "<script>alert('title')</script>",
    )
    section = split_notice_sections(
        "【活動一】<script>alert('raw')</script>",
        source="joybomb_archive",
        raw_post_id=raw_id,
    ).sections[0]
    ParseDraftRepository(database_path).save_parse_draft(
        raw_id,
        "rules-v1",
        ParseDraft(
            title=None,
            event_name_candidate=None,
            official_series_candidate=None,
            period_type_candidate="unknown",
            start_at_candidate=None,
            end_at_candidate=None,
            player_category_candidate=None,
            acquisition_method_candidate=None,
            confidence=0.3,
            parser_notes=None,
            suits=[],
            content_type_candidate="other",
        ),
        section=section,
    )

    output = tmp_path / "report.html"
    summary = export_report(output, database_path)
    rendered = output.read_text(encoding="utf-8")

    assert summary.raw_posts == summary.sections == summary.drafts == 1
    assert "&lt;script&gt;alert(&#x27;title&#x27;)&lt;/script&gt;" in rendered
    assert "&lt;script&gt;alert(&#x27;raw&#x27;)&lt;/script&gt;" in rendered
    assert "活動名稱候選</dt><dd>未辨識" in rendered
    assert "套裝候選</dt><dd>無" in rendered


def test_report_renders_all_multi_section_drafts_and_filter_controls(tmp_path: Path) -> None:
    database_path = tmp_path / "multi.db"
    content = "【活動一】套裝【海沙暢想】\n【活動二】登入送"
    raw_id = _save_joybomb_raw(database_path, "10002", content, "多段公告")
    sections = split_notice_sections(content, source="joybomb_archive", raw_post_id=raw_id).sections
    repository = ParseDraftRepository(database_path)
    for section in sections:
        repository.save_parse_draft(
            raw_id,
            "rules-v1",
            ParseDraft(
                title="多段公告", event_name_candidate=section.heading,
                official_series_candidate=None, period_type_candidate="unknown",
                start_at_candidate=None, end_at_candidate=None,
                player_category_candidate=None, acquisition_method_candidate=None,
                confidence=0.9, parser_notes=None,
                suits=[SuitCandidate("海沙暢想", 1.0)] if section.section_index == 1 else [],
                content_type_candidate="event",
            ),
            section=section,
        )

    output = tmp_path / "multi.html"
    summary = export_report(output, database_path)
    rendered = output.read_text(encoding="utf-8")

    assert summary.multi_section_raw_posts == 1
    assert rendered.count("class=\"section-card\"") == 2
    assert "切分原因：explicit_activity" in rendered
    for control_id in ("search", "year", "type", "rec", "multi", "suits", "story"):
        assert f'id="{control_id}"' in rendered
    assert "Wayback" in rendered


def test_export_does_not_write_knowledge_or_announcement_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "readonly.db"
    init_database(database_path)
    _save_joybomb_raw(database_path, "10003", "純文字公告", "空候選公告")
    before_connection = get_connection(database_path)
    try:
        before = {
            table: before_connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("events", "suits", "event_periods", "announcement_jobs")
        }
    finally:
        before_connection.close()

    export_report(tmp_path / "readonly.html", database_path)

    after_connection = get_connection(database_path)
    try:
        after = {
            table: after_connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in before
        }
    finally:
        after_connection.close()
    assert after == before


def test_full_draft_only_reparse_is_idempotent_and_never_creates_queue_jobs(tmp_path: Path) -> None:
    database_path = tmp_path / "draft-only.db"
    _save_joybomb_raw(database_path, "10004", "【活動一】套裝【海沙暢想】", "公告一")
    _save_joybomb_raw(database_path, "10005", "【活動一】登入送", "公告二")

    first = parse_pending_raw_posts(10, database_path, source="joybomb_archive", draft_only=True)
    second = parse_pending_raw_posts(10, database_path, source="joybomb_archive", draft_only=True)
    connection = get_connection(database_path)
    try:
        draft_count = connection.execute("SELECT COUNT(*) FROM parse_drafts").fetchone()[0]
        queue_count = connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0]
        knowledge_counts = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("events", "suits", "event_periods")
        ]
    finally:
        connection.close()

    assert first.selected == 2
    assert second.selected == 0
    assert draft_count == first.drafts
    assert queue_count == 0
    assert knowledge_counts == [0, 0, 0]
