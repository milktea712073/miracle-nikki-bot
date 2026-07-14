from datetime import datetime, timedelta, timezone

import pytest

from crawler.models import Post
from database.raw_post_repository import RawPostRepository


UTC = timezone.utc


def make_post(
    post_id: str = "post-1",
    content: str = "content",
    images: list[str] | None = None,
    published_at: datetime | None = None,
) -> Post:
    return Post(
        post_id=post_id,
        url=f"https://www.facebook.com/posts/{post_id}",
        content=content,
        published_at=published_at or datetime(2026, 7, 11, 4, 0, tzinfo=UTC),
        images=images or ["https://images.example/one.png", "https://images.example/two.png"],
    )


@pytest.fixture
def repository(tmp_path):
    return RawPostRepository(tmp_path / "raw-posts.db")


def test_inserts_post_with_ordered_images_and_pending_status(repository):
    saved = repository.save_raw_post(make_post())

    row = repository.get_raw_post_by_source_id("post-1")
    assert saved.action == "inserted"
    assert row["parse_status"] == "pending"
    assert row["images"] == [
        "https://images.example/one.png",
        "https://images.example/two.png",
    ]
    assert row["published_at"] == "2026-07-11T04:00:00+00:00"


def test_inserts_trusted_post_without_facebook_publication_time(repository):
    post = Post(
        post_id="without-time",
        url="https://www.facebook.com/TwNikkiNikki/posts/without-time",
        content="可信官方公告",
        published_at=None,
        images=["https://images.example/official.png"],
    )

    saved = repository.save_raw_post(post)
    row = repository.get_raw_post_by_source_id(post.post_id)

    assert saved.action == "inserted"
    assert row is not None
    assert row["published_at"] is None
    assert row["scraped_at"]


def test_duplicate_post_is_unchanged(repository):
    repository.save_raw_post(make_post())
    saved = repository.save_raw_post(make_post())

    assert saved.action == "unchanged"
    assert repository.get_raw_post_by_source_id("post-1")["id"] == saved.raw_post_id


def test_changed_content_updates_and_clears_parse_error(repository):
    repository.save_raw_post(make_post())
    connection = repository._connect()
    try:
        connection.execute(
            "UPDATE raw_posts SET parse_status = 'failed', parse_error = 'bad parser'"
        )
        connection.commit()
    finally:
        connection.close()

    saved = repository.save_raw_post(make_post(content="changed"))
    row = repository.get_raw_post_by_source_id("post-1")
    assert saved.action == "updated"
    assert row["content"] == "changed"
    assert row["parse_status"] == "pending"
    assert row["parse_error"] is None


def test_image_reorder_and_changes_replace_ordered_images(repository):
    repository.save_raw_post(make_post(images=["a", "b", "c"]))
    repository.save_raw_post(make_post(images=["c", "a", "d", "a"]))

    row = repository.get_raw_post_by_source_id("post-1")
    assert row["images"] == ["c", "a", "d"]


def test_transaction_rolls_back_post_when_image_write_fails(repository, monkeypatch):
    def fail_images(*args, **kwargs):
        raise RuntimeError("image insert failed")

    monkeypatch.setattr(repository, "_insert_images", fail_images)
    with pytest.raises(RuntimeError, match="image insert failed"):
        repository.save_raw_post(make_post())

    assert not repository.raw_post_exists("post-1")


def test_batch_continues_when_one_post_fails(repository):
    invalid = make_post("bad", published_at=datetime(2026, 7, 11, 4, 0))
    valid = make_post("good")

    result = repository.save_raw_posts([invalid, valid])
    assert result.inserted == 1
    assert result.failed == 1
    assert result.failures[0].source_post_id == "bad"
    assert repository.raw_post_exists("good")


def test_hash_includes_published_at(repository):
    repository.save_raw_post(make_post())
    saved = repository.save_raw_post(
        make_post(published_at=datetime(2026, 7, 11, 5, 0, tzinfo=UTC))
    )
    assert saved.action == "updated"


def test_changed_url_updates_existing_post(repository):
    repository.save_raw_post(make_post())
    changed = make_post()
    changed = Post(
        post_id=changed.post_id,
        url="https://www.facebook.com/posts/post-1-updated",
        content=changed.content,
        published_at=changed.published_at,
        images=changed.images,
    )

    assert repository.save_raw_post(changed).action == "updated"


def test_fbcdn_query_changes_do_not_trigger_update(repository):
    repository.save_raw_post(
        make_post(images=["https://scontent.example.fbcdn.net/image.png?token=first"])
    )
    saved = repository.save_raw_post(
        make_post(images=["https://scontent.example.fbcdn.net/image.png?token=second"])
    )

    assert saved.action == "unchanged"
