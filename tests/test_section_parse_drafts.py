"""Section-level parse draft persistence and JoyBomb draft-only coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from content.section_splitter import calculate_section_hash, split_notice_sections
from crawler.models import Post
from database.database import get_connection, init_database
from database.auto_import_service import auto_import_parse_draft
from database.raw_post_repository import RawPostRepository
from database.parse_draft_repository import ParseDraftRepository
from parser.models import ParseDraft, SuitCandidate
from scripts.data.parse_raw_posts import parse_pending_raw_posts


def _save_joybomb(database_path: Path, post_id: str, content: str) -> int:
    return RawPostRepository(database_path).save_raw_post(
        Post(
            post_id=post_id,
            url=f"https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K={post_id}",
            content=content,
            published_at=None,
            images=[],
            source="joybomb_archive",
            metadata={"title": "\u65b0\u805e\u516c\u544a"},
        ),
        enqueue_announcement=False,
    ).raw_post_id


def test_explicit_bracketed_and_emoji_activity_headings_preserve_all_text() -> None:
    content = (
        "\u5171\u540c\u524d\u8a00\n"
        "\u3010\u6d3b\u52d5\u4e00\u3011\u590f\u6cab\u6d77\u6b4c\n\u7b2c\u4e00\u6bb5\n"
        "\U0001f49f\u6d3b\u52d5\u4e8c\u3001\u767b\u5165\u9001\n\u7b2c\u4e8c\u6bb5\n"
        "\U0001f31f\u6d3b\u52d5\u4e09\uff1a\u7b2c\u4e09\u6bb5"
    )
    result = split_notice_sections(content, source="joybomb_archive")

    assert [section.heading for section in result.sections] == [None, "\u6d3b\u52d5\u4e00", "\u6d3b\u52d5\u4e8c", "\u6d3b\u52d5\u4e09"]
    assert [section.text for section in result.sections] == ["\u5171\u540c\u524d\u8a00", "\u590f\u6cab\u6d77\u6b4c\n\u7b2c\u4e00\u6bb5", "\u767b\u5165\u9001\n\u7b2c\u4e8c\u6bb5", "\u7b2c\u4e09\u6bb5"]
    assert "\u5171\u540c\u524d\u8a00" in result.sections[0].text
    assert "\u590f\u6cab\u6d77\u6b4c" in result.sections[1].text
    assert "\u767b\u5165\u9001" in result.sections[2].text
    assert "\u7b2c\u4e09\u6bb5" in result.sections[3].text


def test_section_hash_is_stable_for_whitespace_but_changes_for_content() -> None:
    first = calculate_section_hash("\u6d3b\u52d5\u4e00", "\u590f\u6cab\u6d77\u6b4c\n\n\u5167\u5bb9  ")
    same = calculate_section_hash(" \u6d3b\u52d5\u4e00 ", "  \u590f\u6cab\u6d77\u6b4c\r\n\r\n\u5167\u5bb9")
    changed_heading = calculate_section_hash("\u6d3b\u52d5\u4e8c", "\u590f\u6cab\u6d77\u6b4c\n\u5167\u5bb9")
    changed_body = calculate_section_hash("\u6d3b\u52d5\u4e00", "\u590f\u6cab\u6d77\u6b4c\n\u65b0\u5167\u5bb9")
    assert first == same
    assert first != changed_heading
    assert first != changed_body


def test_joybomb_multi_sections_create_distinct_drafts_and_never_auto_import(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-sections.db"
    raw_id = _save_joybomb(
        database_path,
        "10061",
        "\u3010\u6d3b\u52d5\u4e00\u3011\u590f\u6cab\u6d77\u6b4c\n\u5957\u88dd\u3010\u6d77\u6c99\u66a2\u60f3\u3011\n"
        "\u3010\u6d3b\u52d5\u4e8c\u3011\u767b\u5165\u9001\n\u6b61\u8fce\u767b\u5165",
    )

    result = parse_pending_raw_posts(10, database_path, source="joybomb_archive", draft_only=True)

    assert result.selected == result.succeeded == 1
    assert result.sections == result.drafts == 2
    assert result.multi_section_raw_posts == 1
    assert result.story_matches == 1
    assert len({row["section_hash"] for row in result.diagnostics}) == 2
    connection = get_connection(database_path)
    try:
        rows = connection.execute(
            "SELECT section_index, section_heading, splitter_version FROM parse_drafts WHERE raw_post_id = ? ORDER BY section_index",
            (raw_id,),
        ).fetchall()
        assert rows == [(1, "\u6d3b\u52d5\u4e00", "section-split-v1"), (2, "\u6d3b\u52d5\u4e8c", "section-split-v1")]
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
    finally:
        connection.close()


def test_joybomb_section_reparse_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "idempotent.db"
    _save_joybomb(database_path, "10062", "\u3010\u6d3b\u52d5\u4e00\u3011\u590f\u6cab\u6d77\u6b4c\n\u3010\u6d3b\u52d5\u4e8c\u3011\u767b\u5165\u9001")
    first = parse_pending_raw_posts(10, database_path, source="joybomb_archive", draft_only=True)
    second = parse_pending_raw_posts(10, database_path, source="joybomb_archive", force=True, raw_post_id=1, draft_only=True)
    assert first.drafts == second.drafts == 2
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM parse_drafts").fetchone()[0] == 2
    finally:
        connection.close()


def _sync_sections(content: str):
    return split_notice_sections(content, source="joybomb_archive").sections


def _sync_draft(section, suit_name: str) -> ParseDraft:
    return ParseDraft(
        title="同步測試",
        event_name_candidate=section.text,
        official_series_candidate=None,
        period_type_candidate="unknown",
        start_at_candidate=None,
        end_at_candidate=None,
        player_category_candidate=None,
        acquisition_method_candidate=None,
        confidence=0.9,
        parser_notes=None,
        suits=[SuitCandidate(suit_name, 0.9)],
        content_type_candidate="event",
    )


def _save_sync_sections(repository: ParseDraftRepository, raw_post_id: int, sections) -> None:
    for section in sections:
        repository.save_parse_draft(
            raw_post_id, "rules-v1", _sync_draft(section, f"suit-{section.text}"), section=section
        )


def _section_rows(database_path: Path, raw_post_id: int):
    connection = get_connection(database_path)
    try:
        return connection.execute(
            "SELECT id, section_hash, event_name_candidate FROM parse_drafts "
            "WHERE raw_post_id = ? ORDER BY event_name_candidate",
            (raw_post_id,),
        ).fetchall()
    finally:
        connection.close()


def test_joybomb_sync_removes_obsolete_section_draft_and_its_suits(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-sync-remove.db"
    raw_post_id = _save_joybomb(database_path, "10101", "old")
    repository = ParseDraftRepository(database_path)
    _save_sync_sections(repository, raw_post_id, _sync_sections("【活動一】A\n【活動二】B\n【活動三】C"))

    current = _sync_sections("【活動一】A\n【活動二】B")
    result = repository.sync_joybomb_section_drafts(
        raw_post_id, "rules-v1", [(section, _sync_draft(section, f"suit-{section.text}")) for section in current]
    )

    assert result.deleted_obsolete == 1
    assert [row[2] for row in _section_rows(database_path, raw_post_id)] == ["A", "B"]
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM parse_draft_suits").fetchone()[0] == 2
    finally:
        connection.close()


def test_joybomb_sync_adds_new_section_without_duplicate_current_drafts(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-sync-add.db"
    raw_post_id = _save_joybomb(database_path, "10102", "old")
    repository = ParseDraftRepository(database_path)
    _save_sync_sections(repository, raw_post_id, _sync_sections("【活動一】A\n【活動二】B"))

    current = _sync_sections("【活動一】A\n【活動二】B\n【活動三】C")
    first = repository.sync_joybomb_section_drafts(
        raw_post_id, "rules-v1", [(section, _sync_draft(section, f"suit-{section.text}")) for section in current]
    )
    second = repository.sync_joybomb_section_drafts(
        raw_post_id, "rules-v1", [(section, _sync_draft(section, f"suit-{section.text}")) for section in current]
    )

    assert first.deleted_obsolete == second.deleted_obsolete == 0
    assert [row[2] for row in _section_rows(database_path, raw_post_id)] == ["A", "B", "C"]


def test_joybomb_sync_preserves_current_hashes_and_replaces_only_difference(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-sync-replace.db"
    raw_post_id = _save_joybomb(database_path, "10103", "old")
    repository = ParseDraftRepository(database_path)
    _save_sync_sections(repository, raw_post_id, _sync_sections("【活動一】A\n【活動二】B\n【活動三】C"))
    before_ids = {row[2]: row[0] for row in _section_rows(database_path, raw_post_id)}

    current = _sync_sections("【活動一】A\n【活動三】C\n【活動四】D")
    result = repository.sync_joybomb_section_drafts(
        raw_post_id, "rules-v1", [(section, _sync_draft(section, f"suit-{section.text}")) for section in current]
    )
    after_ids = {row[2]: row[0] for row in _section_rows(database_path, raw_post_id)}

    assert result.deleted_obsolete == 1
    assert after_ids["A"] == before_ids["A"]
    assert after_ids["C"] == before_ids["C"]
    assert "B" not in after_ids
    assert "D" in after_ids


def test_joybomb_reparse_syncs_stale_hashes_at_the_raw_post_boundary(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-script-sync.db"
    raw_post_id = _save_joybomb(
        database_path, "10104", "前言\n【活動一】A\n【活動二】B"
    )
    first = parse_pending_raw_posts(1, database_path, source="joybomb_archive", draft_only=True)
    assert first.drafts == 3

    RawPostRepository(database_path).save_raw_post(
        Post(
            post_id="10104",
            url="https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10104",
            content="【活動一】A\n【活動二】B",
            published_at=None,
            images=[],
            source="joybomb_archive",
            metadata={"title": "新聞公告"},
        ),
        enqueue_announcement=False,
    )
    second = parse_pending_raw_posts(1, database_path, source="joybomb_archive", draft_only=True)

    assert second.drafts == 2
    assert [row[2] for row in _section_rows(database_path, raw_post_id)] == ["A", "B"]


def test_joybomb_sync_rolls_back_obsolete_deletion_when_current_save_fails(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "joybomb-sync-rollback.db"
    raw_post_id = _save_joybomb(database_path, "10105", "old")
    repository = ParseDraftRepository(database_path)
    _save_sync_sections(repository, raw_post_id, _sync_sections("【活動一】A\n【活動二】B\n【活動三】C"))
    before = _section_rows(database_path, raw_post_id)
    current = _sync_sections("【活動一】A\n【活動二】B")

    def fail_replace(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated suit write failure")

    monkeypatch.setattr(repository, "replace_parse_draft_suits", fail_replace)
    with pytest.raises(RuntimeError, match="simulated suit write failure"):
        repository.sync_joybomb_section_drafts(
            raw_post_id,
            "rules-v1",
            [(section, _sync_draft(section, f"suit-{section.text}")) for section in current],
        )

    assert _section_rows(database_path, raw_post_id) == before


def test_joybomb_draft_only_mode_does_not_auto_import(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-no-auto-import.db"
    _save_joybomb(database_path, "10064", "\u5957\u88dd\u3010\u6d77\u6c99\u66a2\u60f3\u3011")

    result = parse_pending_raw_posts(
        1, database_path, source="joybomb_archive", draft_only=True
    )

    assert result.succeeded == 1
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT status FROM parse_drafts").fetchone()[0] == "pending"
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
    finally:
        connection.close()


def test_joybomb_normal_parse_auto_imports_sections(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-auto-import-via-script.db"
    _save_joybomb(
        database_path,
        "10066",
        "【活動一】夏沫海歌\n套裝【海沙暢想】\n"
        "【活動二】暮色花園\n套裝【星夜花園】",
    )

    result = parse_pending_raw_posts(1, database_path, source="joybomb_archive")

    assert result.succeeded == 1
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM event_suits").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
    finally:
        connection.close()


def test_joybomb_sections_auto_import_as_distinct_idempotent_events(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-section-auto-import.db"
    raw_post_id = _save_joybomb(
        database_path,
        "10065",
        "【活動一】夏沫海歌\n套裝【海沙暢想】\n"
        "【活動二】暮色花園\n套裝【星夜花園】",
    )
    sections = split_notice_sections(
        "【活動一】夏沫海歌\n套裝【海沙暢想】\n"
        "【活動二】暮色花園\n套裝【星夜花園】",
        source="joybomb_archive",
        source_post_id="1:10065",
        raw_post_id=raw_post_id,
    ).sections
    repository = ParseDraftRepository(database_path)
    first_draft = repository.save_parse_draft(
        raw_post_id,
        "rules-v1",
        ParseDraft(
            title="新聞公告",
            event_name_candidate="夏沫海歌",
            official_series_candidate=None,
            period_type_candidate="debut",
            start_at_candidate=None,
            end_at_candidate=None,
            player_category_candidate=None,
            acquisition_method_candidate=None,
            confidence=1.0,
            parser_notes=None,
            suits=[SuitCandidate("海沙暢想", 1.0)],
            content_type_candidate="suit_event",
        ),
        section=sections[0],
    ).parse_draft_id
    second_draft = repository.save_parse_draft(
        raw_post_id,
        "rules-v1",
        ParseDraft(
            title="新聞公告",
            event_name_candidate="暮色花園",
            official_series_candidate=None,
            period_type_candidate="debut",
            start_at_candidate=None,
            end_at_candidate=None,
            player_category_candidate=None,
            acquisition_method_candidate=None,
            confidence=1.0,
            parser_notes=None,
            suits=[SuitCandidate("星夜花園", 1.0)],
            content_type_candidate="suit_event",
        ),
        section=sections[1],
    ).parse_draft_id

    first = auto_import_parse_draft(first_draft, database_path)
    second = auto_import_parse_draft(second_draft, database_path)
    repeated = auto_import_parse_draft(first_draft, database_path)

    assert first.event_id is not None
    assert second.event_id is not None
    assert first.event_id != second.event_id
    assert repeated.event_id == first.event_id

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM event_periods").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM event_suits").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM suits").fetchone()[0] == 2
        rows = connection.execute(
            "SELECT source_raw_post_id, source_section_hash, source_splitter_version "
            "FROM events ORDER BY id"
        ).fetchall()
        assert rows == [
            (raw_post_id, sections[0].section_hash, sections[0].splitter_version),
            (raw_post_id, sections[1].section_hash, sections[1].splitter_version),
        ]
    finally:
        connection.close()


def test_joybomb_sections_reuse_same_suit_across_distinct_events(tmp_path: Path) -> None:
    database_path = tmp_path / "joybomb-section-shared-suit.db"
    raw_post_id = _save_joybomb(
        database_path,
        "10067",
        "【活動一】春日活動\n套裝【共用套裝】\n"
        "【活動二】夏日活動\n套裝【共用套裝】",
    )
    sections = split_notice_sections(
        "【活動一】春日活動\n套裝【共用套裝】\n"
        "【活動二】夏日活動\n套裝【共用套裝】",
        source="joybomb_archive",
        source_post_id="1:10067",
        raw_post_id=raw_post_id,
    ).sections
    repository = ParseDraftRepository(database_path)
    draft_ids = [
        repository.save_parse_draft(
            raw_post_id,
            "rules-v1",
            ParseDraft(
                title="新聞公告",
                event_name_candidate=name,
                official_series_candidate=None,
                period_type_candidate="debut",
                start_at_candidate=None,
                end_at_candidate=None,
                player_category_candidate=None,
                acquisition_method_candidate=None,
                confidence=1.0,
                parser_notes=None,
                suits=[SuitCandidate("共用套裝", 1.0)],
                content_type_candidate="suit_event",
            ),
            section=section,
        ).parse_draft_id
        for name, section in zip(("春日活動", "夏日活動"), sections, strict=True)
    ]

    results = [auto_import_parse_draft(draft_id, database_path) for draft_id in draft_ids]

    assert results[0].event_id != results[1].event_id
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM suits").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM event_suits").fetchone()[0] == 2
    finally:
        connection.close()


def test_legacy_parse_drafts_migrate_without_losing_row_ids(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute("DROP TABLE parse_drafts")
        connection.execute(
            """CREATE TABLE parse_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, raw_post_id INTEGER NOT NULL, parser_version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', title TEXT, event_name_candidate TEXT,
                official_series_candidate TEXT, period_type_candidate TEXT, start_at_candidate TEXT,
                end_at_candidate TEXT, player_category_candidate TEXT, acquisition_method_candidate TEXT,
                confidence REAL, parser_notes TEXT, review_notes TEXT, error_message TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(raw_post_id, parser_version)
            )"""
        )
        connection.commit()
    finally:
        connection.close()
    raw_id = _save_joybomb(database_path, "10063", "\u820a\u516c\u544a")
    connection = get_connection(database_path)
    try:
        connection.execute(
            "INSERT INTO parse_drafts (id, raw_post_id, parser_version, status, created_at, updated_at) VALUES (7, ?, 'rules-v1', 'pending', 'x', 'x')",
            (raw_id,),
        )
        connection.commit()
    finally:
        connection.close()

    init_database(database_path)
    connection = get_connection(database_path)
    try:
        row = connection.execute("SELECT id, section_hash, splitter_version FROM parse_drafts").fetchone()
        assert row[0] == 7
        assert row[1]
        assert row[2] == "whole-post-v0"
    finally:
        connection.close()
