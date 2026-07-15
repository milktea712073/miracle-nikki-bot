"""Independent spike crawler for Miracle Nikki's official website announcements.

This module deliberately does not write ``raw_posts``, enqueue announcements, or
invoke the announcement parser.  It only produces JSON reports for evaluating the
official website as a possible future source.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEBSITE_BASE_URL = "https://nu3.fearlessgames.net"
NEWS_LIST_URL = f"{WEBSITE_BASE_URL}/api/news"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "website_crawler_report.json"
DEFAULT_COMPARISON_PATH = PROJECT_ROOT / "data" / "website_facebook_comparison.json"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "database" / "database.db"
SECTION_NAMES = {
    1: "活動",
    2: "新聞",
    3: "客服",
    11: "系統",
    21: "系統",
}
REQUEST_HEADERS = {"User-Agent": "MiracleNikkiDatabaseWebsiteSpike/1.0"}

JsonFetcher = Callable[[str], object]
TextFetcher = Callable[[str], str]


class WebsiteCrawlerError(RuntimeError):
    """Raised when an official website response cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class WebsiteAnnouncement:
    """One official website announcement parsed without touching application data."""

    source_post_id: str
    url: str
    title: str
    section: int
    section_name: str
    publish_time: str | None
    content_text: str
    content_html: str
    image_urls: list[str]
    source: str = "website"


@dataclass(frozen=True, slots=True)
class WebsiteDetailFailure:
    """A list item whose detail page could not be parsed."""

    source_post_id: str
    url: str
    title: str
    error: str


@dataclass(frozen=True, slots=True)
class WebsiteCrawlResult:
    """Successful details and explicit failures from one crawl."""

    announcements: list[WebsiteAnnouncement]
    failures: list[WebsiteDetailFailure]
    listed_count: int


def build_news_url(news_id: str | int) -> str:
    """Return the stable detail URL for a numeric official news identifier."""
    return f"{WEBSITE_BASE_URL}/news/{parse_numeric_news_id(str(news_id))}"


def parse_numeric_news_id(value: str) -> str:
    """Extract and validate a numeric ``/news/<id>`` identifier."""
    match = re.fullmatch(r"(?:https?://[^/]+)?/?news/(\d+)/?", value.strip())
    if match:
        return match.group(1)
    if value.strip().isdigit():
        return value.strip()
    raise WebsiteCrawlerError(f"Invalid numeric news id: {value!r}")


