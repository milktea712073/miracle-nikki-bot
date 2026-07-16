"""SQLite persistence for source-agnostic raw posts."""

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

from crawler.models import Post
from database.announcement_identity import canonical_announcement_url
from database.announcement_job_repository import AnnouncementJobRepository
from database.database import ensure_database_initialized, get_connection


LOGGER = logging.getLogger(__name__)
SOURCE_FACEBOOK = "facebook"
SOURCE_WEBSITE = "website"
SaveAction = Literal["inserted", "updated", "unchanged"]


@dataclass(frozen=True, slots=True)
class RawPostSaveResult:
    """Result of saving one raw post."""

    source_post_id: str
    action: SaveAction
    raw_post_id: int


@dataclass(frozen=True, slots=True)
class RawPostFailure:
    """A post that could not be persisted during a batch."""

    source_post_id: str
    error: str


@dataclass(slots=True)
class RawPostBatchResult:
    """Aggregate result for a raw-post batch."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    failures: list[RawPostFailure] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return len(self.failures)


def ensure_aware(value: datetime) -> datetime:
    """Return an aware datetime or reject an ambiguous timestamp."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Post.published_at must include timezone information.")
    return value


def to_iso8601(value: datetime | None) -> str | None:
    """Serialize an optional aware Facebook publication time."""
    if value is None:
        return None
    return ensure_aware(value).isoformat()


def utc_now_iso8601() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def unique_images(images: list[str]) -> list[str]:
    """Keep first occurrences of image URLs in their original order."""
    unique: list[str] = []
    seen: set[str] = set()
    for image_url in images:
        if image_url not in seen:
            seen.add(image_url)
            unique.append(image_url)
    return unique


def image_hash_value(image_url: str) -> str:
    """Remove volatile Facebook CDN query parameters for change detection."""
    parsed = urlsplit(image_url)
    if "fbcdn.net" in parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return image_url


def stable_image_filenames(images: list[str]) -> frozenset[str]:
    """Return stable media file names for conservative Facebook alias matching."""
    return frozenset(
        filename.lower()
        for image_url in images
        if (filename := unquote(urlsplit(image_url).path.rsplit("/", 1)[-1]))
    )


