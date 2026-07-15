"""Safely skip historical jobs accidentally created by a development rebuild."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.announcement_job_repository import AnnouncementJobRepository
from database.database import init_database


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark reviewed historical rebuild jobs as skipped without deleting delivery history."
    )
    parser.add_argument(
        "--keep-pending-post-url",
        action="append",
        default=[],
        help="Canonical URL that is truly new and must remain pending. Repeat as needed.",
    )
    parser.add_argument(
        "--all-pending-are-history",
        action="store_true",
        help="Explicitly confirm that no pending/failed/sending job in this repair is new.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, input_fn=input) -> int:
    args = parse_args(argv)
    if not args.keep_pending_post_url and not args.all_pending_are_history:
        print(
            "Refusing to skip jobs without a keep URL. Provide --keep-pending-post-url "
            "or explicitly pass --all-pending-are-history."
        )
        return 2
    init_database()
    repository = AnnouncementJobRepository()
    plan = repository.plan_rebuild_repair(tuple(args.keep_pending_post_url))
    print("Historical jobs to mark skipped:")
    for job in plan.jobs_to_skip:
        print(f"- job {job.id}: {job.post_url} ({job.status})")
    print("Jobs kept pending for delivery:")
    for job in plan.jobs_to_keep_pending:
        print(f"- job {job.id}: {job.post_url} ({job.status})")
    if input_fn("Type YES to mark only the listed historical jobs as skipped: ").strip() != "YES":
        print("Queue repair cancelled. No database records were changed.")
        return 0
    changed = repository.apply_rebuild_repair(plan)
    print(f"Queue repair complete: {changed} historical job(s) marked skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
