from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from crawler.models import Post
from bot.main import add_auto_status_notice
import discord
from database.auto_import_service import auto_import_parse_draft
from database.database import get_connection
from database.knowledge_query_repository import KnowledgeQueryRepository
from database.parse_draft_repository import ParseDraftRepository
from database.raw_post_repository import RawPostRepository
from parser.models import ParseDraft, SuitCandidate


def save_draft(database_path: Path, draft: ParseDraft, post_id: str = "auto-post") -> int:
    raw_post_id = RawPostRepository(database_path).save_raw_post(
        Post(
            post_id=post_id,
            url=f"https://example.test/posts/{post_id}",
            content="raw source",
            published_at=datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc),
            images=[],
        )
    ).raw_post_id
    return ParseDraftRepository(database_path).save_parse_draft(
        raw_post_id, "rules-v1", draft
    ).parse_draft_id


def draft_with_candidates(
    title: str = "奇迹演唱會 公告", suits: list[str] | None = None
) -> ParseDraft:
    return ParseDraft(
        title=title,
        event_name_candidate="奇迹演唱會",
        official_series_candidate=None,
        period_type_candidate="debut",
        start_at_candidate="2026-07-13T05:00:00+08:00",
        end_at_candidate="2026-07-19T23:59:00+08:00",
        player_category_candidate=None,
        acquisition_method_candidate=None,
        confidence=0.7,
        parser_notes=None,
        suits=[SuitCandidate(name, 0.7) for name in (suits or ["元氣應援"])],
    )


def test_parse_success_auto_imports_data_that_is_immediately_queryable(tmp_path: Path) -> None:
    database_path = tmp_path / "auto-import.db"
    draft_id = save_draft(database_path, draft_with_candidates(suits=["元氣應援", "絕對搖滾"]))

    result = auto_import_parse_draft(draft_id, database_path)

    assert result.status == "auto"
    assert result.event_id is not None
    repository = KnowledgeQueryRepository(database_path)
    event = repository.get_event_by_name("奇迹演唱會")
    suit = repository.get_suit_by_name("元氣應援")
    assert event is not None
    assert [item.name for item in event.suits] == ["元氣應援", "絕對搖滾"]
    assert suit is not None
    assert suit.events[0].event_name == "奇迹演唱會"
    assert event.data_status == "auto"
    assert suit.data_status == "auto"


def test_auto_import_keeps_same_named_events_from_distinct_raw_posts_separate(tmp_path: Path) -> None:
    database_path = tmp_path / "auto-upsert.db"
    first_id = save_draft(database_path, draft_with_candidates(suits=["元氣應援"]), "post-1")
    second_id = save_draft(
        database_path,
        draft_with_candidates("奇迹演唱會 更新公告", ["元氣應援", "絕對搖滾"]),
        "post-2",
    )

    auto_import_parse_draft(first_id, database_path)
    auto_import_parse_draft(second_id, database_path)

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM suits").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM event_suits").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM event_periods").fetchone()[0] == 2
    finally:
        connection.close()


def test_verified_event_is_not_overwritten_by_later_parser_output(tmp_path: Path) -> None:
    database_path = tmp_path / "verified-protection.db"
    first_id = save_draft(database_path, draft_with_candidates("自動標題"), "post-1")
    auto_import_parse_draft(first_id, database_path)
    connection = get_connection(database_path)
    try:
        connection.execute(
            """
            UPDATE events
            SET description = ?, data_status = 'verified', updated_via = 'admin'
            WHERE name = ?
            """,
            ("管理員確認內容", "奇迹演唱會"),
        )
        connection.commit()
    finally:
        connection.close()

    second_id = save_draft(database_path, draft_with_candidates("Parser 新標題"), "post-1")
    auto_import_parse_draft(second_id, database_path)

    connection = get_connection(database_path)
    try:
        row = connection.execute(
            "SELECT description, data_status, updated_via FROM events WHERE name = ?",
            ("奇迹演唱會",),
        ).fetchone()
    finally:
        connection.close()
    assert row == ("管理員確認內容", "verified", "admin")


