"""Raw-only persistence for official announcements retained in state storage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from announcement.history_archive import (
    ArchiveMigrationStats,
    ArchivedRawImage,
    ArchivedRawPost,
    HistoricalRawArchive,
)
from announcement.models import Announcement
from announcement.state_store import DEFAULT_STATE_DATABASE_PATH, utc_now


_MAX_SQLITE_INTEGER = (1 << 63) - 1


def _archive_storage_id(source: str, external_id: str) -> int:
    """Create the integer compatibility key required by the existing raw archive table."""
    try:
        value = int(external_id)
    except ValueError:
        value = 0
    if 0 < value <= _MAX_SQLITE_INTEGER:
        return value
    digest = hashlib.sha256(f"{source}\x1f{external_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & _MAX_SQLITE_INTEGER or 1


def _content_hash(announcement: Announcement) -> str:
    return hashlib.sha256(announcement.content_text.encode("utf-8")).hexdigest()


def announcement_to_archived_raw_post(announcement: Announcement) -> ArchivedRawPost:
    """Map one source-neutral announcement to the existing raw-post archive contract."""
    metadata = {
        **dict(announcement.metadata),
        "title": announcement.title,
        "category": announcement.category,
        "content_html": announcement.content_html,
        "external_id": announcement.external_id,
        "official_source": announcement.source,
    }
    return ArchivedRawPost(
        legacy_raw_post_id=_archive_storage_id(announcement.source, announcement.external_id),
        source=announcement.source,
        source_post_id=announcement.external_id,
        url=announcement.canonical_url,
        content=announcement.content_text,
        published_at=announcement.published_at.isoformat() if announcement.published_at else None,
        scraped_at=None,
        updated_at=None,
        parse_status=None,
        parse_error=None,
        content_hash=_content_hash(announcement),
        metadata_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    )


def announcement_to_archived_raw_images(announcement: Announcement) -> tuple[ArchivedRawImage, ...]:
    """Keep source image order while removing repeated URLs before state persistence."""
    archive_id = _archive_storage_id(announcement.source, announcement.external_id)
    seen: set[str] = set()
    images: list[ArchivedRawImage] = []
    for image_url in announcement.images:
        candidate = image_url.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        images.append(
            ArchivedRawImage(
                legacy_raw_post_id=archive_id,
                image_url=candidate,
                position=len(images),
                created_at="",
            )
        )
    return tuple(images)


@dataclass(frozen=True, slots=True)
class OfficialRawImportResult:
    """Raw import outcome without announcement delivery or semantic parsing side effects."""

    fetched_announcements: int
    fetched_images: int
    storage: ArchiveMigrationStats


class OfficialRawAnnouncementImporter:
    """Write official notices to existing state raw tables transactionally and idempotently."""

    def __init__(self, state_database_path: Path = DEFAULT_STATE_DATABASE_PATH) -> None:
        self.state_database_path = state_database_path

    def plan(self, announcements: list[Announcement]) -> OfficialRawImportResult:
        posts, images = _archive_records(announcements)
        storage = HistoricalRawArchive(self.state_database_path).plan(posts, images)
        return OfficialRawImportResult(len(announcements), len(images), storage)

    def synchronize(self, announcements: list[Announcement]) -> OfficialRawImportResult:
        posts, images = _archive_records(announcements)
        storage = HistoricalRawArchive(self.state_database_path).synchronize(
            posts,
            images,
            migrated_at=utc_now(),
        )
        return OfficialRawImportResult(len(announcements), len(images), storage)


def _archive_records(
    announcements: list[Announcement],
) -> tuple[tuple[ArchivedRawPost, ...], tuple[ArchivedRawImage, ...]]:
    posts = tuple(announcement_to_archived_raw_post(item) for item in announcements)
    images = tuple(
        image
        for item in announcements
        for image in announcement_to_archived_raw_images(item)
    )
    return posts, images
