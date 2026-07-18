"""Read-only Wayback Machine spike for the retired JoyBomb notice website.

This experiment intentionally does not import database or queue modules.  It
only indexes archived notice URLs, samples a bounded set of static snapshots,
and writes local reports for a later source-quality decision.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
ARCHIVE_ROOT = "https://web.archive.org/web"
JOYBOMB_HOST = "nu3.joybomb.com.tw"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"
DEFAULT_FROM_YEAR = 2017
DEFAULT_TO_YEAR = 2024
MAX_SAMPLE_COUNT = 24
REQUEST_HEADERS = {"User-Agent": "MiracleNikkiJoyBombArchiveSpike/1.0"}
PATH_NOTICE_ID_PATTERN = re.compile(
    r"/(?:notice|mobile)/noticecontent/(?P<section>[^/]+)/(?P<notice_id>\d+)(?:/.*)?$", re.I
)
WAYBACK_REWRITTEN_URL_PATTERN = re.compile(
    r"^https?://web\.archive\.org/web/\d+(?:[a-z_]+)?/(https?://.+)$", re.I
)
DATE_PATTERN = re.compile(r"(20\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})")
_DATE_ONLY_NODE_PATTERN = re.compile(
    r"^\s*20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}(?:\s+\d{1,2}:\d{2})?\s*$"
)
_PAGE_CHROME_TEXT = frozenset({"返回公告列表", "回公告列表", "返回列表", "公告列表"})
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
CDX_URL_PATTERNS = (
    # CDX wildcard behaviour differs for path and query-style URL families;
    # retain the original path wildcard while adding the legacy query wildcard.
    f"{JOYBOMB_HOST}/notice/noticecontent/*",
    f"{JOYBOMB_HOST}/notice/noticecontent*",
    f"{JOYBOMB_HOST}/mobile/noticecontent/*",
    f"{JOYBOMB_HOST}/mobile/noticecontent*",
    f"{JOYBOMB_HOST}/notice/noticelist*",
    f"{JOYBOMB_HOST}/mobile/noticelist*",
    f"{JOYBOMB_HOST}/index/index2*",
)


class JoyBombArchiveError(RuntimeError):
    """Raised when a Wayback response cannot safely be used for this spike."""


@dataclass(frozen=True, slots=True)
class CdxSnapshot:
    timestamp: str
    original_url: str
    status_code: str
    mimetype: str
    digest: str
    query_pattern: str = ""

    @property
    def year(self) -> int:
        return int(self.timestamp[:4])


@dataclass(frozen=True, slots=True)
class ArchiveImage:
    original_url: str
    archive_url: str
    status: str


@dataclass(frozen=True, slots=True)
class JoyBombArchiveNotice:
    archive_timestamp: str
    original_url: str
    archive_url: str
    notice_id: str
    title: str | None
    published_at: str | None
    content_html: str
    content_text: str
    image_original_urls: list[str]
    image_archive_urls: list[str]
    template_signature: str
    parse_warnings: list[str]
    images: list[ArchiveImage] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CdxIndexResult:
    snapshots: list[CdxSnapshot]
    query_failures: dict[str, str]


def parse_notice_identity(url: str) -> tuple[str, str] | None:
    """Return the stable JoyBomb ``(section, notice_id)`` for either URL family."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.")
    if host != JOYBOMB_HOST:
        return None
    path_match = PATH_NOTICE_ID_PATTERN.search(parts.path)
    if path_match:
        return path_match.group("section"), path_match.group("notice_id")
    normalized_path = parts.path.rstrip("/").lower()
    if normalized_path not in {"/notice/noticecontent", "/mobile/noticecontent"}:
        return None
    query = {key.lower(): values for key, values in parse_qs(parts.query).items()}
    section = query.get("n", [None])[0]
    notice_id = query.get("k", [None])[0]
    if not section or not notice_id or not str(notice_id).isdigit():
        return None
    return str(section), str(notice_id)


