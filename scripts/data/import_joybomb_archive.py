"""Import JoyBomb Wayback notices into the raw layer only.

This historical importer intentionally stops at ``raw_posts`` and
``raw_post_images``.  It neither invokes the Parser nor creates Discord
announcement jobs.
"""

from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.joybomb_archive_crawler import (
    CdxIndexResult,
    CdxSnapshot,
    JoyBombArchiveNotice,
    canonicalize_original_url,
    crawl_samples,
    fetch_cdx_index,
    parse_notice_identity,
    select_notice_snapshots,
)
from crawler.models import Post
from database.database import get_connection, init_database
from database.raw_post_repository import RawPostBatchResult, RawPostFailure, RawPostRepository


LOGGER = logging.getLogger(__name__)
JOYBOMB_ARCHIVE_SOURCE = "joybomb_archive"
DEFAULT_FROM_YEAR = 2017
DEFAULT_TO_YEAR = 2024


@dataclass(frozen=True, slots=True)
class JoyBombRawImportResult:
    """One complete JoyBomb archive import run and its raw-layer outcome."""

    discovered_notices: int
    duplicate_urls: int
    duplicate_identities: int
    missing_html: int
    missing_images: int
    published_at_missing: int
    raw_images_inserted: int
    raw_images_updated: int
    storage: RawPostBatchResult
    samples: list[dict[str, object]]
    query_failures: dict[str, str]

    @property
    def skipped(self) -> int:
        """Count successfully fetched notices already stored unchanged."""
        return self.storage.unchanged


IndexFetcher = Callable[..., CdxIndexResult]
DetailCrawler = Callable[..., list[JoyBombArchiveNotice]]


def source_post_id_for(section: str, notice_id: str) -> str:
    """Create the stable source-local identity for one JoyBomb notice."""
    return f"{section}:{notice_id}"


def notice_to_post(notice: JoyBombArchiveNotice) -> Post | None:
    """Convert one successfully parsed archived notice to source-agnostic raw data."""
    identity = parse_notice_identity(notice.original_url)
    canonical_url = canonicalize_original_url(notice.original_url)
    if identity is None or canonical_url is None or not notice.content_html.strip():
        return None

    section, notice_id = identity
    published_at = datetime.fromisoformat(notice.published_at) if notice.published_at else None
    # ``content_text`` has already had page title/chrome removed by the archive
    # crawler.  Keep the source title in metadata instead of duplicating it at
    # the top of the parser input.
    content = notice.content_text.strip() or (notice.title or "").strip()
    if not content:
        return None

    return Post(
        post_id=source_post_id_for(section, notice_id),
        url=canonical_url,
        content=content,
        published_at=published_at,
        images=notice.image_original_urls,
        source=JOYBOMB_ARCHIVE_SOURCE,
        metadata={
            "archive_timestamp": notice.archive_timestamp,
            "archive_url": notice.archive_url,
            "canonical_url": canonical_url,
            "content_html": notice.content_html,
            "notice_id": notice_id,
            "original_url": notice.original_url,
            "section": section,
            "source_name": JOYBOMB_ARCHIVE_SOURCE,
            "template_signature": notice.template_signature,
            "title": notice.title,
        },
    )


def _image_count(database_path: Path | None, raw_post_id: int) -> int:
    connection = get_connection(database_path)
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM raw_post_images WHERE raw_post_id = ?", (raw_post_id,)
            ).fetchone()[0]
        )
    finally:
        connection.close()


def _duplicate_counts(snapshots: Sequence[CdxSnapshot]) -> tuple[int, int]:
    """Report CDX URL variants separately from stable notice identity variants."""
    canonical_urls = [
        canonicalize_original_url(snapshot.original_url)
        for snapshot in snapshots
        if canonicalize_original_url(snapshot.original_url) is not None
    ]
    identities = [
        parse_notice_identity(snapshot.original_url)
        for snapshot in snapshots
        if parse_notice_identity(snapshot.original_url) is not None
    ]
    return len(canonical_urls) - len(set(canonical_urls)), len(identities) - len(set(identities))


def _sample_rows(
    repository: RawPostRepository,
    notices: Sequence[JoyBombArchiveNotice],
    *,
    sample_size: int = 10,
) -> list[dict[str, object]]:
    """Create deterministic cross-run verification rows without mutating raw data."""
    rows: list[dict[str, object]] = []
    sample_count = min(sample_size, len(notices))
    # A fixed seed gives operators a representative, repeatable verification
    # sample without making this import alter its database write order.
    sampled_notices = random.Random(20_260_716).sample(list(notices), sample_count)
    for notice in sampled_notices:
        identity = parse_notice_identity(notice.original_url)
        if identity is None:
            continue
        section, notice_id = identity
        row = repository.get_raw_post_by_source_id(
            source_post_id_for(section, notice_id), source=JOYBOMB_ARCHIVE_SOURCE
        )
        if row is None:
            continue
        rows.append(
            {
                "raw_post_id": row["id"],
                "notice_id": notice_id,
                "section": section,
                "published_at": row["published_at"],
                "title": (row.get("metadata") or {}).get("title"),
                "canonical_url": row["url"],
                "image_count": len(row["images"]),
            }
        )
    return rows


