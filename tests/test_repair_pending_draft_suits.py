"""Safety tests for explicit pending-draft suit repair."""

from __future__ import annotations

from pathlib import Path

import pytest

from crawler.models import Post
from database.database import get_connection
from database.parse_draft_repository import ParseDraftRepository
from database.raw_post_repository import RawPostRepository
from parser.models import ParseDraft, SuitCandidate
from scripts.data.repair_pending_draft_suits import (
    apply_selected_repairs,
    build_repair_plan,
)


def _save_pending_joybomb_draft(
    database_path: Path,
    *,
    event_name: str | None = "Event candidate",
    content_type: str = "suit_event",
    confidence: float = 1.0,
) -> int:
    raw_post_id = RawPostRepository(database_path).save_raw_post(
        Post(
            post_id="notice-100",
            url="https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=100",
            content="\u5957\u88dd\u3010Candidate suit\u3011",
            published_at=None,
            images=[],
            source="joybomb_archive",
        ),
        enqueue_announcement=False,
    ).raw_post_id
    draft = ParseDraft(
        title="Source title",
        event_name_candidate=event_name,
        official_series_candidate=None,
        period_type_candidate="unknown",
        start_at_candidate=None,
        end_at_candidate=None,
        player_category_candidate=None,
        acquisition_method_candidate=None,
        confidence=confidence,
        parser_notes=None,
        suits=[SuitCandidate("Candidate suit", confidence)],
        content_type_candidate=content_type,
    )
    return ParseDraftRepository(database_path).save_parse_draft(raw_post_id, "rules-v1", draft).parse_draft_id


def _knowledge_counts(database_path: Path) -> tuple[int, int, int]:
    connection = get_connection(database_path)
    try:
        return tuple(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("events", "suits", "event_suits")
        )
    finally:
        connection.close()


def test_repair_dry_run_does_not_modify_knowledge_data(tmp_path: Path) -> None:
    database_path = tmp_path / "repair-dry-run.db"
    draft_id = _save_pending_joybomb_draft(database_path)

    plan = build_repair_plan(database_path)

    assert [candidate.draft_id for candidate in plan.eligible] == [draft_id]
    assert plan.needs_manual_review == ()
    assert _knowledge_counts(database_path) == (0, 0, 0)


def test_selected_repair_is_idempotent_and_does_not_duplicate_knowledge(tmp_path: Path) -> None:
    database_path = tmp_path / "repair-idempotent.db"
    draft_id = _save_pending_joybomb_draft(database_path)

    first = apply_selected_repairs({draft_id}, database_path)
    second = apply_selected_repairs({draft_id}, database_path)

    assert first[0].status == second[0].status == "auto"
    assert _knowledge_counts(database_path) == (1, 1, 1)


def test_repair_rejects_ambiguous_drafts_even_with_apply(tmp_path: Path) -> None:
    database_path = tmp_path / "repair-ambiguous.db"
    draft_id = _save_pending_joybomb_draft(
        database_path,
        event_name=None,
        confidence=0.5,
    )

    plan = build_repair_plan(database_path)

    assert plan.eligible == ()
    assert plan.needs_manual_review[0][0].draft_id == draft_id
    with pytest.raises(ValueError, match="not eligible"):
        apply_selected_repairs({draft_id}, database_path)
    assert _knowledge_counts(database_path) == (0, 0, 0)
