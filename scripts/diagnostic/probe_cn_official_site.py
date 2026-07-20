"""Read-only probe that reuses the formal China official crawler parser."""

from __future__ import annotations

import argparse

import requests
from bs4 import BeautifulSoup

from crawler.cn_official_crawler import (
    LIST_URL_TEMPLATE,
    REQUEST_HEADERS,
    parse_detail,
    parse_list,
    select_encoding,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=2)
    args = parser.parse_args()
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    first = session.get(LIST_URL_TEMPLATE.format(page=1), timeout=20)
    first.raise_for_status()
    first.encoding = select_encoding(first)
    notices = parse_list(first.text, first.url)
    if not notices:
        raise RuntimeError("No notices found with ul#newsList.news-list > li")
    latest = notices[0]
    detail = session.get(latest.url, timeout=20)
    detail.raise_for_status()
    detail.encoding = select_encoding(detail)
    content_html, content_text, images, published_at = parse_detail(detail.text, detail.url)

    print("CN official site HTTP probe")
    print(f"list_status={first.status_code}")
    print(f"selected_encoding={first.encoding}")
    print("list_selector=ul#newsList.news-list > li; a.title[href]; p.info > span")
    print(f"latest_title={latest.title}")
    print(f"latest_category={latest.category or 'not_structured'}")
    print(f"latest_url={latest.url}")
    print(f"detail_status={detail.status_code}")
    print("detail_selector=.content .context")
    print("image_selector=.content .context img[src]")
    print(f"published_at={published_at.isoformat() if published_at else latest.published_date}")
    print(f"body_characters={len(content_text)}")
    print(f"content_html_characters={len(content_html)}")
    print(f"image_count={len(images)}")
    for page in range(1, args.pages + 1):
        response = session.get(LIST_URL_TEMPLATE.format(page=page), timeout=20)
        response.raise_for_status()
        response.encoding = select_encoding(response)
        soup = BeautifulSoup(response.text, "html.parser")
        print(f"list_{page}_items={len(parse_list(response.text, response.url))}")
        print(f"list_{page}_pagination_links={len(soup.select('.guid a[href]'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
