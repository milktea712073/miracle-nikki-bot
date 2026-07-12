from pathlib import Path

from bot.admin.knowledge_event_views import EventEditSession, EventSuitCorrectionModal
from database.database import get_connection, init_database
from database.knowledge_query_repository import KnowledgeQueryRepository


def seed_event_suits(database_path: Path) -> tuple[int, dict[str, int]]:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        event_id = connection.execute(
            "INSERT INTO events (name, created_at, updated_at) VALUES ('翼之活動', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        ).lastrowid
        suit_ids: dict[str, int] = {}
        for name in ("逐風之翎", "灼火之翼", "奇巧機械↑", "精密齒輪", "冶金秘典超值包", "新套裝"):
            suit_ids[name] = int(
                connection.execute(
                    "INSERT INTO suits (name, created_at, updated_at) VALUES (?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
                    (name,),
                ).lastrowid
            )
        for position, name in enumerate(("逐風之翎", "灼火之翼", "奇巧機械↑", "精密齒輪", "冶金秘典超值包")):
            connection.execute(
                "INSERT INTO event_suits (event_id, suit_id, display_order) VALUES (?, ?, ?)",
                (event_id, suit_ids[name], position),
            )
        connection.commit()
        return int(event_id), suit_ids
    finally:
        connection.close()


def test_each_correction_modal_loads_a_fresh_nonduplicated_suit_list(tmp_path: Path) -> None:
    database_path = tmp_path / "modal.db"
    event_id, _ = seed_event_suits(database_path)
    repository = KnowledgeQueryRepository(database_path)

    session = EventEditSession(1, 2, 3, event_id, 4)
    first = EventSuitCorrectionModal(session, repository.get_event_suit_names(event_id), None)
    repository.synchronize_event_suits(event_id, ["逐風之翎", "灼火之翼"])
    second = EventSuitCorrectionModal(session, repository.get_event_suit_names(event_id), None)

    assert str(first.suits.default).splitlines()[:2] == ["逐風之翎", "灼火之翼"]
    assert str(second.suits.default) == "逐風之翎\n灼火之翼"


def test_correction_removes_associations_but_keeps_removed_suit_records(tmp_path: Path) -> None:
    database_path = tmp_path / "remove.db"
    event_id, suit_ids = seed_event_suits(database_path)
    repository = KnowledgeQueryRepository(database_path)

    final_names = repository.synchronize_event_suits(event_id, ["逐風之翎", "灼火之翼"])

    assert final_names == ["逐風之翎", "灼火之翼"]
    assert repository.get_event_suit_names(event_id) == final_names
    connection = get_connection(database_path)
    try:
        assert connection.execute(
            "SELECT id FROM suits WHERE id = ?", (suit_ids["奇巧機械↑"],)
        ).fetchone() is not None
    finally:
        connection.close()


def test_correction_adds_renames_deduplicates_and_reuses_existing_suits(tmp_path: Path) -> None:
    database_path = tmp_path / "sync.db"
    event_id, suit_ids = seed_event_suits(database_path)
    repository = KnowledgeQueryRepository(database_path)

    final_names = repository.synchronize_event_suits(
        event_id,
        ["灼火之翼", "新套裝", "新套裝", "  ", "逐風之翎（改）", ""],
    )

    assert final_names == ["灼火之翼", "新套裝", "逐風之翎（改）"]
    assert repository.get_event_suit_names(event_id) == final_names
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM suits WHERE name = '新套裝'").fetchone()[0] == 1
        assert connection.execute(
            "SELECT suit_id FROM event_suits WHERE event_id = ? AND suit_id = ?",
            (event_id, suit_ids["新套裝"]),
        ).fetchone() is not None
        assert connection.execute("SELECT COUNT(*) FROM suits WHERE name = '逐風之翎（改）'").fetchone()[0] == 1
    finally:
        connection.close()


def test_correction_marks_event_verified_with_discord_provenance(tmp_path: Path) -> None:
    database_path = tmp_path / "verified.db"
    event_id, _ = seed_event_suits(database_path)

    KnowledgeQueryRepository(database_path).synchronize_event_suits(event_id, ["逐風之翎"])

    connection = get_connection(database_path)
    try:
        row = connection.execute(
            "SELECT data_status, updated_via, updated_at FROM events WHERE id = ?", (event_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row[0:2] == ("verified", "discord_admin")
    assert row[2] != "2026-01-01T00:00:00+00:00"
