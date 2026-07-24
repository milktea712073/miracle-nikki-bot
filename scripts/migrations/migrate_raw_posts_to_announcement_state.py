"""Copy retained legacy raw announcements into the standalone v2 state database.

The legacy database is opened read-only.  This script never creates deliveries
or writes to the legacy Knowledge database.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from announcement.history_archive import ArchivedRawImage, ArchivedRawPost, HistoricalRawArchive
from announcement.state_store import AnnouncementStateStore, DEFAULT_STATE_DATABASE_PATH, utc_now
from database.database import DATABASE_PATH


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--state-database", type=Path, default=DEFAULT_STATE_DATABASE_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Report the migration plan without writing state.")
    return parser.parse_args(argv)


def _legacy_connection(database_path: Path) -> sqlite3.Connection:
    if not database_path.exists():
        raise FileNotFoundError(f"Legacy database not found: {database_path}")
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _column_expression(columns: set[str], name: str) -> str:
    return name if name in columns else f"NULL AS {name}"


def read_legacy_archive(database_path: Path) -> tuple[tuple[ArchivedRawPost, ...], tuple[ArchivedRawImage, ...]]:
    """Read legacy rows without changing the source database."""
    connection = _legacy_connection(database_path)
    try:
        table_names = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "raw_posts" not in table_names:
            raise RuntimeError("Legacy database does not contain raw_posts.")
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(raw_posts)")}
        required = {"id", "source", "source_post_id", "url", "content"}
        missing = sorted(required - columns)
        if missing:
            raise RuntimeError(f"Legacy raw_posts is missing required columns: {', '.join(missing)}")
        optional = ("published_at", "scraped_at", "updated_at", "parse_status", "parse_error", "content_hash", "metadata_json")
        select_columns = ["id", "source", "source_post_id", "url", "content", *[_column_expression(columns, name) for name in optional]]
        rows = connection.execute(f"SELECT {', '.join(select_columns)} FROM raw_posts ORDER BY id").fetchall()
        posts = tuple(
            ArchivedRawPost(
                legacy_raw_post_id=int(row[0]), source=str(row[1]),
                source_post_id=str(row[2]) if row[2] is not None else None,
                url=str(row[3]), content=str(row[4]),
                published_at=str(row[5]) if row[5] is not None else None,
                scraped_at=str(row[6]) if row[6] is not None else None,
                updated_at=str(row[7]) if row[7] is not None else None,
                parse_status=str(row[8]) if row[8] is not None else None,
                parse_error=str(row[9]) if row[9] is not None else None,
                content_hash=str(row[10]) if row[10] is not None else None,
                metadata_json=str(row[11]) if row[11] is not None else None,
            )
            for row in rows
        )
        if "raw_post_images" not in table_names:
            return posts, ()
        image_rows = connection.execute(
            "SELECT raw_post_id, image_url, position, created_at FROM raw_post_images ORDER BY raw_post_id, position, id"
        ).fetchall()
        images = tuple(
            ArchivedRawImage(
                legacy_raw_post_id=int(row[0]), image_url=str(row[1]), position=int(row[2]),
                created_at=str(row[3]) if row[3] is not None else "",
            )
            for row in image_rows
        )
        return posts, images
    finally:
        connection.close()


def print_stats(stats: object, *, dry_run: bool) -> None:
    prefix = "Would " if dry_run else ""
    print(f"Legacy raw_posts: {stats.source_raw_posts}")
    print(f"{prefix}insert raw_posts: {stats.inserted_raw_posts}")
    print(f"Existing/skip raw_posts: {stats.existing_raw_posts}")
    print("Failed raw_posts: 0")
    print(f"Legacy raw_post_images: {stats.source_images}")
    print(f"{prefix}insert images: {stats.inserted_images}")
    print(f"Duplicate/skip images: {stats.duplicate_images}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        posts, images = read_legacy_archive(args.legacy_database)
        archive = HistoricalRawArchive(args.state_database)
        if args.dry_run:
            print_stats(archive.plan(posts, images), dry_run=True)
            print("Dry run only. No state was changed.")
            return 0
        AnnouncementStateStore(args.state_database)
        print_stats(archive.synchronize(posts, images, migrated_at=utc_now()), dry_run=False)
        return 0
    except Exception as error:
        print(f"ERROR: migration rolled back: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
