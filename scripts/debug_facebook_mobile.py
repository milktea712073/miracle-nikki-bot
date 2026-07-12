"""Diagnose Facebook timeline DOM in a mobile Playwright environment."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Error, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import (
    FACEBOOK_PAGE_URL,
    PAGE_TIMEOUT_MS,
    POST_ARTICLE_SELECTOR,
    debug_timeline_candidates,
    dismiss_cookie_dialog,
)
from crawler.facebook_session import FACEBOOK_STORAGE_STATE_PATH, has_storage_state


LOGGER = logging.getLogger(__name__)
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
)
MOBILE_VIEWPORT = {"width": 390, "height": 844}
MOBILE_URLS = (
    FACEBOOK_PAGE_URL,
    "https://m.facebook.com/TwNikkiNikki",
    "https://mbasic.facebook.com/TwNikkiNikki",
)
TARGET_POST_TEXT = "【預告】蒸汽文明 暫日呢喃"


def create_mobile_context(browser: Browser) -> BrowserContext:
    """Create a mobile-emulation context using saved Facebook state if available."""
    options: dict[str, object] = {
        "viewport": MOBILE_VIEWPORT,
        "user_agent": MOBILE_USER_AGENT,
        "is_mobile": True,
        "has_touch": True,
    }
    if has_storage_state():
        options["storage_state"] = str(FACEBOOK_STORAGE_STATE_PATH)
    return browser.new_context(**options)


def diagnose_url(browser: Browser, url: str) -> None:
    """Print all mobile timeline candidates and target-post visibility for one URL."""
    context = create_mobile_context(browser)
    try:
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        except Error as error:
            # Facebook often aborts the initial www navigation while redirecting
            # a mobile UA; inspect the resulting page instead of ending diagnostics.
            LOGGER.info("Mobile navigation redirected from %s: %s", url, error)
        dismiss_cookie_dialog(page)
        page.wait_for_timeout(3_000)
        candidates = debug_timeline_candidates(page)
        target_in_candidate = page.locator(POST_ARTICLE_SELECTOR).evaluate_all(
            "(elements, target) => elements.some(element => element.innerText.includes(target))",
            TARGET_POST_TEXT,
        )
        target_in_page_html = TARGET_POST_TEXT in page.content()
        print(f"\n=== Mobile diagnostic: {url} ===")
        print(f"Final URL: {page.url}")
        print(f"Candidate containers: {len(candidates)}")
        print(f"Target in candidate text: {target_in_candidate}")
        print(f"Target in page HTML: {target_in_page_html}")
    finally:
        context.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for url in MOBILE_URLS:
                diagnose_url(browser, url)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
