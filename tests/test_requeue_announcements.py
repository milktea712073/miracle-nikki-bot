from __future__ import annotations

from crawler.facebook_crawler import normalize_post_url
from crawler.models import Post
from database.announcement_job_repository import AnnouncementJobRepository
from database.database import get_connection, init_database, insert_announcement
from database.raw_post_repository import RawPostRepository
from scripts.requeue_announcement import main as requeue_announcement_main
from scripts.requeue_latest import main as requeue_latest_main


def make_post(post_id: str) -> Post:
    return Post(
        post_id=post_id,
        url=f"https://www.facebook.com/TwNikkiNikki/posts/{post_id}",
        content=post_id,
        published_at=None,
        images=[],
    )


def seeded_repository(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    jobs = AnnouncementJobRepository(database_path)
    jobs.initialize_from_existing_raw_posts()
    return database_path, jobs


def test_requeue_resets_every_existing_job_state_and_keeps_one_job(tmp_path):
    database_path, jobs = seeded_repository(tmp_path)
    post = make_post("post")
    RawPostRepository(database_path).save_raw_post(post)
    connection = get_connection(database_path)
    try:
        for status in ("sent", "failed", "skipped", "sending", "pending"):
            connection.execute(
                "UPDATE announcement_jobs SET status = ?, attempt_count = 4, "
                "last_error = 'old', sent_at = '2026-01-01T00:00:00+00:00' WHERE id = 1",
                (status,),
            )
            connection.commit()
            result = jobs.requeue_announcement_job(post.url)
            assert result is not None
            assert result.old_status == status
            row = connection.execute(
                "SELECT status, attempt_count, last_error, sent_at FROM announcement_jobs WHERE id = 1"
            ).fetchone()
            assert row == ("pending", 0, None, None)
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 1
    finally:
        connection.close()


def test_requeue_creates_missing_job_normalizes_url_and_preserves_announcements(tmp_path):
    database_path = tmp_path / "queue.db"
    init_database(database_path)
    post = make_post("post")
    RawPostRepository(database_path).save_raw_post(post)
    jobs = AnnouncementJobRepository(database_path)
    connection = get_connection(database_path)
    try:
        insert_announcement(connection, "", post.content, post.url)
    finally:
        connection.close()

    result = jobs.requeue_announcement_job(normalize_post_url(f"{post.url}?utm_source=test"))
    assert result is not None
    assert result.old_status is None
    assert jobs.get_job(result.job_id).status == "pending"
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1
    finally:
        connection.close()


def test_requeue_missing_raw_post_is_safe(tmp_path):
    _, jobs = seeded_repository(tmp_path)
    assert jobs.requeue_announcement_job("https://www.facebook.com/TwNikkiNikki/posts/missing") is None


def test_requeue_latest_selects_real_sent_record_not_baseline_or_skipped(tmp_path, monkeypatch, capsys):
    database_path, jobs = seeded_repository(tmp_path)
    skipped, sent = make_post("skipped"), make_post("sent")
    RawPostRepository(database_path).save_raw_posts([skipped, sent])
    jobs.mark_sent(2)
    connection = get_connection(database_path)
    try:
        connection.execute("UPDATE announcement_jobs SET status = 'skipped' WHERE id = 1")
        insert_announcement(connection, "", "[baseline skipped; not sent to Discord] old", skipped.url)
        connection.commit()
    finally:
        connection.close()
    assert jobs.find_latest_sent_announcement_url() == sent.url
    monkeypatch.setattr("scripts.requeue_latest.AnnouncementJobRepository", lambda: jobs)

    assert requeue_latest_main() == 0
    assert "Requeued latest announcement:" in capsys.readouterr().out
    assert jobs.get_job(2).status == "pending"
    assert jobs.requeue_announcement_job(sent.url).job_id == 2


def test_requeue_latest_without_sent_record_exits_nonzero(tmp_path, monkeypatch, capsys):
    _, jobs = seeded_repository(tmp_path)
    monkeypatch.setattr("scripts.requeue_latest.AnnouncementJobRepository", lambda: jobs)

    assert requeue_latest_main() == 1
    assert "No sent announcement found." in capsys.readouterr().out


def test_requeue_script_reports_missing_raw_post(monkeypatch, tmp_path, capsys):
    _, jobs = seeded_repository(tmp_path)
    monkeypatch.setattr("scripts.requeue_announcement.AnnouncementJobRepository", lambda: jobs)

    assert requeue_announcement_main(["--post-url", "https://www.facebook.com/TwNikkiNikki/posts/missing"]) == 1
    assert "Raw post not found." in capsys.readouterr().out
