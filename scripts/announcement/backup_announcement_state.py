"""Create a verified, compressed backup of the official announcement state."""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from announcement.state_store import DEFAULT_STATE_DATABASE_PATH


DEFAULT_BACKUP_DIRECTORY = PROJECT_ROOT / "database" / "backups"


@dataclass(frozen=True, slots=True)
class BackupResult:
    archive_path: Path
    archive_size: int
    snapshot_size: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_BACKUP_DIRECTORY,
        help=f"Directory for .db.gz backups (default: {DEFAULT_BACKUP_DIRECTORY}).",
    )
    return parser.parse_args(argv)


def _timestamped_archive_path(output_dir: Path) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    candidate = output_dir / f"announcement_state-{timestamp}.db.gz"
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"announcement_state-{timestamp}-{suffix}.db.gz"
        suffix += 1
    return candidate


def verify_integrity(database_path: Path) -> None:
    """Raise when SQLite cannot verify the completed backup copy."""
    connection = sqlite3.connect(database_path)
    try:
        result = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
    finally:
        connection.close()
    if result != ["ok"]:
        raise RuntimeError(f"SQLite integrity_check failed: {', '.join(result)}")


def backup_announcement_state(source_path: Path, output_dir: Path) -> BackupResult:
    """Back up a SQLite database through the Backup API without writing its source."""
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Announcement state database was not found: {source_path}")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = _timestamped_archive_path(output_dir)
    snapshot_path = output_dir / f".{archive_path.stem}.partial.db"
    compressed_path = output_dir / f".{archive_path.name}.partial"

    try:
        source_uri = source_path.as_uri() + "?mode=ro"
        source = sqlite3.connect(source_uri, uri=True)
        destination = sqlite3.connect(snapshot_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        verify_integrity(snapshot_path)
        snapshot_size = snapshot_path.stat().st_size
        with snapshot_path.open("rb") as source_file, gzip.open(compressed_path, "wb") as archive_file:
            shutil.copyfileobj(source_file, archive_file)
        os.replace(compressed_path, archive_path)
        return BackupResult(
            archive_path=archive_path,
            archive_size=archive_path.stat().st_size,
            snapshot_size=snapshot_size,
        )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        snapshot_path.unlink(missing_ok=True)
        compressed_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = backup_announcement_state(DEFAULT_STATE_DATABASE_PATH, args.output_dir)
    except Exception as error:
        print(f"ERROR: backup failed: {error}", file=sys.stderr)
        return 1

    print(f"Backup path: {result.archive_path}")
    print(f"Compressed size: {result.archive_size} bytes")
    print(f"Snapshot size: {result.snapshot_size} bytes")
    print("Backup completed and integrity_check returned ok.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
