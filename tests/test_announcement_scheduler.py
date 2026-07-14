"""Regression tests for announcement candidate selection and image delivery."""

from __future__ import annotations

import asyncio
from pathlib import Path

import bot.main as bot_main
from crawler.models import Post
from database.announcement_job_repository import AnnouncementJobRepository
from database.database import announcement_exists, get_connection, init_database
from database.raw_post_repository import RawPostRepository


def make_post(post_id: str, image_count: int = 0) -> Post:
    return Post(
        post_id=post_id,
        url=f"https://www.facebook.com/TwNikkiNikki/posts/{post_id}",
        content=f"post {post_id}",
        published_at=None,
        images=[f"https://images.example/{post_id}-{index}.png" for index in range(image_count)],
    )


def configure_worker(monkeypatch, database_path: Path, sent: list[str]) -> AnnouncementJobRepository:
    repository = AnnouncementJobRepository(database_path)
    monkeypatch.setattr(bot_main, "AnnouncementJobRepository", lambda: repository)

    async def record_send(payload: dict[str, object]) -> None:
        sent.append(str(payload["post_url"]))

    monkeypatch.setattr(bot_main, "send_announcement_post", record_send)
    return repository


def initialize_queue(database_path: Path) -> AnnouncementJobRepository:
    repository = AnnouncementJobRepository(database_path)
    repository.initialize_from_existing_raw_posts()
    return repository


def test_new_raw_post_creates_one_pending_job_and_update_does_not_duplicate(tmp_path):
    database_path = tmp_path / "scheduler.db"
    init_database(database_path)
    initialize_queue(database_path)
    post = make_post("new")
    raw = RawPostRepository(database_path)
    raw.save_raw_post(post)
    raw.save_raw_post(post)
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT status FROM announcement_jobs").fetchone()[0] == "pending"
        assert connection.execute("SELECT COUNT(*) FROM announcement_jobs").fetchone()[0] == 1
    finally:
        connection.close()


def test_pending_job_sends_even_when_the_feed_no_longer_returns_the_post(monkeypatch, tmp_path):
    database_path = tmp_path / "scheduler.db"
    init_database(database_path)
    initialize_queue(database_path)
    post = make_post("disappeared-from-feed")
    RawPostRepository(database_path).save_raw_post(post)
    sent: list[str] = []
    repository = configure_worker(monkeypatch, database_path, sent)

    asyncio.run(bot_main.check_new_post.coro())

    assert sent == [post.url]
    assert repository.get_job(1).status == "sent"
    connection = get_connection(database_path)
    try:
        assert announcement_exists(connection, post.url)
    finally:
        connection.close()


def test_failed_job_is_retryable_after_worker_restart(monkeypatch, tmp_path):
    database_path = tmp_path / "scheduler.db"
    init_database(database_path)
    initialize_queue(database_path)
    post = make_post("retry")
    RawPostRepository(database_path).save_raw_post(post)
    sent: list[str] = []
    repository = configure_worker(monkeypatch, database_path, sent)

    async def fail_send(_payload: dict[str, object]) -> None:
        raise RuntimeError("Discord unavailable")

    monkeypatch.setattr(bot_main, "send_announcement_post", fail_send)
    asyncio.run(bot_main.check_new_post.coro())
    assert repository.get_job(1).status == "failed"
    assert not announcement_exists(get_connection(database_path), post.url)

    async def record_send(payload: dict[str, object]) -> None:
        sent.append(str(payload["post_url"]))

    monkeypatch.setattr(bot_main, "send_announcement_post", record_send)
    asyncio.run(bot_main.check_new_post.coro())

    assert sent == [post.url]
    assert repository.get_job(1).status == "sent"


def test_worker_processes_at_most_three_jobs_per_poll(monkeypatch, tmp_path):
    database_path = tmp_path / "scheduler.db"
    init_database(database_path)
    initialize_queue(database_path)
    posts = [make_post(f"post-{index}") for index in range(4)]
    RawPostRepository(database_path).save_raw_posts(posts)
    sent: list[str] = []
    repository = configure_worker(monkeypatch, database_path, sent)

    asyncio.run(bot_main.check_new_post.coro())

    assert sent == [post.url for post in posts[:3]]
    assert repository.get_job(4).status == "pending"


class Destination:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def sent_image_urls(destination: Destination) -> list[str]:
    return [
        str(embed.image.url)
        for call in destination.calls
        for embed in call["embeds"]
        if embed.image.url
    ]


def test_announcement_image_embeds_preserve_all_images_and_order():
    for image_count in (1, 5, 6, 10):
        destination = Destination()
        post = make_post(f"images-{image_count}", image_count=image_count)

        asyncio.run(bot_main.send_post(destination, bot_main.announcement_payload_from_post(post)))

        assert sent_image_urls(destination) == post.images
        assert sum(len(call["embeds"]) for call in destination.calls) == image_count
        assert len(destination.calls) == 1


def test_multiple_image_batches_remain_one_announcement_record(monkeypatch, tmp_path):
    database_path = tmp_path / "scheduler.db"
    init_database(database_path)
    initialize_queue(database_path)
    post = make_post("many-images", image_count=11)
    RawPostRepository(database_path).save_raw_post(post)
    sent: list[str] = []
    configure_worker(monkeypatch, database_path, sent)

    asyncio.run(bot_main.check_new_post.coro())

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 11
    finally:
        connection.close()


def test_raw_storage_readback_and_delivery_keep_six_images_in_order(monkeypatch, tmp_path):
    database_path = tmp_path / "scheduler.db"
    init_database(database_path)
    post = make_post("six-images", image_count=6)
    repository = RawPostRepository(database_path)
    repository.save_raw_post(post)

    stored = repository.get_raw_post_by_source_id(post.post_id)
    assert stored is not None
    assert stored["images"] == post.images

    destination = Destination()
    asyncio.run(bot_main.send_post(destination, bot_main.announcement_payload_from_post(post)))
    assert sent_image_urls(destination) == post.images
