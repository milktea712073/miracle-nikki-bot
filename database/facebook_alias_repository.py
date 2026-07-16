"""Human-confirmed repair support for duplicate Facebook pfbid raw posts."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from database.database import ensure_database_initialized, get_connection
from database.raw_post_repository import SOURCE_FACEBOOK, stable_image_filenames, utc_now_iso8601


@dataclass(frozen=True, slots=True)
class FacebookDuplicateGroup:
    """One conservative content/media/time duplicate group for operator review."""

    raw_post_ids: tuple[int, ...]
    urls: tuple[str, ...]
    source_post_ids: tuple[str, ...]
    published_at: str | None
    image_filenames: tuple[str, ...]
    content_preview: str


@dataclass(frozen=True, slots=True)
class FacebookAliasRepairResult:
    """Counts from merging one reviewed duplicate group."""

    survivor_raw_post_id: int
    merged_raw_post_ids: tuple[int, ...]
    aliases_created: int


def _images(connection: sqlite3.Connection, raw_post_id: int) -> list[tuple[int, str, int]]:
    return [
        (int(row[0]), str(row[1]), int(row[2]))
        for row in connection.execute(
            "SELECT id, image_url, position FROM raw_post_images WHERE raw_post_id = ? ORDER BY position, id",
            (raw_post_id,),
        ).fetchall()
    ]


def find_facebook_duplicate_groups(connection: sqlite3.Connection) -> list[FacebookDuplicateGroup]:
    """Find review candidates using exact content, media filenames, and publish time."""
    rows = connection.execute(
        "SELECT id, source_post_id, url, content, published_at FROM raw_posts "
        "WHERE source = ? ORDER BY id",
        (SOURCE_FACEBOOK,),
    ).fetchall()
    buckets: dict[tuple[str, str | None, tuple[str, ...]], list[tuple[int, str, str]]] = {}
    for raw_post_id, source_post_id, url, content, published_at in rows:
        filenames = tuple(sorted(stable_image_filenames([url for _, url, _ in _images(connection, int(raw_post_id))])))
        key = (str(content), published_at, filenames)
        buckets.setdefault(key, []).append((int(raw_post_id), str(source_post_id), str(url)))

    groups: list[FacebookDuplicateGroup] = []
    for (content, published_at, filenames), members in buckets.items():
        if len(members) < 2:
            continue
        groups.append(
            FacebookDuplicateGroup(
                raw_post_ids=tuple(member[0] for member in members),
                source_post_ids=tuple(member[1] for member in members),
                urls=tuple(member[2] for member in members),
                published_at=published_at,
                image_filenames=filenames,
                content_preview=content[:300],
            )
        )
    return groups


def _move_image_references(
    connection: sqlite3.Connection, survivor_raw_post_id: int, duplicate_raw_post_id: int
) -> None:
    survivor_images = {url: image_id for image_id, url, _ in _images(connection, survivor_raw_post_id)}
    next_position = max((position for _, _, position in _images(connection, survivor_raw_post_id)), default=-1) + 1
    for image_id, image_url, _ in _images(connection, duplicate_raw_post_id):
        survivor_image_id = survivor_images.get(image_url)
        if survivor_image_id is not None:
            connection.execute(
                "DELETE FROM suit_images WHERE raw_post_image_id = ? "
                "AND suit_id IN (SELECT suit_id FROM suit_images WHERE raw_post_image_id = ?)",
                (image_id, survivor_image_id),
            )
            connection.execute(
                "UPDATE suit_images SET raw_post_image_id = ? WHERE raw_post_image_id = ?",
                (survivor_image_id, image_id),
            )
            connection.execute("DELETE FROM raw_post_images WHERE id = ?", (image_id,))
            continue
        connection.execute(
            "UPDATE raw_post_images SET raw_post_id = ?, position = ? WHERE id = ?",
            (survivor_raw_post_id, next_position, image_id),
        )
        survivor_images[image_url] = image_id
        next_position += 1


def _move_parse_drafts(
    connection: sqlite3.Connection, survivor_raw_post_id: int, duplicate_raw_post_id: int
) -> None:
    status_priority = {"approved": 5, "reviewed": 4, "auto": 3, "pending": 2, "failed": 1}
    for duplicate_draft_id, parser_version, duplicate_status in connection.execute(
        "SELECT id, parser_version, status FROM parse_drafts WHERE raw_post_id = ?",
        (duplicate_raw_post_id,),
    ).fetchall():
        existing = connection.execute(
            "SELECT id, status FROM parse_drafts WHERE raw_post_id = ? AND parser_version = ?",
            (survivor_raw_post_id, parser_version),
        ).fetchone()
        if existing is None:
            connection.execute(
                "UPDATE parse_drafts SET raw_post_id = ? WHERE id = ?",
                (survivor_raw_post_id, duplicate_draft_id),
            )
        elif status_priority.get(str(duplicate_status), 0) > status_priority.get(str(existing[1]), 0):
            connection.execute("DELETE FROM parse_drafts WHERE id = ?", (int(existing[0]),))
            connection.execute(
                "UPDATE parse_drafts SET raw_post_id = ? WHERE id = ?",
                (survivor_raw_post_id, duplicate_draft_id),
            )
        else:
            connection.execute("DELETE FROM parse_drafts WHERE id = ?", (duplicate_draft_id,))


class FacebookAliasRepository:
    """Repair duplicate Facebook raw posts after an explicit human confirmation."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._database_path = database_path
        ensure_database_initialized(database_path)

    def list_duplicate_groups(self) -> list[FacebookDuplicateGroup]:
        connection = get_connection(self._database_path)
        try:
            return find_facebook_duplicate_groups(connection)
        finally:
            connection.close()

    def merge_group(self, group: FacebookDuplicateGroup) -> FacebookAliasRepairResult:
        """Merge exactly one reviewed group while preserving queue delivery states."""
        survivor_raw_post_id = min(group.raw_post_ids)
        duplicate_raw_post_ids = tuple(
            raw_post_id for raw_post_id in group.raw_post_ids if raw_post_id != survivor_raw_post_id
        )
        connection = get_connection(self._database_path)
        aliases_created = 0
        try:
            connection.execute("BEGIN")
            for duplicate_raw_post_id in duplicate_raw_post_ids:
                duplicate = connection.execute(
                    "SELECT source, source_post_id, url FROM raw_posts WHERE id = ? AND source = ?",
                    (duplicate_raw_post_id, SOURCE_FACEBOOK),
                ).fetchone()
                if duplicate is None:
                    raise ValueError(f"Raw post {duplicate_raw_post_id} is no longer a Facebook post.")
                before = connection.total_changes
                connection.execute(
                    "INSERT OR IGNORE INTO raw_post_aliases "
                    "(raw_post_id, source, source_post_id, url, created_at) VALUES (?, ?, ?, ?, ?)",
                    (survivor_raw_post_id, duplicate[0], duplicate[1], duplicate[2], utc_now_iso8601()),
                )
                aliases_created += connection.total_changes - before
                connection.execute(
                    "UPDATE raw_post_aliases SET raw_post_id = ? WHERE raw_post_id = ?",
                    (survivor_raw_post_id, duplicate_raw_post_id),
                )
                _move_image_references(connection, survivor_raw_post_id, duplicate_raw_post_id)
                _move_parse_drafts(connection, survivor_raw_post_id, duplicate_raw_post_id)
                for table_name in ("events", "event_periods", "suits", "event_suits"):
                    connection.execute(
                        f"UPDATE {table_name} SET source_raw_post_id = ? WHERE source_raw_post_id = ?",
                        (survivor_raw_post_id, duplicate_raw_post_id),
                    )
                connection.execute(
                    "UPDATE announcement_jobs SET raw_post_id = ? WHERE raw_post_id = ?",
                    (survivor_raw_post_id, duplicate_raw_post_id),
                )
                connection.execute("DELETE FROM raw_posts WHERE id = ?", (duplicate_raw_post_id,))
            connection.commit()
            return FacebookAliasRepairResult(
                survivor_raw_post_id, duplicate_raw_post_ids, aliases_created
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
