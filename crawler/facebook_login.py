"""Interactively create a Playwright storage state for Facebook."""

import sys
import time

from playwright.sync_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

try:
    from crawler.facebook_session import (
        FACEBOOK_STORAGE_STATE_PATH,
        ensure_data_dir,
        has_login_cookie,
    )
except ModuleNotFoundError:
    from facebook_session import (
        FACEBOOK_STORAGE_STATE_PATH,
        ensure_data_dir,
        has_login_cookie,
    )


FACEBOOK_LOGIN_URL = "https://www.facebook.com/login"
LOGIN_TIMEOUT_SECONDS = 600


def wait_for_manual_login(context: BrowserContext, page: Page) -> None:
    """Wait for the user to finish Facebook login in the visible browser."""
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if has_login_cookie(context):
            return
        page.wait_for_timeout(1_000)
    raise PlaywrightTimeoutError(
        "Facebook login was not completed within 10 minutes. No session was saved."
    )


def main() -> None:
    """Open Facebook for manual login and save the resulting storage state."""
    ensure_data_dir()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        try:
            page = context.new_page()
            page.goto(FACEBOOK_LOGIN_URL, wait_until="domcontentloaded")
            print("Complete Facebook login in the opened browser window.")
            wait_for_manual_login(context, page)
            context.storage_state(path=str(FACEBOOK_STORAGE_STATE_PATH))
            print("Facebook storage state saved.")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except PlaywrightTimeoutError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
