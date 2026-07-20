"""China official-site source adapter using requests and BeautifulSoup only."""

from __future__ import annotations

import re
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
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?")
CATEGORY_PATTERN = re.compile(r"^【(?P<category>[^】]+)】")
EXTERNAL_ID_PATTERN = re.compile(r"/(\d+)\.shtml$")
CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
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
    if limit < 1:
        raise ValueError("limit must be at least 1")
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    def request(url: str) -> requests.Response:
        response = get(url) if get else session.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = select_encoding(response)
        return response

    list_response = request(LIST_URL_TEMPLATE.format(page=1))
    items = parse_list(list_response.text, list_response.url)[:limit]
    announcements: list[Announcement] = []
    for item in items:
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
    return announcements
