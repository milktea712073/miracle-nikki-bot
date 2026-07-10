"""Milestone 1: verify that the official Miracle Nikki Facebook page opens."""

import sys

from playwright.sync_api import sync_playwright


FACEBOOK_PAGE_URL = "https://www.facebook.com/TwNikkiNikki"
PAGE_TIMEOUT_MS = 60_000


def main() -> None:
    """Open the official Facebook page and print its title."""
    sys.stdout.reconfigure(encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(
                FACEBOOK_PAGE_URL,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT_MS,
            )
            print(f"Page title: {page.title()}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