def canonicalize_original_url(url: str) -> str | None:
    """Canonicalize retired-site URLs so protocol, port, and query variants collapse."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.")
    if host != JOYBOMB_HOST:
        return None
    identity = parse_notice_identity(url)
    if identity is not None:
        section, notice_id = identity
        # Legacy desktop/mobile query URLs and later path URLs are aliases of the
        # same notice when their section and K/id values match.
        return f"https://{JOYBOMB_HOST}/notice/noticecontent?N={section}&K={notice_id}"
    path = re.sub(r"/{2,}", "/", parts.path or "/").rstrip("/") or "/"
    # Non-detail query values are presentation or list filters, not identity.
    return urlunsplit(("https", host, path, "", ""))


def parse_notice_id(url: str) -> str | None:
    """Return the stable numeric notice identifier, logging unusual detail paths."""
    identity = parse_notice_identity(url)
    if identity is None:
        return None
    return identity[1]


def archive_url_for(timestamp: str, original_url: str) -> str:
    return f"{ARCHIVE_ROOT}/{timestamp}/{original_url}"


def archive_image_url_for(timestamp: str, original_url: str) -> str:
    return f"{ARCHIVE_ROOT}/{timestamp}id_/{original_url}"


def unwrap_wayback_url(url: str) -> str:
    """Recover the original URL when Wayback has rewritten an HTML attribute."""
    match = WAYBACK_REWRITTEN_URL_PATTERN.match(url)
    return match.group(1) if match else url


def parse_cdx_payload(payload: object, *, query_pattern: str = "") -> list[CdxSnapshot]:
    """Parse CDX JSON rows, ignoring malformed rows instead of guessing fields."""
    if not isinstance(payload, list) or not payload:
        return []
    header = payload[0]
    if not isinstance(header, list):
        raise JoyBombArchiveError("CDX JSON is missing its header row")
    index = {str(name): position for position, name in enumerate(header)}
    required = {"timestamp", "original", "statuscode", "mimetype", "digest"}
    if not required.issubset(index):
        raise JoyBombArchiveError("CDX JSON is missing required columns")

    snapshots: list[CdxSnapshot] = []
    for raw_row in payload[1:]:
        if not isinstance(raw_row, list):
            continue
        try:
            snapshots.append(
                CdxSnapshot(
                    timestamp=str(raw_row[index["timestamp"]]),
                    original_url=str(raw_row[index["original"]]),
                    status_code=str(raw_row[index["statuscode"]]),
                    mimetype=str(raw_row[index["mimetype"]]),
                    digest=str(raw_row[index["digest"]]),
                    query_pattern=query_pattern,
                )
            )
        except IndexError:
            LOGGER.warning("Ignoring truncated CDX row")
    return snapshots


def select_notice_snapshots(snapshots: Iterable[CdxSnapshot]) -> list[CdxSnapshot]:
    """Select one earliest valid HTML capture for each canonical notice URL."""
    selected: dict[str, CdxSnapshot] = {}
    for snapshot in sorted(snapshots, key=lambda row: (row.timestamp, row.original_url)):
        if snapshot.status_code != "200" or snapshot.mimetype.lower() != "text/html":
            continue
        canonical = canonicalize_original_url(snapshot.original_url)
        if canonical is None or parse_notice_id(snapshot.original_url) is None:
            continue
        selected.setdefault(canonical, snapshot)
    return list(selected.values())


def index_summary(snapshots: Sequence[CdxSnapshot]) -> dict[str, Any]:
    """Return deterministic index quality metrics without fetching detail pages."""
    detail_rows = [row for row in snapshots if parse_notice_id(row.original_url) is not None]
    canonical_urls = [canonicalize_original_url(row.original_url) for row in detail_rows]
    canonical_urls = [url for url in canonical_urls if url is not None]
    variations = Counter()
    for row in detail_rows:
        parts = urlsplit(row.original_url)
        if parts.scheme == "http":
            variations["http"] += 1
        if parts.scheme == "https":
            variations["https"] += 1
        if parts.port == 80:
            variations["port_80"] += 1
        if parts.query:
            variations["query"] += 1
    timestamps = sorted(row.timestamp for row in detail_rows)
    capture_years = Counter(row.timestamp[:4] for row in detail_rows if len(row.timestamp) >= 4)
    unique_notice_capture_years = Counter(
        row.timestamp[:4] for row in select_notice_snapshots(detail_rows) if len(row.timestamp) >= 4
    )
    unparseable = sorted(
        {row.original_url for row in snapshots if "/notice/noticecontent/" in row.original_url and parse_notice_id(row.original_url) is None}
    )
    return {
        "cdx_index_total": len(snapshots),
        "original_url_total": len({row.original_url for row in snapshots}),
        "detail_snapshot_count": len(detail_rows),
        "unique_detail_url_count": len(set(canonical_urls)),
        "collapsed_duplicate_count": len(detail_rows) - len(set(canonical_urls)),
        "earliest_timestamp": timestamps[0] if timestamps else None,
        "latest_timestamp": timestamps[-1] if timestamps else None,
        "capture_year_distribution": dict(sorted(capture_years.items())),
        "unique_notice_capture_year_distribution": dict(sorted(unique_notice_capture_years.items())),
        "url_variations": dict(sorted(variations.items())),
        "unparseable_detail_urls": unparseable,
    }


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: float,
    request_delay: float,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    follow_redirects: bool = True,
    stream: bool = False,
) -> requests.Response:
    """Request a public archive URL with bounded retry for transient failures."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        response: requests.Response | None = None
        try:
            response = session.request(
                method,
                url,
                headers=REQUEST_HEADERS,
                timeout=timeout,
                allow_redirects=follow_redirects,
                stream=stream,
            )
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt == attempts - 1:
                return response
            last_error = JoyBombArchiveError(f"HTTP {response.status_code}")
        except requests.RequestException as error:
            last_error = error
            if attempt == attempts - 1:
                break
        retry_after = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
        try:
            retry_after_seconds = float(retry_after) if retry_after else 0.0
        except ValueError:
            retry_after_seconds = 0.0
        sleep(max(request_delay * (2**attempt), retry_after_seconds))
    raise JoyBombArchiveError(f"Wayback request failed: {url}: {last_error}") from last_error


