"""Stable announcement data used independently of the legacy knowledge database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from crawler.models import Post


TW_FACEBOOK_SOURCE = "tw_facebook"


def canonical_announcement_url(source: str, url: str) -> str:
    """Canonicalize a source URL without coupling to raw-post storage."""
    parsed = urlsplit(url.strip())
    if source != TW_FACEBOOK_SOURCE:
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))

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
    """One source announcement ready for independent Discord delivery."""

    source: str
    external_id: str
    canonical_url: str
    content: str
    image_urls: tuple[str, ...]
    published_at: datetime | None = None

    @classmethod
    def from_facebook_post(cls, post: Post) -> "Announcement":
        return cls(
            source=TW_FACEBOOK_SOURCE,
            external_id=post.post_id,
            canonical_url=canonical_announcement_url(TW_FACEBOOK_SOURCE, post.url),
            content=post.content,
            image_urls=tuple(url for url in post.images if isinstance(url, str) and url),
            published_at=post.published_at,
        )

    def payload(self) -> dict[str, object]:
        return {
            "publish_time": self.published_at.strftime("%Y/%m/%d %H:%M") if self.published_at else None,
            "content": self.content,
            "image_urls": list(self.image_urls),
            "post_url": self.canonical_url,
        }
