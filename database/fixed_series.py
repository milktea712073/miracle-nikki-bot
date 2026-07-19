"""Static, administrator-owned fixed series for the knowledge base."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class FixedSeriesSeed:
    name: str
    category: str
    display_order: int
    contents: tuple[tuple[str, str], ...] = ()


STORY_SERIES = (
    "相伴四季", "夏沫海歌", "永夜國之夢", "雲巔之戰", "時光流轉", "魑魅魍魎",
    "血月初擁", "風林火山", "歲月集影", "山海雲荒", "雲空之境", "萬象之汐",
    "綻階之庭", "蒼穹秘軌", "浮光境界", "朝夜之畔", "神眷之地", "迷緒心境",
    "時遇之流", "薔薇光華", "光域凝晶", "紀夢銘書", "旋沫之境", "四時畫語",
    "溯時之墟", "沉落之海", "星引明途", "星暉遺響", "魔盒幻旅", "蘑菇秘境",
    "失序之圜", "奇蹟的閃光", "循光覓影", "馥夢映像", "聖庭之謁", "遙夜夢譚",
)

STAR_CONTENTS = (
    "翼火蛇", "奎木狼", "鬼金羊", "畢月烏", "女土蝠", "尾火虎", "心月狐",
    "亢金龍", "角木蛟", "張月鹿", "房日兔",
)

WEDDING_CONTENTS = (
    "白羽戀詩", "旋夢心韻", "溯海鯨夢", "榮花良緣", "芳庭誓約", "與子成說",
    "喜繡緣", "童心愛戀", "紫藤花誓言", "花嫁童話", "琉璃花焰", "純白小戀歌",
    "月光奏鳴曲", "花雨誓約", "夢中的婚禮", "明日如詩", "醉繡閨", "緣定今生",
    "美夢成真",
)

FIXED_SERIES_SEEDS: tuple[FixedSeriesSeed, ...] = tuple(
    FixedSeriesSeed(name, "故事套裝", index)
    for index, name in enumerate(STORY_SERIES)
) + (
    FixedSeriesSeed(
        "滿天繁星", "滿天繁星", len(STORY_SERIES),
        tuple((name, "main") for name in STAR_CONTENTS),
    ),
    FixedSeriesSeed(
        "夢戀奇蹟", "夢戀奇蹟", len(STORY_SERIES) + 1,
        tuple((name, "main") for name in WEDDING_CONTENTS),
    ),
    FixedSeriesSeed("化石展", "奇妙博物館", len(STORY_SERIES) + 2),
    FixedSeriesSeed("星座展", "奇妙博物館", len(STORY_SERIES) + 3),
    FixedSeriesSeed("奧秘展", "奇妙博物館", len(STORY_SERIES) + 4),
    FixedSeriesSeed("童話夢鄉", "童話夢鄉", len(STORY_SERIES) + 5),
)


def seed_fixed_series(connection: sqlite3.Connection) -> tuple[int, int]:
    """Insert static series and contents without overwriting administrator edits."""
    now = datetime.now(timezone.utc).isoformat()
    created_series = created_contents = 0
    for seed in FIXED_SERIES_SEEDS:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO series (
                name, category, display_order, notes, diamond_cost, is_active,
                created_at, updated_at
            ) VALUES (?, ?, ?, NULL, NULL, 1, ?, ?)
            """,
            (seed.name, seed.category, seed.display_order, now, now),
        )
        created_series += int(cursor.rowcount == 1)
        series_id = int(
            connection.execute("SELECT id FROM series WHERE name = ?", (seed.name,)).fetchone()[0]
        )
        for position, (name, content_type) in enumerate(seed.contents):
            connection.execute(
                """
                INSERT INTO suits (name, is_live2d, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO NOTHING
                """,
                (name, int(content_type == "live2d"), now, now),
            )
            suit_id = int(connection.execute("SELECT id FROM suits WHERE name = ?", (name,)).fetchone()[0])
            if content_type == "live2d":
                connection.execute("UPDATE suits SET is_live2d = 1 WHERE id = ?", (suit_id,))
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO series_contents (
                    series_id, suit_id, type, display_order, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (series_id, suit_id, content_type, position, now, now),
            )
            created_contents += int(cursor.rowcount == 1)
    # Seed data is maintained through Series, but every Series is represented
    # by the normal Event -> EventSuit -> Suit graph used by Discord.
    from database.database import _synchronize_existing_series_events

    _synchronize_existing_series_events(connection)
    return created_series, created_contents