def fetch_cdx_index(
    *,
    from_year: int,
    to_year: int,
    timeout: float,
    request_delay: float,
    session: requests.Session | None = None,
) -> CdxIndexResult:
    """Fetch all known JoyBomb URL families, recording partial CDX failures."""
    active_session = session or requests.Session()
    snapshots: list[CdxSnapshot] = []
    failures: dict[str, str] = {}
    for pattern in CDX_URL_PATTERNS:
        params: list[tuple[str, str]] = [
            ("url", pattern),
            ("output", "json"),
            ("fl", "timestamp,original,statuscode,mimetype,digest"),
            ("filter", "statuscode:200"),
            ("filter", "mimetype:text/html"),
            ("collapse", "digest"),
            ("from", str(from_year)),
            ("to", str(to_year)),
        ]
        try:
            response = request_with_retry(
                active_session,
                "GET",
                f"{CDX_ENDPOINT}?" + "&".join(f"{key}={value}" for key, value in params),
                timeout=timeout,
                request_delay=request_delay,
            )
            if response.status_code != 200:
                raise JoyBombArchiveError(f"CDX returned HTTP {response.status_code}")
            snapshots.extend(parse_cdx_payload(response.json(), query_pattern=pattern))
        except (JoyBombArchiveError, ValueError) as error:
            failures[pattern] = type(error).__name__
            LOGGER.warning("CDX query failed for %s: %s", pattern, type(error).__name__)
    if not snapshots and failures:
        raise JoyBombArchiveError("All JoyBomb CDX URL family queries failed")
    return CdxIndexResult(snapshots=snapshots, query_failures=failures)


def select_samples_by_year(snapshots: Sequence[CdxSnapshot], sample_per_year: int) -> list[CdxSnapshot]:
    """Select a bounded, deterministic earliest sample set for each archive year."""
    if sample_per_year < 1:
        raise ValueError("sample_per_year must be at least 1")
    selected: list[CdxSnapshot] = []
    for year in sorted({snapshot.year for snapshot in snapshots}):
        rows = [snapshot for snapshot in snapshots if snapshot.year == year]
        selected.extend(rows[:sample_per_year])
        if len(selected) >= MAX_SAMPLE_COUNT:
            break
    return selected[:MAX_SAMPLE_COUNT]


def _clean_document(document: str) -> BeautifulSoup:
    soup = BeautifulSoup(document, "html.parser")
    for selector in ("#wm-ipp", "#wm-ipp-base", ".wm-ipp", "#donato", "script", "style", "nav", "footer", "aside"):
        for node in soup.select(selector):
            node.decompose()
    return soup


def _has_class_token(node: Tag, *tokens: str) -> bool:
    classes = " ".join(node.get("class", [])) + " " + str(node.get("id", ""))
    normalized = classes.lower().replace("_", "-")
    return any(token in normalized for token in tokens)


def _find_content_root(soup: BeautifulSoup) -> tuple[Tag | None, str]:
    for node in soup.find_all(["article", "div", "section"]):
        if _has_class_token(node, "notice-content", "noticecontent", "content-bg"):
            return node, "joybomb_notice_v1"
    for node in soup.find_all(["article", "div", "section"]):
        if _has_class_token(node, "article-content", "notice-body"):
            return node, "joybomb_notice_v2"
    return None, "unknown"


