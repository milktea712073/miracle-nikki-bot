"""Fixed-series schema, seed, activity-query, and editing integration tests."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import bot.main as bot_main
from bot.main import create_event_embed, create_event_response_view, create_suit_embed
from bot.admin.knowledge_event_views import (
    EventEditSession,
    SeriesInfoModal,
    SeriesPeriodsModal,
    SeriesSuitsModal,
)
from bot.admin.knowledge_suit_views import SuitImageManagementView
from database.database import get_connection, init_database
from database.fixed_series import FIXED_SERIES_SEEDS, seed_fixed_series
from database.knowledge_query_repository import KnowledgeQueryRepository


def seed_series(database_path: Path) -> tuple[int, int]:
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute("BEGIN")
        result = seed_fixed_series(connection)
        connection.commit()
        return result
    finally:
        connection.close()

def test_fixed_series_seed_is_idempotent_and_keeps_story_series_empty(tmp_path: Path) -> None:
    database_path = tmp_path / "series.db"
    created_series, created_contents = seed_series(database_path)
    assert created_series == len(FIXED_SERIES_SEEDS)
    assert created_contents == 30
    assert seed_series(database_path) == (0, 0)

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM series").fetchone()[0] == len(FIXED_SERIES_SEEDS)
        assert connection.execute(
            "SELECT COUNT(*) FROM series_contents WHERE series_id = (SELECT id FROM series WHERE name = '相伴四季')"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM series WHERE event_id IS NOT NULL"
        ).fetchone()[0] == len(FIXED_SERIES_SEEDS)
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM event_suits
            WHERE event_id = (SELECT event_id FROM series WHERE name = '滿天繁星')
            """
        ).fetchone()[0] == 11
    finally:
        connection.close()


