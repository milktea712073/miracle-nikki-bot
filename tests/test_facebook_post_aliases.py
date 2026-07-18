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
RESENT_INCIDENT_PFBIDS = (
    "pfbid02HP4BziD9vVME885n6c1HKLRCCU7whYXBVgNrDD78jnAra8A89peePrwPVuGSMUnal",
    "pfbid0DqR15Yao5F8T6UbVbz8AuUeVsZPppZ9uNuxzpLiMSAsZLfk6xMU9ToQz8s3DPN72l",
)


def facebook_post(
    pfbid: str,
    *,
    content: str = "【奇迹報報】月刊",
    image_name: str | None = "monthly.png",
    published_at: datetime | None = None,
    verified: bool | None = True,
    url: str | None = None,
) -> Post:
    images = [] if image_name is None else [f"https://scontent.example.fbcdn.net/media/{image_name}?token={pfbid}"]
    return Post(
        post_id=pfbid,
        url=url or f"https://www.facebook.com/TwNikkiNikki/posts/{pfbid}",
        content=content,
        published_at=published_at,
        images=images,
        metadata=None if verified is None else {"official_post_verified": verified},
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


@pytest.mark.parametrize(
    "alias_url",
    [
        "https://www.facebook.com/TwNikkiNikki/posts/pfbid-alias?__tn__=tracking",
        "https://m.facebook.com/TwNikkiNikki/posts/pfbid-alias?ref=share",
        "https://www.facebook.com/share/p/pfbid-alias?mibextid=tracking",
    ],
)
def test_verified_alias_merges_legacy_row_without_metadata_and_sends_once(
    tmp_path: Path, alias_url: str
) -> None:
    database_path = tmp_path / "legacy-alias.db"
    repository = RawPostRepository(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()

    first = repository.save_raw_post(
        facebook_post("pfbid-primary", verified=None, image_name="same-media.png")
    )
    claimed = jobs.claim_jobs(1)
    assert [job.id for job in claimed] == [1]
    jobs.mark_sent(claimed[0].id)

    second = repository.save_raw_post(
        facebook_post(
            "pfbid-alias",
            verified=True,
            image_name="same-media.png",
            url=alias_url,
        )
    )

    assert second.action == "unchanged"
    assert second.raw_post_id == first.raw_post_id
    assert jobs.claim_jobs(3) == []
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM raw_post_aliases").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1
    finally:
        connection.close()


def test_queue_guard_skips_preexisting_duplicate_alias_job(tmp_path: Path) -> None:
    """A legacy duplicate job must not resend after the sent original."""
    database_path = tmp_path / "legacy-queue-guard.db"
    repository = RawPostRepository(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()
    first = repository.save_raw_post(facebook_post("pfbid-primary", image_name="same-media.png"))
    claimed = jobs.claim_jobs(1)
    jobs.mark_sent(claimed[0].id)

    connection = get_connection(database_path)
    try:
        now = "2026-07-17T00:00:00+00:00"
        duplicate_raw_id = connection.execute(
            "INSERT INTO raw_posts (source, source_post_id, url, content, published_at, scraped_at, updated_at, "
            "parse_status, content_hash, metadata_json) "
            "SELECT source, 'pfbid-legacy-alias', 'https://www.facebook.com/TwNikkiNikki/posts/pfbid-legacy-alias', "
            "content, published_at, ?, ?, parse_status, content_hash, NULL FROM raw_posts WHERE id = ?",
            (now, now, first.raw_post_id),
        ).lastrowid
        connection.execute(
            "INSERT INTO raw_post_images (raw_post_id, image_url, position, created_at) "
            "SELECT ?, image_url, position, ? FROM raw_post_images WHERE raw_post_id = ?",
            (duplicate_raw_id, now, first.raw_post_id),
        )
        connection.execute(
            "INSERT INTO announcement_jobs (raw_post_id, post_url, status, attempt_count, created_at, updated_at) "
            "VALUES (?, 'https://www.facebook.com/TwNikkiNikki/posts/pfbid-legacy-alias', 'pending', 0, ?, ?)",
            (duplicate_raw_id, now, now),
        )
        connection.commit()
    finally:
        connection.close()

    assert jobs.claim_jobs(3) == []
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1
        assert connection.execute(
            "SELECT status FROM announcement_jobs WHERE raw_post_id = ?", (duplicate_raw_id,)
        ).fetchone()[0] == "skipped"
    finally:
        connection.close()


def test_resend_incident_pfbids_merge_a_legacy_row_and_keep_one_delivery(tmp_path: Path) -> None:
    """Regression for the two pfbids that resent the July community-results post."""
    database_path = tmp_path / "resend-incident.db"
    repository = RawPostRepository(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()

    original = repository.save_raw_post(
        facebook_post(
            RESENT_INCIDENT_PFBIDS[0],
            content="incident-content",
            image_name="747127178_1019137040748634_3350597006999456569_n.png",
            verified=None,
        )
    )
    claimed = jobs.claim_jobs(1)
    jobs.mark_sent(claimed[0].id)
    alias = repository.save_raw_post(
        facebook_post(
            RESENT_INCIDENT_PFBIDS[1],
            content="incident-content",
            image_name="747127178_1019137040748634_3350597006999456569_n.png",
        )
    )

    assert alias.raw_post_id == original.raw_post_id
    assert alias.action == "unchanged"
    assert jobs.claim_jobs(1) == []
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1
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
