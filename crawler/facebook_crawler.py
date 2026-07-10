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
    """Return the first feed article that has a Facebook post permalink."""
    page.locator("div[role='article'], article").first.wait_for(
        state="visible", timeout=PAGE_TIMEOUT_MS
    )
    page.wait_for_timeout(2_000)

    articles = page.locator("div[role='article'], article")
    for index in range(articles.count()):
        article = articles.nth(index)
        if article.locator(POST_LINK_SELECTOR).count():
            return article

    raise RuntimeError("Facebook feed loaded, but no post article was found.")


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
    link = article.locator(POST_LINK_SELECTOR).first
    href = link.get_attribute("href")
    if not href:
        raise RuntimeError("The newest post did not contain a permalink.")
    post_url = urlsplit(urljoin("https://www.facebook.com", href))
    return urlunsplit((post_url.scheme, post_url.netloc, post_url.path, "", ""))


def get_image_url(article: Locator) -> str | None:
    """Get the first image associated with the post, if the post has one."""
    image = article.locator("img[src*='scontent.']").first
    if not image.count():
        return None

    return image.get_attribute("src")


def expand_post_content(article: Locator) -> None:
    """Expand a truncated post message when Facebook renders a 'See more' control."""
    more_button = article.get_by_text(
        re.compile(r"^(查看更多|See more)$", re.I)
    ).first
    if more_button.count():
        try:
            more_button.click(timeout=5_000)
        except PlaywrightTimeoutError:
            # Facebook can require sign-in before expanding a public post.
            pass


def dismiss_cookie_dialog(page: Page) -> None:
    """Dismiss a cookie prompt when Facebook presents one."""
    buttons = page.get_by_role(
        "button", name=re.compile(r"allow all|accept all|允許所有|全部接受", re.I)
    )
    if buttons.count():
        buttons.first.click(timeout=5_000)


def main() -> None:
    """Load the Facebook feed and print the newest post's data."""
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
            dismiss_cookie_dialog(page)

            article = get_post_article(page)
            expand_post_content(article)
            post_time = get_post_time(article)
            post_content = first_text(article, MESSAGE_SELECTORS)
            image_url = get_image_url(article)
            post_url = get_post_url(article)

            print("======== 最新貼文 ========")
            print(f"發文時間：\n{post_time}")
            print(f"\n貼文內容：\n{post_content}")
            print(f"\n圖片網址：\n{image_url}")
            print(f"\n貼文網址：\n{post_url}")
            print("==========================")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
