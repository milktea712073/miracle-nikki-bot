"""Regression coverage for JoyBomb whole-notice event title handling."""

from __future__ import annotations

from pathlib import Path

from content.section_splitter import split_notice_sections
from crawler import joybomb_archive_crawler as crawler
from crawler.models import Post
from database.database import get_connection, init_database
from database.knowledge_repository import KnowledgeRepository
from database.parse_draft_repository import ParseDraftRepository
from parser.models import ParseDraft
from parser.shared_parser import parse_notice_section
from scripts.data.repair_joybomb_long_event_names import (
    apply_repair_plan,
    build_repair_plan,
)


def _whole_notice(text: str):
    return split_notice_sections(text, source="joybomb_archive").sections[0]


def test_whole_notice_uses_a_cleaned_raw_title_for_the_event_name() -> None:
    section = _whole_notice("主打換裝題材的手機遊戲宣布推出活動。")

    result = parse_notice_section(
        section,
        raw_title="【活動】2024/07/01 海沙暢想",
        source="joybomb_archive",
    )

    assert result.draft.event_name_candidate == "海沙暢想"


def test_generic_raw_title_does_not_promote_a_press_release_lede_to_event_name() -> None:
    section = _whole_notice(
        "主打換裝題材的夢幻手機遊戲《奇迹暖暖》今(2日)宣布，"
        "將推出多項全新內容，邀請玩家一同參與。"
    )

    result = parse_notice_section(section, raw_title="新聞公告", source="joybomb_archive")

    assert result.draft.event_name_candidate is None


def test_explicit_section_heading_keeps_existing_event_name_behavior() -> None:
    section = split_notice_sections(
        "【活動一】海沙暢想\n活動時間：2024/07/01 05:00～2024/07/05 23:59",
        source="joybomb_archive",
    ).sections[0]

    result = parse_notice_section(
        section,
        raw_title="【活動】不同的公告標題",
        source="joybomb_archive",
    )

    assert result.draft.event_name_candidate == "海沙暢想"


def test_non_joybomb_whole_notice_keeps_existing_first_line_behavior() -> None:
    section = _whole_notice("Facebook 活動名稱\n活動時間：2024/07/01 05:00～2024/07/05 23:59")

    result = parse_notice_section(
        section,
        raw_title="不應覆寫的來源標題",
        source="facebook",
    )

    assert result.draft.event_name_candidate == "Facebook 活動名稱"


def test_notice_title_prefers_h5_inside_notice_title_container() -> None:
    snapshot = crawler.CdxSnapshot(
        "20200101000000",
        "https://nu3.joybomb.com.tw/notice/noticecontent/1/13000/0",
        "200",
        "text/html",
        "digest",
    )
    html = """
    <div class='notice-wrap'>
      <div class='noticeTitle'><span>活動</span><h5>精確活動標題</h5><span>2020/01/01</span></div>
      <div class='notice-content'><p>公告正文</p></div>
    </div>
    """

    notice = crawler.parse_notice_document(snapshot, html)

    assert notice.title == "精確活動標題"


def _save_long_whole_notice_event(database_path: Path, *, raw_title: str) -> tuple[int, int]:
    init_database(database_path)
    from database.raw_post_repository import RawPostRepository

    long_lede = "主打換裝題材的夢幻手機遊戲《奇迹暖暖》今(2日)宣布，" + "內容" * 50
    raw_post_id = RawPostRepository(database_path).save_raw_post(
        Post(
            post_id="1:99999",
            url="https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=99999",
            content=long_lede,
            published_at=None,
            images=[],
            source="joybomb_archive",
            metadata={"title": raw_title},
        ),
        enqueue_announcement=False,
    ).raw_post_id
    section = _whole_notice(long_lede)
    draft = ParseDraft(
        title=long_lede,
        event_name_candidate=long_lede,
        official_series_candidate=None,
        period_type_candidate="unknown",
        start_at_candidate=None,
        end_at_candidate=None,
        player_category_candidate=None,
        acquisition_method_candidate=None,
        confidence=0.7,
        parser_notes=None,
        content_type_candidate="event",
    )
    ParseDraftRepository(database_path).save_parse_draft(raw_post_id, "rules-v1", draft, section=section)
    repository = KnowledgeRepository(database_path)
    connection = repository.connect()
    try:
        connection.execute("BEGIN")
        event_id = repository.upsert_auto_event(
            connection,
            long_lede,
            None,
            None,
            raw_post_id,
            "event",
            section.section_hash,
            section.splitter_version,
        )
        connection.commit()
    finally:
        connection.close()
    return raw_post_id, event_id


def test_long_event_repair_dry_run_apply_and_repeat_are_safe(tmp_path: Path) -> None:
    database_path = tmp_path / "repair.db"
    _raw_post_id, event_id = _save_long_whole_notice_event(
        database_path, raw_title="【活動】海沙暢想 2024/07/01"
    )

    plan = build_repair_plan(database_path)
    assert [item.event_id for item in plan.automatic] == [event_id]
    assert plan.automatic[0].proposed_name == "海沙暢想"
    connection = get_connection(database_path)
    try:
        assert len(connection.execute("SELECT name FROM events WHERE id = ?", (event_id,)).fetchone()[0]) > 80
    finally:
        connection.close()

    assert apply_repair_plan(plan, database_path) == 1
    assert apply_repair_plan(plan, database_path) == 0
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT name FROM events WHERE id = ?", (event_id,)).fetchone()[0] == "海沙暢想"
    finally:
        connection.close()


def test_long_event_repair_marks_generic_title_for_manual_review(tmp_path: Path) -> None:
    database_path = tmp_path / "repair-generic.db"
    _raw_post_id, event_id = _save_long_whole_notice_event(database_path, raw_title="新聞公告")

    plan = build_repair_plan(database_path)

    assert plan.automatic == ()
    assert [item.event_id for item in plan.manual_review] == [event_id]
    assert plan.manual_review[0].proposed_name is None
