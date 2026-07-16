"""Regression coverage for Facebook pfbid aliases and legacy repair."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crawler.models import Post
from database.announcement_job_repository import AnnouncementJobRepository
from database.database import get_connection, init_database
from database.facebook_alias_repository import FacebookAliasRepository
from database.raw_post_repository import RawPostRepository
from scripts.data.repair_facebook_post_aliases import main as repair_main


UTC = timezone.utc

MAY_MONTHLY_PFBIDS = (
    "pfbid0WfyCNrs7CPGnhk4fDxCyWgfM9hh3JtYVJENDzsJfAiGEiS5RodNeykEdyAenGPqFl",
    "pfbid02aXQuZXnw3koBqxexixaE6s55guv5iSCDP7EGCF8yYte8kr4aDKcwbWTNxApZZDRCl",
)
JUNE_MONTHLY_PFBIDS = (
    "pfbid032ki82hFVEfauBhP6SAq1wh585Cj3DSommemwiAPkCK8NHC9VX4Pi4fVe7GLEo8v4l",
    "pfbid0yD4w7Xd8PUGJk22FwRfVztMb3hBqUSa87Upx3Fz2jMaxV7xd426sF6icM2euQ9DDl",
)


def facebook_post(
    pfbid: str,
    *,
    content: str = "【奇迹報報】月刊",
    image_name: str | None = "monthly.png",
    published_at: datetime | None = None,
    verified: bool = True,
) -> Post:
    images = [] if image_name is None else [f"https://scontent.example.fbcdn.net/media/{image_name}?token={pfbid}"]
    return Post(
        post_id=pfbid,
        url=f"https://www.facebook.com/TwNikkiNikki/posts/{pfbid}",
        content=content,
        published_at=published_at,
        images=images,
        metadata={"official_post_verified": verified},
    )


@pytest.mark.parametrize(
    ("pfbids", "content", "image_name"),
    [
        (MAY_MONTHLY_PFBIDS, "【奇迹報報】5月月刊", "may-monthly.jpg"),
        (JUNE_MONTHLY_PFBIDS, "【奇迹報報】6月月刊", "june-monthly.png"),
    ],
)
def test_known_monthly_pfbid_pairs_create_one_raw_post_and_one_alias(
    tmp_path: Path, pfbids: tuple[str, str], content: str, image_name: str
) -> None:
    database_path = tmp_path / "aliases.db"
    repository = RawPostRepository(database_path)
    AnnouncementJobRepository(database_path).initialize_from_existing_raw_posts()

    first = repository.save_raw_post(facebook_post(pfbids[0], content=content, image_name=image_name))
    second = repository.save_raw_post(facebook_post(pfbids[1], content=content, image_name=image_name))

    assert first.action == "inserted"
    assert second.action == "unchanged"
    assert second.raw_post_id == first.raw_post_id
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM raw_post_aliases").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 1
    finally:
        connection.close()


def test_same_content_with_different_media_is_not_automatically_merged(tmp_path: Path) -> None:
    repository = RawPostRepository(tmp_path / "different-media.db")
    repository.save_raw_post(facebook_post("pfbid-a", image_name="one.jpg"))
    repository.save_raw_post(facebook_post("pfbid-b", image_name="two.jpg"))

    connection = repository._connect()
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM raw_post_aliases").fetchone()[0] == 0
    finally:
        connection.close()


def test_unverified_legacy_row_is_not_automatically_merged(tmp_path: Path) -> None:
    repository = RawPostRepository(tmp_path / "unverified.db")
    repository.save_raw_post(facebook_post("pfbid-a", verified=False))
    repository.save_raw_post(facebook_post("pfbid-b", verified=True))

    connection = repository._connect()
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM raw_post_aliases").fetchone()[0] == 0
    finally:
        connection.close()


def test_same_content_without_images_but_different_publication_times_is_not_merged(tmp_path: Path) -> None:
    repository = RawPostRepository(tmp_path / "different-time.db")
    repository.save_raw_post(
        facebook_post("pfbid-a", image_name=None, published_at=datetime(2026, 7, 1, tzinfo=UTC))
    )
    repository.save_raw_post(
        facebook_post("pfbid-b", image_name=None, published_at=datetime(2026, 7, 2, tzinfo=UTC))
    )

    connection = repository._connect()
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 2
    finally:
        connection.close()


def test_existing_alias_is_known_and_does_not_create_a_second_queue_job(tmp_path: Path) -> None:
    database_path = tmp_path / "alias-repeat.db"
    repository = RawPostRepository(database_path)
    AnnouncementJobRepository(database_path).initialize_from_existing_raw_posts()
    repository.save_raw_post(facebook_post("pfbid-primary"))
    repository.save_raw_post(facebook_post("pfbid-alias"))
    repeated = repository.save_raw_post(facebook_post("pfbid-alias"))

    assert repeated.action == "unchanged"
    assert repository.get_raw_post_by_source_id("pfbid-alias") is not None
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 1
    finally:
        connection.close()


def test_repair_rebinds_downstream_references_and_keeps_queue_statuses(tmp_path: Path) -> None:
    database_path = tmp_path / "repair.db"
    repository = RawPostRepository(database_path)
    AnnouncementJobRepository(database_path).initialize_from_existing_raw_posts()
    first = repository.save_raw_post(facebook_post("pfbid-primary", verified=False))
    duplicate = repository.save_raw_post(facebook_post("pfbid-duplicate", verified=False))
    connection = get_connection(database_path)
    try:
        now = "2026-07-16T00:00:00+00:00"
        connection.execute(
            "INSERT INTO parse_drafts (raw_post_id, parser_version, status, created_at, updated_at) VALUES (?, 'rules-v1', 'pending', ?, ?)",
            (duplicate.raw_post_id, now, now),
        )
        connection.execute(
            "INSERT INTO events (name, created_at, updated_at, source_raw_post_id) VALUES ('重複活動', ?, ?, ?)",
            (now, now, duplicate.raw_post_id),
        )
        connection.execute(
            "UPDATE announcement_jobs SET status = CASE raw_post_id WHEN ? THEN 'sent' ELSE 'skipped' END "
            "WHERE raw_post_id IN (?, ?)",
            (first.raw_post_id, first.raw_post_id, duplicate.raw_post_id),
        )
        connection.commit()
    finally:
        connection.close()

    groups = FacebookAliasRepository(database_path).list_duplicate_groups()
    assert len(groups) == 1
    result = FacebookAliasRepository(database_path).merge_group(groups[0])

    assert result.survivor_raw_post_id == first.raw_post_id
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 1
        assert connection.execute("SELECT raw_post_id FROM parse_drafts").fetchone()[0] == first.raw_post_id
        assert connection.execute("SELECT source_raw_post_id FROM events").fetchone()[0] == first.raw_post_id
        assert set(row[0] for row in connection.execute("SELECT status FROM announcement_jobs")) == {"sent", "skipped"}
        assert set(row[0] for row in connection.execute("SELECT raw_post_id FROM announcement_jobs")) == {first.raw_post_id}
    finally:
        connection.close()


def test_repair_requires_yes_before_modifying_legacy_candidates(tmp_path: Path) -> None:
    database_path = tmp_path / "repair-cancelled.db"
    repository = RawPostRepository(database_path)
    repository.save_raw_post(facebook_post("pfbid-primary", verified=False))
    repository.save_raw_post(facebook_post("pfbid-duplicate", verified=False))

    assert repair_main(["--database-path", str(database_path)], input_fn=lambda _: "NO") == 0

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM raw_post_aliases").fetchone()[0] == 0
    finally:
        connection.close()
