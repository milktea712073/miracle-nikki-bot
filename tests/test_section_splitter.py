"""Coverage for the read-only, source-neutral announcement section splitter."""

from __future__ import annotations

from pathlib import Path

from content.section_splitter import split_notice_sections
from database.database import get_connection, init_database
from database.raw_post_repository import RawPostRepository
from crawler.models import Post
from scripts.diagnostic.section_split_diagnostic import diagnose_records, read_raw_posts


def test_facebook_and_joybomb_use_the_same_section_output_contract() -> None:
    content = "公告標題\n活動一\n活動一內容\n活動二：活動二內容\n登入送\n登入獎勵"
    facebook = split_notice_sections(content, source="facebook", source_post_id="pfbid-1")
    joybomb = split_notice_sections(content, source="joybomb_archive", source_post_id="1:10061")

    assert facebook.section_count == joybomb.section_count == 4
    assert [section.heading for section in facebook.sections] == [
        None, "活動一", "活動二", "登入送"
    ]
    assert [section.split_reason for section in facebook.sections] == [
        "whole_notice", "explicit_activity", "explicit_activity", "explicit_category"
    ]
    assert facebook.to_dict().keys() == joybomb.to_dict().keys()


def test_unstructured_notice_is_preserved_as_one_section_without_parsing() -> None:
    result = split_notice_sections("【活動】夏日限時開放\n完整公告文字", source="facebook")

    assert result.section_count == 1
    assert result.sections[0].split_reason == "whole_notice"
    assert result.sections[0].text == "【活動】夏日限時開放\n完整公告文字"
    assert result.warnings == ["no_explicit_section_heading"]


def test_category_heading_does_not_require_knowledge_or_parser_rules() -> None:
    result = split_notice_sections("新聞公告\n【儲值活動】\n儲值內容\n【維護】\n維護內容", source="joybomb_archive")

    assert [section.heading for section in result.sections] == [None, "儲值活動", "維護"]
    assert [section.text for section in result.sections[1:]] == ["儲值內容", "維護內容"]


def test_joybomb_activity_number_heading_with_ideographic_comma_is_split() -> None:
    result = split_notice_sections(
        "新聞公告\n活動一、夏日之約\n活動內容\n活動二、登入送\n登入內容",
        source="joybomb_archive",
    )

    assert [section.heading for section in result.sections] == [None, "活動一", "活動二"]
    assert result.sections[1].text == "夏日之約\n活動內容"
    assert result.sections[2].text == "登入送\n登入內容"


def test_empty_content_reports_diagnostic_warning() -> None:
    result = split_notice_sections("  \n", source="facebook")
    assert result.section_count == 0
    assert result.warnings == ["empty_content"]


def test_blank_preamble_before_activity_heading_is_not_a_section() -> None:
    result = split_notice_sections("\ufeff\u200b\n\n活動一、活動正文", source="joybomb_archive")

    assert result.section_count == 1
    assert result.sections[0].heading == "活動一"


def test_meaningful_preamble_before_activity_heading_is_preserved() -> None:
    result = split_notice_sections("共同前言\n活動一、活動正文", source="joybomb_archive")

    assert result.section_count == 2
    assert result.sections[0].heading is None
    assert result.sections[0].text == "共同前言"


def test_notice_without_heading_remains_a_single_whole_notice_section() -> None:
    result = split_notice_sections("沒有明確標題的公告正文", source="joybomb_archive")

    assert result.section_count == 1
    assert result.sections[0].split_reason == "whole_notice"


def test_diagnostic_reads_raw_posts_without_creating_drafts_or_queue(tmp_path: Path) -> None:
    database_path = tmp_path / "section-diagnostic.db"
    init_database(database_path)
    RawPostRepository(database_path).save_raw_post(
        Post(
            post_id="joybomb-1",
            url="https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10061",
            content="新聞公告\n活動一\n內容",
            published_at=None,
            images=[],
            source="joybomb_archive",
        ),
        enqueue_announcement=False,
    )

    records = read_raw_posts(database_path=database_path, source="joybomb_archive", limit=1)
    results = diagnose_records(records)

    assert results[0].source == "joybomb_archive"
    assert results[0].sections[-1].heading == "活動一"
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM parse_drafts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
    finally:
        connection.close()
