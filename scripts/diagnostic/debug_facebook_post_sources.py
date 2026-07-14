"""Read-only desktop diagnostics for Facebook page post-source entry points."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Browser, Page, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import (
    FACEBOOK_PAGE_URL,
    PAGE_TIMEOUT_MS,
    POST_ARTICLE_SELECTOR,
    dismiss_cookie_dialog,
    get_post_url,
)
from crawler.facebook_session import create_browser_context


LOGGER = logging.getLogger(__name__)
TARGET_POST_TEXT = "蒸汽文明 舊日呢喃"
DIRECT_POSTS_URL = "https://www.facebook.com/TwNikkiNikki/posts"
ENTRY_PATTERN = re.compile(r"貼文|posts?|feed|精選|featured|置頂|pinned", re.I)


@dataclass(frozen=True, slots=True)
class EntryLink:
    label: str
    href: str


def wait_for_page(page: Page) -> None:
    """Give Facebook time to populate client-rendered page content."""
    dismiss_cookie_dialog(page)
    page.wait_for_timeout(3_000)


def find_post_source_links(page: Page) -> list[EntryLink]:
    """Return visible desktop links whose label or href suggests a post source."""
    links = page.locator("a[href]")
    entries: list[EntryLink] = []
    seen: set[str] = set()
    for index in range(links.count()):
        link = links.nth(index)
        href = link.get_attribute("href")
        if not href:
            continue
        label = (link.inner_text().strip() or link.get_attribute("aria-label") or "").strip()
        if not ENTRY_PATTERN.search(f"{label} {href}"):
            continue
        absolute_href = urljoin("https://www.facebook.com", href)
        if absolute_href in seen:
            continue
        seen.add(absolute_href)
        entries.append(EntryLink(label=label, href=absolute_href))
    return entries


def canonical_permalinks(page: Page) -> list[str]:
    """List unique post permalinks found in all current article/FeedUnit containers."""
    containers = page.locator(POST_ARTICLE_SELECTOR)
    urls: list[str] = []
    seen: set[str] = set()
    for index in range(containers.count()):
        try:
            post_url = get_post_url(containers.nth(index))
        except Exception:
            continue
        if post_url not in seen:
            seen.add(post_url)
            urls.append(post_url)
    return urls


def report_page(page: Page, label: str) -> None:
    """Print target visibility, container count, and canonical permalinks."""
    html = page.content()
    visible_text = page.locator("body").inner_text()
    permalinks = canonical_permalinks(page)
    print(f"\n=== {label} ===")
    print(f"Final URL: {page.url}")
    print(f"Target in HTML: {TARGET_POST_TEXT in html}")
    print(f"Target in visible text: {TARGET_POST_TEXT in visible_text}")
    print(f"article / FeedUnit containers: {page.locator(POST_ARTICLE_SELECTOR).count()}")
    print(f"Canonical post permalinks: {permalinks}")


def open_and_report(page: Page, url: str, label: str) -> None:
    """Open one discovered desktop source URL and print diagnostics."""
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    wait_for_page(page)
    report_page(page, label)


def click_posts_tab_and_report(page: Page) -> bool:
    """Click the actual homepage Posts tab, if Facebook exposes a visible one."""
    links = page.locator("a[href]")
    for index in range(links.count()):
        link = links.nth(index)
        label = (link.inner_text().strip() or link.get_attribute("aria-label") or "").strip()
        if not re.fullmatch(r"貼文|Posts?", label, re.I):
            continue
        if not link.is_visible():
            continue
        link.click(timeout=5_000)
        page.wait_for_timeout(3_000)
        report_page(page, "Clicked homepage Posts tab")
        return True
    print("\n=== Clicked homepage Posts tab ===")
    print("No visible Posts / 貼文 tab was present in the homepage DOM.")
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return argparse.ArgumentParser(
        description="Read-only Facebook post-source diagnostic; does not write the database."
    ).parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=True)
        context = create_browser_context(browser)
        try:
            page = context.new_page()
            open_and_report(page, FACEBOOK_PAGE_URL, "Homepage")
            homepage_entries = find_post_source_links(page)
            print("Homepage post-source links:")
            for entry in homepage_entries:
                print(f"- label={entry.label!r} href={entry.href}")

            click_posts_tab_and_report(page)
            open_and_report(page, DIRECT_POSTS_URL, "Direct /posts URL")

            for index, entry in enumerate(homepage_entries[:10], 1):
                if entry.href.rstrip("/") == DIRECT_POSTS_URL.rstrip("/"):
                    continue
                open_and_report(page, entry.href, f"Discovered source {index}: {entry.label or entry.href}")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
