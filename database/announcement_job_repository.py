"""Durable announcement queue storage and delivery state transitions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from database.database import (
    get_connection,
    initialize_announcement_queue_tables,
    initialize_raw_tables,
)


BASELINE_CONTENT_PREFIX = "[baseline skipped; not sent to Discord] "


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class AnnouncementJob:
    id: int
    raw_post_id: int
    status: str
    attempt_count: int
    last_error: str | None
    created_at: str
    updated_at: str
    sent_at: str | None
    post_url: str
    content: str
    published_at: str | None
    images: list[str]


@dataclass(frozen=True, slots=True)
class RequeueResult:
    raw_post_id: int
    job_id: int
    old_status: str | None
    post_url: str


class AnnouncementJobRepository:
    """Keep announcement queue state independent from crawler polling order."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = get_connection(self._database_path)
        initialize_raw_tables(connection)
        initialize_announcement_queue_tables(connection)
        return connection

    @staticmethod
    def is_initialized_in_connection(connection: sqlite3.Connection) -> bool:
        return connection.execute(
            "SELECT 1 FROM announcement_queue_settings WHERE id = 1"
        ).fetchone() is not None

    @staticmethod
    def create_pending_for_new_raw_post(
        connection: sqlite3.Connection, raw_post_id: int, now: str
    ) -> None:
        """Enqueue only newly inserted raw posts after queue initialization."""
        if not AnnouncementJobRepository.is_initialized_in_connection(connection):
            return
        connection.execute(
            "INSERT OR IGNORE INTO announcement_jobs "
            "(raw_post_id, status, attempt_count, created_at, updated_at) "
            "VALUES (?, 'pending', 0, ?, ?)",
            (raw_post_id, now, now),
        )

    def is_initialized(self) -> bool:
        connection = self._connect()
        try:
            return self.is_initialized_in_connection(connection)
        finally:
            connection.close()

    def initialize_from_existing_raw_posts(self, pending_urls: tuple[str, ...] = ()) -> int:
        """Create skipped jobs for all existing raw posts and activate future enqueueing."""
        connection = self._connect()
        now = utc_now()
        try:
            connection.execute("BEGIN")
            if self.is_initialized_in_connection(connection):
                raise ValueError("Announcement queue is already initialized.")
            rows = connection.execute("SELECT id, url FROM raw_posts ORDER BY id").fetchall()
            pending_url_set = set(pending_urls)
            connection.executemany(
                "INSERT OR IGNORE INTO announcement_jobs "
                "(raw_post_id, status, attempt_count, created_at, updated_at) "
                "VALUES (?, ?, 0, ?, ?)",
                [
                    (
                        int(row[0]),
                        "pending" if str(row[1]) in pending_url_set else "skipped",
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
            connection.execute(
                "INSERT INTO announcement_queue_settings (id, initialized_at) VALUES (1, ?)",
                (now,),
            )
            connection.commit()
            return len(rows)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def recover_interrupted_jobs(self) -> int:
        """Make jobs claimed by a stopped worker retryable on the next poll."""
        connection = self._connect()
        try:
            cursor = connection.execute(
                "UPDATE announcement_jobs SET status = 'failed', "
                "last_error = COALESCE(last_error, 'Worker restarted before completion'), "
                "updated_at = ? WHERE status = 'sending'",
                (utc_now(),),
            )
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()

    def claim_jobs(self, limit: int) -> list[AnnouncementJob]:
        """Atomically claim up to ``limit`` pending or failed jobs in creation order."""
        if limit < 1:
            return []
        connection = self._connect()
        now = utc_now()
        try:
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT id FROM announcement_jobs WHERE status IN ('pending', 'failed') "
                "ORDER BY created_at ASC, id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            job_ids = [int(row[0]) for row in rows]
            for job_id in job_ids:
                connection.execute(
                    "UPDATE announcement_jobs SET status = 'sending', attempt_count = attempt_count + 1, "
                    "last_error = NULL, updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return [job for job_id in job_ids if (job := self.get_job(job_id)) is not None]

    def get_job(self, job_id: int) -> AnnouncementJob | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT j.id, j.raw_post_id, j.status, j.attempt_count, j.last_error, "
                "j.created_at, j.updated_at, j.sent_at, r.url, r.content, r.published_at "
                "FROM announcement_jobs j JOIN raw_posts r ON r.id = j.raw_post_id WHERE j.id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            images = connection.execute(
                "SELECT image_url FROM raw_post_images WHERE raw_post_id = ? ORDER BY position ASC",
                (int(row[1]),),
            ).fetchall()
            return AnnouncementJob(
                id=int(row[0]), raw_post_id=int(row[1]), status=str(row[2]),
                attempt_count=int(row[3]), last_error=row[4], created_at=str(row[5]),
                updated_at=str(row[6]), sent_at=row[7], post_url=str(row[8]),
                content=str(row[9]), published_at=row[10], images=[str(image[0]) for image in images],
            )
        finally:
            connection.close()

    def mark_failed(self, job_id: int, error: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE announcement_jobs SET status = 'failed', last_error = ?, updated_at = ? "
                "WHERE id = ?",
                (error[:1000], utc_now(), job_id),
            )
            connection.commit()
        finally:
            connection.close()

    def mark_sent(self, job_id: int) -> None:
        """Write the successful delivery ledger and job completion in one transaction."""
        connection = self._connect()
        now = utc_now()
        try:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT r.url, r.content, r.published_at FROM announcement_jobs j "
                "JOIN raw_posts r ON r.id = j.raw_post_id WHERE j.id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Announcement job {job_id} does not exist.")
            announcement = connection.execute(
                "SELECT id FROM announcements WHERE post_url = ?", (str(row[0]),)
            ).fetchone()
            if announcement is None:
                cursor = connection.execute(
                    "INSERT INTO announcements (publish_time, content, post_url) VALUES (?, ?, ?)",
                    (str(row[2] or ""), str(row[1]), str(row[0])),
                )
                announcement_id = int(cursor.lastrowid)
                images = connection.execute(
                    "SELECT image_url FROM raw_post_images WHERE raw_post_id = "
                    "(SELECT raw_post_id FROM announcement_jobs WHERE id = ?) ORDER BY position ASC",
                    (job_id,),
                ).fetchall()
                connection.executemany(
                    "INSERT INTO images (announcement_id, image_url) VALUES (?, ?)",
                    [(announcement_id, str(image[0])) for image in images],
                )
            connection.execute(
                "UPDATE announcement_jobs SET status = 'sent', last_error = NULL, "
                "sent_at = ?, updated_at = ? WHERE id = ?",
                (now, now, job_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def requeue_announcement_job(self, post_url: str) -> RequeueResult | None:
        """Create or reset exactly one job for an explicit manual resend."""
        connection = self._connect()
        now = utc_now()
        try:
            connection.execute("BEGIN")
            raw_post = connection.execute(
                "SELECT id, url FROM raw_posts WHERE url = ?", (post_url,)
            ).fetchone()
            if raw_post is None:
                connection.rollback()
                return None
            raw_post_id = int(raw_post[0])
            existing = connection.execute(
                "SELECT id, status FROM announcement_jobs WHERE raw_post_id = ?",
                (raw_post_id,),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO announcement_jobs "
                    "(raw_post_id, status, attempt_count, last_error, created_at, updated_at, sent_at) "
                    "VALUES (?, 'pending', 0, NULL, ?, ?, NULL)",
                    (raw_post_id, now, now),
                )
                job_id = int(cursor.lastrowid)
                old_status = None
            else:
                job_id = int(existing[0])
                old_status = str(existing[1])
                connection.execute(
                    "UPDATE announcement_jobs SET status = 'pending', attempt_count = 0, "
                    "last_error = NULL, sent_at = NULL, updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
            connection.commit()
            return RequeueResult(raw_post_id, job_id, old_status, str(raw_post[1]))
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def find_latest_sent_announcement_url(self) -> str | None:
        """Return the latest real delivery, excluding legacy baseline/skipped rows."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT a.post_url FROM announcements a "
                "JOIN raw_posts r ON r.url = a.post_url "
                "LEFT JOIN announcement_jobs j ON j.raw_post_id = r.id "
                "WHERE a.content NOT LIKE ? AND COALESCE(j.status, 'sent') != 'skipped' "
                "ORDER BY CASE WHEN j.sent_at IS NULL THEN 1 ELSE 0 END, "
                "j.sent_at DESC, a.id DESC LIMIT 1",
                (f"{BASELINE_CONTENT_PREFIX}%",),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            connection.close()

    def migrate_legacy_announcements(self) -> tuple[int, int]:
        """Move legacy baseline rows out of announcements and create durable jobs."""
        connection = self._connect()
        now = utc_now()
        migrated_sent = migrated_skipped = 0
        try:
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT id, post_url, content FROM announcements ORDER BY id"
            ).fetchall()
            for announcement_id, post_url, content in rows:
                raw = connection.execute(
                    "SELECT id FROM raw_posts WHERE url = ?", (str(post_url),)
                ).fetchone()
                if raw is None:
                    continue
                raw_post_id = int(raw[0])
                if str(content).startswith(BASELINE_CONTENT_PREFIX):
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO announcement_jobs "
                        "(raw_post_id, status, attempt_count, created_at, updated_at) "
                        "VALUES (?, 'skipped', 0, ?, ?)",
                        (raw_post_id, now, now),
                    )
                    connection.execute("DELETE FROM images WHERE announcement_id = ?", (announcement_id,))
                    connection.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
                    migrated_skipped += max(cursor.rowcount, 0)
                else:
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO announcement_jobs "
                        "(raw_post_id, status, attempt_count, created_at, updated_at, sent_at) "
                        "VALUES (?, 'sent', 1, ?, ?, ?)",
                        (raw_post_id, now, now, now),
                    )
                    migrated_sent += max(cursor.rowcount, 0)
            connection.commit()
            return migrated_sent, migrated_skipped
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
