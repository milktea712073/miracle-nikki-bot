"""Read-only diagnostics for source-neutral raw announcement section splitting."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from content.section_splitter import SectionSplitResult, split_notice_sections
from database.database import DATABASE_PATH, get_connection


def read_raw_posts(
    *, database_path: Path = DATABASE_PATH, raw_post_id: int | None = None,
    source: str | None = None, limit: int = 10,
) -> list[dict[str, object]]:
    """Read raw post text only; this function has no database write path."""
    clauses: list[str] = []
    parameters: list[object] = []
    if raw_post_id is not None:
        clauses.append("id = ?")
        parameters.append(raw_post_id)
    if source is not None:
        clauses.append("source = ?")
        parameters.append(source)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    connection = get_connection(database_path)
    try:
        rows = connection.execute(
            "SELECT id, source, source_post_id, content FROM raw_posts"
            f"{where} ORDER BY id DESC LIMIT ?",
            (*parameters, limit),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "raw_post_id": int(row[0]),
            "source": str(row[1]),
            "source_post_id": str(row[2]),
            "content": str(row[3]),
        }
        for row in rows
    ]


def diagnose_records(records: Sequence[dict[str, object]]) -> list[SectionSplitResult]:
    """Run the common splitter against raw records without semantic parsing."""
    return [
        split_notice_sections(
            str(record["content"]),
            source=str(record["source"]),
            source_post_id=str(record["source_post_id"]),
            raw_post_id=int(record["raw_post_id"]),
        )
        for record in records
    ]


def _print_result(result: SectionSplitResult) -> None:
    print(
        f"raw_post_id={result.raw_post_id} source={result.source} "
        f"source_post_id={result.source_post_id} sections={result.section_count}"
    )
    print(f"title: {result.title or 'None'}")
    for section in result.sections:
        preview = section.text.replace("\n", " ")[:160]
        print(
            f"  [{section.index}] {section.split_reason} heading={section.heading!r} "
            f"lines={section.start_line}-{section.end_line} text={preview!r}"
        )
    if result.warnings:
        print(f"warnings: {', '.join(result.warnings)}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only section splitter diagnostic. Does not parse or write data."
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--text", help="Inspect literal announcement text without accessing SQLite.")
    inputs.add_argument("--raw-post-id", type=int, help="Inspect one raw_posts row.")
    inputs.add_argument("--limit", type=int, help="Inspect recent raw posts; combine with --source.")
    parser.add_argument("--source", help="Filter raw_posts by source, such as facebook or joybomb_archive.")
    parser.add_argument("--output", type=Path, help="Optional JSON diagnostic output path.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args(argv)
    if args.text is not None:
        results = [split_notice_sections(args.text, source=args.source or "text")]
    else:
        records = read_raw_posts(
            raw_post_id=args.raw_post_id,
            source=args.source,
            limit=1 if args.raw_post_id is not None else args.limit,
        )
        results = diagnose_records(records)
    for result in results:
        _print_result(result)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
