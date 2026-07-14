"""Explicitly queue one canonical Facebook post for a development resend."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import normalize_post_url
from database.announcement_job_repository import AnnouncementJobRepository, RequeueResult
from database.database import init_database


def print_result(result: RequeueResult, *, latest: bool = False) -> None:
    print("Requeued latest announcement:" if latest else "Requeued announcement:")
    print(f"- raw_post_id: {result.raw_post_id}")
    print(f"- job_id: {result.job_id}")
    print(f"- old_status: {result.old_status}")
    print("- new_status: pending")
    print(f"- URL: {result.post_url}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-url", required=True)
    args = parser.parse_args(argv)
    init_database()
    result = AnnouncementJobRepository().requeue_announcement_job(
        normalize_post_url(args.post_url)
    )
    if result is None:
        print("Raw post not found.")
        return 1
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
