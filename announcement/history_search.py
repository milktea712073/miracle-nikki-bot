"""Read-only historical-announcement search across active and retained SQLite stores."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from announcement.models import CN_OFFICIAL, TW_FACEBOOK_SOURCE, TW_OFFICIAL, canonical_announcement_url
from announcement.search import keyword_search_variants
from announcement.search_models import AnnouncementSearchPage, AnnouncementSearchResult
from announcement.state_store import AnnouncementStateStore, DEFAULT_STATE_DATABASE_PATH
from database.database import SQLITE_BUSY_TIMEOUT_MS, SQLITE_TIMEOUT_SECONDS


TW_REGION = "tw"
CN_REGION = "cn"
RAW_SOURCE_REGIONS = {
    "facebook": TW_REGION,
    "joybomb_archive": TW_REGION,
    "website": TW_REGION,
    "tw_official": TW_REGION,
    "tw_fearless_official": TW_REGION,
    "cn_official": CN_REGION,
    "cn_website": CN_REGION,
}
DEFAULT_CANDIDATE_LIMIT = 50


@dataclass(frozen=True, slots=True)
class AnnouncementSearchDiagnostics:
    """Read-only search details for tracing source selection and deduplication."""

    page: AnnouncementSearchPage
    candidates: tuple[AnnouncementSearchResult, ...]
    retained_keys: frozenset[tuple[str, int]]


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _matches_variants(value: str, variants: tuple[str, ...]) -> bool:
    folded = value.casefold()
    return any(variant.casefold() in folded for variant in variants)


def _metadata_title(metadata_json: object) -> str | None:
    if not isinstance(metadata_json, str) or not metadata_json.strip():
        return None
    try:
        metadata = json.loads(metadata_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    for key in ("title", "notice_title"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_nonempty_line(content: str) -> str:
    for line in content.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _raw_canonical_url(source: str, url: str) -> str:
    parsed = urlsplit(url)
    is_facebook_url = parsed.netloc.lower().endswith("facebook.com")
    announcement_source = TW_FACEBOOK_SOURCE if source == "facebook" and is_facebook_url else source
    return canonical_announcement_url(announcement_source, url)


def _canonical_url_key(url: str) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def _identity_source(source: str) -> str:
    return TW_FACEBOOK_SOURCE if source == "facebook" else source


def _normalize_title(value: str) -> str:
    return " ".join(value.split()).casefold()


def _published_sort_value(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _deduplication_keys(result: AnnouncementSearchResult) -> tuple[str, ...]:
    keys: list[str] = []
    canonical_url = _canonical_url_key(result.canonical_url)
    if canonical_url:
        keys.append(f"url:{canonical_url}")
    if result.external_id:
        keys.append(f"identity:{_identity_source(result.source)}:{result.external_id}")
    normalized_title = _normalize_title(result.title)
    if normalized_title and result.published_at:
        keys.append(f"title-date:{normalized_title}:{result.published_at.strip()}")
    return tuple(keys)


def _result_key(result: AnnouncementSearchResult) -> tuple[str, int]:
    return result.source_kind, result.source_record_id


def _priority(result: AnnouncementSearchResult) -> tuple[int, int]:
    return (0 if result.source_kind == "announcement" else 1, result.source_record_id)


def _ordered_unique(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def merge_search_results(
    candidates: tuple[AnnouncementSearchResult, ...],
) -> tuple[tuple[AnnouncementSearchResult, ...], frozenset[tuple[str, int]]]:
    """Deduplicate two stores while giving active announcement rows canonical priority."""
    groups: list[list[AnnouncementSearchResult]] = []
    key_to_group: dict[str, int] = {}

    for candidate in candidates:
        matching_groups = {key_to_group[key] for key in _deduplication_keys(candidate) if key in key_to_group}
        if not matching_groups:
            group_index = len(groups)
            groups.append([candidate])
        else:
            group_index = min(matching_groups)
            for other_index in sorted(matching_groups - {group_index}, reverse=True):
                groups[group_index].extend(groups[other_index])
                groups[other_index] = []
                for key, mapped_index in tuple(key_to_group.items()):
                    if mapped_index == other_index:
                        key_to_group[key] = group_index
            groups[group_index].append(candidate)
        for key in _deduplication_keys(candidate):
            key_to_group[key] = group_index

    merged: list[AnnouncementSearchResult] = []
    retained_keys: set[tuple[str, int]] = set()
    for group in groups:
        if not group:
            continue
        ordered = sorted(group, key=_priority)
        primary = ordered[0]
        retained_keys.add(_result_key(primary))
        title = next((result.title for result in ordered if result.title), "")
        content = next((result.content_text for result in ordered if result.content_text), "")
        canonical_url = next((result.canonical_url for result in ordered if result.canonical_url), "")
        published_at = next((result.published_at for result in ordered if result.published_at), None)
        images = _ordered_unique([url for result in ordered for url in result.image_urls])
        merged.append(
            AnnouncementSearchResult(
                source_kind=primary.source_kind,
                source_record_id=primary.source_record_id,
                source=primary.source,
                region=primary.region,
                external_id=primary.external_id,
                title=title,
                canonical_url=canonical_url,
                published_at=published_at,
                content_text=content,
                image_urls=images,
            )
        )

    merged.sort(
        key=lambda result: (
            _published_sort_value(result.published_at) is not None,
            _published_sort_value(result.published_at) or 0.0,
            result.source_record_id,
        ),
        reverse=True,
    )
    return tuple(merged), frozenset(retained_keys)


class AnnouncementHistorySearchService:
    """Search active and archived notices from the standalone announcement state database."""

    def __init__(
        self,
        *,
        state_database_path: Path = DEFAULT_STATE_DATABASE_PATH,
    ) -> None:
        self.state_database_path = state_database_path

    @staticmethod
    def _desired_region(source: str | None) -> str | None:
        if source == TW_OFFICIAL:
            return TW_REGION
        if source == CN_OFFICIAL:
            return CN_REGION
        return None

    def _search_state_candidates(
        self,
        keyword: str,
        *,
        source: str | None,
        candidate_limit: int,
    ) -> tuple[tuple[AnnouncementSearchResult, ...], bool]:
        if not self.state_database_path.exists():
            return (), False
        page = AnnouncementStateStore(self.state_database_path, initialize=False).search_announcements(
            keyword,
            source=source,
            limit=candidate_limit,
        )
        return page.results, page.has_more

    def _search_raw_candidates(
        self,
        keyword: str,
        *,
        desired_region: str | None,
        candidate_limit: int,
    ) -> tuple[tuple[AnnouncementSearchResult, ...], bool]:
        if not self.state_database_path.exists():
            return (), False
        source_regions = {
            source: region
            for source, region in RAW_SOURCE_REGIONS.items()
            if desired_region is None or region == desired_region
        }
        if not source_regions:
            return (), False
        variants = keyword_search_variants(keyword)
        match_clauses: list[str] = []
        match_parameters: list[str] = []
        for variant in variants:
            pattern = f"%{_escape_like_literal(variant)}%"
            match_clauses.append("(content LIKE ? ESCAPE '\\' OR metadata_json LIKE ? ESCAPE '\\')")
            match_parameters.extend((pattern, pattern))
        source_placeholders = ", ".join("?" for _ in source_regions)
        database_uri = f"file:{self.state_database_path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True, timeout=SQLITE_TIMEOUT_SECONDS)
        connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        try:
            raw_posts_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'raw_posts'"
            ).fetchone()
            if raw_posts_exists is None:
                return (), False
            rows = connection.execute(
                f"""
                SELECT id, source, source_post_id, url, content, published_at, metadata_json
                FROM raw_posts
                WHERE source IN ({source_placeholders})
                  AND ({' OR '.join(match_clauses)})
                ORDER BY published_at IS NULL ASC, published_at DESC, id DESC
                LIMIT ?
                """,
                [*source_regions, *match_parameters, candidate_limit + 1],
            ).fetchall()
            candidate_rows = rows[:candidate_limit]
            images_by_raw_post_id: dict[int, list[str]] = {}
            if candidate_rows:
                raw_ids = [int(row[0]) for row in candidate_rows]
                image_placeholders = ", ".join("?" for _ in raw_ids)
                for raw_post_id, image_url in connection.execute(
                    f"""
                    SELECT raw_post_id, image_url
                    FROM raw_post_images
                    WHERE raw_post_id IN ({image_placeholders})
                    ORDER BY raw_post_id ASC, position ASC, id ASC
                    """,
                    raw_ids,
                ):
                    images_by_raw_post_id.setdefault(int(raw_post_id), []).append(str(image_url))
        finally:
            connection.close()

        results: list[AnnouncementSearchResult] = []
        for raw_post_id, source, source_post_id, url, content, published_at, metadata_json in candidate_rows:
            source_text = str(source)
            content_text = str(content or "")
            title = _metadata_title(metadata_json) or _first_nonempty_line(content_text)
            if not (_matches_variants(title, variants) or _matches_variants(content_text, variants)):
                continue
            results.append(
                AnnouncementSearchResult(
                    source_kind="raw_post",
                    source_record_id=int(raw_post_id),
                    source=source_text,
                    region=source_regions[source_text],
                    external_id=str(source_post_id),
                    title=title,
                    canonical_url=_raw_canonical_url(source_text, str(url)),
                    published_at=str(published_at) if published_at is not None else None,
                    content_text=content_text,
                    image_urls=tuple(images_by_raw_post_id.get(int(raw_post_id), [])),
                )
            )
        return tuple(results), len(rows) > candidate_limit

    def diagnose(
        self,
        keyword: str,
        *,
        source: str | None = None,
        limit: int = 10,
    ) -> AnnouncementSearchDiagnostics:
        normalized_keyword = keyword.strip()
        if not normalized_keyword:
            raise ValueError("keyword must not be blank")
        if limit < 1:
            raise ValueError("limit must be positive")
        desired_region = self._desired_region(source)
        state_source = TW_OFFICIAL if desired_region == TW_REGION else CN_OFFICIAL if desired_region == CN_REGION else None
        state_candidates, state_has_more = self._search_state_candidates(
            normalized_keyword,
            source=state_source,
            candidate_limit=DEFAULT_CANDIDATE_LIMIT,
        )
        raw_candidates, raw_has_more = self._search_raw_candidates(
            normalized_keyword,
            desired_region=desired_region,
            candidate_limit=DEFAULT_CANDIDATE_LIMIT,
        )
        merged, retained_keys = merge_search_results((*state_candidates, *raw_candidates))
        return AnnouncementSearchDiagnostics(
            page=AnnouncementSearchPage(
                results=merged[:limit],
                has_more=len(merged) > limit or raw_has_more or state_has_more,
            ),
            candidates=(*state_candidates, *raw_candidates),
            retained_keys=retained_keys,
        )

    def search(
        self,
        keyword: str,
        *,
        source: str | None = None,
        limit: int = 10,
    ) -> AnnouncementSearchPage:
        return self.diagnose(keyword, source=source, limit=limit).page
