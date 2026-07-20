"""Read-only HTTP feasibility probe for the China official notice website.

This script intentionally has no dependency on the bot, database, queue, or
existing crawlers.  It verifies that the public notice list and detail pages
can be parsed with ``requests`` and BeautifulSoup alone.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


SITE_ROOT = "https://qjnn.qq.com"
LIST_URL_TEMPLATE = (
    SITE_ROOT
    + "/webplat/info/news_version3/11785/23142/23143/m14776/list_{page}.shtml"
)
REQUEST_HEADERS = {
    "User-Agent": "MiracleNikkiBotCNProbe/1.0 (+https://qjnn.qq.com/)"
}
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?")
CATEGORY_PATTERN = re.compile(r"^【(?P<category>[^】]+)】")


@dataclass(frozen=True, slots=True)
class NoticeListItem:
    title: str
    published_date: str | None
    category: str | None
    url: str


def _meta_charset(response: requests.Response) -> str | None:
    """Read the page-declared encoding from raw HTML without assuming UTF-8."""
    prefix = response.content[:4096].decode("latin-1", errors="ignore")
    match = re.search(
        r"<meta[^>]+charset=[\"']?\s*([\w.-]+)", prefix, flags=re.IGNORECASE
    )
    return match.group(1) if match else None


def select_encoding(response: requests.Response) -> tuple[str, str | None, str | None]:
    """Return the selected encoding plus declared and apparent candidates."""
    declared = _meta_charset(response)
    apparent = response.apparent_encoding
    selected = declared or response.encoding or apparent or "utf-8"
    return selected, declared, apparent


def fetch_html(session: requests.Session, url: str) -> tuple[requests.Response, BeautifulSoup, str, str | None, str | None]:
    response = session.get(url, timeout=20)
    response.raise_for_status()
    selected, declared, apparent = select_encoding(response)
    response.encoding = selected
    return response, BeautifulSoup(response.text, "html.parser"), selected, declared, apparent


def category_from_title(title: str) -> str | None:
    match = CATEGORY_PATTERN.match(title)
    return match.group("category").strip() if match else None


def parse_list_items(soup: BeautifulSoup, page_url: str) -> list[NoticeListItem]:
    """Parse the static ``ul#newsList.news-list`` list entries in document order."""
    items: list[NoticeListItem] = []
    for item in soup.select("ul#newsList.news-list > li"):
        anchor = item.select_one("a.title[href]")
        if anchor is None:
            continue
        title = anchor.get_text(" ", strip=True)
        date_node = item.select_one("p.info > span")
        date_text = date_node.get_text(" ", strip=True) if date_node else None
        items.append(
            NoticeListItem(
                title=title,
                published_date=date_text or None,
                category=category_from_title(title),
                url=urljoin(page_url, anchor["href"]),
            )
        )
    return items


def parse_detail(soup: BeautifulSoup, detail_url: str) -> tuple[str, list[str], str | None]:
    """Extract body text, ordered body images, and the detail-page timestamp."""
    context = soup.select_one(".content .context")
    if context is None:
        raise ValueError("Detail body selector .content .context was not found.")

    image_urls = [
        urljoin(detail_url, image["src"])
        for image in context.select("img[src]")
        if image.get("src", "").strip()
    ]
    # Keep image order but collapse exact duplicate source URLs.
    image_urls = list(dict.fromkeys(image_urls))

    timestamp: str | None = None
    for node in soup.select(".content .hd .info span"):
        value = node.get_text(" ", strip=True)
        if DATE_PATTERN.fullmatch(value):
            timestamp = value
            break
    return context.get_text("\n", strip=True), image_urls, timestamp


def _pagination_links(soup: BeautifulSoup, page_url: str) -> Iterable[str]:
    for anchor in soup.select(".guid a[href]"):
        yield urljoin(page_url, anchor["href"])


def print_probe(page_count: int) -> None:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    first_url = LIST_URL_TEMPLATE.format(page=1)
    response, list_soup, encoding, declared, apparent = fetch_html(session, first_url)
    items = parse_list_items(list_soup, response.url)
    if not items:
        raise RuntimeError("No notice entries found with ul#newsList.news-list > li.")

    latest = items[0]
    print("CN official site HTTP probe")
    print(f"list_url={response.url}")
    print(f"list_status={response.status_code}")
    print(f"content_type={response.headers.get('Content-Type', '')}")
    print(f"declared_encoding={declared or 'none'}")
    print(f"apparent_encoding={apparent or 'none'}")
    print(f"selected_encoding={encoding}")
    print("list_selector=ul#newsList.news-list > li; a.title[href]; p.info > span")
    print(f"list_item_count={len(items)}")
    print("latest_notice")
    print(f"  title={latest.title}")
    print(f"  published_date={latest.published_date or 'none'}")
    print(f"  category={latest.category or 'not_structured'}")
    print(f"  url={latest.url}")

    detail_response, detail_soup, detail_encoding, detail_declared, detail_apparent = fetch_html(
        session, latest.url
    )
    body, image_urls, detail_timestamp = parse_detail(detail_soup, detail_response.url)
    print("detail_notice")
    print(f"  url={detail_response.url}")
    print(f"  status={detail_response.status_code}")
    print(f"  declared_encoding={detail_declared or 'none'}")
    print(f"  apparent_encoding={detail_apparent or 'none'}")
    print(f"  selected_encoding={detail_encoding}")
    print("  body_selector=.content .context")
    print("  image_selector=.content .context img[src]")
    print(f"  published_timestamp={detail_timestamp or latest.published_date or 'none'}")
    print(f"  body_characters={len(body)}")
    print(f"  body_preview={body[:240]}")
    print(f"  image_count={len(image_urls)}")
    for index, image_url in enumerate(image_urls[:5], start=1):
        print(f"  image_{index}={image_url}")

    print("pagination")
    for page in range(1, page_count + 1):
        page_url = LIST_URL_TEMPLATE.format(page=page)
        page_response, page_soup, _, _, _ = fetch_html(session, page_url)
        page_items = parse_list_items(page_soup, page_response.url)
        links = list(_pagination_links(page_soup, page_response.url))
        print(
            f"  list_{page}: status={page_response.status_code}; "
            f"items={len(page_items)}; pagination_links={','.join(links) or 'none'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pages", type=int, default=2, help="Number of list_N.shtml pages to probe."
    )
    args = parser.parse_args()
    if args.pages < 1:
        parser.error("--pages must be at least 1")
    print_probe(args.pages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
