"""Small, standalone SQLite state store for v2 announcement delivery."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlsplit

from announcement.models import Announcement, TW_FACEBOOK_SOURCE, canonical_announcement_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DATABASE_PATH = PROJECT_ROOT / "database" / "announcement_state.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or DEFAULT_STATE_DATABASE_PATH
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
                """
            )
            connection.commit()
        finally:
            connection.close()

    def register(self, announcement: Announcement, channel_ids: Iterable[int]) -> int:
        """Store one announcement and snapshot delivery targets only on first discovery."""
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
                        source, external_id, canonical_url, content, image_urls_json, published_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        announcement.source,
                        announcement.external_id,
                        announcement.canonical_url,
                        announcement.content,
                        json.dumps(announcement.image_urls, ensure_ascii=False),
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
                    SET canonical_url = ?, content = ?, image_urls_json = ?, published_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        announcement.canonical_url,
                        announcement.content,
                        json.dumps(announcement.image_urls, ensure_ascii=False),
                        announcement.published_at.isoformat() if announcement.published_at else None,
                        now,
                        announcement_id,
                    ),
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

    def claim_deliveries(self, limit: int) -> list[PendingDelivery]:
        if limit < 1:
            return []
        connection = self._connect()
        now = utc_now()
        try:
            connection.execute("BEGIN")
            rows = connection.execute(
                """
                SELECT d.id, d.announcement_id, d.channel_id
                FROM announcement_deliveries AS d
                WHERE d.status IN ('pending', 'failed')
                ORDER BY d.created_at, d.id
                LIMIT ?
                """,
                (limit,),
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
                       a.canonical_url, a.content, a.image_urls_json, a.published_at
                FROM announcement_deliveries AS d
                JOIN announcements AS a ON a.id = d.announcement_id
                WHERE d.id = ?
                """,
                (delivery_id,),
            ).fetchone()
            if row is None:
                return None
            published_at = datetime.fromisoformat(row[8]) if row[8] else None
            return PendingDelivery(
                delivery_id=int(row[0]),
                announcement_id=int(row[1]),
                channel_id=int(row[2]),
                announcement=Announcement(
                    source=str(row[3]), external_id=str(row[4]), canonical_url=str(row[5]),
                    content=str(row[6]), image_urls=tuple(json.loads(str(row[7]))), published_at=published_at,
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
                canonical_url=canonical_announcement_url(TW_FACEBOOK_SOURCE, url),
                content="",
                image_urls=(),
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