def fetch_json(url: str) -> object:
    """Fetch JSON from the official website without requiring Playwright."""
    try:
        with urlopen(Request(url, headers=REQUEST_HEADERS), timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WebsiteCrawlerError(f"Could not fetch JSON from {url}: {error}") from error


def fetch_text(url: str) -> str:
    """Fetch one official news detail document."""
    try:
        with urlopen(Request(url, headers=REQUEST_HEADERS), timeout=30) as response:
            return response.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise WebsiteCrawlerError(f"Could not fetch detail page {url}: {error}") from error


def fetch_news_list(limit: int, *, json_fetcher: JsonFetcher = fetch_json) -> list[Mapping[str, object]]:
    """Read the current official list API, which is the homepage's data source."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    payload = json_fetcher(f"{NEWS_LIST_URL}?sectionType=0&offset=0&limit={limit}")
    if not isinstance(payload, Mapping) or payload.get("ret") != 0:
        raise WebsiteCrawlerError("Official news list response has an unexpected result code")

    outer_data = payload.get("data")
    if not isinstance(outer_data, Mapping):
        raise WebsiteCrawlerError("Official news list response is missing data")
    entries = outer_data.get("data")
    if not isinstance(entries, list):
        raise WebsiteCrawlerError("Official news list response is missing data.data")

    rows: list[Mapping[str, object]] = []
    for entry in entries[:limit]:
        if not isinstance(entry, Mapping):
            LOGGER.warning("Ignoring non-object official news list entry")
            continue
        parse_numeric_news_id(str(entry.get("id", "")))
        if not str(entry.get("title", "")).strip():
            raise WebsiteCrawlerError("Official news list item is missing title")
        rows.append(entry)
    return rows


class _NextDataParser(HTMLParser):
    """Extract the exact ``__NEXT_DATA__`` script without relying on CSS classes."""

    def __init__(self) -> None:
        super().__init__()
        self._in_next_data = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._in_next_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_next_data:
            self._in_next_data = False

    def handle_data(self, data: str) -> None:
        if self._in_next_data:
            self.parts.append(data)


class _ContentHTMLParser(HTMLParser):
    """Convert official HTML into readable text and ordered image URLs."""

    BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.image_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in self.BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag == "img":
            source = attributes.get("src")
            if source and source.strip():
                self.image_urls.append(source.strip())

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)

    def get_text(self) -> str:
        text = "".join(self.text_parts).replace("\r\n", "\n")
        text = re.sub(r"[\t \f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def parse_next_data(document: str, *, url: str) -> Mapping[str, object]:
    """Return ``props.pageProps.data`` from a detail page or raise a clear error."""
    parser = _NextDataParser()
    parser.feed(document)
    raw_data = "".join(parser.parts).strip()
    if not raw_data:
        raise WebsiteCrawlerError(f"Detail page is missing __NEXT_DATA__: {url}")
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError as error:
        raise WebsiteCrawlerError(f"Detail page has invalid __NEXT_DATA__: {url}") from error

    try:
        detail = payload["props"]["pageProps"]["data"]
    except (KeyError, TypeError) as error:
        raise WebsiteCrawlerError(f"Detail page is missing props.pageProps.data: {url}") from error
    if not isinstance(detail, Mapping):
        raise WebsiteCrawlerError(f"Detail page data is not an object: {url}")
    return detail


def parse_publish_time(value: object) -> str | None:
    """Normalize official ISO or epoch time to a timezone-aware ISO 8601 string."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise WebsiteCrawlerError(f"Invalid official publish_time: {value!r}") from error
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.isoformat()
    raise WebsiteCrawlerError(f"Unsupported official publish_time value: {value!r}")


def extract_content(content_html: str) -> tuple[str, list[str]]:
    """Extract plain text and image URLs in source DOM order from official content."""
    parser = _ContentHTMLParser()
    parser.feed(content_html)
    return parser.get_text(), parser.image_urls


def parse_website_announcement(list_item: Mapping[str, object], document: str) -> WebsiteAnnouncement:
    """Parse one list item and its Next.js detail page into a standalone data object."""
    source_post_id = parse_numeric_news_id(str(list_item.get("id", "")))
    url = build_news_url(source_post_id)
    detail = parse_next_data(document, url=url)

    title = detail.get("title")
    content_html = detail.get("content_html")
    if not isinstance(title, str) or not title.strip():
        raise WebsiteCrawlerError(f"Detail page is missing title: {url}")
    if not isinstance(content_html, str):
        raise WebsiteCrawlerError(f"Detail page is missing content_html: {url}")

    try:
        section = int(list_item.get("section", 0))
    except (TypeError, ValueError) as error:
        raise WebsiteCrawlerError(f"List item has invalid section: {url}") from error
    content_text, image_urls = extract_content(content_html)
    return WebsiteAnnouncement(
        source_post_id=source_post_id,
        url=url,
        title=title.strip(),
        section=section,
        section_name=SECTION_NAMES.get(section, "其他"),
        publish_time=parse_publish_time(detail.get("publish_time", list_item.get("publish_time"))),
        content_text=content_text,
        content_html=content_html,
        image_urls=image_urls,
    )


def crawl_recent_announcements(
    limit: int,
    *,
    json_fetcher: JsonFetcher = fetch_json,
    text_fetcher: TextFetcher = fetch_text,
) -> WebsiteCrawlResult:
    """Fetch up to ``limit`` website announcements without any database mutation."""
    rows = fetch_news_list(limit, json_fetcher=json_fetcher)
    announcements: list[WebsiteAnnouncement] = []
    failures: list[WebsiteDetailFailure] = []
    for row in rows:
        source_post_id = parse_numeric_news_id(str(row["id"]))
        url = build_news_url(source_post_id)
        title = str(row.get("title", "")).strip()
        try:
            announcements.append(parse_website_announcement(row, text_fetcher(url)))
        except WebsiteCrawlerError as error:
            LOGGER.warning("Official website detail parse failed url=%s error=%s", url, error)
            failures.append(WebsiteDetailFailure(source_post_id, url, title, str(error)))
    return WebsiteCrawlResult(announcements, failures, len(rows))


def _statistics(result: WebsiteCrawlResult) -> dict[str, int]:
    counts = {"活動": 0, "新聞": 0, "客服": 0, "系統": 0, "其他": 0}
    for announcement in result.announcements:
        counts[announcement.section_name] = counts.get(announcement.section_name, 0) + 1
    return {
        "listed": result.listed_count,
        "parsed": len(result.announcements),
        "activity": counts["活動"],
        "news": counts["新聞"],
        "customer_service": counts["客服"],
        "system": counts["系統"],
        "other": counts["其他"],
        "with_publish_time": sum(item.publish_time is not None for item in result.announcements),
        "with_images": sum(bool(item.image_urls) for item in result.announcements),
        "detail_failures": len(result.failures),
    }


def write_report(result: WebsiteCrawlResult, path: Path = DEFAULT_REPORT_PATH) -> dict[str, object]:
    """Write a human-inspectable crawler report; this never touches SQLite."""
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "list_endpoint": NEWS_LIST_URL,
        "statistics": _statistics(result),
        "announcements": [asdict(item) for item in result.announcements],
        "detail_failures": [asdict(item) for item in result.failures],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def normalize_title(value: str) -> str:
    """Conservatively normalize titles for report-only Facebook comparison."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", "", normalized)


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def compare_with_facebook(
    announcements: Sequence[WebsiteAnnouncement], database_path: Path = DEFAULT_DATABASE_PATH
) -> dict[str, object]:
    """Read Facebook raw posts conservatively, without using repository initialization."""
    if not database_path.is_file():
        return {"available": False, "reason": "Facebook database does not exist", "items": []}

    try:
        connection = sqlite3.connect(f"file:{database_path.resolve().as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, url, content, published_at
            FROM raw_posts
            WHERE source = 'facebook'
            ORDER BY scraped_at DESC
            LIMIT 500
            """
        ).fetchall()
    except sqlite3.Error as error:
        return {"available": False, "reason": f"Could not read Facebook raw_posts: {error}", "items": []}
    finally:
        if "connection" in locals():
            connection.close()

    items: list[dict[str, object]] = []
    for website in announcements:
        normalized_website_title = normalize_title(website.title)
        exact = [row for row in rows if normalize_title(str(row["content"]).splitlines()[0]) == normalized_website_title]
        if exact:
            items.append({"website_source_post_id": website.source_post_id, "status": "matched", "facebook_raw_post_ids": [row["id"] for row in exact]})
            continue

        close = [
            row
            for row in rows
            if SequenceMatcher(None, normalized_website_title, normalize_title(str(row["content"]).splitlines()[0])).ratio() >= 0.92
        ]
        website_time = _parse_iso(website.publish_time)
        dated_close = [
            row
            for row in close
            if website_time and (facebook_time := _parse_iso(row["published_at"]))
            and abs((website_time - facebook_time).total_seconds()) <= 7 * 24 * 60 * 60
        ]
        if dated_close:
            status = "possible_match"
            matched_rows = dated_close
        elif close:
            status = "unmatched"
            matched_rows = close
        else:
            status = "website_only"
            matched_rows = []
        items.append({"website_source_post_id": website.source_post_id, "status": status, "facebook_raw_post_ids": [row["id"] for row in matched_rows]})

    return {
        "available": True,
        "facebook_posts_checked": len(rows),
        "summary": {status: sum(item["status"] == status for item in items) for status in ("matched", "possible_match", "website_only", "unmatched")},
        "items": items,
    }


