from __future__ import annotations

from crawler.models import Post
from database.announcement_job_repository import (
    BASELINE_CONTENT_PREFIX,
    AnnouncementJobRepository,
)
from database.database import get_connection, init_database, insert_announcement
from database.raw_post_repository import RawPostRepository
from scripts.reset_database import reset_rebuildable_data


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
