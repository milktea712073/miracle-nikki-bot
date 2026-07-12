"""Safely identify and remove clearly invalid automatically created suits."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH, get_connection, initialize_knowledge_base_tables
from parser.announcement_parser import is_valid_suit_name


@dataclass(frozen=True, slots=True)
class InvalidAutoSuit:
    suit_id: int
    name: str
    event_names: tuple[str, ...]


def find_invalid_auto_suits(database_path: Path = DATABASE_PATH) -> list[InvalidAutoSuit]:
    """Return auto-only suits matching the parser's invalid-name rules."""
    connection = get_connection(database_path)
    try:
        initialize_knowledge_base_tables(connection)
        rows = connection.execute(
            """
            SELECT s.id, s.name, GROUP_CONCAT(e.name, ' | ')
            FROM suits AS s
            LEFT JOIN event_suits AS es ON es.suit_id = s.id
            LEFT JOIN events AS e ON e.id = es.event_id
            WHERE s.created_via = 'auto' AND s.data_status = 'auto'
            GROUP BY s.id, s.name
            ORDER BY s.id
            """
        ).fetchall()
        return [
            InvalidAutoSuit(int(row[0]), str(row[1]), tuple(filter(None, str(row[2] or "").split(" | "))))
            for row in rows
            if not is_valid_suit_name(str(row[1]))
        ]
    finally:
        connection.close()


def delete_invalid_auto_suits(
    suits: list[InvalidAutoSuit], database_path: Path = DATABASE_PATH
) -> int:
    """Remove only the supplied auto-only suits and their dependent associations."""
    if not suits:
        return 0
    connection = get_connection(database_path)
    try:
        initialize_knowledge_base_tables(connection)
        connection.execute("BEGIN")
        deleted = 0
        for suit in suits:
            current = connection.execute(
                "SELECT created_via, data_status FROM suits WHERE id = ?", (suit.suit_id,)
            ).fetchone()
            if current != ("auto", "auto"):
                continue
            connection.execute("DELETE FROM event_suits WHERE suit_id = ?", (suit.suit_id,))
            connection.execute("DELETE FROM cost_records WHERE suit_id = ?", (suit.suit_id,))
            connection.execute("DELETE FROM suits WHERE id = ?", (suit.suit_id,))
            deleted += 1
        connection.commit()
        return deleted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List or remove invalid auto-created suits.")
    parser.add_argument("--apply", action="store_true", help="Delete listed suits after confirmation.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    suits = find_invalid_auto_suits()
    if not suits:
        print("No invalid auto-created suits found.")
        return
    print("ID | Suit | Events")
    for suit in suits:
        print(f"{suit.suit_id} | {suit.name} | {'; '.join(suit.event_names) or '-'}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to delete these auto-only suits.")
        return
    if input("Type YES to delete the listed auto-created suits: ").strip() != "YES":
        print("Cleanup cancelled.")
        return
    print(f"Deleted {delete_invalid_auto_suits(suits)} suit(s).")


if __name__ == "__main__":
    main()
