from pathlib import Path

import pytest

from bot.admin.knowledge_event_views import EventAdminView, EventEditMenuView, EventEditSession
from bot.admin.knowledge_suit_views import SuitRelationModal
from bot.main import create_suit_embed
from bot.main import create_event_response_view
from database.database import get_connection, init_database
from database.knowledge_query_repository import KnowledgeQueryRepository


def seed_events(database_path: Path) -> tuple[int, int]:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        event_id = connection.execute(
            """
            INSERT INTO events (name, content_type, created_at, updated_at)
            VALUES ('正常活動', 'event', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        ).lastrowid
        wallpaper_id = connection.execute(
            """
            INSERT INTO events (name, content_type, created_at, updated_at)
            VALUES ('六月桌布套組', 'wallpaper', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        ).lastrowid
        connection.execute(
            "INSERT INTO event_periods (event_id, period_type, created_at) VALUES (?, 'unknown', '2026-01-01T00:00:00+00:00')",
            (event_id,),
        )
        connection.commit()
        return int(event_id), int(wallpaper_id)
    finally:
        connection.close()


def test_wallpaper_does_not_appear_in_event_queries(tmp_path: Path) -> None:
    database_path = tmp_path / "event-filter.db"
    seed_events(database_path)
    repository = KnowledgeQueryRepository(database_path)

    assert repository.get_event_by_name("正常活動") is not None
    assert repository.get_event_by_name("六月桌布套組") is None
    assert repository.search_event_names("") == ["正常活動"]


def test_admin_event_update_marks_event_verified_and_can_hide_it(tmp_path: Path) -> None:
    database_path = tmp_path / "event-edit.db"
    event_id, _ = seed_events(database_path)
    repository = KnowledgeQueryRepository(database_path)

    repository.update_event_management(
        event_id,
        name="已校正活動",
        content_type="event",
        event_status="預告",
        official_series="官方系列",
        notes="管理員備註",
        start_at="2026-07-13T05:00:00+08:00",
        end_at="2026-07-19T23:59:00+08:00",
        is_visible=False,
    )

    connection = get_connection(database_path)
    try:
        assert connection.execute(
            "SELECT data_status, event_status, official_series, description, is_visible FROM events WHERE id = ?",
            (event_id,),
        ).fetchone() == ("verified", "預告", "官方系列", "管理員備註", 0)
        assert connection.execute(
            "SELECT start_at, end_at, data_status FROM event_periods WHERE event_id = ?",
            (event_id,),
        ).fetchone() == ("2026-07-13T05:00:00+08:00", "2026-07-19T23:59:00+08:00", "verified")
    finally:
        connection.close()
    assert repository.get_event_by_name("已校正活動") is None


def test_only_administrators_receive_event_management_buttons() -> None:
    admin_view = create_event_response_view(1, "活動", True)
    assert isinstance(admin_view, EventAdminView)
    assert create_event_response_view(1, "活動", False) is None
    assert {child.label for child in admin_view.children} == {"✏️ 編輯", "✅ 標記已確認"}
    menu = EventEditMenuView(EventEditSession(1, 2, 3, 4, 5))
    assert {child.label for child in menu.children} == {"1️⃣ 活動資訊", "2️⃣ 完成編輯", "3️⃣ 取消"}


def test_compact_event_info_creates_category_and_validates_period(tmp_path: Path) -> None:
    database_path = tmp_path / "compact-info.db"
    event_id, _ = seed_events(database_path)
    repository = KnowledgeQueryRepository(database_path)

    repository.save_event_info(event_id, "扭蛋", "2026-07-10 05:00", "2026-07-16 23:59", "測試備註")

    context = repository.get_event_edit_context(event_id)
    assert context is not None
    assert context.event_type_name == "扭蛋"
    assert context.start_at == "2026-07-10T05:00:00+08:00"
    with pytest.raises(ValueError, match="結束時間"):
        repository.save_event_info(event_id, "扭蛋", "2026-07-16 23:59", "2026-07-10 05:00", None)


def test_compact_suit_editor_saves_appearance_method_and_cost(tmp_path: Path) -> None:
    database_path = tmp_path / "compact-suit.db"
    event_id, _ = seed_events(database_path)
    repository = KnowledgeQueryRepository(database_path)

    suit_id = repository.save_event_suit_details(
        event_id, None, name="逐風之翎", appearance_status="debut", acquisition_method="花鑽", cost_text="620 星曜石"
    )

    details = repository.get_event_suit_details(event_id, suit_id)
    assert details == {"name": "逐風之翎", "appearance_status": "debut", "acquisition_method": "花鑽", "cost_text": "620 星曜石"}


def test_suit_relation_modal_replaces_appearance_with_event_category(tmp_path: Path) -> None:
    database_path = tmp_path / "relation-modal.db"
    event_id, _ = seed_events(database_path)
    repository = KnowledgeQueryRepository(database_path)
    suit_id = repository.save_event_suit_details(event_id, None, name="逐風之翎", acquisition_method="花鑽", cost_text="1000")
    context = repository.get_suit_edit_context(suit_id)
    assert context is not None

    modal = SuitRelationModal(context, context.events[0], None)

    labels = [item.label for item in modal.children]
    assert "活動分類" in labels
    assert not any("登場狀態" in label for label in labels)


def test_suit_relation_category_updates_event_not_suit(tmp_path: Path) -> None:
    database_path = tmp_path / "relation-category.db"
    event_id, _ = seed_events(database_path)
    repository = KnowledgeQueryRepository(database_path)
    suit_id = repository.save_event_suit_details(
        event_id, None, name="逐風之翎", event_type_name="扭蛋", acquisition_method="花鑽", cost_text="1000"
    )

    suit = repository.get_suit_by_name("逐風之翎")
    assert suit is not None
    assert suit.events[0].event_type == "扭蛋"
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT event_type_id FROM events WHERE id = ?", (event_id,)).fetchone()[0] is not None
        columns = [row[1] for row in connection.execute("PRAGMA table_info(suits)")]
    finally:
        connection.close()
    assert "event_type_id" not in columns


def test_suit_card_admin_shows_missing_category_but_player_hides_it(tmp_path: Path) -> None:
    database_path = tmp_path / "missing-category.db"
    event_id, _ = seed_events(database_path)
    repository = KnowledgeQueryRepository(database_path)
    repository.save_event_suit_details(event_id, None, name="逐風之翎", acquisition_method="花鑽", cost_text="1000")
    suit = repository.get_suit_by_name("逐風之翎")
    assert suit is not None

    assert "🏷️ 活動分類：尚未設定" in create_suit_embed(suit, show_missing_category=True).description
    assert "活動分類" not in create_suit_embed(suit).description
