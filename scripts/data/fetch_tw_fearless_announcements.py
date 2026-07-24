"""Fetch Taiwan Fearless official announcements into raw archive tables only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from announcement.raw_import import OfficialRawAnnouncementImporter
from announcement.state_store import DEFAULT_STATE_DATABASE_PATH
from crawler.tw_fearless_official_crawler import fetch_recent_announcements_with_failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Fetch up to N newest matching official notices.")
    parser.add_argument("--category", choices=("all", "news", "support"), default="all")
    parser.add_argument("--state-database", type=Path, default=DEFAULT_STATE_DATABASE_PATH)
    return parser.parse_args(argv)


def _print_page(page: int, total: int) -> None:
    print(f"正在抓取公告列表：第 {page} 頁（官方共 {total} 篇）")


def _print_detail(index: int, total: int, external_id: str, title: str) -> None:
    print(f"正在下載：第 {index}/{total} 篇 [{external_id}] {title}")


def fetch_and_store_tw_fearless_announcements(
    limit: int, *, category: str, state_database_path: Path
) -> tuple[object, object]:
    """Fetch first, then persist only raw_posts and raw_post_images."""
    print("正在抓取台服 Fearless 官網公告列表")
    crawl_result = fetch_recent_announcements_with_failures(
        limit,
        category=category,  # argparse restricts this to the crawler's literals.
        on_page=_print_page,
        on_detail_start=_print_detail,
    )
    importer = OfficialRawAnnouncementImporter(state_database_path)
    return crawl_result, importer.synchronize(crawl_result.announcements)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        print("ERROR: --limit must be at least 1.", file=sys.stderr)
        return 2
    try:
        crawl_result, import_result = fetch_and_store_tw_fearless_announcements(
            args.limit, category=args.category, state_database_path=args.state_database
        )
    except Exception as error:
        print(f"ERROR: Taiwan Fearless raw import failed: {error}", file=sys.stderr)
        return 1

    storage = import_result.storage
    print("完成：")
    print(f"成功：{len(crawl_result.announcements)}")
    print(f"失敗：{len(crawl_result.failures)}")
    print(f"新增 raw_posts：{storage.inserted_raw_posts}")
    print(f"既有／略過 raw_posts：{storage.existing_raw_posts}")
    print(f"圖片總數：{import_result.fetched_images}")
    print(f"新增圖片：{storage.inserted_images}")
    print(f"重複圖片略過：{storage.duplicate_images}")
    for failure in crawl_result.failures:
        print(f"DETAIL FAILURE [{failure.external_id}] {failure.error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
