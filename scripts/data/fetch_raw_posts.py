"""Fetch recent Facebook posts and persist their raw source data."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import get_latest_posts
from crawler.models import Post
from database.database import init_database
from database.raw_post_repository import RawPostBatchResult, RawPostRepository


@dataclass(frozen=True, slots=True)
class FetchRawPostsResult:
    """Crawler output and its raw-storage outcome."""

    fetched_count: int
    storage: RawPostBatchResult


def fetch_and_save_raw_posts(
    limit: int,
    database_path: Path | None = None,
    *,
    crawler: Callable[[int], list[Post]] = get_latest_posts,
) -> FetchRawPostsResult:
    """Fetch recent posts and persist them without involving Discord."""
    init_database(database_path)
    posts = crawler(limit)
    storage = RawPostRepository(database_path).save_raw_posts(posts)
    if any("locked" in failure.error.lower() for failure in storage.failures):
        raise sqlite3.OperationalError("database is locked")
    return FetchRawPostsResult(len(posts), storage)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Facebook posts and save raw source data. Modifies the local database; does not send Discord."
    )
    parser.add_argument("--limit", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    outcome = fetch_and_save_raw_posts(parse_args().limit)
    result = outcome.storage
    print(f"\u6293\u53d6\u5b8c\u6210\uff1a{outcome.fetched_count} \u7bc7")
    print(f"\u65b0\u589e\uff1a{result.inserted}")
    print(f"\u66f4\u65b0\uff1a{result.updated}")
    print(f"\u672a\u8b8a\u66f4\uff1a{result.unchanged}")
    print(f"\u5931\u6557\uff1a{result.failed}")
    for failure in result.failures:
        print(f"- {failure.source_post_id}: {failure.error}")


if __name__ == "__main__":
    main()
