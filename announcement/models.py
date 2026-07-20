"""Source-neutral announcement data for the active official-site pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from crawler.models import Post


TW_FACEBOOK_SOURCE = "tw_facebook"  # Legacy archive identity only; never polled live.
TW_OFFICIAL = "tw_official"
CN_OFFICIAL = "cn_official"


def canonical_announcement_url(source: str, url: str) -> str:
    """Canonicalize a source URL without coupling to raw-post storage."""
    parsed = urlsplit(url.strip())
    if source != TW_FACEBOOK_SOURCE:
        return urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, "")
        )

    query = parse_qs(parsed.query)
    identity_query = {
        key: query[key][0]
        for key in ("story_fbid", "fbid", "id")
        if query.get(key)
    }
    return urlunsplit(
        ("https", "www.facebook.com", parsed.path.rstrip("/"), urlencode(identity_query), "")
    )


@dataclass(frozen=True, slots=True)
class Announcement:
    """One official notice, independent of Discord and database implementation."""

    source: str
    external_id: str
    url: str
    title: str
    category: str | None
    published_at: datetime | None
    content_html: str | None
    content_text: str
    images: tuple[str, ...]

    @property
    def canonical_url(self) -> str:
        return canonical_announcement_url(self.source, self.url)

    @property
    def content(self) -> str:
        """Compatibility alias for the legacy dispatcher payload shape."""
        return self.content_text

    @property
    def image_urls(self) -> tuple[str, ...]:
        """Compatibility alias for the legacy dispatcher payload shape."""
        return self.images

    @classmethod
    def from_facebook_post(cls, post: Post) -> "Announcement":
        """Create a retained legacy Facebook record without activating its crawler."""
        return cls(
            source=TW_FACEBOOK_SOURCE,
            external_id=post.post_id,
            url=post.url,
            title="",
            category=None,
            published_at=post.published_at,
            content_html=None,
            content_text=post.content,
            images=tuple(url for url in post.images if isinstance(url, str) and url),
        )

    def payload(self) -> dict[str, object]:
        return {
            "title": self.title,
            "category": self.category,
            "publish_time": self.published_at.strftime("%Y/%m/%d %H:%M") if self.published_at else None,
            "content": self.content_text,
            "image_urls": list(self.images),
            "post_url": self.canonical_url,
        }
