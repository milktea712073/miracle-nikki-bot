"""Fetch recent China official notices into announcement_state.db raw storage only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from announcement.raw_import import OfficialRawAnnouncementImporter
from announcement.state_store import DEFAULT_STATE_DATABASE_PATH
from crawler.cn_official_crawler import (
    CNNoticeListItem,
    MAX_LIST_PAGES,
    fetch_all_announcements_with_failures,
    fetch_recent_announcements_with_failures,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Fetch the newest N notices from the list page.")
    parser.add_argument("--all", action="store_true", help="Fetch every reachable official list page; ignores --limit.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=MAX_LIST_PAGES,
        help="Safety cap used only with --all.",
    )
    parser.add_argument(
        "--state-database",
        type=Path,
        default=DEFAULT_STATE_DATABASE_PATH,
        help="Target announcement state SQLite path.",
    )
    return parser.parse_args(argv)


def _print_detail_progress(index: int, total: int, item: CNNoticeListItem) -> None:
    print(f"正在下載：第 {index}/{total} 篇 [{item.external_id}] {item.title}")


def _print_list_progress(page: int, cumulative: int, new_items: int) -> None:
    print(f"目前頁數：{page}；累積公告數：{cumulative}；本頁新增：{new_items}")


def fetch_and_store_cn_announcements(
    limit: int,
    *,
    state_database_path: Path,
    fetch_all: bool = False,
    max_pages: int = MAX_LIST_PAGES,
) -> tuple[object, object]:
    """Fetch CN notices, then write only raw_posts/raw_post_images to the state database."""
    print("正在抓取：公告列表")
    if fetch_all:
        crawl_result = fetch_all_announcements_with_failures(
            max_pages=max_pages,
            on_list_page=_print_list_progress,
            on_detail_start=_print_detail_progress,
        )
    else:
        crawl_result = fetch_recent_announcements_with_failures(limit, on_detail_start=_print_detail_progress)
    importer = OfficialRawAnnouncementImporter(state_database_path)
    import_result = importer.synchronize(crawl_result.announcements)
    return crawl_result, import_result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.all and args.limit < 1:
        print("ERROR: --limit must be at least 1.", file=sys.stderr)
        return 2
    if args.all and args.max_pages < 1:
        print("ERROR: --max-pages must be at least 1.", file=sys.stderr)
        return 2
    try:
        crawl_result, import_result = fetch_and_store_cn_announcements(
            args.limit,
            state_database_path=args.state_database,
            fetch_all=args.all,
            max_pages=args.max_pages,
        )
    except Exception as error:
        print(f"ERROR: CN raw import failed: {error}", file=sys.stderr)
        return 1

    storage = import_result.storage
    print("完成：")
    print(f"成功：{len(crawl_result.announcements)}")
    print(f"失敗：{len(crawl_result.failures)}")
    print(f"抓取列表頁數：{crawl_result.pages_fetched}")
    print(f"列表累積公告數：{crawl_result.listed_count}")
    print(f"列表停止原因：{crawl_result.stopped_reason}")
    print(f"新增：{storage.inserted_raw_posts} 篇")
    print(f"略過／既有：{storage.existing_raw_posts} 篇")
    print(f"圖片：共 {import_result.fetched_images} 張")
    print(f"新增圖片：{storage.inserted_images} 張")
    print(f"重複／既有圖片：{storage.duplicate_images} 張")
    for failure in crawl_result.failures:
        print(f"單篇失敗：[{failure.external_id}] {failure.error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
