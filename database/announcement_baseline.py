"""Safe baseline support for historical posts that must not be backfilled."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from database.database import announcement_exists


BASELINE_CONTENT_PREFIX = "[baseline skipped; not sent to Discord] "


@dataclass(frozen=True, slots=True)
class AnnouncementBaselinePlan:
    """Validated announcement URLs that may be marked as intentionally skipped."""

    baseline_urls: tuple[str, ...]
    excluded_url: str
    already_announced_urls: tuple[str, ...]


def _unique_urls(post_urls: list[str]) -> list[str]:
    """Trim URLs while preserving the caller's explicit order."""
    urls: list[str] = []
    seen: set[str] = set()
    for raw_url in post_urls:
        url = raw_url.strip()
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def build_announcement_baseline_plan(
    connection: sqlite3.Connection,
    candidate_urls: list[str],
    excluded_url: str,
) -> AnnouncementBaselinePlan:
    """Validate explicit current-cycle URLs before marking historical ones skipped."""
    urls = _unique_urls(candidate_urls)
    excluded_url = excluded_url.strip()
    if not excluded_url:
        raise ValueError("A post URL to keep pending is required.")
    if excluded_url not in urls:
        raise ValueError("The excluded post URL must also be included in --post-url.")

    missing_raw_urls = [
        url
        for url in urls
        if connection.execute("SELECT 1 FROM raw_posts WHERE url = ?", (url,)).fetchone()
        is None
    ]
    if missing_raw_urls:
        raise ValueError(
            "These URLs are not present in raw_posts: " + ", ".join(missing_raw_urls)
        )
    if announcement_exists(connection, excluded_url):
        raise ValueError("The excluded post already has an announcement record.")

    baseline_urls: list[str] = []
    already_announced_urls: list[str] = []
    for url in urls:
        if url == excluded_url:
            continue
        if announcement_exists(connection, url):
            already_announced_urls.append(url)
        else:
            baseline_urls.append(url)
    return AnnouncementBaselinePlan(
        baseline_urls=tuple(baseline_urls),
        excluded_url=excluded_url,
        already_announced_urls=tuple(already_announced_urls),
    )


def apply_announcement_baseline(
    connection: sqlite3.Connection, plan: AnnouncementBaselinePlan
) -> int:
    """Create durable skipped jobs without sending Discord or faking delivery."""
    try:
        connection.execute("BEGIN")
        for url in plan.baseline_urls:
            raw_post = connection.execute(
                "SELECT id FROM raw_posts WHERE url = ?", (url,)
            ).fetchone()
            connection.execute(
                "INSERT OR IGNORE INTO announcement_jobs "
                "(raw_post_id, status, attempt_count, created_at, updated_at) "
                "VALUES (?, 'skipped', 0, datetime('now'), datetime('now'))",
                (int(raw_post[0]),),
            )
        connection.commit()
        return len(plan.baseline_urls)
    except Exception:
        connection.rollback()
        raise
