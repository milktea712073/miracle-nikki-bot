"""Archived raw-announcement storage inside the v2 announcement state database."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def initialize_history_tables(connection: sqlite3.Connection) -> None:
    """Create isolated legacy raw storage without involving delivery tables."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS raw_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            legacy_raw_post_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            source_post_id TEXT,
            identity_key TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            content TEXT NOT NULL,
            published_at TEXT,
            scraped_at TEXT,
            updated_at TEXT,
            parse_status TEXT,
            parse_error TEXT,
            content_hash TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            migrated_at TEXT NOT NULL,
            UNIQUE(source, legacy_raw_post_id)
        );

        CREATE TABLE IF NOT EXISTS raw_post_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_post_id INTEGER NOT NULL,
            image_url TEXT NOT NULL,
            position INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
            UNIQUE(raw_post_id, image_url)
        );

        CREATE INDEX IF NOT EXISTS idx_state_raw_posts_source_published
            ON raw_posts(source, published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_state_raw_images_post_position
            ON raw_post_images(raw_post_id, position, id);
        """
    )


def canonical_raw_url(url: str) -> str:
    """Normalize only transport details; preserve source-specific path/query identity."""
    parsed = urlsplit(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def raw_identity_key(source: str, source_post_id: str | None, url: str, content: str, published_at: str | None) -> str:
    """Return the deterministic source identity used by the migrated archive."""
    normalized_source = source.strip()
    normalized_id = (source_post_id or "").strip()
    if normalized_id:
        return f"source-id:{normalized_source}:{normalized_id}"
    canonical_url = canonical_raw_url(url)
    if canonical_url:
        return f"source-url:{normalized_source}:{canonical_url}"
    digest = hashlib.sha256(
        "\x1f".join((normalized_source, content, published_at or "")).encode("utf-8")
    ).hexdigest()
    return f"fallback:{digest}"


@dataclass(frozen=True, slots=True)
class ArchivedRawPost:
    legacy_raw_post_id: int
    source: str
    source_post_id: str | None
    url: str
    content: str
    published_at: str | None
    scraped_at: str | None
    updated_at: str | None
    parse_status: str | None
    parse_error: str | None
    content_hash: str | None
    metadata_json: str | None


@dataclass(frozen=True, slots=True)
class ArchivedRawImage:
    legacy_raw_post_id: int
    image_url: str
    position: int
    created_at: str


@dataclass(frozen=True, slots=True)
class ArchiveMigrationStats:
    source_raw_posts: int
    inserted_raw_posts: int
    existing_raw_posts: int
    source_images: int
    inserted_images: int
    duplicate_images: int


class HistoricalRawArchive:
    """Transactional writer for legacy raw posts retained for announcement search."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def plan(self, posts: tuple[ArchivedRawPost, ...], images: tuple[ArchivedRawImage, ...]) -> ArchiveMigrationStats:
        if not self.database_path.exists():
            unique_images = {
                (image.legacy_raw_post_id, image.image_url.strip())
                for image in images
                if image.image_url.strip()
            }
            return ArchiveMigrationStats(
                source_raw_posts=len(posts), inserted_raw_posts=len(posts), existing_raw_posts=0,
                source_images=len(images), inserted_images=len(unique_images),
                duplicate_images=len(images) - len(unique_images),
            )
        connection = self._connect()
        try:
            table_names = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            existing_keys = (
                {str(row[0]) for row in connection.execute("SELECT identity_key FROM raw_posts")}
                if "raw_posts" in table_names else set()
            )
            archive_post_ids = (
                {int(row[0]): int(row[1]) for row in connection.execute("SELECT legacy_raw_post_id, id FROM raw_posts")}
                if "raw_posts" in table_names else {}
            )
            existing_images = (
                {(int(row[0]), str(row[1])) for row in connection.execute("SELECT raw_post_id, image_url FROM raw_post_images")}
                if "raw_post_images" in table_names else set()
            )
            inserted_posts = 0
            existing_posts = 0
            prospective_ids = dict(archive_post_ids)
            for post in posts:
                key = raw_identity_key(post.source, post.source_post_id, post.url, post.content, post.published_at)
                if key in existing_keys:
                    existing_posts += 1
                else:
                    inserted_posts += 1
            inserted_images = 0
            duplicate_images = 0
            seen_images: set[tuple[int, str]] = set()
            for image in images:
                image_url = image.image_url.strip()
                if not image_url:
                    continue
                target_id = prospective_ids.get(image.legacy_raw_post_id)
                marker = (target_id or -image.legacy_raw_post_id, image_url)
                if marker in existing_images or marker in seen_images:
                    duplicate_images += 1
                else:
                    inserted_images += 1
                    seen_images.add(marker)
            return ArchiveMigrationStats(
                source_raw_posts=len(posts), inserted_raw_posts=inserted_posts,
                existing_raw_posts=existing_posts, source_images=len(images),
                inserted_images=inserted_images, duplicate_images=duplicate_images,
            )
        finally:
            connection.close()

    def synchronize(self, posts: tuple[ArchivedRawPost, ...], images: tuple[ArchivedRawImage, ...], *, migrated_at: str) -> ArchiveMigrationStats:
        """Upsert all archive rows and images atomically, preserving source order."""
        connection = self._connect()
        inserted_posts = 0
        existing_posts = 0
        inserted_images = 0
        duplicate_images = 0
        try:
            initialize_history_tables(connection)
            connection.execute("BEGIN")
            archive_ids: dict[int, int] = {}
            for post in posts:
                key = raw_identity_key(post.source, post.source_post_id, post.url, post.content, post.published_at)
                existing = connection.execute(
                    "SELECT id FROM raw_posts WHERE identity_key = ?", (key,)
                ).fetchone()
                if existing is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO raw_posts (
                            legacy_raw_post_id, source, source_post_id, identity_key, url, canonical_url,
                            content, published_at, scraped_at, updated_at, parse_status, parse_error,
                            content_hash, metadata_json, created_at, migrated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            post.legacy_raw_post_id, post.source, post.source_post_id, key, post.url,
                            canonical_raw_url(post.url), post.content, post.published_at, post.scraped_at,
                            post.updated_at, post.parse_status, post.parse_error, post.content_hash,
                            post.metadata_json, migrated_at, migrated_at,
                        ),
                    )
                    archive_id = int(cursor.lastrowid)
                    inserted_posts += 1
                else:
                    archive_id = int(existing[0])
                    connection.execute(
                        """
                        UPDATE raw_posts
                        SET legacy_raw_post_id = ?, source = ?, source_post_id = ?, url = ?, canonical_url = ?,
                            content = ?, published_at = ?, scraped_at = ?, updated_at = ?, parse_status = ?,
                            parse_error = ?, content_hash = ?, metadata_json = ?, migrated_at = ?
                        WHERE id = ?
                        """,
                        (
                            post.legacy_raw_post_id, post.source, post.source_post_id, post.url,
                            canonical_raw_url(post.url), post.content, post.published_at, post.scraped_at,
                            post.updated_at, post.parse_status, post.parse_error, post.content_hash,
                            post.metadata_json, migrated_at, archive_id,
                        ),
                    )
                    existing_posts += 1
                archive_ids[post.legacy_raw_post_id] = archive_id

            seen_images: set[tuple[int, str]] = set()
            for image in images:
                image_url = image.image_url.strip()
                archive_id = archive_ids.get(image.legacy_raw_post_id)
                if archive_id is None or not image_url:
                    continue
                marker = (archive_id, image_url)
                if marker in seen_images:
                    duplicate_images += 1
                    continue
                seen_images.add(marker)
                exists = connection.execute(
                    "SELECT 1 FROM raw_post_images WHERE raw_post_id = ? AND image_url = ?",
                    marker,
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(raw_post_id, image_url) DO UPDATE SET position = excluded.position
                    """,
                    (archive_id, image_url, image.position, image.created_at),
                )
                if exists is None:
                    inserted_images += 1
                else:
                    duplicate_images += 1
            connection.commit()
            return ArchiveMigrationStats(
                source_raw_posts=len(posts), inserted_raw_posts=inserted_posts,
                existing_raw_posts=existing_posts, source_images=len(images),
                inserted_images=inserted_images, duplicate_images=duplicate_images,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
