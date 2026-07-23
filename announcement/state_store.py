"""Small, standalone SQLite state store for v2 announcement delivery."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlsplit

from announcement.models import (
    Announcement,
    CN_OFFICIAL,
    TW_FACEBOOK_SOURCE,
    TW_OFFICIAL,
    canonical_announcement_url,
)
from announcement.history_archive import initialize_history_tables
from announcement.search import keyword_search_variants
from announcement.search_models import AnnouncementSearchPage, AnnouncementSearchResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DATABASE_PATH = PROJECT_ROOT / "database" / "announcement_state.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_image_urls(value: object) -> tuple[str, ...]:
    """Return stored announcement image URLs without letting malformed JSON break search."""
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(url.strip() for url in parsed if isinstance(url, str) and url.strip())


@dataclass(frozen=True, slots=True)
class PendingDelivery:
    delivery_id: int
    announcement_id: int
    channel_id: int
    announcement: Announcement


@dataclass(frozen=True, slots=True)
class LegacyInitializationPlan:
    legacy_sent: tuple[Announcement, ...]
    already_initialized: tuple[Announcement, ...]


class AnnouncementStateStore:
    """Persist only announcement delivery and future reminder state."""

    def __init__(self, database_path: Path | None = None, *, initialize: bool = True) -> None:
        self.database_path = database_path or DEFAULT_STATE_DATABASE_PATH
        if initialize:
            self.initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS announcements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_urls_json TEXT NOT NULL,
                    published_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    UNIQUE(source, external_id),
                    UNIQUE(source, canonical_url)
                );

                CREATE TABLE IF NOT EXISTS announcement_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    announcement_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    message_ids_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    FOREIGN KEY (announcement_id) REFERENCES announcements(id) ON DELETE CASCADE,
                    UNIQUE(announcement_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    activity_name TEXT NOT NULL,
                    deadline_at TEXT NOT NULL,
                    reminder_sent_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, external_id, deadline_at)
                );

                CREATE INDEX IF NOT EXISTS idx_v2_delivery_status
                    ON announcement_deliveries(status, created_at);

                CREATE TABLE IF NOT EXISTS official_baselines (
                    source TEXT PRIMARY KEY,
                    external_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(announcements)").fetchall()
            }
            for column_sql in (
                "title TEXT NOT NULL DEFAULT ''",
                "category TEXT",
                "content_html TEXT",
            ):
                column_name = column_sql.split()[0]
                if column_name not in columns:
                    connection.execute(f"ALTER TABLE announcements ADD COLUMN {column_sql}")
            initialize_history_tables(connection)
            connection.commit()
        finally:
            connection.close()

    def get_official_baseline(self, source: str) -> str | None:
        """Return the last known official notice identity for one source."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT external_id FROM official_baselines WHERE source = ?", (source,)
            ).fetchone()
            return str(row[0]) if row is not None else None
        finally:
            connection.close()

    def set_official_baseline(self, source: str, external_id: str) -> None:
        """Persist one official source's latest known external identifier."""
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO official_baselines (source, external_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    external_id = excluded.external_id, updated_at = excluded.updated_at
                """,
                (source, str(external_id), utc_now()),
            )
            connection.commit()
        finally:
            connection.close()

    def search_announcements(
        self,
        keyword: str,
        *,
        source: str | None = None,
        limit: int = 10,
    ) -> AnnouncementSearchPage:
        """Search title and body with literal Traditional/Simplified keyword variants."""
        normalized_keyword = keyword.strip()
        if not normalized_keyword:
            raise ValueError("keyword must not be blank")
        if limit < 1:
            raise ValueError("limit must be positive")

        match_clauses: list[str] = []
        parameters: list[object] = []
        for variant in keyword_search_variants(normalized_keyword):
            escaped_variant = variant.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            match_clauses.append("(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')")
            parameters.extend((f"%{escaped_variant}%", f"%{escaped_variant}%"))
        where_clauses = [f"({' OR '.join(match_clauses)})"]
        if source == TW_OFFICIAL:
            where_clauses.append("source IN (?, ?)")
            parameters.extend((TW_OFFICIAL, TW_FACEBOOK_SOURCE))
        elif source is not None:
            where_clauses.append("source = ?")
            parameters.append(source)
        else:
            where_clauses.append("source IN (?, ?, ?)")
            parameters.extend((TW_OFFICIAL, CN_OFFICIAL, TW_FACEBOOK_SOURCE))
        parameters.append(limit + 1)

        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT id, source, external_id, title, canonical_url, published_at, content, image_urls_json
                FROM announcements
                WHERE {' AND '.join(where_clauses)}
                ORDER BY published_at IS NULL ASC, published_at DESC, id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        finally:
            connection.close()

        has_more = len(rows) > limit
        return AnnouncementSearchPage(
            results=tuple(
                AnnouncementSearchResult(
                    source_kind="announcement",
                    source_record_id=int(row[0]),
                    source=str(row[1]),
                    region=("cn" if str(row[1]) == CN_OFFICIAL else "tw"),
                    external_id=str(row[2]),
                    title=str(row[3]),
                    canonical_url=str(row[4]),
                    published_at=str(row[5]) if row[5] is not None else None,
                    content_text=str(row[6]),
                    image_urls=_load_image_urls(row[7]),
                )
                for row in rows[:limit]
            ),
            has_more=has_more,
        )

    def register(
        self,
        announcement: Announcement,
        channel_ids: Iterable[int],
        *,
        reset_deliveries: bool = False,
    ) -> int:
        """Store one announcement and optionally reset only explicit target deliveries.

        Normal polling uses the default snapshot behaviour. Explicit replay tools
        pass ``reset_deliveries=True`` to requeue only the supplied channels.
        """
        channels = tuple(dict.fromkeys(int(channel_id) for channel_id in channel_ids))
        now = utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            existing = connection.execute(
                "SELECT id FROM announcements WHERE source = ? AND (external_id = ? OR canonical_url = ?)",
                (announcement.source, announcement.external_id, announcement.canonical_url),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO announcements (
                        source, external_id, canonical_url, title, category, content_html,
                        content, image_urls_json, published_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        announcement.source,
                        announcement.external_id,
                        announcement.canonical_url,
                        announcement.title,
                        announcement.category,
                        announcement.content_html,
                        announcement.content_text,
                        json.dumps(announcement.images, ensure_ascii=False),
                        announcement.published_at.isoformat() if announcement.published_at else None,
                        now,
                        now,
                    ),
                )
                announcement_id = int(cursor.lastrowid)
                connection.executemany(
                    """
                    INSERT INTO announcement_deliveries (
                        announcement_id, channel_id, status, created_at, updated_at
                    ) VALUES (?, ?, 'pending', ?, ?)
                    """,
                    [(announcement_id, channel_id, now, now) for channel_id in channels],
                )
            else:
                announcement_id = int(existing[0])
                connection.execute(
                    """
                    UPDATE announcements
                    SET canonical_url = ?, title = ?, category = ?, content_html = ?, content = ?,
                        image_urls_json = ?, published_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        announcement.canonical_url,
                        announcement.title,
                        announcement.category,
                        announcement.content_html,
                        announcement.content_text,
                        json.dumps(announcement.images, ensure_ascii=False),
                        announcement.published_at.isoformat() if announcement.published_at else None,
                        now,
                        announcement_id,
                    ),
                )
                if reset_deliveries:
                    connection.executemany(
                        """
                        INSERT INTO announcement_deliveries (
                            announcement_id, channel_id, status, attempt_count, last_error,
                            message_ids_json, created_at, updated_at, sent_at
                        ) VALUES (?, ?, 'pending', 0, NULL, '[]', ?, ?, NULL)
                        ON CONFLICT(announcement_id, channel_id) DO UPDATE SET
                            status = 'pending', attempt_count = 0, last_error = NULL,
                            message_ids_json = '[]', updated_at = excluded.updated_at, sent_at = NULL
                        """,
                        [(announcement_id, channel_id, now, now) for channel_id in channels],
                    )
            connection.commit()
            return announcement_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def recover_interrupted_deliveries(self) -> int:
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE announcement_deliveries
                SET status = 'failed', last_error = COALESCE(last_error, 'Worker restarted before completion'),
                    updated_at = ?
                WHERE status = 'sending'
                """,
                (utc_now(),),
            )
            connection.commit()
            return int(cursor.rowcount)
        finally:
            connection.close()

    def claim_deliveries(
        self, limit: int, *, sources: Iterable[str] | None = None
    ) -> list[PendingDelivery]:
        if limit < 1:
            return []
        source_values = tuple(dict.fromkeys(str(source) for source in sources or ()))
        connection = self._connect()
        now = utc_now()
        try:
            connection.execute("BEGIN")
            source_clause = ""
            parameters: list[object] = []
            if source_values:
                source_clause = " AND a.source IN (" + ", ".join("?" for _ in source_values) + ")"
                parameters.extend(source_values)
            parameters.append(limit)
            rows = connection.execute(
                """
                SELECT d.id, d.announcement_id, d.channel_id
                FROM announcement_deliveries AS d
                JOIN announcements AS a ON a.id = d.announcement_id
                WHERE d.status IN ('pending', 'failed')
                """
                + source_clause
                +
                """
                ORDER BY d.created_at, d.id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
            delivery_ids = [int(row[0]) for row in rows]
            connection.executemany(
                """
                UPDATE announcement_deliveries
                SET status = 'sending', attempt_count = attempt_count + 1, last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                [(now, delivery_id) for delivery_id in delivery_ids],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return [delivery for delivery_id in delivery_ids if (delivery := self.get_delivery(delivery_id))]

    def get_delivery(self, delivery_id: int) -> PendingDelivery | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT d.id, d.announcement_id, d.channel_id, a.source, a.external_id,
                       a.canonical_url, a.title, a.category, a.content_html, a.content,
                       a.image_urls_json, a.published_at
                FROM announcement_deliveries AS d
                JOIN announcements AS a ON a.id = d.announcement_id
                WHERE d.id = ?
                """,
                (delivery_id,),
            ).fetchone()
            if row is None:
                return None
            published_at = datetime.fromisoformat(row[11]) if row[11] else None
            return PendingDelivery(
                delivery_id=int(row[0]),
                announcement_id=int(row[1]),
                channel_id=int(row[2]),
                announcement=Announcement(
                    source=str(row[3]), external_id=str(row[4]), url=str(row[5]),
                    title=str(row[6]), category=str(row[7]) if row[7] is not None else None,
                    content_html=str(row[8]) if row[8] is not None else None,
                    content_text=str(row[9]), images=tuple(json.loads(str(row[10]))),
                    published_at=published_at,
                ),
            )
        finally:
            connection.close()

    def mark_delivery_sent(self, delivery_id: int, message_ids: Iterable[int | str]) -> None:
        now = utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT announcement_id FROM announcement_deliveries WHERE id = ?", (delivery_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown v2 announcement delivery.")
            announcement_id = int(row[0])
            connection.execute(
                """
                UPDATE announcement_deliveries
                SET status = 'sent', last_error = NULL, message_ids_json = ?, sent_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps([str(value) for value in message_ids]), now, now, delivery_id),
            )
            unsent = connection.execute(
                "SELECT 1 FROM announcement_deliveries WHERE announcement_id = ? AND status != 'sent' LIMIT 1",
                (announcement_id,),
            ).fetchone()
            if unsent is None:
                connection.execute("UPDATE announcements SET sent_at = ?, updated_at = ? WHERE id = ?", (now, now, announcement_id))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_delivery_failed(self, delivery_id: int, error: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE announcement_deliveries SET status = 'failed', last_error = ?, updated_at = ? WHERE id = ?",
                (error[:1000], utc_now(), delivery_id),
            )
            connection.commit()
        finally:
            connection.close()

    def legacy_initialization_plan(self, legacy_database_path: Path) -> LegacyInitializationPlan:
        """Read legacy sent ledgers without modifying the legacy database."""
        connection = sqlite3.connect(f"file:{legacy_database_path.resolve()}?mode=ro", uri=True)
        try:
            urls: set[str] = set()
            try:
                urls.update(
                    str(row[0])
                    for row in connection.execute(
                        "SELECT post_url FROM announcements WHERE post_url IS NOT NULL"
                    ).fetchall()
                    if row[0]
                )
            except sqlite3.OperationalError:
                pass
        finally:
            connection.close()
        candidates = tuple(
            Announcement(
                source=TW_FACEBOOK_SOURCE,
                external_id=_external_id_from_url(url),
                url=canonical_announcement_url(TW_FACEBOOK_SOURCE, url),
                title="",
                category=None,
                published_at=None,
                content_html=None,
                content_text="",
                images=(),
            )
            for url in sorted(urls)
        )
        existing = set(self._existing_identities())
        return LegacyInitializationPlan(
            legacy_sent=tuple(item for item in candidates if (item.source, item.external_id) not in existing),
            already_initialized=tuple(item for item in candidates if (item.source, item.external_id) in existing),
        )

    def initialize_legacy_sent(self, plan: LegacyInitializationPlan, channel_ids: Iterable[int]) -> int:
        """Write a reviewed legacy sent plan into v2 state only."""
        channels = tuple(dict.fromkeys(int(channel_id) for channel_id in channel_ids))
        now = utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            for announcement in plan.legacy_sent:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO announcements (
                        source, external_id, canonical_url, content, image_urls_json, published_at,
                        created_at, updated_at, sent_at
                    ) VALUES (?, ?, ?, '', '[]', NULL, ?, ?, ?)
                    """,
                    (announcement.source, announcement.external_id, announcement.canonical_url, now, now, now),
                )
                row = connection.execute(
                    "SELECT id FROM announcements WHERE source = ? AND external_id = ?",
                    (announcement.source, announcement.external_id),
                ).fetchone()
                if row is not None:
                    connection.executemany(
                        """
                        INSERT OR IGNORE INTO announcement_deliveries (
                            announcement_id, channel_id, status, attempt_count, created_at, updated_at, sent_at
                        ) VALUES (?, ?, 'sent', 0, ?, ?, ?)
                        """,
                        [(int(row[0]), channel_id, now, now, now) for channel_id in channels],
                    )
            connection.commit()
            return len(plan.legacy_sent)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _existing_identities(self) -> list[tuple[str, str]]:
        connection = self._connect()
        try:
            return [(str(source), str(external_id)) for source, external_id in connection.execute("SELECT source, external_id FROM announcements")]
        finally:
            connection.close()


def _external_id_from_url(url: str) -> str:
    path_parts = [part for part in urlsplit(url).path.split("/") if part]
    if "posts" in path_parts:
        index = path_parts.index("posts")
        if index + 1 < len(path_parts):
            return path_parts[index + 1]
    query = parse_qs(urlsplit(url).query)
    for key in ("story_fbid", "fbid", "id"):
        if query.get(key):
            return query[key][0]
    return canonical_announcement_url(TW_FACEBOOK_SOURCE, url)
