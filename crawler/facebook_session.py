"""Playwright storage-state helpers for Facebook sessions."""

import logging
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Error


LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
FACEBOOK_STORAGE_STATE_PATH = DATA_DIR / "facebook_storage_state.json"
FACEBOOK_URL = "https://www.facebook.com"


def ensure_data_dir() -> Path:
    """Create and return the local directory used for session state."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def has_storage_state() -> bool:
    """Return whether a saved Facebook storage state exists locally."""
    return FACEBOOK_STORAGE_STATE_PATH.is_file()


def create_browser_context(browser: Browser) -> BrowserContext:
    """Create a context with saved Facebook state when it is available."""
    ensure_data_dir()
    if not has_storage_state():
        LOGGER.warning(
            "Facebook storage state is missing; continuing in anonymous mode. "
            "Run python crawler/facebook_login.py to create a session."
        )
        return browser.new_context()

    try:
        return browser.new_context(storage_state=str(FACEBOOK_STORAGE_STATE_PATH))
    except Error:
        LOGGER.warning(
            "Facebook storage state could not be loaded; continuing in anonymous mode. "
            "Run python crawler/facebook_login.py to refresh it."
        )
        return browser.new_context()


def has_login_cookie(context: BrowserContext) -> bool:
    """Check for Facebook's authenticated-session cookie without exposing it."""
    return any(
        cookie["name"] == "c_user" for cookie in context.cookies(urls=[FACEBOOK_URL])
    )