def _first_text(nodes: Iterable[Tag]) -> str | None:
    for node in nodes:
        value = node.get_text(" ", strip=True)
        if value:
            return value
    return None


def _extract_notice_title(container: Tag) -> str | None:
    """Prefer a concrete title child over a metadata-bearing title wrapper."""
    for selector in (
        ".noticeTitle h5, .notice-title h5",
        ".noticeTitle h1, .notice-title h1",
        ".noticeTitle h2, .notice-title h2",
        "h1, h2",
        ".notice-title, .noticeTitle",
    ):
        title = _first_text(container.select(selector))
        if title:
            return title
    return None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = DATE_PATTERN.search(value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return datetime(year, month, day, tzinfo=UTC).isoformat()


def _clean_notice_body_root(content_root: Tag, *, title: str | None) -> Tag:
    """Return a cloned content root with only clear notice chrome removed.

    ``content_html`` remains the original archived fragment for later audit.  This
    helper is intentionally limited to title/date nodes and explicit navigation
    or footer markup, so dates and prose inside the actual notice body survive.
    """
    body_root = copy.copy(content_root)
    normalized_title = title.strip() if title else None

    for node in list(body_root.select("h1, h2, .notice-title, .noticeTitle")):
        if normalized_title and node.get_text(" ", strip=True) == normalized_title:
            node.decompose()

    for node in list(body_root.select("time, .notice-date, .noticeDate")):
        node.decompose()

    for node in list(body_root.select(".date, .time")):
        if _DATE_ONLY_NODE_PATTERN.fullmatch(node.get_text(" ", strip=True)):
            node.decompose()

    for node in list(body_root.find_all(["span", "div", "p"])):
        if node.find(True) is None and _DATE_ONLY_NODE_PATTERN.fullmatch(node.get_text(" ", strip=True)):
            node.decompose()

    for node in list(body_root.find_all(["a", "button", "span", "div", "p"])):
        # A previously removed ancestor leaves already-enumerated descendants
        # as inert BeautifulSoup tags.
        if node.attrs is None:
            continue
        text = node.get_text(" ", strip=True)
        if text in _PAGE_CHROME_TEXT or _has_class_token(
            node,
            "notice-footer",
            "notice-nav",
            "notice-list",
            "return-list",
            "back-list",
            "breadcrumb",
            "page-footer",
        ):
            node.decompose()
    return body_root


def parse_notice_document(snapshot: CdxSnapshot, document: str) -> JoyBombArchiveNotice:
    """Parse a static archived notice, declining to use whole-page text as fallback."""
    notice_id = parse_notice_id(snapshot.original_url)
    if notice_id is None:
        raise JoyBombArchiveError(f"Not a recognized JoyBomb detail URL: {snapshot.original_url}")
    soup = _clean_document(document)
    content_root, template_signature = _find_content_root(soup)
    warnings: list[str] = []
    if content_root is None:
        warnings.append("unknown_template: content root not found")
        return JoyBombArchiveNotice(
            archive_timestamp=snapshot.timestamp,
            original_url=snapshot.original_url,
            archive_url=archive_url_for(snapshot.timestamp, snapshot.original_url),
            notice_id=notice_id,
            title=None,
            published_at=None,
            content_html="",
            content_text="",
            image_original_urls=[],
            image_archive_urls=[],
            template_signature=template_signature,
            parse_warnings=warnings,
        )

    container = content_root.parent if isinstance(content_root.parent, Tag) else content_root
    title = _extract_notice_title(container)
    date_text = _first_text(container.select("time, .notice-date, .noticeDate, .date, .time"))
    if not date_text:
        date_text = container.get_text(" ", strip=True)
    published_at = _parse_date(date_text)
    if published_at is None:
        warnings.append("published_at_not_found")
    image_original_urls: list[str] = []
    for image in content_root.find_all("img"):
        src = image.get("src")
        if not isinstance(src, str) or not src.strip() or src.startswith("data:"):
            continue
        absolute = unwrap_wayback_url(urljoin(snapshot.original_url, src.strip()))
        if absolute not in image_original_urls:
            image_original_urls.append(absolute)
    content_text = _clean_notice_body_root(content_root, title=title).get_text("\n", strip=True)
    return JoyBombArchiveNotice(
        archive_timestamp=snapshot.timestamp,
        original_url=snapshot.original_url,
        archive_url=archive_url_for(snapshot.timestamp, snapshot.original_url),
        notice_id=notice_id,
        title=title,
        published_at=published_at,
        content_html=str(content_root),
        content_text=content_text,
        image_original_urls=image_original_urls,
        image_archive_urls=[archive_image_url_for(snapshot.timestamp, image) for image in image_original_urls],
        template_signature=template_signature,
        parse_warnings=warnings,
    )


def check_archived_image(
    session: requests.Session,
    archive_url: str,
    *,
    timeout: float,
    request_delay: float,
) -> str:
    """Classify image availability without downloading the response body."""
    try:
        response = request_with_retry(
            session,
            "HEAD",
            archive_url,
            timeout=timeout,
            request_delay=request_delay,
            follow_redirects=False,
            stream=True,
        )
        if response.status_code in {405, 501}:
            response = request_with_retry(
                session,
                "GET",
                archive_url,
                timeout=timeout,
                request_delay=request_delay,
                follow_redirects=False,
                stream=True,
            )
    except JoyBombArchiveError:
        return "blocked"
    if 200 <= response.status_code < 300:
        return "archived"
    if 300 <= response.status_code < 400:
        return "redirect"
    if response.status_code == 404:
        return "missing"
    return "invalid"


def _image_status_counts(notices: Sequence[JoyBombArchiveNotice]) -> dict[str, int]:
    counts = Counter(image.status for notice in notices for image in notice.images)
    return {status: counts.get(status, 0) for status in ("archived", "missing", "redirect", "blocked", "invalid")}


def integration_assessment(index: Mapping[str, Any], notices: Sequence[JoyBombArchiveNotice]) -> dict[str, Any]:
    """Make an explicit non-production recommendation from bounded spike evidence."""
    sampled = len(notices)
    parsed = sum(bool(notice.content_text) for notice in notices)
    unknown_templates = sum(notice.template_signature == "unknown" for notice in notices)
    image_statuses = _image_status_counts(notices)
    checked_images = sum(image_statuses.values())
    archived_images = image_statuses["archived"]
    return {
        "decision": "defer_production_integration",
        "reason": "This is a bounded archival sample, not a complete or continuously available official feed.",
        "sample_parse_success_rate": (parsed / sampled) if sampled else None,
        "unknown_template_count": unknown_templates,
        "checked_image_count": checked_images,
        "archived_image_success_rate": (archived_images / checked_images) if checked_images else None,
        "coverage_note": (
            "CDX captures are available only for the years reported by the index; missing years must not be treated as no announcements."
        ),
        "recommended_next_step": "Keep this crawler read-only until a broader template and image-availability audit is complete.",
    }


def crawl_samples(
    snapshots: Sequence[CdxSnapshot],
    *,
    timeout: float,
    request_delay: float,
    session: requests.Session | None = None,
    check_images: bool = True,
) -> list[JoyBombArchiveNotice]:
    """Fetch and parse selected static snapshots only; no application writes occur."""
    active_session = session or requests.Session()
    results: list[JoyBombArchiveNotice] = []
    for snapshot in snapshots:
        try:
            response = request_with_retry(
                active_session,
                "GET",
                archive_url_for(snapshot.timestamp, snapshot.original_url),
                timeout=timeout,
                request_delay=request_delay,
            )
        except JoyBombArchiveError as error:
            notice_id = parse_notice_id(snapshot.original_url)
            if notice_id is None:
                LOGGER.warning("Skipping invalid archived notice URL: %s", snapshot.original_url)
                continue
            LOGGER.warning("Archived notice request failed; recording sample failure: %s", snapshot.original_url)
            results.append(
                JoyBombArchiveNotice(
                    archive_timestamp=snapshot.timestamp,
                    original_url=snapshot.original_url,
                    archive_url=archive_url_for(snapshot.timestamp, snapshot.original_url),
                    notice_id=notice_id,
                    title=None,
                    published_at=None,
                    content_html="",
                    content_text="",
                    image_original_urls=[],
                    image_archive_urls=[],
                    template_signature="request_failed",
                    parse_warnings=[f"request_failed: {type(error).__name__}"],
                )
            )
            continue
        if response.status_code != 200:
            LOGGER.warning("Skipping archived notice with HTTP %s: %s", response.status_code, snapshot.original_url)
            continue
        if isinstance(response, requests.Response):
            response.encoding = response.apparent_encoding or response.encoding
        notice = parse_notice_document(snapshot, response.text)
        if check_images:
            images = [
                ArchiveImage(original, archived, check_archived_image(active_session, archived, timeout=timeout, request_delay=request_delay))
                for original, archived in zip(notice.image_original_urls, notice.image_archive_urls, strict=True)
            ]
            notice = JoyBombArchiveNotice(**{**asdict(notice), "images": images})
        results.append(notice)
        if request_delay:
            time.sleep(request_delay)
    return results


def write_reports(
    *,
    output_dir: Path,
    snapshots: Sequence[CdxSnapshot],
    notices: Sequence[JoyBombArchiveNotice],
    query_failures: Mapping[str, str] | None = None,
) -> None:
    """Write concise machine-readable and human-readable reports for the spike."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index = index_summary(snapshots)
    failures = dict(query_failures or {})
    published_years = Counter(
        notice.published_at[:4] for notice in notices if notice.published_at is not None
    )
    index["sampled_published_year_distribution"] = dict(sorted(published_years.items()))
    captured_years = set(index["capture_year_distribution"])
    index["unverified_query_patterns"] = failures
    index["unverified_capture_years"] = [
        year for year in range(DEFAULT_FROM_YEAR, DEFAULT_TO_YEAR + 1) if str(year) not in captured_years and failures
    ]
    template_counts = Counter(notice.template_signature for notice in notices)
    parsed = sum(1 for notice in notices if notice.content_text)
    image_count = sum(len(notice.image_original_urls) for notice in notices)
    image_statuses = _image_status_counts(notices)
    assessment = integration_assessment(index, notices)
    (output_dir / "joybomb_archive_index_report.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sample_rows = [asdict(notice) for notice in notices]
    (output_dir / "joybomb_archive_sample_report.json").write_text(
        json.dumps(sample_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# JoyBomb Wayback Archive Spike",
        "",
        f"- CDX detail captures: {index['detail_snapshot_count']}",
        f"- Unique detail URLs: {index['unique_detail_url_count']}",
        f"- Sampled notices: {len(notices)}",
        f"- Parsed notices: {parsed}",
        f"- Images found: {image_count}",
        f"- Image availability: {image_statuses}",
        f"- Templates: {dict(sorted(template_counts.items()))}",
        f"- Published year distribution (sampled pages only): {dict(sorted(published_years.items()))}",
        f"- Unverified CDX URL patterns: {len(failures)}",
        "",
        "## Formal Integration Decision",
        "",
        "**Decision: defer production integration.**",
        "",
        f"- Reason: {assessment['reason']}",
        f"- Content parse success: {parsed}/{len(notices)}",
        f"- Unknown templates: {assessment['unknown_template_count']}",
        f"- Image archive checks: {assessment['checked_image_count']} (archived: {image_statuses['archived']})",
        f"- Coverage: {assessment['coverage_note']}",
        f"- Next step: {assessment['recommended_next_step']}",
    ]
    (output_dir / "joybomb_archive_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only JoyBomb Wayback archive spike")
    parser.add_argument("--analyze-index", action="store_true", help="Only fetch and analyze the CDX index")
    parser.add_argument("--from-year", type=int, default=DEFAULT_FROM_YEAR)
    parser.add_argument("--to-year", type=int, default=DEFAULT_TO_YEAR)
    parser.add_argument("--sample-per-year", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-image-check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _build_argument_parser().parse_args(argv)
    if args.from_year > args.to_year:
        raise SystemExit("--from-year cannot be later than --to-year")
    snapshots = fetch_cdx_index(
        from_year=args.from_year,
        to_year=args.to_year,
        timeout=args.timeout,
        request_delay=args.request_delay,
    )
    selected = select_notice_snapshots(snapshots.snapshots)
    notices: list[JoyBombArchiveNotice] = []
    if not args.analyze_index:
        samples = select_samples_by_year(selected, args.sample_per_year)
        notices = crawl_samples(
            samples,
            timeout=args.timeout,
            request_delay=args.request_delay,
            check_images=not args.skip_image_check,
        )
    write_reports(
        output_dir=args.output_dir,
        snapshots=snapshots.snapshots,
        notices=notices,
        query_failures=snapshots.query_failures,
    )
    LOGGER.info("CDX rows=%s unique notices=%s sampled=%s", len(snapshots.snapshots), len(selected), len(notices))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
