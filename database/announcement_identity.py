"""Stable identity helpers for Facebook announcement delivery."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit


def canonical_announcement_url(url: str) -> str:
    """Normalize a Facebook post URL without retaining tracking parameters."""
    parsed = urlsplit(urljoin("https://www.facebook.com", url.strip()))
    query = parse_qs(parsed.query)
    identity_query = {
        key: query[key][0]
        for key in ("story_fbid", "fbid", "id")
        if query.get(key)
    }
    return urlunsplit(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            urlencode(identity_query),
            "",
        )
    )
