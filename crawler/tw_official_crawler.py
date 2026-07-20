"""Taiwan official-site source adapter for the active announcement pipeline.

Parsing is deliberately delegated to the existing website spike implementation
so the source has one JSON/Next.js parsing path and no Discord or SQLite code.
"""

from __future__ import annotations

from announcement.models import Announcement, TW_OFFICIAL, canonical_announcement_url
from crawler.website_crawler import crawl_recent_announcements


SECTION_CATEGORIES = {
    1: "活動",
    2: "新聞",
    3: "客服",
    11: "系統",
    21: "系統",
}


def fetch_recent_announcements(limit: int) -> list[Announcement]:
    """Fetch current Taiwan notices without writing state or touching Discord."""
    result = crawl_recent_announcements(limit)
    return [
        Announcement(
            source=TW_OFFICIAL,
            external_id=item.source_post_id,
            url=canonical_announcement_url(TW_OFFICIAL, item.url),
            title=item.title,
            category=SECTION_CATEGORIES.get(item.section),
            published_at=_parse_datetime(item.publish_time),
            content_html=item.content_html,
            content_text=item.content_text,
            images=tuple(item.image_urls),
        )
        for item in result.announcements
    ]


def _parse_datetime(value: str | None):
    if value is None:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value)
