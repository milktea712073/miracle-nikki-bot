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
EXTERNAL_ID_LOOKUP_LIMIT = 100


class OfficialAnnouncementNotFound(LookupError):
    """Raised when a requested official external ID is absent from the crawler result."""

    def __init__(self, source: str, external_id: str) -> None:
        super().__init__(f"Official announcement not found: {source}/{external_id}")
        self.source = source
        self.external_id = external_id


@dataclass(frozen=True, slots=True)
class ReplayResult:
    announcement: Announcement
    channel_id: int | None
    announcement_id: int | None
    replayed: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=sorted(FETCHERS), required=True)
    parser.add_argument("--external-id", help="Replay one official announcement by its source-specific external ID.")
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


def select_announcement(
    source: str,
    external_id: str | None,
    *,
    fetchers: dict[str, Fetcher],
) -> Announcement:
    """Return the newest announcement or a requested ID from the existing source crawler."""
    announcements = fetchers[source](1 if external_id is None else EXTERNAL_ID_LOOKUP_LIMIT)
    if external_id is None:
        if not announcements:
            raise RuntimeError(f"No latest {source} official announcement was returned.")
        return announcements[0]

    for announcement in announcements:
        if announcement.external_id == external_id:
            return announcement
    raise OfficialAnnouncementNotFound(source, external_id)


def replay_latest(
    source: str,
    channel_id: int | None,
    *,
    replay: bool,
    state_database: Path,
    external_id: str | None = None,
    fetchers: dict[str, Fetcher] | None = None,
) -> ReplayResult:
    announcement = select_announcement(source, external_id, fetchers=fetchers or FETCHERS)
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
        print("Dry run only.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = replay_latest(
            args.source,
            args.channel_id,
            replay=args.replay,
            state_database=args.state_database,
            external_id=args.external_id,
        )
    except OfficialAnnouncementNotFound as error:
        print("ERROR: Official announcement not found.", file=sys.stderr)
        print(f"Source: {error.source}", file=sys.stderr)
        print(f"External ID: {error.external_id}", file=sys.stderr)
        return 1
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
