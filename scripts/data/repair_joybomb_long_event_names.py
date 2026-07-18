"""Safely repair prose-like JoyBomb whole-notice event names.

The tool is intentionally narrow: it only considers auto-created JoyBomb
events whose source section is a whole notice and whose current name exceeds
the configured maximum.  Dry-run is the default.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH, get_connection, init_database
from database.knowledge_repository import KnowledgeRepository
from content.section_splitter import split_notice_sections
from parser.announcement_parser import normalize_source_event_title


@dataclass(frozen=True, slots=True)
class LongEventNameRepair:
    event_id: int
    source_raw_post_id: int
    old_name: str
    raw_title: str | None
    proposed_name: str | None
    reason: str
    confidence: float | None


@dataclass(frozen=True, slots=True)
class LongEventNameRepairPlan:
    automatic: tuple[LongEventNameRepair, ...]
    manual_review: tuple[LongEventNameRepair, ...]


def _metadata_title(value: object) -> str | None:
    if not value:
        return None
    try:
        metadata = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    title = metadata.get("title") if isinstance(metadata, dict) else None
    return str(title).strip() if title else None


def build_repair_plan(
    database_path: Path | None = None, *, max_name_length: int = 80
) -> LongEventNameRepairPlan:
    """List only verified whole-notice anomalies; never write database state."""
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        rows = connection.execute(
            """
            SELECT e.id, e.name, e.source_raw_post_id, e.source_section_hash,
                   e.source_splitter_version, e.data_status, r.metadata_json,
                   r.content, r.source_post_id
            FROM events AS e
            JOIN raw_posts AS r ON r.id = e.source_raw_post_id
            WHERE r.source = 'joybomb_archive'
              AND length(e.name) > ?
            ORDER BY e.id
            """,
            (max_name_length,),
        ).fetchall()
        automatic: list[LongEventNameRepair] = []
        manual_review: list[LongEventNameRepair] = []
        for (
            event_id,
            old_name,
            raw_post_id,
            source_section_hash,
            source_splitter_version,
            data_status,
            metadata_json,
            content,
            source_post_id,
        ) in rows:
            sections = split_notice_sections(
                str(content),
                source="joybomb_archive",
                source_post_id=str(source_post_id),
                raw_post_id=int(raw_post_id),
            ).sections
            whole_notice = next(
                (
                    section
                    for section in sections
                    if section.heading is None
                    and section.split_reason == "whole_notice"
                    and section.section_hash == source_section_hash
                    and section.splitter_version == source_splitter_version
                ),
                None,
            )
            if whole_notice is None:
                continue
            raw_title = _metadata_title(metadata_json)
            proposed_name = normalize_source_event_title(raw_title)
            base = dict(
                event_id=int(event_id),
                source_raw_post_id=int(raw_post_id),
                old_name=str(old_name),
                raw_title=raw_title,
                proposed_name=proposed_name,
            )
            if data_status != "auto":
                manual_review.append(LongEventNameRepair(
                    **base,
                    reason=f"event data_status is {data_status}, not auto",
                    confidence=None,
                ))
                continue
            if proposed_name is None:
                manual_review.append(LongEventNameRepair(
                    **base,
                    reason="raw title is generic, prose-like, or unavailable",
                    confidence=None,
                ))
                continue
            conflict = connection.execute(
                "SELECT id FROM events WHERE name = ? AND id != ? LIMIT 1",
                (proposed_name, event_id),
            ).fetchone()
            if conflict is not None:
                manual_review.append(LongEventNameRepair(
                    **base,
                    reason=f"proposed name conflicts with event_id={int(conflict[0])}",
                    confidence=None,
                ))
                continue
            automatic.append(LongEventNameRepair(
                **base,
                reason="normalized metadata title for verified whole_notice source",
                confidence=1.0,
            ))
        return LongEventNameRepairPlan(tuple(automatic), tuple(manual_review))
    finally:
        connection.close()


def apply_repair_plan(
    plan: LongEventNameRepairPlan, database_path: Path | None = None
) -> int:
    """Apply the already-reviewed automatic subset in one transaction."""
    if not plan.automatic:
        return 0
    repository = KnowledgeRepository(database_path)
    connection = repository.connect()
    try:
        connection.execute("BEGIN")
        changed = 0
        for repair in plan.automatic:
            if repair.proposed_name is None:
                continue
            changed += int(repository.rename_auto_event(connection, repair.event_id, repair.proposed_name))
        connection.commit()
        return changed
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def backup_database(database_path: Path) -> Path:
    """Create a SQLite-consistent backup before an explicit apply."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = database_path.parent / "backups" / f"{database_path.stem}.before-joybomb-long-event-repair-{stamp}{database_path.suffix}"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup_path


def _print_repair(repair: LongEventNameRepair, *, label: str) -> None:
    print(f"{label}: event_id={repair.event_id} raw_post_id={repair.source_raw_post_id}")
    print(f"  old_name={repair.old_name!r}")
    print(f"  raw_title={repair.raw_title!r}")
    print(f"  proposed_name={repair.proposed_name!r}")
    print(f"  reason={repair.reason}; confidence={repair.confidence}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair long auto JoyBomb whole-notice event names.")
    parser.add_argument("--apply", action="store_true", help="Back up then apply the automatic repair plan.")
    parser.add_argument("--database-path", type=Path, default=DATABASE_PATH)
    parser.add_argument("--max-name-length", type=int, default=80)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    database_path = args.database_path.resolve()
    plan = build_repair_plan(database_path, max_name_length=args.max_name_length)
    print(f"Automatic repairs: {len(plan.automatic)}")
    for repair in plan.automatic:
        _print_repair(repair, label="AUTO")
    print(f"Manual review: {len(plan.manual_review)}")
    for repair in plan.manual_review:
        _print_repair(repair, label="REVIEW")

    if not args.apply:
        print("Dry run only. Re-run with --apply after reviewing the proposed names.")
        return 0

    backup_path = backup_database(database_path)
    print(f"Database backup created: {backup_path}")
    if input("This will rename only the listed auto events. Type YES to continue: ").strip() != "YES":
        print("Cancelled. No events were changed.")
        return 0
    changed = apply_repair_plan(plan, database_path)
    print(f"Repaired events: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
