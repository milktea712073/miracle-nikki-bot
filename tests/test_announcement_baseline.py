from __future__ import annotations

import pytest

from database.announcement_baseline import apply_announcement_baseline, build_announcement_baseline_plan
from database.database import announcement_exists, get_connection, init_database, insert_announcement
from database.raw_post_repository import RawPostRepository
from crawler.models import Post


def make_post(post_id: str) -> Post:
    return Post(
        post_id=post_id,
        url=f"https://www.facebook.com/TwNikkiNikki/posts/{post_id}",
        content=post_id,
        published_at=None,
        images=[],
    )


def test_baseline_marks_only_explicit_historical_posts_and_leaves_current_post_pending(tmp_path):
    database_path = tmp_path / "baseline.db"
    init_database(database_path)
    historical_a, current, historical_b = (
        make_post("historical-a"),
        make_post("current"),
        make_post("historical-b"),
    )
    RawPostRepository(database_path).save_raw_posts([historical_a, current, historical_b])
    connection = get_connection(database_path)
    try:
        plan = build_announcement_baseline_plan(
            connection,
            [historical_a.url, current.url, historical_b.url],
            current.url,
        )
        assert plan.baseline_urls == (historical_a.url, historical_b.url)
        assert plan.excluded_url == current.url

        assert apply_announcement_baseline(connection, plan) == 2
        assert not announcement_exists(connection, historical_a.url)
        assert not announcement_exists(connection, historical_b.url)
        assert not announcement_exists(connection, current.url)
        assert connection.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
        statuses = connection.execute(
            "SELECT status FROM announcement_jobs ORDER BY raw_post_id"
        ).fetchall()
        assert statuses == [("skipped",), ("skipped",)]
    finally:
        connection.close()


def test_baseline_rejects_an_excluded_url_that_is_not_pending(tmp_path):
    database_path = tmp_path / "baseline.db"
    init_database(database_path)
    post = make_post("already-announced")
    RawPostRepository(database_path).save_raw_post(post)
    connection = get_connection(database_path)
    try:
        insert_announcement(connection, "", post.content, post.url)
        with pytest.raises(ValueError, match="already has an announcement"):
            build_announcement_baseline_plan(connection, [post.url], post.url)
    finally:
        connection.close()
