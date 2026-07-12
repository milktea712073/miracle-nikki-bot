from pathlib import Path

from database.database import get_connection, init_database
from scripts.cleanup_auto_suits import delete_invalid_auto_suits, find_invalid_auto_suits


def seed_auto_suits(database_path: Path) -> tuple[int, int]:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        event_id = connection.execute(
            "INSERT INTO events (name, created_at, updated_at) VALUES ('活動', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        ).lastrowid
        invalid_id = connection.execute(
            "INSERT INTO suits (name, created_at, updated_at, created_via, data_status) VALUES ('5', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 'auto', 'auto')"
        ).lastrowid
        verified_id = connection.execute(
            "INSERT INTO suits (name, created_at, updated_at, created_via, data_status) VALUES ('下裝·保留', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 'auto', 'verified')"
        ).lastrowid
        connection.execute("INSERT INTO event_suits (event_id, suit_id, display_order) VALUES (?, ?, 0)", (event_id, invalid_id))
        connection.execute("INSERT INTO event_suits (event_id, suit_id, display_order) VALUES (?, ?, 1)", (event_id, verified_id))
        connection.commit()
        return int(invalid_id), int(verified_id)
    finally:
        connection.close()


def test_cleanup_dry_run_does_not_change_database(tmp_path: Path) -> None:
    database_path = tmp_path / "cleanup.db"
    invalid_id, verified_id = seed_auto_suits(database_path)

    candidates = find_invalid_auto_suits(database_path)

    assert [candidate.suit_id for candidate in candidates] == [invalid_id]
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM suits").fetchone()[0] == 2
        assert connection.execute("SELECT id FROM suits WHERE id = ?", (verified_id,)).fetchone() is not None
    finally:
        connection.close()


def test_cleanup_deletes_only_invalid_auto_suits_and_relationships(tmp_path: Path) -> None:
    database_path = tmp_path / "cleanup-apply.db"
    invalid_id, verified_id = seed_auto_suits(database_path)

    assert delete_invalid_auto_suits(find_invalid_auto_suits(database_path), database_path) == 1

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT id FROM suits WHERE id = ?", (invalid_id,)).fetchone() is None
        assert connection.execute("SELECT id FROM suits WHERE id = ?", (verified_id,)).fetchone() is not None
        assert connection.execute("SELECT COUNT(*) FROM event_suits WHERE suit_id = ?", (invalid_id,)).fetchone()[0] == 0
    finally:
        connection.close()