def write_comparison_report(comparison: Mapping[str, object], path: Path = DEFAULT_COMPARISON_PATH) -> None:
    """Write the optional read-only website/Facebook comparison report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone website coverage spike."""
    parser = argparse.ArgumentParser(description="Crawl official website announcements for coverage analysis.")
    parser.add_argument("--limit", type=int, default=30, help="Number of recent official announcements to inspect.")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--comparison-path", type=Path, default=DEFAULT_COMPARISON_PATH)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--skip-comparison", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        result = crawl_recent_announcements(args.limit)
    except (WebsiteCrawlerError, ValueError) as error:
        LOGGER.error("Official website spike failed: %s", error)
        return 1

    report = write_report(result, args.report_path)
    statistics = report["statistics"]
    print(f"Official website announcements: {statistics['parsed']}")
    print(f"活動: {statistics['activity']}")
    print(f"新聞: {statistics['news']}")
    print(f"系統／客服: {statistics['system'] + statistics['customer_service']}")
    print(f"有日期: {statistics['with_publish_time']}")
    print(f"有圖片: {statistics['with_images']}")
    print(f"詳細頁解析失敗: {statistics['detail_failures']}")
    print(f"Report: {args.report_path}")

    if not args.skip_comparison:
        comparison = compare_with_facebook(result.announcements, args.database_path)
        write_comparison_report(comparison, args.comparison_path)
        print(f"Comparison: {args.comparison_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
