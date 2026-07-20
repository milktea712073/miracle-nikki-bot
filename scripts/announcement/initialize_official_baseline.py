"""Initialize latest-known official notices without creating deliveries."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from announcement.models import Announcement, CN_OFFICIAL, TW_OFFICIAL
from announcement.state_store import AnnouncementStateStore, DEFAULT_STATE_DATABASE_PATH
from crawler.cn_official_crawler import fetch_recent_announcements as fetch_cn_official
from crawler.tw_official_crawler import fetch_recent_announcements as fetch_tw_official


Fetcher = Callable[[int], list[Announcement]]


@dataclass(frozen=True, slots=True)
class OfficialBaselinePlan:
    announcements: tuple[Announcement, ...]
    dry_run: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show latest IDs without changing v2 state.")
    parser.add_argument("--state-database", type=Path, default=DEFAULT_STATE_DATABASE_PATH)
    return parser.parse_args(argv)


def build_plan(fetchers: dict[str, Fetcher]) -> OfficialBaselinePlan:
    announcements = []
    for source in (TW_OFFICIAL, CN_OFFICIAL):
        rows = fetchers[source](1)
        if not rows:
            raise RuntimeError(f"No latest official announcement returned for {source}.")
        announcements.append(rows[0])
    return OfficialBaselinePlan(tuple(announcements), False)


def apply_plan(store: AnnouncementStateStore, plan: OfficialBaselinePlan) -> None:
    for announcement in plan.announcements:
        store.set_official_baseline(announcement.source, announcement.external_id)


def print_plan(plan: OfficialBaselinePlan) -> None:
    labels = {TW_OFFICIAL: "TW", CN_OFFICIAL: "CN"}
    for announcement in plan.announcements:
        print(labels[announcement.source])
        print(f"external_id: {announcement.external_id}")
        print(f"title: {announcement.title}")
    print("mode: dry-run (no state was changed)" if plan.dry_run else "mode: baseline initialized")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plan = build_plan({TW_OFFICIAL: fetch_tw_official, CN_OFFICIAL: fetch_cn_official})
    plan = OfficialBaselinePlan(plan.announcements, args.dry_run)
    if not args.dry_run:
        apply_plan(AnnouncementStateStore(args.state_database), plan)
    print_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