def import_joybomb_archive(
    *,
    database_path: Path | None = None,
    from_year: int = DEFAULT_FROM_YEAR,
    to_year: int = DEFAULT_TO_YEAR,
    timeout: float = 30.0,
    request_delay: float = 0.2,
    limit: int | None = None,
    index_fetcher: IndexFetcher = fetch_cdx_index,
    detail_crawler: DetailCrawler = crawl_samples,
) -> JoyBombRawImportResult:
    """Fetch archived notices and save only raw posts and ordered raw images."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1 when provided")

    # Uses the established application initializer but does not introduce or
    # alter any schema.  The importer itself writes exclusively through the
    # raw repository below.
    init_database(database_path)
    index = index_fetcher(
        from_year=from_year,
        to_year=to_year,
        timeout=timeout,
        request_delay=request_delay,
    )
    all_valid = [
        snapshot
        for snapshot in index.snapshots
        if parse_notice_identity(snapshot.original_url) is not None
        and canonicalize_original_url(snapshot.original_url) is not None
    ]
    duplicate_urls, duplicate_identities = _duplicate_counts(all_valid)
    snapshots = select_notice_snapshots(all_valid)
    if limit is not None:
        snapshots = snapshots[:limit]

    notices = detail_crawler(
        snapshots,
        timeout=timeout,
        request_delay=request_delay,
        check_images=False,
    )
    repository = RawPostRepository(database_path)
    storage = RawPostBatchResult()
    missing_html = 0
    missing_images = 0
    published_at_missing = 0
    raw_images_inserted = 0
    raw_images_updated = 0

    for notice in notices:
        post = notice_to_post(notice)
        if post is None:
            missing_html += 1
            continue
        if not notice.image_original_urls:
            missing_images += 1
        if notice.published_at is None:
            published_at_missing += 1
        try:
            saved = repository.save_raw_post(post, enqueue_announcement=False)
        except Exception as error:  # Keep one malformed archived notice isolated.
            LOGGER.exception("Failed to persist JoyBomb notice %s", notice.notice_id)
            storage.failures.append(RawPostFailure(post.post_id, str(error)))
            continue

        image_count = _image_count(database_path, saved.raw_post_id)
        if saved.action == "inserted":
            storage.inserted += 1
            raw_images_inserted += image_count
        elif saved.action == "updated":
            storage.updated += 1
            raw_images_updated += image_count
        else:
            storage.unchanged += 1

    if any("locked" in failure.error.lower() for failure in storage.failures):
        raise sqlite3.OperationalError("database is locked")
    return JoyBombRawImportResult(
        discovered_notices=len(snapshots),
        duplicate_urls=duplicate_urls,
        duplicate_identities=duplicate_identities,
        missing_html=missing_html + max(0, len(snapshots) - len(notices)),
        missing_images=missing_images,
        published_at_missing=published_at_missing,
        raw_images_inserted=raw_images_inserted,
        raw_images_updated=raw_images_updated,
        storage=storage,
        samples=_sample_rows(repository, notices),
        query_failures=index.query_failures,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import JoyBomb Wayback notices into raw_posts only; does not parse or announce."
    )
    parser.add_argument("--from-year", type=int, default=DEFAULT_FROM_YEAR)
    parser.add_argument("--to-year", type=int, default=DEFAULT_TO_YEAR)
    parser.add_argument("--limit", type=int, help="Bound notices for a development run.")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--request-delay", type=float, default=0.2)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    result = import_joybomb_archive(
        from_year=args.from_year,
        to_year=args.to_year,
        limit=args.limit,
        timeout=args.timeout,
        request_delay=args.request_delay,
    )
    print(f"Found notices: {result.discovered_notices}")
    print(f"Inserted raw_posts: {result.storage.inserted}")
    print(f"Updated raw_posts: {result.storage.updated}")
    print(f"Skipped raw_posts: {result.skipped}")
    print(f"Failed raw_posts: {result.storage.failed}")
    print(f"Inserted raw_images: {result.raw_images_inserted}")
    print(f"Updated raw_images: {result.raw_images_updated}")
    print(f"Duplicate URLs: {result.duplicate_urls}")
    print(f"Duplicate identities: {result.duplicate_identities}")
    print(f"Missing HTML: {result.missing_html}")
    print(f"Missing images: {result.missing_images}")
    print(f"Missing published_at: {result.published_at_missing}")
    if result.query_failures:
        print(f"CDX query failures: {len(result.query_failures)}")
    print("Sample verification:")
    for row in result.samples:
        print(
            "- raw_post_id={raw_post_id} notice_id={notice_id} section={section} "
            "published_at={published_at} title={title!r} canonical_url={canonical_url} "
            "image_count={image_count}".format(**row)
        )
    return 0 if not result.storage.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
