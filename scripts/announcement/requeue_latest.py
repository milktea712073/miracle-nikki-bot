"""Queue the latest real Discord delivery for an explicit development resend."""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from database.announcement_job_repository import AnnouncementJobRepository
from database.database import init_database
from scripts.announcement.requeue_announcement import print_result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return argparse.ArgumentParser(
        description="Requeue the most recently sent real Discord announcement for an explicit development resend."
    ).parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv or [])
    init_database()
    repository = AnnouncementJobRepository()
    post_url = repository.find_latest_sent_announcement_url()
    if post_url is None:
        print("No sent announcement found.")
        return 1
    result = repository.requeue_announcement_job(post_url)
    if result is None:
        print("No sent announcement found.")
        return 1
    print_result(result, latest=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
