"""Stage one latest official notice for an explicit test-channel replay.

This utility never reads the legacy Queue or ``database.db``. It does not send
Discord itself: it only creates or resets the requested v2 delivery so the
existing dispatcher remains the sole delivery implementation.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from announcement.models import Announcement
from announcement.state_store import AnnouncementStateStore, DEFAULT_STATE_DATABASE_PATH
from crawler.cn_official_crawler import fetch_recent_announcements as fetch_cn_official
from crawler.tw_official_crawler import fetch_recent_announcements as fetch_tw_official


Fetcher = Callable[[int], list[Announcement]]
FETCHERS: dict[str, Fetcher] = {"tw": fetch_tw_official, "cn": fetch_cn_official}


@dataclass(frozen=True, slots=True)
class ReplayResult:
    announcement: Announcement
    channel_id: int | None
    announcement_id: int | None
    replayed: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=sorted(FETCHERS), required=True)
    parser.add_argument("--channel-id", type=int, help="Explicit Discord channel to receive this replay.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and preview only; do not change v2 state.")
    parser.add_argument("--replay", action="store_true", help="Create or reset only the explicit channel delivery.")
    parser.add_argument("--state-database", type=Path, default=DEFAULT_STATE_DATABASE_PATH)
    args = parser.parse_args(argv)
    if args.dry_run and args.replay:
        parser.error("--dry-run and --replay cannot be used together.")
    if args.replay and args.channel_id is None:
        parser.error("--replay requires --channel-id; no default announcement channel is used.")
    if not args.dry_run and not args.replay:
        args.dry_run = True
    return args


def replay_latest(
    source: str,
    channel_id: int | None,
    *,
    replay: bool,
    state_database: Path,
    fetchers: dict[str, Fetcher] = FETCHERS,
) -> ReplayResult:
    announcements = fetchers[source](1)
    if not announcements:
        raise RuntimeError(f"No latest {source} official announcement was returned.")
    announcement = announcements[0]
    if not replay:
        return ReplayResult(announcement, channel_id, None, False)
    if channel_id is None:
        raise ValueError("A replay channel is required.")
    announcement_id = AnnouncementStateStore(state_database).register(
        announcement, [channel_id], reset_deliveries=True
    )
    return ReplayResult(announcement, channel_id, announcement_id, True)


def print_result(result: ReplayResult) -> None:
    announcement = result.announcement
    print(f"source: {announcement.source}")
    print(f"external_id: {announcement.external_id}")
    print(f"title: {announcement.title}")
    print(f"channel_id: {result.channel_id if result.channel_id is not None else 'not provided'}")
    print(f"url: {announcement.canonical_url}")
    print(f"images: {len(announcement.images)}")
    if result.replayed:
        print(f"announcement_id: {result.announcement_id}")
        print("delivery: pending (only the explicit channel was created or reset)")
        print("dispatch: not performed; use the existing authenticated dispatcher path to send it.")
    else:
        print("mode: dry-run (no state was changed)")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = replay_latest(
        args.source,
        args.channel_id,
        replay=args.replay,
        state_database=args.state_database,
    )
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
