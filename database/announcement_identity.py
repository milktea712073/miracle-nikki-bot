"""Stable identity helpers for Facebook announcement delivery."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit


def canonical_announcement_url(url: str) -> str:
    """Normalize Facebook post URLs while preserving non-Facebook source URLs."""
    parsed = urlsplit(urljoin("https://www.facebook.com", url.strip()))
    facebook_hosts = {"facebook.com", "www.facebook.com", "m.facebook.com"}
    if parsed.netloc.lower() not in facebook_hosts:
        # This helper is also used by the source-agnostic raw layer.  Query
        # parameters can be a stable identifier for other sources (for example
        # JoyBomb's legacy N/K notice identity), so only Facebook URLs lose
        # non-identity query parameters.
        return urlunsplit(
            (
                parsed.scheme.lower() or "https",
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                parsed.query,
                "",
            )
        )
    query = parse_qs(parsed.query)
    identity_query = {
        key: query[key][0]
        for key in ("story_fbid", "fbid", "id")
        if query.get(key)
    }
    return urlunsplit(
        (
            "https",
            "www.facebook.com",
            parsed.path.rstrip("/"),
            urlencode(identity_query),
            "",
        )
    )
