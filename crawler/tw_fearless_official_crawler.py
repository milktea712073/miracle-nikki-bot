"""Raw-layer crawler for Taiwan's current Fearless Games official website.

This is deliberately separate from ``tw_official_crawler``: that module is the
live Discord-announcement adapter.  This module only returns notices that a
caller may persist as archived ``raw_posts``.  It shares the site's verified
JSON-list and Next.js-detail parsing primitives from ``website_crawler``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, Mapping

from announcement.models import Announcement, canonical_announcement_url
from crawler.website_crawler import (
    JsonFetcher,
    TextFetcher,
    WebsiteCrawlerError,
    build_news_url,
    fetch_json,
    fetch_news_page,
    fetch_text,
    parse_numeric_news_id,
    parse_website_announcement,
)


LOGGER = logging.getLogger(__name__)
TW_FEARLESS_OFFICIAL = "tw_fearless_official"
CategoryFilter = Literal["all", "news", "support"]

# The list API returns section numbers on each row.  `sectionType=0` is the
# only observed API value that reliably returns the complete mixed list, so
# category filtering happens from those first-party row values.
NEWS_SECTIONS = frozenset({1, 2})
SUPPORT_SECTIONS = frozenset({3, 11, 21})
_VALID_CATEGORIES = frozenset({"all", "news", "support"})


@dataclass(frozen=True, slots=True)
class TWFearlessDetailFailure:
    """A valid list entry whose detail page could not be retained."""

    external_id: str
    url: str
    title: str
    error: str


@dataclass(frozen=True, slots=True)
class TWFearlessFetchResult:
    """Raw-source crawl outcome; no SQLite or delivery side effects."""

    announcements: list[Announcement]
    failures: list[TWFearlessDetailFailure]
    listed_count: int
    pages_fetched: int
    list_total: int


def _category_includes(category: CategoryFilter, section: int) -> bool:
    if category == "all":
        return True
    if category == "news":
        return section in NEWS_SECTIONS
    return section in SUPPORT_SECTIONS


def _section_metadata(section: int, section_name: str) -> dict[str, object]:
    return {"section": section, "section_name": section_name, "list_endpoint": "https://nu3.fearlessgames.net/api/news"}


def fetch_recent_announcements_with_failures(
    limit: int,
    *,
    category: CategoryFilter = "all",
    page_size: int = 50,
    json_fetcher: JsonFetcher | None = None,
    text_fetcher: TextFetcher | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_detail_start: Callable[[int, int, str, str], None] | None = None,
) -> TWFearlessFetchResult:
    """Fetch up to ``limit`` official notices across JSON-list pages.

    A list failure is raised before any caller can import records.  A malformed
    detail is recorded and skipped so one article never loses the remaining
    independently valid announcements.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"Unsupported category: {category}")

    request_json = json_fetcher or fetch_json
    request_text = text_fetcher or fetch_text
    selected: list[Mapping[str, object]] = []
    offset = 0
    pages_fetched = 0
    list_total = 0

    while len(selected) < limit:
        page = fetch_news_page(offset=offset, limit=page_size, section_type=0, json_fetcher=request_json)
        pages_fetched += 1
        list_total = page.total
        if on_page is not None:
            on_page(pages_fetched, page.total)
        if not page.entries:
            break
        for item in page.entries:
            try:
                section = int(item.get("section", 0))
            except (TypeError, ValueError) as error:
                raise WebsiteCrawlerError(f"Official list item has invalid section: {item!r}") from error
            if _category_includes(category, section):
                selected.append(item)
                if len(selected) == limit:
                    break
        offset += len(page.entries)
        if offset >= page.total:
            break

    announcements: list[Announcement] = []
    failures: list[TWFearlessDetailFailure] = []
    for index, item in enumerate(selected, start=1):
        external_id = parse_numeric_news_id(str(item["id"]))
        url = build_news_url(external_id)
        title = str(item.get("title", "")).strip()
        if on_detail_start is not None:
            on_detail_start(index, len(selected), external_id, title)
        try:
            parsed = parse_website_announcement(item, request_text(url))
            published_at = datetime.fromisoformat(parsed.publish_time) if parsed.publish_time else None
            if published_at is None:
                LOGGER.warning("Fearless official detail has no publish time external_id=%s", external_id)
            announcements.append(
                Announcement(
                    source=TW_FEARLESS_OFFICIAL,
                    external_id=parsed.source_post_id,
                    url=canonical_announcement_url(TW_FEARLESS_OFFICIAL, parsed.url),
                    title=parsed.title,
                    category=parsed.section_name,
                    published_at=published_at,
                    content_html=parsed.content_html,
                    content_text=parsed.content_text,
                    images=tuple(parsed.image_urls),
                    metadata=_section_metadata(parsed.section, parsed.section_name),
                )
            )
        except Exception as error:
            LOGGER.exception("Fearless official detail fetch failed external_id=%s url=%s", external_id, url)
            failures.append(TWFearlessDetailFailure(external_id, url, title, str(error)))

    return TWFearlessFetchResult(
        announcements=announcements,
        failures=failures,
        listed_count=len(selected),
        pages_fetched=pages_fetched,
        list_total=list_total,
    )


def fetch_recent_announcements(
    limit: int,
    *,
    category: CategoryFilter = "all",
) -> list[Announcement]:
    """Fetch raw-compatible Taiwan official announcements without side effects."""
    return fetch_recent_announcements_with_failures(limit, category=category).announcements
