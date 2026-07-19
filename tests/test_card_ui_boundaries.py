"""Regression boundaries for event, fixed-series, and suit card responsibilities."""

from __future__ import annotations

import inspect
from pathlib import Path

from bot.admin.knowledge_event_views import EventAdminView
from bot.admin.knowledge_suit_views import SuitAdminView, SuitImageManagementView
from bot.main import create_event_embed, create_suit_embed
from database.database import get_connection, init_database
from database.fixed_series import seed_fixed_series
from database.knowledge_query_repository import KnowledgeQueryRepository


def _seed_regular_event(database_path: Path, *, source_raw_post_id: int | None = None) -> tuple[int, int]:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        now = "2026-07-19T00:00:00+00:00"
        event_type_id = connection.execute(
            "INSERT INTO event_types (name) VALUES ('測試活動')"
        ).lastrowid
        event_id = connection.execute(
            """
            INSERT INTO events (name, event_type_id, description, source_raw_post_id, created_at, updated_at)
            VALUES ('一般活動', ?, '活動備註', ?, ?, ?)
            """,
            (event_type_id, source_raw_post_id, now, now),
        ).lastrowid
        suit_id = connection.execute(
            "INSERT INTO suits (name, created_at, updated_at) VALUES ('一般套裝', ?, ?)",
            (now, now),
        ).lastrowid
        connection.execute(
            "INSERT INTO event_suits (event_id, suit_id, display_order) VALUES (?, ?, 0)",
            (event_id, suit_id),
        )
        connection.execute(
            """
            INSERT INTO event_periods (event_id, period_type, start_at, end_at, created_at)
            VALUES (?, 'debut', '2026-07-01T00:00:00+00:00', '2026-07-10T00:00:00+00:00', ?)
            """,
            (event_id, now),
        )
        connection.execute(
            "INSERT INTO cost_records (event_id, suit_id, cost_scope, cost_text) VALUES (?, NULL, 'event_total', '1992')",
            (event_id,),
        )
        connection.commit()
        return int(event_id), int(suit_id)
    finally:
        connection.close()


def test_regular_event_card_uses_only_its_source_raw_post_image_and_edit_button(tmp_path: Path) -> None:
    database_path = tmp_path / "regular-event-card.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        raw_post_id = connection.execute(
            """
            INSERT INTO raw_posts (source, source_post_id, url, content, scraped_at, updated_at)
            VALUES ('facebook', 'card-source', 'https://example.test/card-source', '公告', 'x', 'x')
            """
        ).lastrowid
        connection.execute(
            "INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at) VALUES (?, 'https://images.test/first.jpg', 0, 'x')",
            (raw_post_id,),
        )
        connection.execute(
            "INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at) VALUES (?, 'https://images.test/second.jpg', 1, 'x')",
            (raw_post_id,),
        )
        connection.commit()
    finally:
        connection.close()
    event_id, _ = _seed_regular_event(database_path, source_raw_post_id=int(raw_post_id))
    repository = KnowledgeQueryRepository(database_path)
    event = repository.get_event_by_id(event_id)
    assert event is not None

    embed = create_event_embed(event, repository.get_announcement_image_for_event_id(event_id))
    assert embed.image.url == "https://images.test/first.jpg"
    assert all(value in embed.description for value in ("測試活動", "活動期間", "一般套裝", "1992", "活動備註"))
    assert {child.label for child in EventAdminView(event_id, event.name).children} == {"✏️ 編輯"}


def test_fixed_series_card_has_only_fixed_series_controls_and_no_source_image(tmp_path: Path) -> None:
    database_path = tmp_path / "series-card.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute("BEGIN")
        seed_fixed_series(connection)
        connection.commit()
    finally:
        connection.close()
    repository = KnowledgeQueryRepository(database_path)
    series = repository.get_series_by_name("滿天繁星")
    assert series is not None

    embed = create_event_embed(series, repository.get_announcement_image_for_event_id(series.id))
    assert "主套" in embed.description
    assert "小套" not in embed.description
    assert embed.image.url is None
    assert {child.label for child in EventAdminView(series.id, series.name, entity_type="series").children} == {
        "✏️ 編輯資訊", "👗 編輯套裝", "📅 編輯檔期"
    }


def test_mixed_series_and_regular_event_relations_are_both_rendered(tmp_path: Path) -> None:
    database_path = tmp_path / "mixed-relations.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute("BEGIN")
        seed_fixed_series(connection)
        connection.commit()
    finally:
        connection.close()
    repository = KnowledgeQueryRepository(database_path)
    suit = repository.get_suit_by_name("翼火蛇")
    assert suit is not None
    regular_event_id, _ = _seed_regular_event(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute(
            "INSERT INTO event_suits (event_id, suit_id, display_order) VALUES (?, ?, 1)",
            (regular_event_id, suit.id),
        )
        connection.commit()
    finally:
        connection.close()

    refreshed = repository.get_suit_by_name("翼火蛇")
    assert refreshed is not None
    fixed_event = next(event for event in refreshed.events if event.series_name == "滿天繁星")
    regular_event = next(event for event in refreshed.events if event.event_name == "一般活動")
    assert fixed_event.event_id != regular_event.event_id

    embed = create_suit_embed(refreshed)
    assert "🏛️ 所屬系列：滿天繁星" in embed.description
    assert "📚 所屬活動：一般活動" in embed.description
    assert "Raw Post" not in embed.description


def test_suit_image_manager_is_suit_owned_and_never_opens_a_url_modal(tmp_path: Path) -> None:
    database_path = tmp_path / "suit-images.db"
    event_id, suit_id = _seed_regular_event(database_path)
    repository = KnowledgeQueryRepository(database_path)
    repository.save_suit_images(suit_id, ["https://images.test/one.jpg", "https://images.test/two.jpg"])
    view = SuitImageManagementView(
        suit_id, "一般套裝", repository.get_suit_image_urls(suit_id), owner_user_id=1, public_message=None
    )

    assert view.embed().image.url == "https://images.test/one.jpg"
    assert {child.label for child in view.children} == {"⬅️ 上一張", "➡️ 下一張", "📝 編輯圖片"}
    assert "send_modal" not in inspect.getsource(SuitImageManagementView.upload)
    assert repository.get_announcement_image_for_event_id(event_id) is None
    assert {child.label for child in SuitAdminView(suit_id).children} == {"✏️ 編輯套裝", "🖼️ 編輯圖片"}
