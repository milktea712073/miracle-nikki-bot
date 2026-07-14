"""Set the first-deployment announcement start point without sending Discord."""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from database.announcement_job_repository import AnnouncementJobRepository
from database.database import get_connection, init_database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize the first-deployment announcement start point without sending Discord. Existing raw posts become skipped."
    )
    parser.add_argument(
        "--pending-post-url",
        action="append",
        default=[],
        help="Existing canonical URL that should be queued instead of skipped.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_database()
    jobs = AnnouncementJobRepository()
    if jobs.is_initialized():
        print("Announcement queue is already initialized.")
        return 1

    connection = get_connection()
    try:
        count = int(connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0])
    finally:
        connection.close()
    print(f"Existing raw posts to mark skipped: {count}")
    if args.pending_post_url:
        print("Existing raw posts to keep pending:")
        for url in args.pending_post_url:
            print(f"- {url}")
    if input("This establishes the announcement start point. Type YES to continue: ").strip() != "YES":
        print("Announcement queue initialization cancelled.")
        return 1
    initialized = jobs.initialize_from_existing_raw_posts(tuple(args.pending_post_url))
    print(f"Announcement queue initialized. Processed existing raw posts: {initialized}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
