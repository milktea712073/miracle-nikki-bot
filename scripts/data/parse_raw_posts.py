"""Parse raw Facebook posts and automatically import usable knowledge data."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.auto_import_service import auto_import_parse_draft
from database.database import init_database
from database.parse_draft_repository import ParseDraftRepository
from parser.announcement_parser import parse_announcement


LOGGER = logging.getLogger(__name__)
DEFAULT_PARSER_VERSION = "rules-v1"


@dataclass(frozen=True, slots=True)
class ParseRawPostsResult:
    selected: int
    succeeded: int
    failed: int
    skipped: int
    needs_review: int


def parse_pending_raw_posts(
    limit: int,
    database_path: Path | None = None,
    *,
    raw_post_id: int | None = None,
    force: bool = False,
    parser_version: str = DEFAULT_PARSER_VERSION,
) -> ParseRawPostsResult:
    """Parse pending raw posts; a per-post failure preserves all raw source data."""
    init_database(database_path)
    if force and raw_post_id is None:
        raise ValueError("--force requires --raw-post-id.")
    repository = ParseDraftRepository(database_path)
    raw_posts = repository.list_raw_posts_for_parsing(limit, raw_post_id, force)
    succeeded = failed = needs_review = 0
    for raw_post in raw_posts:
        try:
            metadata = json.loads(str(raw_post["metadata_json"])) if raw_post["metadata_json"] else {}
            content_type_hint = metadata.get("content_type_candidate")
            draft = parse_announcement(
                str(raw_post["content"]),
                content_type_hint=str(content_type_hint) if content_type_hint else None,
            )
            saved = repository.save_parse_draft(int(raw_post["id"]), parser_version, draft)
            imported = auto_import_parse_draft(saved.parse_draft_id, database_path)
            succeeded += 1
            needs_review += int(imported.status == "needs_review")
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower():
                raise
            LOGGER.exception("Failed to parse raw post %s", raw_post["source_post_id"])
            repository.save_failed_draft(int(raw_post["id"]), parser_version, str(error))
            failed += 1
        except Exception as error:
            LOGGER.exception("Failed to parse raw post %s", raw_post["source_post_id"])
            repository.save_failed_draft(int(raw_post["id"]), parser_version, str(error))
            failed += 1
    return ParseRawPostsResult(len(raw_posts), succeeded, failed, 0, needs_review)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse pending raw posts and update derived knowledge data in the local database."
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--raw-post-id", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--parser-version", default=DEFAULT_PARSER_VERSION)
    return parser.parse_args()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    try:
        result = parse_pending_raw_posts(
            args.limit,
            raw_post_id=args.raw_post_id,
            force=args.force,
            parser_version=args.parser_version,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"\u5f85\u89e3\u6790\uff1a{result.selected}")
    print(f"\u6210\u529f\uff1a{result.succeeded}")
    print(f"\u5931\u6557\uff1a{result.failed}")
    print(f"\u7565\u904e\uff1a{result.skipped}")


if __name__ == "__main__":
    main()
