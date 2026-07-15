"""Fetch official website announcements into the source-agnostic raw layer."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.models import Post
from crawler.website_crawler import WebsiteCrawlResult, WebsiteAnnouncement, crawl_recent_announcements
from database.database import init_database
from database.raw_post_repository import RawPostBatchResult, RawPostRepository


WEBSITE_SECTION_METADATA: dict[int, tuple[str, str]] = {
    1: ("activity", "event"),
    2: ("news", "notice"),
    3: ("customer_service", "notice"),
    11: ("system", "system"),
    21: ("system", "system"),
}


@dataclass(frozen=True, slots=True)
class FetchWebsitePostsResult:
    """Website crawl output and its raw-storage outcome."""

    fetched_count: int
    detail_failures: int
    storage: RawPostBatchResult


def website_announcement_to_post(announcement: WebsiteAnnouncement) -> Post:
    """Convert a website detail page to generic raw data with parser hints."""
    section, content_type_candidate = WEBSITE_SECTION_METADATA.get(
        announcement.section, ("other", "other")
    )
    publish_time = datetime.fromisoformat(announcement.publish_time) if announcement.publish_time else None
    content = "\n".join(part for part in (announcement.title, announcement.content_text) if part).strip()
    return Post(
        post_id=announcement.source_post_id,
        url=announcement.url,
        content=content,
        published_at=publish_time,
        images=announcement.image_urls,
        source="website",
        metadata={
            "section": section,
            "section_id": announcement.section,
            "section_name": announcement.section_name,
            "content_type_candidate": content_type_candidate,
            "title": announcement.title,
        },
    )


def fetch_and_save_website_posts(
    limit: int,
    database_path: Path | None = None,
    *,
    crawler: Callable[[int], WebsiteCrawlResult] = crawl_recent_announcements,
) -> FetchWebsitePostsResult:
    """Fetch website details and save raw posts without touching announcement jobs."""
    init_database(database_path)
    crawled = crawler(limit)
    posts = [website_announcement_to_post(announcement) for announcement in crawled.announcements]
    storage = RawPostRepository(database_path).save_raw_posts(posts, enqueue_announcements=False)
    if any("locked" in failure.error.lower() for failure in storage.failures):
        raise sqlite3.OperationalError("database is locked")
    return FetchWebsitePostsResult(len(posts), len(crawled.failures), storage)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch official website announcements into raw_posts. Does not send Discord."
    )
    parser.add_argument("--limit", type=int, default=30)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    result = fetch_and_save_website_posts(parse_args(argv).limit)
    print(f"官網抓取完成：{result.fetched_count} 篇")
    print(f"新增：{result.storage.inserted}")
    print(f"更新：{result.storage.updated}")
    print(f"未變更：{result.storage.unchanged}")
    print(f"儲存失敗：{result.storage.failed}")
    print(f"詳細頁解析失敗：{result.detail_failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
