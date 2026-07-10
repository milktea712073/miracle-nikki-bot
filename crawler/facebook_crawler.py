"""Fetch the newest post from the official Miracle Nikki Facebook page."""

import re
import sys
from typing import Final
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


FACEBOOK_PAGE_URL: Final = "https://www.facebook.com/TwNikkiNikki"
PAGE_TIMEOUT_MS: Final = 60_000
POST_LINK_SELECTOR: Final = (
    "a[href*='/posts/'], a[href*='/videos/'], a[href*='/permalink/'], "
    "a[href*='/reel/']"
)
MESSAGE_SELECTORS: Final = (
    "[data-ad-preview='message']",
    "[data-ad-comet-preview='message']",
)


def first_text(locator: Locator, selectors: tuple[str, ...]) -> str:
    """Return text from the first matching descendant selector."""
    for selector in selectors:
        candidate = locator.locator(selector).first
        if candidate.count():
            text = candidate.inner_text().strip()
            if text:
                return text
    return ""


def get_post_article(page: Page) -> Locator:
    """Return the first page article that has a Facebook post permalink."""
    page.locator("div[role='article'], article").first.wait_for(
        state="visible", timeout=PAGE_TIMEOUT_MS
    )
    page.wait_for_timeout(2_000)

    articles = page.locator("div[role='article'], article")
    for index in range(articles.count()):
        article = articles.nth(index)
        if article.locator(POST_LINK_SELECTOR).count():
            return article

    raise RuntimeError("Facebook page loaded, but no post article was found.")


def get_post_time(article: Locator) -> str:
    """Get the visible publication time from the post permalink."""
    links = article.locator(POST_LINK_SELECTOR)
    for index in range(links.count()):
        text = links.nth(index).inner_text().strip()
        if text:
            return text

    time_element = article.locator("time, abbr").first
    return time_element.inner_text().strip() if time_element.count() else ""


def get_post_url(article: Locator) -> str:
    """Get and normalize the post permalink."""
    href = article.locator(POST_LINK_SELECTOR).first.get_attribute("href")
    if not href:
        raise RuntimeError("The newest post did not contain a permalink.")

    post_url = urlsplit(urljoin("https://www.facebook.com", href))
    return urlunsplit((post_url.scheme, post_url.netloc, post_url.path, "", ""))


def get_image_url(article: Locator) -> str | None:
    """Get the first image associated with the post, if the post has one."""
    image = article.locator("img[src*='scontent.']").first
    return image.get_attribute("src") if image.count() else None


def expand_post_content(article: Locator) -> bool:
    """Try to expand a truncated post message once."""
    more_button = article.get_by_text(
        re.compile(r"^(\u67e5\u770b\u66f4\u591a|See more)$", re.I)
    ).first
    if not more_button.count():
        return True

    try:
        more_button.click(timeout=5_000)
        return True
    except PlaywrightTimeoutError:
        return False


def dismiss_cookie_dialog(page: Page) -> None:
    """Dismiss a cookie prompt when Facebook presents one."""
    buttons = page.get_by_role(
        "button",
        name=re.compile(
            r"allow all|accept all|\u5141\u8a31\u6240\u6709|\u5168\u90e8\u63a5\u53d7",
            re.I,
        ),
    )
    if buttons.count():
        buttons.first.click(timeout=5_000)


def get_full_post_content(page: Page, post_url: str) -> str:
    """Open a post permalink and return its full message text."""
    page.goto(post_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    dismiss_cookie_dialog(page)

    message = page.locator(
        "[data-ad-preview='message'], [data-ad-comet-preview='message']"
    ).first
    message.wait_for(state="visible", timeout=PAGE_TIMEOUT_MS)

    article = get_post_article(page)
    expanded = expand_post_content(article)
    content = first_text(article, MESSAGE_SELECTORS)
    if content and not content.endswith(("\u67e5\u770b\u66f4\u591a", "See more")):
        return content

    if not expanded:
        raise RuntimeError(
            "Facebook blocked expanding the full post in anonymous mode. "
            "Use a persistent Playwright context with a logged-in Facebook session."
        )

    raise RuntimeError(
        "Facebook did not expose the full post content. "
        "Use a persistent Playwright context with a logged-in Facebook session."
    )


def fetch_latest_post() -> dict[str, str | None]:
    """Return the newest official Facebook post as a dictionary."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(
                FACEBOOK_PAGE_URL,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT_MS,
            )
            dismiss_cookie_dialog(page)

            article = get_post_article(page)
            post_url = get_post_url(article)
            post_time = get_post_time(article)
            image_url = get_image_url(article)
            content = get_full_post_content(page, post_url)
            return {
                "time": post_time,
                "content": content,
                "image_url": image_url,
                "post_url": post_url,
            }
        finally:
            browser.close()


def main() -> None:
    """Fetch and print the newest post for command-line testing."""
    sys.stdout.reconfigure(encoding="utf-8")
    post = fetch_latest_post()

    print("======== \u6700\u65b0\u8cbc\u6587 ========")
    print(f"\u767c\u6587\u6642\u9593\uff1a\n{post['time']}")
    print(f"\n\u8cbc\u6587\u5167\u5bb9\uff1a\n{post['content']}")
    print(f"\n\u5716\u7247\u7db2\u5740\uff1a\n{post['image_url']}")
    print(f"\n\u8cbc\u6587\u7db2\u5740\uff1a\n{post['post_url']}")
    print("==========================")


if __name__ == "__main__":
    main()
