"""Queue the latest real Discord delivery for an explicit development resend."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from database.announcement_job_repository import AnnouncementJobRepository
from scripts.requeue_announcement import print_result


def main() -> int:
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
    raise SystemExit(main())