def compute_content_hash(post: Post) -> str:
    """Hash the raw fields that should trigger a parser re-run when changed."""
    payload = {
        "content": post.content,
        "images": [image_hash_value(image_url) for image_url in unique_images(post.images)],
        "published_at": to_iso8601(post.published_at),
        "url": canonical_announcement_url(post.url),
        "metadata": post.metadata or {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RawPostRepository:
    """Repository for raw_posts and raw_post_images."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path
        ensure_database_initialized(database_path)

    def _connect(self) -> sqlite3.Connection:
        return get_connection(self._database_path)

    def raw_post_exists(self, source_post_id: str, *, source: str = SOURCE_FACEBOOK) -> bool:
        """Return whether one source-specific post was already persisted."""
        return self.get_raw_post_by_source_id(source_post_id, source=source) is not None

    def get_raw_post_by_source_id(
        self, source_post_id: str, *, source: str = SOURCE_FACEBOOK
    ) -> dict[str, object] | None:
        """Return a raw post and ordered images, or None when it is absent."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM raw_posts WHERE source = ? AND source_post_id = ?",
                (source, source_post_id),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT r.* FROM raw_post_aliases a "
                    "JOIN raw_posts r ON r.id = a.raw_post_id "
                    "WHERE a.source = ? AND a.source_post_id = ?",
                    (source, source_post_id),
                ).fetchone()
            if row is None:
                return None
            return self._raw_row_to_dict(connection, row)
        finally:
            connection.close()

    @staticmethod
    def _raw_row_to_dict(connection: sqlite3.Connection, row: tuple[object, ...]) -> dict[str, object]:
        images = connection.execute(
            "SELECT image_url FROM raw_post_images WHERE raw_post_id = ? ORDER BY position ASC",
            (row[0],),
        ).fetchall()
        columns = [column[0] for column in connection.execute(
            "SELECT * FROM raw_posts LIMIT 0"
        ).description]
        result = dict(zip(columns, row, strict=True))
        result["images"] = [image[0] for image in images]
        metadata_json = result.get("metadata_json")
        result["metadata"] = json.loads(metadata_json) if metadata_json else None
        return result

    @staticmethod
    def _is_verified_facebook_post(post: Post) -> bool:
        return post.source.strip().lower() == SOURCE_FACEBOOK and bool(
            (post.metadata or {}).get("official_post_verified")
        )

    @staticmethod
    def _metadata_is_verified(metadata_json: object) -> bool:
        if not isinstance(metadata_json, str) or not metadata_json:
            return False
        try:
            metadata = json.loads(metadata_json)
        except json.JSONDecodeError:
            return False
        return isinstance(metadata, dict) and bool(metadata.get("official_post_verified"))

    def _images_for_raw_post(self, connection: sqlite3.Connection, raw_post_id: int) -> list[str]:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT image_url FROM raw_post_images WHERE raw_post_id = ? ORDER BY position ASC",
                (raw_post_id,),
            ).fetchall()
        ]

    def _is_conservative_facebook_duplicate(
        self,
        connection: sqlite3.Connection,
        existing: tuple[object, ...],
        post: Post,
        published_at: str | None,
        images: list[str],
    ) -> bool:
        """Require all independent trusted signals before automatic pfbid merging."""
        if not self._is_verified_facebook_post(post):
            return False
        existing_id = int(existing[0])
        existing_content = str(existing[4])
        existing_published_at = existing[5]
        existing_metadata = existing[6]
        return (
            self._metadata_is_verified(existing_metadata)
            and existing_content == post.content
            and stable_image_filenames(self._images_for_raw_post(connection, existing_id))
            == stable_image_filenames(images)
            and existing_published_at == published_at
        )

    @staticmethod
    def _record_alias(
        connection: sqlite3.Connection,
        raw_post_id: int,
        source: str,
        source_post_id: str,
        post_url: str,
        now: str,
    ) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO raw_post_aliases "
            "(raw_post_id, source, source_post_id, url, created_at) VALUES (?, ?, ?, ?, ?)",
            (raw_post_id, source, source_post_id, post_url, now),
        )

    def _find_conservative_facebook_duplicate(
        self,
        connection: sqlite3.Connection,
        post: Post,
        published_at: str | None,
        images: list[str],
    ) -> tuple[object, ...] | None:
        """Find a trusted legacy row with every alias signal intact."""
        if not self._is_verified_facebook_post(post):
            return None
        rows = connection.execute(
            "SELECT id, source, source_post_id, url, content, published_at, metadata_json "
            "FROM raw_posts WHERE source = ? AND content = ?",
            (SOURCE_FACEBOOK, post.content),
        ).fetchall()
        for row in rows:
            if self._is_conservative_facebook_duplicate(connection, row, post, published_at, images):
                return row
        if rows:
            LOGGER.info(
                "Possible Facebook duplicate was not merged post_id=%s reason=insufficient_identity_evidence",
                post.post_id,
            )
        return None

    def _insert_images(
        self, connection: sqlite3.Connection, raw_post_id: int, images: list[str], now: str
    ) -> None:
        connection.executemany(
            "INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                (raw_post_id, image_url, position, now)
                for position, image_url in enumerate(images)
            ],
        )

    def save_raw_post(
        self, post: Post, *, enqueue_announcement: bool = True
    ) -> RawPostSaveResult:
        """Insert or update a raw post in one transaction."""
        source = post.source.strip().lower()
        if not source:
            raise ValueError("Post.source must not be empty.")
        published_at = to_iso8601(post.published_at)
        images = unique_images(post.images)
        content_hash = compute_content_hash(post)
        post_url = canonical_announcement_url(post.url)
        metadata_json = json.dumps(post.metadata, ensure_ascii=False, sort_keys=True) if post.metadata else None
        now = utc_now_iso8601()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            direct_existing = connection.execute(
                "SELECT id, source, source_post_id, url, content, published_at, metadata_json, content_hash FROM raw_posts "
                "WHERE source = ? AND source_post_id = ?",
                (source, post.post_id),
            ).fetchone()
            alias_existing = None
            if direct_existing is None:
                alias_existing = connection.execute(
                    "SELECT r.id, r.source, r.source_post_id, r.url, r.content, r.published_at, "
                    "r.metadata_json, r.content_hash FROM raw_post_aliases a "
                    "JOIN raw_posts r ON r.id = a.raw_post_id "
                    "WHERE a.source = ? AND a.source_post_id = ?",
                    (source, post.post_id),
                ).fetchone()
            existing = direct_existing or alias_existing

            if direct_existing is not None and direct_existing[7] == content_hash:
                connection.commit()
                return RawPostSaveResult(post.post_id, "unchanged", int(existing[0]))

            if alias_existing is not None and self._is_conservative_facebook_duplicate(
                connection, alias_existing[:7], post, published_at, images
            ):
                connection.execute(
                    "UPDATE raw_posts SET updated_at = ?, metadata_json = ? WHERE id = ?",
                    (now, metadata_json, int(alias_existing[0])),
                )
                connection.commit()
                return RawPostSaveResult(post.post_id, "unchanged", int(alias_existing[0]))

            if existing is None:
                duplicate = self._find_conservative_facebook_duplicate(
                    connection, post, published_at, images
                )
                if duplicate is not None:
                    raw_post_id = int(duplicate[0])
                    self._record_alias(
                        connection, raw_post_id, source, post.post_id, post_url, now
                    )
                    connection.execute(
                        "UPDATE raw_posts SET updated_at = ?, metadata_json = ? WHERE id = ?",
                        (now, metadata_json, raw_post_id),
                    )
                    connection.commit()
                    return RawPostSaveResult(post.post_id, "unchanged", raw_post_id)
                cursor = connection.execute(
                    "INSERT INTO raw_posts (source, source_post_id, url, content, published_at, "
                    "scraped_at, updated_at, parse_status, parse_error, content_hash, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?)",
                    (
                        source,
                        post.post_id,
                        post_url,
                        post.content,
                        published_at,
                        now,
                        now,
                        content_hash,
                        metadata_json,
                    ),
                )
                raw_post_id = int(cursor.lastrowid)
                action: SaveAction = "inserted"
                if source == SOURCE_FACEBOOK:
                    AnnouncementJobRepository.create_pending_for_new_raw_post(
                        connection,
                        raw_post_id,
                        post_url,
                        now,
                        enqueue=enqueue_announcement,
                    )
            else:
                raw_post_id = int(existing[0])
                # An alias already proves this pfbid maps to the same source post.
                # Preserve the first canonical raw URL rather than oscillating between aliases.
                stored_url = str(existing[3]) if alias_existing is not None else post_url
                update_post = post if alias_existing is None else Post(
                    post_id=post.post_id,
                    url=stored_url,
                    content=post.content,
                    published_at=post.published_at,
                    images=post.images,
                    source=post.source,
                    metadata=post.metadata,
                )
                connection.execute(
                    "UPDATE raw_posts SET url = ?, content = ?, published_at = ?, "
                    "updated_at = ?, parse_status = 'pending', parse_error = NULL, "
                    "content_hash = ?, metadata_json = ? WHERE id = ?",
                    (
                        stored_url,
                        post.content,
                        published_at,
                        now,
                        compute_content_hash(update_post),
                        metadata_json,
                        raw_post_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM raw_post_images WHERE raw_post_id = ?", (raw_post_id,)
                )
                action = "updated"

            self._insert_images(connection, raw_post_id, images, now)
            connection.commit()
            return RawPostSaveResult(post.post_id, action, raw_post_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_raw_posts(
        self, posts: list[Post], *, enqueue_announcements: bool = True
    ) -> RawPostBatchResult:
        """Persist posts independently so one failing post does not stop the batch."""
        result = RawPostBatchResult()
        for post in posts:
            try:
                saved = self.save_raw_post(
                    post, enqueue_announcement=enqueue_announcements
                )
            except Exception as error:
                if isinstance(error, sqlite3.OperationalError) and "locked" in str(error).lower():
                    LOGGER.warning("Database is locked while saving raw %s post %s", post.source, post.post_id)
                else:
                    LOGGER.exception("Failed to save raw %s post %s", post.source, post.post_id)
                result.failures.append(RawPostFailure(post.post_id, str(error)))
                continue

            if saved.action == "inserted":
                result.inserted += 1
            elif saved.action == "updated":
                result.updated += 1
            else:
                result.unchanged += 1
        return result


def save_raw_post(post: Post) -> RawPostSaveResult:
    """Save one post to the configured project database."""
    return RawPostRepository().save_raw_post(post)


def save_raw_posts(posts: list[Post]) -> RawPostBatchResult:
    """Save posts to the configured project database."""
    return RawPostRepository().save_raw_posts(posts)


def get_raw_post_by_source_id(
    source_post_id: str, *, source: str = SOURCE_FACEBOOK
) -> dict[str, object] | None:
    """Fetch one source-specific raw post from the configured project database."""
    return RawPostRepository().get_raw_post_by_source_id(source_post_id, source=source)


def raw_post_exists(source_post_id: str, *, source: str = SOURCE_FACEBOOK) -> bool:
    """Check for a source-specific raw post in the configured project database."""
    return RawPostRepository().raw_post_exists(source_post_id, source=source)
