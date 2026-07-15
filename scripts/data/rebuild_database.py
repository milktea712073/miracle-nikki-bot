"""Development-only reset, fetch, and automatic knowledge-base rebuild command."""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH, get_connection, initialize_knowledge_base_tables
from scripts.data.fetch_raw_posts import FetchRawPostsResult, fetch_and_save_raw_posts
from scripts.data.fetch_website_posts import FetchWebsitePostsResult, fetch_and_save_website_posts
from scripts.data.parse_raw_posts import ParseRawPostsResult, parse_pending_raw_posts
from scripts.data.reset_database import ResetResult, reset_rebuildable_data


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RebuildResult:
    reset: ResetResult
    fetch: FetchRawPostsResult
    parse: ParseRawPostsResult
    event_count: int
    suit_count: int
    website_fetch: FetchWebsitePostsResult | None = None


def count_knowledge_records(database_path: Path) -> tuple[int, int]:
    """Return the current event and suit counts after a rebuild stage."""
    connection = get_connection(database_path)
    try:
        initialize_knowledge_base_tables(connection)
        events = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        suits = int(connection.execute("SELECT COUNT(*) FROM suits").fetchone()[0])
        return events, suits
    finally:
        connection.close()


def rebuild_database(
    limit: int,
    database_path: Path = DATABASE_PATH,
    *,
    resetter: Callable[[Path], ResetResult] | None = None,
    fetcher: Callable[[int, Path], FetchRawPostsResult] = fetch_and_save_raw_posts,
    website_fetcher: Callable[[int, Path], FetchWebsitePostsResult] = fetch_and_save_website_posts,
    parser: Callable[[int, Path], ParseRawPostsResult] = parse_pending_raw_posts,
    include_website: bool = False,
) -> RebuildResult:
    """Refresh raw data and derived knowledge without destroying queue history."""
    reset = (
        resetter(database_path)
        if resetter is not None
        else reset_rebuildable_data(database_path)
    )
    if fetcher is fetch_and_save_raw_posts:
        fetch = fetcher(limit, database_path, enqueue_announcements=False)
    else:
        fetch = fetcher(limit, database_path)
    if fetch.fetched_count < limit:
        LOGGER.warning(
            "Facebook exposed %s post(s), fewer than requested limit %s.",
            fetch.fetched_count,
            limit,
        )
    website_fetch: FetchWebsitePostsResult | None = None
    if include_website:
        website_fetch = website_fetcher(limit, database_path)
    parse = parser(limit * (2 if include_website else 1), database_path)
    event_count, suit_count = count_knowledge_records(database_path)
    return RebuildResult(reset, fetch, parse, event_count, suit_count, website_fetch)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DANGEROUS: reset regenerable data, then fetch and parse Facebook posts."
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--include-website",
        action="store_true",
        help="Also fetch official website notices into raw_posts before parsing. Never enqueues Discord announcements.",
    )
    parser.add_argument(
        "--reset-announcements",
        action="store_true",
        help="Also clear announcement jobs and sent delivery history after a second YES confirmation.",
    )
    return parser.parse_args(argv)


def print_summary(result: RebuildResult) -> None:
    storage = result.fetch.storage
    print("=================================")
    print(f"Raw posts fetched: {result.fetch.fetched_count}")
    print(f"Raw posts inserted: {storage.inserted}")
    print(f"Raw posts updated: {storage.updated}")
    print(f"Raw posts unchanged: {storage.unchanged}")
    if result.website_fetch is not None:
        website_storage = result.website_fetch.storage
        print(f"Website raw posts fetched: {result.website_fetch.fetched_count}")
        print(f"Website raw posts inserted: {website_storage.inserted}")
        print(f"Website raw posts updated: {website_storage.updated}")
        print(f"Website detail failures: {result.website_fetch.detail_failures}")
    print(f"Parse succeeded: {result.parse.succeeded}")
    print(f"Parse failed: {result.parse.failed}")
    print(f"Parse skipped: {result.parse.skipped}")
    print(f"Events created: {result.event_count}")
    print(f"Suits created: {result.suit_count}")
    print(f"Needs review: {result.parse.needs_review}")
    print("=================================")


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    runner: Callable[[int], RebuildResult] | None = None,
) -> int:
    """Confirm the destructive action and run the development rebuild."""
    args = parse_args(argv)
    print("WARNING: this clears regenerable database records before rebuilding.")
    if input_fn("Type YES to continue: ").strip() != "YES":
        print("Database rebuild cancelled.")
        return 0
    if args.reset_announcements and input_fn(
        "This also clears announcement jobs and sent announcements. Type YES to continue: "
    ).strip() != "YES":
        print("Announcement reset cancelled.")
        return 0
    active_runner = runner or (
        lambda limit: rebuild_database(
            limit,
            resetter=(
                lambda path: reset_rebuildable_data(
                    path, reset_announcements=args.reset_announcements
                )
            ),
            include_website=args.include_website,
        )
    )
    try:
        result = active_runner(args.limit)
    except sqlite3.OperationalError as error:
        if "locked" in str(error).lower():
            print("Database is locked. Close other database tools and try again.")
            return 1
        print(f"Database operation failed: {error}")
        return 1
    except Exception as error:
        print(f"Rebuild stopped: {error}")
        return 1
    print_summary(result)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
