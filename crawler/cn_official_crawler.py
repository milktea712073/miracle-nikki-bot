"""China official-site source adapter using requests and BeautifulSoup only."""

from __future__ import annotations

import re
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from announcement.models import Announcement, CN_OFFICIAL, canonical_announcement_url


SITE_ROOT = "https://qjnn.qq.com"
LIST_URL_TEMPLATE = (
    SITE_ROOT + "/webplat/info/news_version3/11785/23142/23143/m14776/list_{page}.shtml"
)
REQUEST_HEADERS = {"User-Agent": "MiracleNikkiBot/2.0 (+https://qjnn.qq.com/)"}
REQUEST_TIMEOUT_SECONDS = 20
REQUEST_RETRY_ATTEMPTS = 3
MAX_LIST_PAGES = 500
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?")
CATEGORY_PATTERN = re.compile(r"^【(?P<category>[^】]+)】")
EXTERNAL_ID_PATTERN = re.compile(r"/(\d+)\.shtml$")
CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
LOGGER = logging.getLogger(__name__)
_BLOCK_TEXT_TAGS = frozenset({"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})
_IGNORED_TEXT_TAGS = frozenset({"script", "style"})
_QR_IMAGE_ATTRIBUTE_PATTERN = re.compile(r"二维码|公众号|游戏圈子|qrcode|qr[_-]?code", re.IGNORECASE)
_QR_FOOTER_CONTEXT_PATTERN = re.compile(
    r"(?:关注.{0,30}(?:公众号|微信)|(?:微信|公众号).{0,30}二维码|扫描下方二维码)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CNNoticeListItem:
    external_id: str
    title: str
    category: str | None
    published_date: str | None
    url: str


@dataclass(frozen=True, slots=True)
class CNFetchFailure:
    """One detail-page failure that did not stop the remaining source crawl."""

    external_id: str
    url: str
    error: str


@dataclass(frozen=True, slots=True)
class CNFetchResult:
    """Successful notices plus isolated detail failures from one list-page crawl."""

    announcements: list[Announcement]
    failures: list[CNFetchFailure]
    pages_fetched: int = 0
    listed_count: int = 0
    stopped_reason: str = "limit"


def select_encoding(response: requests.Response) -> str:
    """Use declared HTML charset first; Tencent's pages are not always UTF-8."""
    prefix = response.content[:4096].decode("latin-1", errors="ignore")
    match = re.search(r"<meta[^>]+charset=[\"']?\s*([\w.-]+)", prefix, re.IGNORECASE)
    return (match.group(1) if match else None) or response.encoding or response.apparent_encoding or "utf-8"


def parse_list(document: str, page_url: str) -> list[CNNoticeListItem]:
    soup = BeautifulSoup(document, "html.parser")
    notices: list[CNNoticeListItem] = []
    for item in soup.select("ul#newsList.news-list > li"):
        anchor = item.select_one("a.title[href]")
        if anchor is None:
            continue
        url = urljoin(page_url, str(anchor["href"]))
        identifier = EXTERNAL_ID_PATTERN.search(url)
        if identifier is None:
            continue
        title = anchor.get_text(" ", strip=True)
        date_node = item.select_one("p.info > span")
        category_match = CATEGORY_PATTERN.match(title)
        notices.append(
            CNNoticeListItem(
                external_id=identifier.group(1),
                title=title,
                category=category_match.group("category").strip() if category_match else None,
                published_date=date_node.get_text(" ", strip=True) if date_node else None,
                url=canonical_announcement_url(CN_OFFICIAL, url),
            )
        )
    return notices


def next_list_page_url(document: str, *, current_url: str) -> str | None:
    """Return the actual next-list URL from Tencent's legacy ``.guid`` markup.

    The site transitions from ``list_3.shtml`` to GUID-style paths such as
    ``list_n101.shtml``.  The crawler must therefore follow the site's link,
    rather than derive a numeric page URL locally.
    """
    soup = BeautifulSoup(document, "html.parser")
    next_link = soup.select_one(".guid a.next[href]")
    if next_link is None:
        return None
    href = str(next_link.get("href", "")).strip()
    return urljoin(current_url, href) if href else None


def extract_content_text(context: Tag) -> str:
    """Preserve paragraph breaks without separating text inside inline tags.

    Tencent's CMS wraps individual Chinese words, dates, and punctuation in
    adjacent ``span``/``font`` nodes. ``BeautifulSoup.get_text("\\n")`` inserts a
    line break between every such text node, so only structural block tags and
    explicit ``br`` nodes are allowed to add line breaks here.
    """
    parts: list[str] = []

    def append_break() -> None:
        if not parts or parts[-1] != "\n":
            parts.append("\n")

    def walk(node: object) -> None:
        if isinstance(node, NavigableString):
            value = str(node)
            # Pretty-printed source HTML contributes indentation-only text nodes;
            # paragraph and br tags already provide the meaningful boundaries.
            if value.strip():
                parts.append(value)
            return
        if not isinstance(node, Tag) or node.name in _IGNORED_TEXT_TAGS:
            return
        if node.name == "br":
            append_break()
            return

        is_block = node.name in _BLOCK_TEXT_TAGS
        if is_block:
            append_break()
        for child in node.children:
            walk(child)
        if is_block:
            append_break()

    for child in context.children:
        walk(child)

    text = "".join(parts).replace("\xa0", " ").replace("\r\n", "\n")
    text = re.sub(r"[\t \f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_qr_promotion_image(image: Tag) -> bool:
    """Identify Tencent's fixed official-account QR footer without positional rules."""
    attributes = " ".join(
        str(image.get(name, ""))
        for name in ("alt", "title", "id", "class", "src")
    )
    if _QR_IMAGE_ATTRIBUTE_PATTERN.search(attributes):
        return True

    container = image.find_parent("p") or image.parent
    if not isinstance(container, Tag):
        return False
    # Deliberately inspect only a sibling. ``find_previous`` can climb to the
    # enclosing context, whose text includes the QR footer after earlier body
    # images and would therefore incorrectly exclude those images.
    preceding_block = container.find_previous_sibling(["p", "div", "li"])
    if preceding_block is None:
        return False
    return bool(_QR_FOOTER_CONTEXT_PATTERN.search(preceding_block.get_text(" ", strip=True)))


def parse_detail(document: str, url: str) -> tuple[str, str, list[str], datetime | None]:
    """Return body HTML/text, image URLs in DOM order, and official timestamp."""
    soup = BeautifulSoup(document, "html.parser")
    context = soup.select_one(".content .context")
    if context is None:
        raise ValueError("CN official detail is missing .content .context")
    image_urls = list(
        dict.fromkeys(
            urljoin(url, str(image["src"]))
            for image in context.select("img[src]")
            if str(image.get("src", "")).strip()
            and not is_qr_promotion_image(image)
        )
    )
    timestamp = None
    for node in soup.select(".content .hd .info span"):
        value = node.get_text(" ", strip=True)
        if DATE_PATTERN.fullmatch(value):
            timestamp = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CHINA_TIMEZONE)
            break
    return str(context), extract_content_text(context), image_urls, timestamp


def fetch_recent_announcements(
    limit: int,
    *,
    get: Callable[[str], requests.Response] | None = None,
) -> list[Announcement]:
    """Fetch latest China notices without database or Discord side effects."""
    return fetch_recent_announcements_with_failures(limit, get=get).announcements


def fetch_recent_announcements_with_failures(
    limit: int,
    *,
    get: Callable[[str], requests.Response] | None = None,
    on_detail_start: Callable[[int, int, CNNoticeListItem], None] | None = None,
) -> CNFetchResult:
    """Fetch current notices while allowing one malformed detail page to be skipped."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    request = _build_request(get)
    list_response = request(LIST_URL_TEMPLATE.format(page=1))
    items = parse_list(list_response.text, list_response.url)[:limit]
    return _fetch_detail_items(items, request=request, on_detail_start=on_detail_start, pages_fetched=1)


def fetch_all_announcements_with_failures(
    *,
    get: Callable[[str], requests.Response] | None = None,
    max_pages: int = MAX_LIST_PAGES,
    on_list_page: Callable[[int, int, int], None] | None = None,
    on_detail_start: Callable[[int, int, CNNoticeListItem], None] | None = None,
) -> CNFetchResult:
    """Fetch all reachable official list pages without hard-coding a page count.

    The importer remains outside this function.  Therefore a list-page failure
    cannot create a partial raw import, while individual detail failures are
    collected and do not discard valid notices from other pages.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")

    request = _build_request(get)
    seen_external_ids: set[str] = set()
    all_items: list[CNNoticeListItem] = []
    pages_fetched = 0
    stopped_reason = "max_pages"

    current_url = LIST_URL_TEMPLATE.format(page=1)
    visited_urls: set[str] = set()

    while pages_fetched < max_pages:
        if current_url in visited_urls:
            stopped_reason = "visited_next_url"
            break
        visited_urls.add(current_url)
        list_response = request(current_url)
        pages_fetched += 1
        page_items = parse_list(list_response.text, list_response.url)
        if not page_items:
            stopped_reason = "empty_page"
            if on_list_page is not None:
                on_list_page(pages_fetched, len(all_items), 0)
            break

        new_items = [item for item in page_items if item.external_id not in seen_external_ids]
        if not new_items:
            stopped_reason = "no_new_notices"
            if on_list_page is not None:
                on_list_page(pages_fetched, len(all_items), 0)
            break
        seen_external_ids.update(item.external_id for item in new_items)
        all_items.extend(new_items)
        if on_list_page is not None:
            on_list_page(pages_fetched, len(all_items), len(new_items))

        next_url = next_list_page_url(list_response.text, current_url=list_response.url)
        if next_url is None:
            stopped_reason = "no_next_page"
            break

        if next_url in visited_urls:
            stopped_reason = "visited_next_url"
            break
        current_url = next_url
    else:
        LOGGER.warning("CN official crawl stopped at max_pages=%s", max_pages)

    result = _fetch_detail_items(
        all_items,
        request=request,
        on_detail_start=on_detail_start,
        pages_fetched=pages_fetched,
    )
    return CNFetchResult(
        announcements=result.announcements,
        failures=result.failures,
        pages_fetched=pages_fetched,
        listed_count=len(all_items),
        stopped_reason=stopped_reason,
    )


def _build_request(
    get: Callable[[str], requests.Response] | None,
) -> Callable[[str], requests.Response]:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    def request(url: str) -> requests.Response:
        for attempt in range(REQUEST_RETRY_ATTEMPTS):
            try:
                response = get(url) if get else session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                response.encoding = select_encoding(response)
                return response
            except requests.RequestException:
                if attempt == REQUEST_RETRY_ATTEMPTS - 1:
                    raise
                LOGGER.warning(
                    "CN official request failed; retrying url=%s attempt=%s/%s",
                    url,
                    attempt + 1,
                    REQUEST_RETRY_ATTEMPTS,
                )
                time.sleep(0.5 * (attempt + 1))
        raise AssertionError("unreachable")

    return request


def _fetch_detail_items(
    items: list[CNNoticeListItem],
    *,
    request: Callable[[str], requests.Response],
    on_detail_start: Callable[[int, int, CNNoticeListItem], None] | None,
    pages_fetched: int,
) -> CNFetchResult:
    announcements: list[Announcement] = []
    failures: list[CNFetchFailure] = []
    for index, item in enumerate(items, start=1):
        if on_detail_start is not None:
            on_detail_start(index, len(items), item)
        try:
            detail_response = request(item.url)
            content_html, content_text, images, published_at = parse_detail(detail_response.text, detail_response.url)
            if published_at is None and item.published_date:
                published_at = datetime.strptime(item.published_date, "%Y-%m-%d").replace(tzinfo=CHINA_TIMEZONE)
            announcements.append(
                Announcement(
                    source=CN_OFFICIAL,
                    external_id=item.external_id,
                    url=item.url,
                    title=item.title,
                    category=item.category,
                    published_at=published_at,
                    content_html=content_html,
                    content_text=content_text,
                    images=tuple(images),
                )
            )
        except Exception as error:
            LOGGER.exception("Failed to fetch CN official detail external_id=%s url=%s", item.external_id, item.url)
            failures.append(CNFetchFailure(item.external_id, item.url, str(error)))
    return CNFetchResult(
        announcements=announcements,
        failures=failures,
        pages_fetched=pages_fetched,
        listed_count=len(items),
    )
