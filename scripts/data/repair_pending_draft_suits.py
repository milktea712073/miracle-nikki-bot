"""Review and explicitly import selected pending draft suit candidates.

This is intentionally a conservative maintenance tool.  It never bulk-imports
pending drafts: dry-run is the default, and ``--apply`` requires one or more
explicit draft IDs after the administrator has reviewed the output.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.auto_import_service import AutoImportResult, auto_import_parse_draft
from database.draft_suit_classifier import classify_stored_suit_candidate
from database.parse_draft_repository import (
    DraftSuitCandidateRecord,
    ParseDraftRepository,
    PendingDraftSuitRepairCandidate,
)


ELIGIBLE_CONTENT_TYPES = frozenset({"event", "suit_event"})
MINIMUM_CONFIDENCE = 0.9


@dataclass(frozen=True, slots=True)
class DraftSuitRepairPlan:
    eligible: tuple[PendingDraftSuitRepairCandidate, ...]
    eligible_suit_names_by_draft: dict[int, tuple[str, ...]]
    needs_manual_review: tuple[tuple[PendingDraftSuitRepairCandidate, str], ...]


def repair_reason(candidate: PendingDraftSuitRepairCandidate) -> str | None:
    """Return a reason the candidate must not be imported by this tool."""
    if candidate.content_type_candidate not in ELIGIBLE_CONTENT_TYPES:
        return "content type is not event or suit_event"
    if not (candidate.event_name_candidate or "").strip():
        return "event name candidate is empty"
    if candidate.confidence is None or candidate.confidence < MINIMUM_CONFIDENCE:
        return f"confidence is below {MINIMUM_CONFIDENCE:.1f}"
    return None


def _candidate_level_repair_candidates(
    repository: ParseDraftRepository,
    *,
    source: str,
    statuses: tuple[str, ...],
) -> tuple[
    dict[int, PendingDraftSuitRepairCandidate],
    dict[int, tuple[str, ...]],
    dict[int, str],
]:
    candidates = repository.list_pending_draft_suit_repair_candidates(
        source=source,
        statuses=statuses,
    )
    records_by_draft: dict[int, list[DraftSuitCandidateRecord]] = {}
    for record in repository.list_draft_suit_candidates(source=source, statuses=statuses):
        records_by_draft.setdefault(record.draft_id, []).append(record)

    eligible: dict[int, PendingDraftSuitRepairCandidate] = {}
    eligible_suit_names_by_draft: dict[int, tuple[str, ...]] = {}
    blocked: dict[int, str] = {}
    for candidate in candidates:
        reason = repair_reason(candidate)
        if reason is None:
            allowed_names = tuple(
                dict.fromkeys(
                    record.suit_name_candidate
                    for record in records_by_draft.get(candidate.draft_id, [])
                    if classify_stored_suit_candidate(
                        record.suit_name_candidate,
                        record.section_text,
                        event_name_candidate=record.event_name_candidate,
                        section_heading=record.section_heading,
                    ).classification == "eligible"
                )
            )
            if allowed_names:
                eligible[candidate.draft_id] = candidate
                eligible_suit_names_by_draft[candidate.draft_id] = allowed_names
            else:
                blocked[candidate.draft_id] = "no candidate is classified eligible"
        else:
            blocked[candidate.draft_id] = reason
    return eligible, eligible_suit_names_by_draft, blocked


def build_repair_plan(
    database_path: Path | None = None, *, source: str = "joybomb_archive"
) -> DraftSuitRepairPlan:
    repository = ParseDraftRepository(database_path)
    eligible_by_id, eligible_suit_names_by_draft, blocked_by_id = _candidate_level_repair_candidates(
        repository,
        source=source,
        statuses=("pending",),
    )
    eligible = list(eligible_by_id.values())
    needs_manual_review: list[tuple[PendingDraftSuitRepairCandidate, str]] = []
    for candidate in repository.list_pending_draft_suit_repair_candidates(source=source):
        if candidate.draft_id in blocked_by_id:
            needs_manual_review.append((candidate, blocked_by_id[candidate.draft_id]))
    return DraftSuitRepairPlan(
        tuple(eligible), eligible_suit_names_by_draft, tuple(needs_manual_review)
    )


def apply_selected_repairs(
    draft_ids: set[int],
    database_path: Path | None = None,
    *,
    source: str = "joybomb_archive",
) -> tuple[AutoImportResult, ...]:
    """Import explicitly selected eligible drafts via the existing service."""
    if not draft_ids:
        raise ValueError("--apply requires at least one --draft-id.")
    repository = ParseDraftRepository(database_path)
    eligible_by_id, eligible_suit_names_by_draft, _blocked_by_id = _candidate_level_repair_candidates(
        repository,
        source=source,
        # A prior explicit repair marks the draft auto.  Including that state
        # makes a repeated explicit command idempotent while excluding
        # verified/reviewed drafts.
        statuses=("pending", "auto"),
    )
    unavailable = sorted(draft_ids - eligible_by_id.keys())
    if unavailable:
        raise ValueError(
            "Draft IDs are not eligible for safe repair: "
            + ", ".join(str(draft_id) for draft_id in unavailable)
        )
    return tuple(
        auto_import_parse_draft(
            draft_id,
            database_path,
            eligible_suit_names=eligible_suit_names_by_draft[draft_id],
        )
        for draft_id in sorted(draft_ids)
    )


def apply_all_eligible_repairs(
    database_path: Path | None = None, *, source: str = "joybomb_archive"
) -> tuple[AutoImportResult, ...]:
    """Batch-import every draft's eligible suit candidates only."""
    plan = build_repair_plan(database_path, source=source)
    return apply_selected_repairs(
        {candidate.draft_id for candidate in plan.eligible},
        database_path,
        source=source,
    ) if plan.eligible else ()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run pending draft suit repairs; apply only explicit eligible draft IDs."
    )
    parser.add_argument("--source", default="joybomb_archive")
    parser.add_argument("--draft-id", action="append", type=int, default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--all-eligible",
        action="store_true",
        help="With --apply, import only eligible suit candidates from every safe draft.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plan = build_repair_plan(source=args.source)
    print(f"Eligible pending drafts: {len(plan.eligible)}")
    for candidate in plan.eligible:
        print(
            f"  draft_id={candidate.draft_id} raw_post_id={candidate.raw_post_id} "
            f"event={candidate.event_name_candidate!r} "
            f"eligible_suits={list(plan.eligible_suit_names_by_draft[candidate.draft_id])!r}"
        )
    print(f"Needs manual review: {len(plan.needs_manual_review)}")
    for candidate, reason in plan.needs_manual_review:
        print(f"  draft_id={candidate.draft_id}: {reason}")

    if not args.apply:
        print("Dry run only. Use --apply with explicit --draft-id values to import selected drafts.")
        return 0

    if args.all_eligible and args.draft_id:
        raise ValueError("Use either --all-eligible or --draft-id, not both.")
    results = (
        apply_all_eligible_repairs(source=args.source)
        if args.all_eligible
        else apply_selected_repairs(set(args.draft_id), source=args.source)
    )
    for result in results:
        print(
            f"Imported draft_id={result.draft_id} status={result.status} "
            f"event_id={result.event_id} suit_ids={result.suit_ids}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