def test_missing_core_candidates_stay_out_of_knowledge_base_and_need_review(tmp_path: Path) -> None:
    database_path = tmp_path / "needs-review.db"
    draft_id = save_draft(
        database_path,
        ParseDraft(
            title=None,
            event_name_candidate=None,
            official_series_candidate=None,
            period_type_candidate="unknown",
            start_at_candidate=None,
            end_at_candidate=None,
            player_category_candidate=None,
            acquisition_method_candidate=None,
            confidence=0.0,
            parser_notes="No candidates",
            suits=[],
        ),
    )

    result = auto_import_parse_draft(draft_id, database_path)

    assert result.status == "needs_review"
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM suits").fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM parse_drafts WHERE id = ?", (draft_id,)
        ).fetchone()[0] == "needs_review"
    finally:
        connection.close()


def test_suit_event_without_reliable_suits_creates_event_for_correction(tmp_path: Path) -> None:
    database_path = tmp_path / "missing-suits.db"
    draft_id = save_draft(
        database_path,
        ParseDraft(
            title="待補套裝活動",
            event_name_candidate="待補套裝活動",
            official_series_candidate=None,
            period_type_candidate="unknown",
            start_at_candidate=None,
            end_at_candidate=None,
            player_category_candidate=None,
            acquisition_method_candidate=None,
            confidence=0.5,
            parser_notes="No high-confidence suit candidates were found.",
            suits=[],
            content_type_candidate="suit_event",
        ),
    )

    result = auto_import_parse_draft(draft_id, database_path)

    assert result.status == "needs_review"
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT data_status FROM events").fetchone()[0] == "needs_review"
        assert connection.execute("SELECT COUNT(*) FROM suits").fetchone()[0] == 0
    finally:
        connection.close()


def test_suits_with_an_unresolved_event_name_use_title_as_a_provisional_link(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provisional-event.db"
    draft_id = save_draft(
        database_path,
        ParseDraft(
            title="未標準化活動標題",
            event_name_candidate=None,
            official_series_candidate=None,
            period_type_candidate="unknown",
            start_at_candidate=None,
            end_at_candidate=None,
            player_category_candidate=None,
            acquisition_method_candidate=None,
            confidence=0.5,
            parser_notes="Event name needs review",
            suits=[SuitCandidate("候選套裝", 0.7)],
        ),
    )

    result = auto_import_parse_draft(draft_id, database_path)

    assert result.status == "auto"
    repository = KnowledgeQueryRepository(database_path)
    suit = repository.get_suit_by_name("候選套裝")
    assert suit is not None
    assert suit.events[0].event_name == "未標準化活動標題"


def test_admin_suit_edit_marks_auto_data_verified(tmp_path: Path) -> None:
    database_path = tmp_path / "admin-verified.db"
    draft_id = save_draft(database_path, draft_with_candidates())
    auto_import_parse_draft(draft_id, database_path)

    connection = get_connection(database_path)
    try:
        event_id = connection.execute("SELECT id FROM events").fetchone()[0]
        suit_id = connection.execute("SELECT id FROM suits").fetchone()[0]
        connection.execute("INSERT INTO acquisition_methods (name) VALUES ('花鑽')")
        method_id = connection.execute("SELECT id FROM acquisition_methods").fetchone()[0]
        connection.commit()
    finally:
        connection.close()

    repository = KnowledgeQueryRepository(database_path)
    repository.update_suit_card_data(suit_id, event_id, method_id, "1992", False)

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT data_status FROM suits WHERE id = ?", (suit_id,)).fetchone()[0] == "verified"
        assert connection.execute(
            "SELECT data_status FROM event_suits WHERE event_id = ? AND suit_id = ?",
            (event_id, suit_id),
        ).fetchone()[0] == "verified"
    finally:
        connection.close()


def test_auto_status_notice_is_only_visible_to_administrators() -> None:
    admin_embed = discord.Embed()
    player_embed = discord.Embed()

    add_auto_status_notice(admin_embed, "auto", True)
    add_auto_status_notice(player_embed, "auto", False)

    assert admin_embed.footer.text == "自動建立，尚未確認"
    assert player_embed.footer.text is None
