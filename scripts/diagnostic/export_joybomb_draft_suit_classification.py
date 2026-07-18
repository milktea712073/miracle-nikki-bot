"""Export a read-only CSV review list for JoyBomb pending suit candidates."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.draft_suit_classifier import classify_stored_suit_candidate
from database.parse_draft_repository import ParseDraftRepository


DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "joybomb_draft_suit_classification.csv"


def excerpt(text: str, *, limit: int = 320) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def export_joybomb_draft_suit_classification(
    output_path: Path = DEFAULT_OUTPUT,
    database_path: Path | None = None,
) -> dict[str, int]:
    """Write CSV only; this function never changes drafts or knowledge records."""
    rows = ParseDraftRepository(database_path).list_draft_suit_candidates(
        source="joybomb_archive",
        statuses=("pending",),
        missing_from_knowledge_suits=True,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"eligible": 0, "reject": 0, "review": 0}
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "parse_draft_suit_id",
                "draft_id",
                "raw_post_id",
                "section_identity",
                "section_index",
                "section_heading",
                "activity_event_name",
                "suit_candidate_name",
                "source_raw_text_excerpt",
                "parser_confidence",
                "classification",
                "classification_reason",
            ),
        )
        writer.writeheader()
        for row in rows:
            result = classify_stored_suit_candidate(
                row.suit_name_candidate,
                row.section_text,
                event_name_candidate=row.event_name_candidate,
                section_heading=row.section_heading,
            )
            counts[result.classification] += 1
            writer.writerow(
                {
                    "parse_draft_suit_id": row.parse_draft_suit_id,
                    "draft_id": row.draft_id,
                    "raw_post_id": row.raw_post_id,
                    "section_identity": f"{row.section_hash}:{row.splitter_version}",
                    "section_index": row.section_index,
                    "section_heading": row.section_heading or "",
                    "activity_event_name": row.event_name_candidate or "",
                    "suit_candidate_name": row.suit_name_candidate,
                    "source_raw_text_excerpt": excerpt(row.section_text),
                    "parser_confidence": "" if row.confidence is None else row.confidence,
                    "classification": result.classification,
                    "classification_reason": result.reason,
                }
            )
    return counts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export JoyBomb pending draft suit classifications to CSV.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    counts = export_joybomb_draft_suit_classification(args.output)
    print(f"CSV: {args.output}")
    for classification in ("eligible", "reject", "review"):
        print(f"{classification}: {counts[classification]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
