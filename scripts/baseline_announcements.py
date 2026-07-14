"""Mark explicit historical announcement URLs as skipped without Discord delivery."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from database.announcement_baseline import (
    apply_announcement_baseline,
    build_announcement_baseline_plan,
)
from database.database import get_connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely baseline historical posts without sending Discord announcements."
    )
    parser.add_argument(
        "--post-url",
        action="append",
        required=True,
        help="A canonical current-cycle Facebook post URL. Repeat for every URL.",
    )
    parser.add_argument(
        "--exclude-post-url",
        required=True,
        help="The one current post URL that must remain unannounced and ready to send.",
    )
    return parser.parse_args()


def print_plan(plan) -> None:
    print("Historical posts to baseline (no Discord message will be sent):")
    for url in plan.baseline_urls:
        print(f"- {url}")
    if plan.already_announced_urls:
        print("Already announced (left unchanged):")
        for url in plan.already_announced_urls:
            print(f"- {url}")
    print("Excluded post that remains pending delivery:")
    print(f"- {plan.excluded_url}")


def main() -> int:
    args = parse_args()
    connection = get_connection()
    try:
        plan = build_announcement_baseline_plan(
            connection, args.post_url, args.exclude_post_url
        )
        print_plan(plan)
        print()
        confirmation = input(
            "This will permanently mark the listed historical posts as skipped. "
            "Type YES to continue: "
        )
        if confirmation != "YES":
            print("Baseline cancelled. No database records were changed.")
            return 1

        count = apply_announcement_baseline(connection, plan)
        print(f"Baseline complete: {count} historical posts marked skipped.")
        print("Still pending delivery:")
        print(f"- {plan.excluded_url}")
        return 0
    except ValueError as error:
        print(f"Baseline aborted: {error}")
        return 2
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
