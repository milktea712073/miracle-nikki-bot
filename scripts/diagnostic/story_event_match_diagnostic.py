"""Read-only diagnostics for exact story-event reference matches."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH
from knowledge.story_event_reference import StoryEventMatch, load_story_event_reference, match_story_events


def extract_title(content: str) -> str:
    """Return a display-only title surrogate from the first non-empty content line."""
    for line in content.splitlines():
        if normalized := line.strip():
            return normalized[:160]
    return ""


def read_raw_posts(
    *,
    database_path: Path,
    raw_post_id: int | None,
    limit: int,
    source: str | None,
) -> list[dict[str, object]]:
    """Read raw posts through a SQLite read-only connection; never initialize or write."""
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    database_uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        clauses: list[str] = []
        parameters: list[object] = []
        if raw_post_id is not None:
            clauses.append("id = ?")
            parameters.append(raw_post_id)
        if source:
            clauses.append("source = ?")
            parameters.append(source)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            f"""
            SELECT id, source, url, content
            FROM raw_posts
            {where_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()
    finally:
        connection.close()

    return [
        {
            "raw_post_id": row["id"],
            "source": row["source"],
            "url": row["url"],
            "title": extract_title(row["content"]),
            "content": row["content"],
        }
        for row in rows
    ]


def render_matches(matches: Iterable[StoryEventMatch]) -> list[dict[str, object]]:
    """Serialize matches for a human-readable, machine-copyable diagnostic report."""
    return [asdict(match) for match in matches]


def print_result(record: dict[str, object], matches: list[StoryEventMatch]) -> None:
    """Print one diagnostic record without modifying its source."""
    print(f"raw_post_id: {record.get('raw_post_id', 'text input')}")
    print(f"source: {record.get('source', 'provided text')}")
    print(f"title: {record['title']}")
    if url := record.get("url"):
        print(f"url: {url}")
    print(f"matched story events: {len(matches)}")
    if len(matches) > 1:
        print("needs_review: true (multiple story-event candidates)")
    else:
        print("needs_review: false")
    for match in matches:
        print(
            "- "
            f"canonical_name={match.canonical_name}; matched_text={match.matched_text}; "
            f"match_type={match.match_type}; category={match.category}; confidence={match.confidence:.2f}"
        )
    print()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only story-event reference matching diagnostic")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--text", help="Text to match directly; no database access is performed.")
    input_group.add_argument("--raw-post-id", type=int, help="Read and inspect one raw_posts row.")
    parser.add_argument("--limit", type=int, default=10, help="Rows to inspect when no --text is supplied.")
    parser.add_argument("--source", help="Optional raw_posts.source filter for database sampling.")
    parser.add_argument("--database-path", type=Path, default=DATABASE_PATH, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    reference = load_story_event_reference()
    if args.text is not None:
        print_result({"title": extract_title(args.text), "content": args.text}, match_story_events(args.text, reference))
        return 0

    try:
        records = read_raw_posts(
            database_path=args.database_path,
            raw_post_id=args.raw_post_id,
            limit=1 if args.raw_post_id is not None else args.limit,
            source=args.source,
        )
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"Diagnostic failed: {error}", file=sys.stderr)
        return 1

    if not records:
        print("No matching raw posts found.")
        return 0
    for record in records:
        print_result(record, match_story_events(str(record["content"]), reference))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
