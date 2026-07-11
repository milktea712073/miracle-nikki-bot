"""Fetch the newest post from the official Miracle Nikki Facebook page."""

import re
import sys
from datetime import datetime
from typing import Final
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


FACEBOOK_PAGE_URL: Final = "https://www.facebook.com/TwNikkiNikki"
PAGE_TIMEOUT_MS: Final = 60_000
DISPLAY_TIMEZONE: Final = ZoneInfo("Asia/Taipei")
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


def format_publish_time(timestamp: int) -> str:
    """Format a Unix timestamp for the bot's Taiwan audience."""
    return datetime.fromtimestamp(timestamp, DISPLAY_TIMEZONE).strftime("%Y/%m/%d %H:%M")


def get_publish_time(page: Page) -> str:
    """Extract an absolute publication time from the post detail page."""
    time_elements = page.locator("time[datetime]")
    for index in range(time_elements.count()):
        value = time_elements.nth(index).get_attribute("datetime")
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=DISPLAY_TIMEZONE)
        return parsed.astimezone(DISPLAY_TIMEZONE).strftime("%Y/%m/%d %H:%M")

    unix_time_elements = page.locator("[data-utime], [data-timestamp]")
    for index in range(unix_time_elements.count()):
        value = unix_time_elements.nth(index).get_attribute("data-utime")
        value = value or unix_time_elements.nth(index).get_attribute("data-timestamp")
        if value and value.isdigit():
            return format_publish_time(int(value))

    page_data = page.content()
    timestamp = re.search(r'"(?:publish_time|creation_time)":(\d{10})', page_data)
    if timestamp:
        return format_publish_time(int(timestamp.group(1)))

    raise RuntimeError(
        "Facebook did not expose an absolute publication time. "
        "Use a persistent Playwright context with a logged-in Facebook session."
    )


def get_post_url(article: Locator) -> str:
    """Get and normalize the post permalink."""
    href = article.locator(POST_LINK_SELECTOR).first.get_attribute("href")
    if not href:
        raise RuntimeError("The newest post did not contain a permalink.")

    post_url = urlsplit(urljoin("https://www.facebook.com", href))
    return urlunsplit((post_url.scheme, post_url.netloc, post_url.path, "", ""))


def get_image_urls(article: Locator) -> list[str]:
    images = article.locator("img[src*='scontent']")

    urls = []

    for i in range(images.count()):
        image = images.nth(i)

        url = image.get_attribute("src")

        if url:
            urls.append(url)

    return urls


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


def open_post_detail(page: Page, post_url: str) -> Locator:
    """Open a post permalink and return its article from the detail page."""
    page.goto(post_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    dismiss_cookie_dialog(page)

    message = page.locator(
        "[data-ad-preview='message'], [data-ad-comet-preview='message']"
    ).first
    message.wait_for(state="visible", timeout=PAGE_TIMEOUT_MS)
    return get_post_article(page)


def get_full_post_content(article: Locator) -> str:
    """Return the full message text from a post detail article."""
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
            detail_article = open_post_detail(page, post_url)
            content = get_full_post_content(detail_article)
            publish_time = get_publish_time(page)
            image_urls = get_image_urls(detail_article)
            return {
                "publish_time": publish_time,
                "content": content,
                "image_urls": image_urls,
                "post_url": post_url,
            }
        finally:
            browser.close()


def main() -> None:
    """Fetch and print the newest post for command-line testing."""
    sys.stdout.reconfigure(encoding="utf-8")
    post = fetch_latest_post()

    print("======== \u6700\u65b0\u8cbc\u6587 ========")
    print(f"\u767c\u5e03\u65e5\u671f\uff1a\n{post['publish_time']}")
    print(f"\n\u8cbc\u6587\u5167\u5bb9\uff1a\n{post['content']}")
    print(f"\n\u5716\u7247\u7db2\u5740\uff1a\n{post['image_urls']}")
    print(f"\n\u8cbc\u6587\u7db2\u5740\uff1a\n{post['post_url']}")
    print("==========================")


if __name__ == "__main__":
    main()
