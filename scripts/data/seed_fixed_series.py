"""Idempotently seed administrator-owned fixed knowledge series."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH, get_connection, init_database
from database.fixed_series import seed_fixed_series


def seed(database_path: Path | None = None) -> tuple[int, int]:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute("BEGIN")
        result = seed_fixed_series(connection)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed fixed Miracle Nikki series data.")
    parser.add_argument("--database-path", type=Path, default=DATABASE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    series, contents = seed(args.database_path)
    print(f"Fixed series created: {series}")
    print(f"Fixed series contents created: {contents}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
