"""Migrate legacy baseline rows out of the sent-announcement ledger."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from database.announcement_job_repository import AnnouncementJobRepository
from database.database import init_database


def main() -> None:
    init_database()
    sent, skipped = AnnouncementJobRepository().migrate_legacy_announcements()
    print(f"Migrated sent announcements: {sent}")
    print(f"Migrated baseline skipped records: {skipped}")


if __name__ == "__main__":
    main()