def test_series_content_migration_replaces_legacy_names_with_suit_links(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-series.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                display_order INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                diamond_cost TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE series_contents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                display_order INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(series_id, name)
            );
            INSERT INTO series (name, category, created_at, updated_at)
            VALUES ('舊系列', '測試', 'x', 'x');
            INSERT INTO series_contents (series_id, name, type, display_order, created_at, updated_at)
            VALUES (1, '舊主套', 'main', 0, 'x', 'x');
            """
        )
        connection.commit()
    finally:
        connection.close()

    init_database(database_path)
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(series_contents)")}
        assert "suit_id" in columns and "name" not in columns
        assert connection.execute("SELECT name FROM suits WHERE name = '舊主套'").fetchone()[0] == "舊主套"
        assert connection.execute(
            """
            SELECT suits.name, series_contents.type
            FROM series_contents JOIN suits ON suits.id = series_contents.suit_id
            """
        ).fetchone() == ("舊主套", "main")
    finally:
        connection.close()


def test_series_activity_queries_include_content_and_empty_story_skeleton(tmp_path: Path) -> None:
    database_path = tmp_path / "series-query.db"
    seed_series(database_path)
    repository = KnowledgeQueryRepository(database_path)

    stars = repository.get_series_by_name("滿天繁星")
    story = repository.get_series_by_name("相伴四季")

    assert stars is not None and stars.entity_type == "series"
    assert [item.name for item in stars.suits] == [
        "翼火蛇", "奎木狼", "鬼金羊", "畢月烏", "女土蝠", "尾火虎", "心月狐",
        "亢金龍", "角木蛟", "張月鹿", "房日兔",
    ]
    assert story is not None and story.suits == []


def test_series_autocomplete_precedes_same_named_event_without_duplicate(tmp_path: Path) -> None:
    database_path = tmp_path / "series-autocomplete.db"
    seed_series(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute(
            "INSERT INTO events (name, content_type, created_at, updated_at) VALUES ('滿天繁星', 'event', 'x', 'x')"
        )
        connection.commit()
    finally:
        connection.close()
    repository = KnowledgeQueryRepository(database_path)

    options = repository.search_activity_options("滿天繁星")
    matches = [option for option in options if option[1] == "滿天繁星"]

    assert len(matches) == 1
    assert matches[0][0].isdigit()


def test_series_edit_updates_card_data_and_preserves_non_editable_content(tmp_path: Path) -> None:
    database_path = tmp_path / "series-edit.db"
    seed_series(database_path)
    repository = KnowledgeQueryRepository(database_path)
    before = repository.get_series_by_name("滿天繁星")
    assert before is not None

    repository.save_series_info(
        before.id,
        name="滿天繁星",
        category="固定系列",
        diamond_cost="1992",
        notes="管理員校正",
    )
    connection = get_connection(database_path)
    try:
        now = "2026-01-01T00:00:00+00:00"
        frame_id = connection.execute(
            "INSERT INTO suits (name, created_at, updated_at) VALUES ('星光框', ?, ?)",
            (now, now),
        ).lastrowid
        other_id = connection.execute(
            "INSERT INTO suits (name, created_at, updated_at) VALUES ('額外內容', ?, ?)",
            (now, now),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO series_contents (series_id, suit_id, type, display_order, created_at, updated_at)
            VALUES (?, ?, 'frame', 0, ?, ?)
            """,
            (before.id, frame_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO series_contents (series_id, suit_id, type, display_order, created_at, updated_at)
            VALUES (?, ?, 'other', 0, ?, ?)
            """,
            (before.id, other_id, now, now),
        )
        connection.commit()
    finally:
        connection.close()
    repository.save_series_contents(
        before.id,
        main=["套裝乙", "套裝甲", "套裝乙"],
        minor=["小套甲"],
        live2d=["夜幕"],
    )
    repository.save_series_periods(before.id, ["2017.12", "", "2018.12", "2017.12", "入心願（2023.6）"])
    after = repository.get_series_by_id(before.id)
    assert after is not None
    assert after.event_type == "固定系列"
    assert after.event_total_cost == "1992"
    assert after.description == "管理員校正"
    assert [(item.name, item.content_type) for item in after.suits] == [
        ("套裝乙", "main"), ("套裝甲", "main"), ("小套甲", "minor"),
        ("夜幕", "live2d"), ("星光框", "frame"), ("額外內容", "other"),
    ]
    assert after.series_periods == ["2017.12", "2018.12", "入心願（2023.6）"]
    embed = create_event_embed(after)
    assert "💎 花費：1992 鑽" in embed.description
    assert "👑 主套：\n套裝乙\n套裝甲" in embed.description
    assert "🎀 小套：\n小套甲" in embed.description
    assert "✨ Live2D：\n夜幕" in embed.description
    assert "📅 檔期：\n2017.12\n2018.12\n入心願（2023.6）" in embed.description
    assert "星光框" not in embed.description

    connection = get_connection(database_path)
    try:
        event_id = int(connection.execute("SELECT event_id FROM series WHERE id = ?", (after.id,)).fetchone()[0])
    finally:
        connection.close()
    event = repository.get_event_by_id(event_id)
    assert event is not None
    assert event.name == "滿天繁星"
    assert event.event_total_cost == "1992"
    assert set((item.name, item.content_type) for item in event.suits) == {
        ("套裝乙", "main"), ("套裝甲", "main"), ("小套甲", "minor"),
        ("夜幕", "live2d"), ("星光框", "frame"), ("額外內容", "other"),
    }


def test_series_admin_view_follows_existing_channel_gated_view_contract() -> None:
    assert create_event_response_view(1, "滿天繁星", False, entity_type="series") is None
    view = create_event_response_view(1, "滿天繁星", True, entity_type="series")
    assert view is not None
    assert view.entity_type == "series"
    assert {child.label for child in view.children} == {
        "✏️ 編輯資訊", "👗 編輯套裝", "📅 編輯檔期"
    }


def test_series_with_no_contents_or_periods_still_has_a_clean_card(tmp_path: Path) -> None:
    database_path = tmp_path / "empty-series.db"
    seed_series(database_path)
    series = KnowledgeQueryRepository(database_path).get_series_by_name("相伴四季")

    assert series is not None
    embed = create_event_embed(series)
    assert embed.description == "📚 分類：故事套裝"


def test_series_info_allows_empty_optional_category_cost_and_notes(tmp_path: Path) -> None:
    database_path = tmp_path / "series-optional-info.db"
    seed_series(database_path)
    repository = KnowledgeQueryRepository(database_path)
    series = repository.get_series_by_name("相伴四季")
    assert series is not None

    repository.save_series_info(
        series.id, name="相伴四季", category="", diamond_cost="", notes=""
    )

    refreshed = repository.get_series_by_id(series.id)
    assert refreshed is not None
    assert refreshed.event_type == ""
    assert refreshed.event_total_cost is None
    assert refreshed.description is None


def test_series_modals_split_information_suits_and_periods(tmp_path: Path) -> None:
    database_path = tmp_path / "series-modals.db"
    seed_series(database_path)
    repository = KnowledgeQueryRepository(database_path)
    series = repository.get_series_by_name("滿天繁星")
    assert series is not None
    context = repository.get_series_edit_context(series.id)
    assert context is not None
    session = EventEditSession(None, 1, 2, series.id, 3, "series")

    info = SeriesInfoModal(context, session)
    suits = SeriesSuitsModal(context, session)
    periods = SeriesPeriodsModal(context, session)

    assert [item.label for item in info.children] == ["系列名稱", "分類", "鑽石花費", "備註"]
    assert [item.label for item in suits.children] == ["主套", "小套", "Live2D"]
    assert [item.label for item in periods.children] == ["檔期"]


def test_series_contents_and_images_use_the_same_suit_records(tmp_path: Path) -> None:
    database_path = tmp_path / "series-shared-suits.db"
    seed_series(database_path)
    repository = KnowledgeQueryRepository(database_path)
    series = repository.get_series_by_name("永夜國之夢")
    assert series is not None

    repository.save_series_contents(series.id, main=["幻夜女王"], minor=[], live2d=[])
    connection = get_connection(database_path)
    try:
        raw_post_id = connection.execute(
            """
            INSERT INTO raw_posts (source, source_post_id, url, content, scraped_at, updated_at)
            VALUES ('test', 'shared-image', 'https://example.test/shared', 'image', 'x', 'x')
            """
        ).lastrowid
        raw_image_id = connection.execute(
            """
            INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at)
            VALUES (?, 'https://images.example.test/queen.jpg', 0, 'x')
            """,
            (raw_post_id,),
        ).lastrowid
        connection.commit()
    finally:
        connection.close()

    repository.save_series_images(series.id, ["https://images.example.test/queen.jpg"])
    suit = repository.get_suit_by_name("幻夜女王")
    assert suit is not None
    assert suit.series_names == ["永夜國之夢"]
    assert repository.get_display_image_for_suit(suit.id) == "https://images.example.test/queen.jpg"
    assert repository.get_primary_image_for_series(series.id) == "https://images.example.test/queen.jpg"
    suit_embed = create_suit_embed(suit)
    assert "🏛️ 所屬系列：永夜國之夢" in suit_embed.description
    assert "🏷️ 活動分類：故事套裝" in suit_embed.description
    assert "📚 所屬活動：" not in suit_embed.description
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM suits WHERE name = '幻夜女王'").fetchone()[0] == 1
        assert connection.execute(
            "SELECT raw_post_image_id FROM suit_images WHERE suit_id = ?", (suit.id,)
        ).fetchone()[0] == raw_image_id
    finally:
        connection.close()


def test_suit_owned_images_update_the_bound_series_event_without_raw_post(tmp_path: Path) -> None:
    database_path = tmp_path / "series-suit-images.db"
    seed_series(database_path)
    repository = KnowledgeQueryRepository(database_path)
    series = repository.get_series_by_name("永夜國之夢")
    assert series is not None
    repository.save_series_contents(series.id, main=["幻夜女王"], minor=[], live2d=[])
    suit = repository.get_suit_by_name("幻夜女王")
    assert suit is not None

    repository.save_suit_images(suit.id, ["https://images.example.test/manual-queen.jpg"])
    connection = get_connection(database_path)
    try:
        event_id = int(connection.execute("SELECT event_id FROM series WHERE id = ?", (series.id,)).fetchone()[0])
    finally:
        connection.close()
    assert repository.get_primary_image_for_event(event_id) == "https://images.example.test/manual-queen.jpg"
    assert repository.get_display_image_for_suit(suit.id) == "https://images.example.test/manual-queen.jpg"
    assert repository.get_suit_edit_context(suit.id).events[0].id == event_id

    view = SuitImageManagementView(suit.id, suit.name, [], owner_user_id=1, public_message=None)
    assert "圖片：【0 / 0】" in view.embed().description



def test_activity_autocomplete_exposes_seeded_series_to_event_command(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "series-command.db"
    seed_series(database_path)
    repository = KnowledgeQueryRepository(database_path)
    monkeypatch.setattr(bot_main, "KnowledgeQueryRepository", lambda: repository)
    interaction = SimpleNamespace()

    choices = asyncio.run(bot_main.event_name_autocomplete(interaction, "滿天繁星"))

    assert len(choices) == 1
    assert choices[0].name.startswith("滿天繁星")
    assert choices[0].value.isdigit()
