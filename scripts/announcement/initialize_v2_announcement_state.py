"""Initialize v2 delivery state from the legacy sent ledger without modifying it."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from announcement.models import Announcement
from announcement.state_store import AnnouncementStateStore, DEFAULT_STATE_DATABASE_PATH
from crawler.facebook_crawler import get_latest_posts
from database.database import DATABASE_PATH


def parse_channel_ids(value: str) -> tuple[int, ...]:
    return tuple(dict.fromkeys(int(item.strip()) for item in value.split(",") if item.strip()))


def load_local_env() -> None:
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read the legacy sent ledger and initialize only the standalone v2 announcement state."
    )
    parser.add_argument("--legacy-database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--state-database", type=Path, default=DEFAULT_STATE_DATABASE_PATH)
    parser.add_argument("--channel-ids", default="", help="Comma-separated target channel IDs for imported sent state.")
    parser.add_argument("--apply", action="store_true", help="Write the reviewed legacy sent state to v2 state DB.")
    parser.add_argument(
        "--check-current", action="store_true",
        help="Also crawl current Taiwan Facebook posts and list identities that would be newly sent.",
    )
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_local_env()
    args = parse_args(argv)
    store = AnnouncementStateStore(args.state_database)
    plan = store.legacy_initialization_plan(args.legacy_database)
    print(f"Legacy sent candidates: {len(plan.legacy_sent)}")
    print(f"Already initialized: {len(plan.already_initialized)}")
    for item in plan.legacy_sent:
        print(f"SENT  {item.source} {item.external_id} {item.canonical_url}")

    if args.check_current:
        try:
            current = [Announcement.from_facebook_post(post) for post in get_latest_posts(args.limit)]
        except Exception as error:
            print(f"Current Taiwan crawl unavailable; would-newly-send check was not performed: {error}")
        else:
            known = {(item.source, item.external_id) for item in (*plan.legacy_sent, *plan.already_initialized)}
            new = [item for item in current if (item.source, item.external_id) not in known]
            print(f"Current Taiwan announcements: {len(current)}")
            print(f"Would newly send: {len(new)}")
            for item in new:
                print(f"NEW   {item.source} {item.external_id} {item.canonical_url}")

    if not args.apply:
        print("Dry run only. Pass --apply to write v2 state; legacy database is always read-only.")
        return 0

    configured_channels = os.getenv("TW_ANNOUNCEMENT_CHANNEL_IDS") or os.getenv(
        "ANNOUNCEMENT_CHANNEL_IDS", ""
    )
    channel_ids = parse_channel_ids(args.channel_ids or configured_channels)
    if not channel_ids:
        print("--channel-ids is required with --apply.", file=sys.stderr)
        return 2
    created = store.initialize_legacy_sent(plan, channel_ids)
    print(f"Initialized v2 sent state: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
