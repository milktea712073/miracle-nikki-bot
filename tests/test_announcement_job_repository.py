from __future__ import annotations

from crawler.models import Post
from database.announcement_job_repository import (
    BASELINE_CONTENT_PREFIX,
    AnnouncementJobRepository,
)
from database.database import get_connection, init_database, insert_announcement
from database.raw_post_repository import RawPostRepository
from scripts.data.reset_database import reset_rebuildable_data


def make_post(post_id: str) -> Post:
    return Post(
        post_id=post_id,
        url=f"https://www.facebook.com/TwNikkiNikki/posts/{post_id}",
        content=post_id,
        published_at=None,
        images=[],
    )


def test_initialization_skips_existing_raw_posts_and_new_raw_posts_become_pending(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    old_post = make_post("old")
    RawPostRepository(database_path).save_raw_post(old_post)
    jobs = AnnouncementJobRepository(database_path)

    assert jobs.initialize_from_existing_raw_posts() == 1
    assert jobs.get_job(1).status == "skipped"

    new_post = make_post("new")
    RawPostRepository(database_path).save_raw_post(new_post)
    assert jobs.get_job(2).status == "pending"


def test_initialization_can_keep_an_explicit_existing_url_pending(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    old_post, current_post = make_post("old"), make_post("current")
    RawPostRepository(database_path).save_raw_posts([old_post, current_post])

    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts((current_post.url,))

    assert jobs.get_job(1).status == "skipped"
    assert jobs.get_job(2).status == "pending"


def test_legacy_baseline_migration_moves_skipped_rows_out_of_announcements(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    skipped_post, sent_post = make_post("skipped"), make_post("sent")
    RawPostRepository(database_path).save_raw_posts([skipped_post, sent_post])
    connection = get_connection(database_path)
    try:
        insert_announcement(
            connection, "", f"{BASELINE_CONTENT_PREFIX}{skipped_post.url}", skipped_post.url
        )
        insert_announcement(connection, "", sent_post.content, sent_post.url)
    finally:
        connection.close()

    jobs = AnnouncementJobRepository(database_path)
    assert jobs.migrate_legacy_announcements() == (1, 1)
    assert jobs.migrate_legacy_announcements() == (0, 0)
    assert jobs.get_job(1).status == "skipped"
    assert jobs.get_job(2).status == "sent"
    connection = get_connection(database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM announcements WHERE post_url = ?", (skipped_post.url,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM announcements WHERE post_url = ?", (sent_post.url,)
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_rebuild_reset_preserves_raw_queue_and_delivery_history_by_default(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()
    post = make_post("queued")
    RawPostRepository(database_path).save_raw_post(post)
    jobs.mark_sent(1)

    reset_rebuildable_data(database_path)

    assert RawPostRepository(database_path).get_raw_post_by_source_id(post.post_id) is not None
    assert jobs.get_job(1).status == "sent"
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1
    finally:
        connection.close()


def test_rebuild_reset_announcements_keeps_raw_but_clears_queue_history(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()
    post = make_post("queued")
    RawPostRepository(database_path).save_raw_post(post)
    jobs.mark_sent(1)

    reset_rebuildable_data(database_path, reset_announcements=True)

    assert RawPostRepository(database_path).get_raw_post_by_source_id(post.post_id) is not None
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 0
    finally:
        connection.close()


def test_sent_job_survives_raw_post_recreation_with_a_new_sqlite_id(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()
    post = make_post("stable-url")
    first_raw_id = RawPostRepository(database_path).save_raw_post(post).raw_post_id
    jobs.mark_sent(1)

    connection = get_connection(database_path)
    try:
        connection.execute("DELETE FROM raw_posts WHERE id = ?", (first_raw_id,))
        connection.commit()
    finally:
        connection.close()

    second_raw_id = RawPostRepository(database_path).save_raw_post(post).raw_post_id
    assert second_raw_id != first_raw_id
    repaired_job = jobs.get_job(1)
    assert repaired_job is not None
    assert repaired_job.raw_post_id == second_raw_id
    assert repaired_job.status == "sent"
    assert jobs.claim_jobs(3) == []


def test_url_variants_and_skipped_jobs_keep_the_same_delivery_identity(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()
    post = make_post("url-variant")
    first_raw_id = RawPostRepository(database_path).save_raw_post(post).raw_post_id
    connection = get_connection(database_path)
    try:
        connection.execute("UPDATE announcement_jobs SET status = 'skipped' WHERE id = 1")
        connection.execute("DELETE FROM raw_posts WHERE id = ?", (first_raw_id,))
        connection.commit()
    finally:
        connection.close()

    variant = Post(
        post_id=post.post_id,
        url=f"{post.url}?__tn__=tracking",
        content=post.content,
        published_at=None,
        images=[],
    )
    RawPostRepository(database_path).save_raw_post(variant)

    assert jobs.get_job(1).status == "skipped"
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 1
    finally:
        connection.close()


def test_different_new_facebook_post_still_creates_a_pending_job(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()

    RawPostRepository(database_path).save_raw_post(make_post("actually-new"))

    assert jobs.get_job(1).status == "pending"


def test_rebuild_fetch_mode_does_not_enqueue_newly_discovered_history(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()

    RawPostRepository(database_path).save_raw_posts(
        [make_post("historical-discovery")], enqueue_announcements=False
    )

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 0
    finally:
        connection.close()


def test_repair_plan_skips_only_reviewed_history_and_keeps_explicit_new_url(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()
    history, current = make_post("history"), make_post("current")
    RawPostRepository(database_path).save_raw_posts([history, current])

    plan = jobs.plan_rebuild_repair((current.url,))
    assert [job.post_url for job in plan.jobs_to_skip] == [history.url]
    assert [job.post_url for job in plan.jobs_to_keep_pending] == [current.url]

    assert jobs.apply_rebuild_repair(plan) == 1
    assert jobs.get_job(1).status == "skipped"
    assert jobs.get_job(2).status == "pending"


def test_legacy_raw_post_id_job_schema_migrates_to_stable_post_url(tmp_path):
    database_path = tmp_path / "legacy-queue.db"
    init_database(database_path)
    connection = get_connection(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE announcement_jobs")
        connection.execute(
            """
            CREATE TABLE announcement_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_post_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT,
                FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE,
                UNIQUE(raw_post_id)
            )
            """
        )
        raw_post_id = connection.execute(
            """
            INSERT INTO raw_posts (
                source, source_post_id, url, content, scraped_at, updated_at, content_hash
            ) VALUES ('facebook', 'legacy', ?, 'legacy', '2026-01-01T00:00:00+00:00',
                      '2026-01-01T00:00:00+00:00', 'hash')
            """,
            ("https://www.facebook.com/TwNikkiNikki/posts/legacy?utm_source=test",),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO announcement_jobs (
                raw_post_id, status, attempt_count, created_at, updated_at, sent_at
            ) VALUES (?, 'sent', 1, '2026-01-01T00:00:00+00:00',
                      '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (raw_post_id,),
        )
        connection.commit()
    finally:
        connection.close()

    init_database(database_path)
    connection = get_connection(database_path)
    try:
        job = connection.execute(
            "SELECT raw_post_id, post_url, status FROM announcement_jobs"
        ).fetchone()
        assert job == (
            raw_post_id,
            "https://www.facebook.com/TwNikkiNikki/posts/legacy",
            "sent",
        )
        connection.execute("DELETE FROM raw_posts WHERE id = ?", (raw_post_id,))
        connection.commit()
        assert connection.execute(
            "SELECT raw_post_id, status FROM announcement_jobs"
        ).fetchone() == (None, "sent")
    finally:
        connection.close()
