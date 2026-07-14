"""Migrate legacy baseline rows out of the sent-announcement ledger."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from database.announcement_job_repository import AnnouncementJobRepository
from database.database import init_database


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return argparse.ArgumentParser(
        description="DEPRECATED one-time migration: move legacy baseline rows into announcement_jobs."
    ).parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    print("DEPRECATED: run this only when migrating a pre-queue announcement database.")
    if input("This updates announcement delivery records. Type YES to continue: ").strip() != "YES":
        print("Migration cancelled.")
        return 1
    init_database()
    sent, skipped = AnnouncementJobRepository().migrate_legacy_announcements()
    print(f"Migrated sent announcements: {sent}")
    print(f"Migrated baseline skipped records: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
