"""Interactive development utility for clearing the project's SQLite data."""

from __future__ import annotations

import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH, get_connection


LOGGER = logging.getLogger(__name__)

# These tables describe migrations or schema state rather than application data.
SYSTEM_TABLE_NAMES = frozenset({"alembic_version", "migration_history", "migrations", "schema_version"})
SYSTEM_TABLE_PREFIXES = ("migration_", "schema_")
SUMMARY_TABLES = {
    "raw_posts": "raw_posts",
    "parse_drafts": "drafts",
    "announcements": "announcements",
    "images": "images",
}


@dataclass(frozen=True, slots=True)
class ResetResult:
    """Outcome of clearing business data from a SQLite database."""

    cleared_tables: tuple[str, ...]
    missing_summary_tables: tuple[str, ...]
    sequence_reset: bool


def is_system_table(table_name: str) -> bool:
    """Return whether a table is reserved for schema or migration metadata."""
    return table_name in SYSTEM_TABLE_NAMES or table_name.startswith(SYSTEM_TABLE_PREFIXES)


def quote_identifier(identifier: str) -> str:
    """Quote an SQLite identifier obtained from sqlite_master safely."""
    return f'"{identifier.replace('"', '""')}"'


def list_business_tables(connection: sqlite3.Connection) -> list[str]:
    """List non-system application tables in deterministic order."""
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row[0]) for row in rows if not is_system_table(str(row[0]))]


def sqlite_sequence_exists(connection: sqlite3.Connection) -> bool:
    """Return whether this database has SQLite AUTOINCREMENT metadata."""
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    ).fetchone()
    return row is not None


def reset_database(database_path: Path = DATABASE_PATH) -> ResetResult:
    """Delete all business records, reset AUTOINCREMENT values, and vacuum SQLite."""
    if not database_path.exists():
        raise FileNotFoundError(f"Database file does not exist: {database_path}")

    connection = get_connection(database_path)
    try:
        business_tables = list_business_tables(connection)
        missing_summary_tables = tuple(
            table_name for table_name in SUMMARY_TABLES if table_name not in business_tables
        )
        for table_name in missing_summary_tables:
            LOGGER.warning("Table %s does not exist; skipping it.", table_name)

        # The table list includes all dependent tables, so temporarily disable FK checks
        # while clearing it. The database remains structurally unchanged.
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute("BEGIN")
            for table_name in business_tables:
                connection.execute(f"DELETE FROM {quote_identifier(table_name)}")

            sequence_reset = sqlite_sequence_exists(connection)
            if sequence_reset:
                connection.execute("DELETE FROM sqlite_sequence")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

        # VACUUM must execute outside an active transaction.
        connection.execute("VACUUM")
        return ResetResult(
            cleared_tables=tuple(business_tables),
            missing_summary_tables=missing_summary_tables,
            sequence_reset=sequence_reset,
        )
    finally:
        connection.close()


def print_reset_summary(result: ResetResult) -> None:
    """Print the concise operator-facing reset summary."""
    print("=================================")
    print("Database reset complete")
    for table_name, label in SUMMARY_TABLES.items():
        status = "cleared" if table_name in result.cleared_tables else "missing"
        print(f"{label}: {status}")
    print("AUTOINCREMENT reset" if result.sequence_reset else "AUTOINCREMENT reset skipped")
    print("VACUUM complete")
    print("=================================")


def main() -> None:
    """Request explicit confirmation before irreversibly clearing the database."""
    print("This will permanently delete all database records.")
    confirmation = input("Type YES to continue: ").strip()
    if confirmation != "YES":
        print("Database reset cancelled.")
        return

    try:
        result = reset_database()
    except (OSError, sqlite3.Error) as error:
        LOGGER.error("Database reset failed: %s", error)
        raise SystemExit(1) from error
    print_reset_summary(result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
