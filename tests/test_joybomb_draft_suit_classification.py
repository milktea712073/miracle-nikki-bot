"""Read-only classification coverage for JoyBomb stored suit candidates."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from crawler.models import Post
from database.database import get_connection
from database.draft_suit_classifier import classify_stored_suit_candidate
from database.parse_draft_repository import ParseDraftRepository
from database.raw_post_repository import RawPostRepository
from parser.models import ParseDraft, SuitCandidate
from scripts.data.repair_pending_draft_suits import (
    apply_all_eligible_repairs,
    apply_selected_repairs,
    build_repair_plan,
)
from scripts.diagnostic.export_joybomb_draft_suit_classification import (
    export_joybomb_draft_suit_classification,
)


def _save_draft(
    database_path: Path,
    content: str,
    suit_name: str,
    *,
    additional_suits: list[str] | None = None,
) -> int:
    raw_post_id = RawPostRepository(database_path).save_raw_post(
        Post(
            post_id=f"notice-{suit_name}",
            url=f"https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K={suit_name}",
            content=content,
            published_at=None,
            images=[],
            source="joybomb_archive",
        ),
        enqueue_announcement=False,
    ).raw_post_id
    return ParseDraftRepository(database_path).save_parse_draft(
        raw_post_id,
        "rules-v1",
        ParseDraft(
            title="Source title",
            event_name_candidate="Event name",
            official_series_candidate=None,
            period_type_candidate="unknown",
            start_at_candidate=None,
            end_at_candidate=None,
            player_category_candidate=None,
            acquisition_method_candidate=None,
            confidence=1.0,
            parser_notes=None,
            suits=[SuitCandidate(name, 1.0) for name in [suit_name, *(additional_suits or [])]],
            content_type_candidate="suit_event",
        ),
    ).parse_draft_id


@pytest.mark.parametrize(
    ("name", "content", "classification"),
    [
        ("\u6d77\u6c99\u66a2\u60f3", "\u5957\u88dd\u3010\u6d77\u6c99\u66a2\u60f3\u3011", "eligible"),
        ("\u661f\u66dc\u77f3", "\u7372\u5f97\u3010\u661f\u66dc\u77f3\u3011", "reject"),
        ("\u4e4b\u96a8\u6a5f", "\u79ae\u5305\u5167\u542b\u672a\u7372\u5f97\u4e4b\u96a8\u6a5f\u5957\u88dd", "reject"),
        ("\u7cbe\u7dfb", "\u512a\u60e0\u671f\u9593\u53ef\u7372\u5f97\u7cbe\u7dfb\u5957\u88dd", "reject"),
        ("\u4e0d\u660e\u5019\u9078", "\u9019\u662f\u4e00\u500b\u6d3b\u52d5\u540d\u7a31", "review"),
    ],
)
def test_classifier_requires_explicit_suit_evidence(name: str, content: str, classification: str) -> None:
    result = classify_stored_suit_candidate(name, content, event_name_candidate="\u6d3b\u52d5\u540d\u7a31")

    assert result.classification == classification


def test_classifier_rejects_event_name_candidate() -> None:
    result = classify_stored_suit_candidate(
        "\u5947\u6df5\u4e4b\u5dbc",
        "\u5947\u6df5\u4e4b\u5dbc\u6d3b\u52d5\u958b\u555f",
        event_name_candidate="\u5947\u6df5\u4e4b\u5dbc",
    )

    assert result.classification == "reject"
    assert result.reason == "matches the event name"


def test_csv_export_is_read_only_and_includes_required_fields(tmp_path: Path) -> None:
    database_path = tmp_path / "classification.db"
    _save_draft(database_path, "\u5957\u88dd\u3010\u6d77\u6c99\u66a2\u60f3\u3011", "\u6d77\u6c99\u66a2\u60f3")
    output_path = tmp_path / "classification.csv"

    counts = export_joybomb_draft_suit_classification(output_path, database_path)

    assert counts == {"eligible": 1, "reject": 0, "review": 0}
    with output_path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert set(row) >= {
        "parse_draft_suit_id",
        "draft_id",
        "raw_post_id",
        "section_identity",
        "activity_event_name",
        "suit_candidate_name",
        "source_raw_text_excerpt",
        "parser_confidence",
        "classification",
        "classification_reason",
    }
    assert row["classification"] == "eligible"


def test_repair_refuses_a_draft_with_rejected_candidate(tmp_path: Path) -> None:
    database_path = tmp_path / "reject-repair.db"
    draft_id = _save_draft(database_path, "\u7372\u5f97\u3010\u661f\u66dc\u77f3\u3011", "\u661f\u66dc\u77f3")

    plan = build_repair_plan(database_path)

    assert plan.eligible == ()
    assert plan.needs_manual_review[0][0].draft_id == draft_id
    with pytest.raises(ValueError, match="not eligible"):
        apply_selected_repairs({draft_id}, database_path)


def test_batch_repair_imports_only_drafts_with_all_eligible_suits(tmp_path: Path) -> None:
    database_path = tmp_path / "batch-repair.db"
    eligible_id = _save_draft(database_path, "\u5957\u88dd\u3010\u6d77\u6c99\u66a2\u60f3\u3011", "\u6d77\u6c99\u66a2\u60f3")
    _save_draft(database_path, "\u7372\u5f97\u3010\u661f\u66dc\u77f3\u3011", "\u661f\u66dc\u77f3")

    results = apply_all_eligible_repairs(database_path)

    assert [result.draft_id for result in results] == [eligible_id]


def test_repair_imports_only_eligible_suits_from_a_mixed_draft(tmp_path: Path) -> None:
    database_path = tmp_path / "candidate-level-repair.db"
    draft_id = _save_draft(
        database_path,
        "\u5957\u88dd\u3010\u6d77\u6c99\u66a2\u60f3\u3011\uff0c\u7372\u5f97\u7cbe\u7f8e\u5957\u88dd",
        "\u6d77\u6c99\u66a2\u60f3",
        additional_suits=["\u7cbe\u7f8e"],
    )

    results = apply_selected_repairs({draft_id}, database_path)

    assert results[0].suit_ids
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT name FROM suits ORDER BY name").fetchall() == [("\u6d77\u6c99\u66a2\u60f3",)]
    finally:
        connection.close()
