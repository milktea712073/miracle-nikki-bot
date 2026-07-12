"""Fetch raw posts from the official Miracle Nikki Facebook page."""

import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

try:
    from crawler.models import Post
    from crawler.facebook_session import (
        create_browser_context,
        has_login_cookie,
        has_storage_state,
    )
except ModuleNotFoundError:
    from models import Post
    from facebook_session import create_browser_context, has_login_cookie, has_storage_state


LOGGER = logging.getLogger(__name__)

FACEBOOK_PAGE_URL: Final = "https://www.facebook.com/TwNikkiNikki"
OFFICIAL_PAGE_SLUG: Final = "TwNikkiNikki"
PAGE_TIMEOUT_MS: Final = 60_000
DISPLAY_TIMEZONE: Final = ZoneInfo("Asia/Taipei")
MAX_SCROLL_ATTEMPTS: Final = 30
MAX_CONSECUTIVE_NO_NEW_ROUNDS: Final = 5
SCROLL_DISTANCE: Final = 2_500
SCROLL_WAIT_MS: Final = 1_500
POST_LINK_SELECTOR: Final = (
    "a[href*='/posts/'], a[href*='/videos/'], a[href*='/permalink/'], "
    "a[href*='/reel/'], a[href*='story_fbid='], a[href*='fbid=']"
)
# Pinned page posts may be wrapped in a FeedUnit without exposing role=article.
POST_ARTICLE_SELECTOR: Final = (
    "div[role='article'], article, div[data-pagelet^='FeedUnit_']"
)
MESSAGE_SELECTORS: Final = (
    "[data-ad-preview='message']",
    "[data-ad-comet-preview='message']",
)


class FacebookCrawlerError(RuntimeError):
    """Raised when Facebook does not expose the requested post data."""


@dataclass(frozen=True, slots=True)
class TimelineCandidateDebug:
    """A timeline article observed while diagnosing Facebook DOM selection."""

    index: int
    text_preview: str
    html_class: str | None
    permalink: str | None
    is_pinned: bool
    hrefs: list[str]


@dataclass(frozen=True, slots=True)
class PostUrlCandidate:
    """One canonical post URL and the timeline sources that exposed it."""

    url: str
    sources: tuple[str, ...]


def first_text(locator: Locator, selectors: tuple[str, ...]) -> str:
    """Return text from the first matching descendant selector."""
    for selector in selectors:
        candidate = locator.locator(selector).first
        if candidate.count():
            text = candidate.inner_text().strip()
            if text:
                return text
    return ""


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


def normalize_post_url(href: str) -> str:
    """Remove tracking parameters while preserving query-style Facebook post IDs."""
    post_url = urlsplit(urljoin("https://www.facebook.com", href))
    query = parse_qs(post_url.query)
    identity_query = {
        key: query[key][0]
        for key in ("story_fbid", "fbid", "id")
        if query.get(key)
    }
    return urlunsplit(
        (
            post_url.scheme,
            post_url.netloc,
            post_url.path,
            urlencode(identity_query),
            "",
        )
    )


def get_post_url_from_hrefs(hrefs: list[str]) -> str:
    """Choose and normalize one Facebook post permalink from article links."""
    preferred_hrefs: list[str] = []
    fallback_hrefs: list[str] = []
    for href in hrefs:
        if not href:
            continue
        if any(
            marker in href
            for marker in ("/posts/", "/videos/", "/permalink/", "/reel/")
        ):
            preferred_hrefs.append(href)
        else:
            fallback_hrefs.append(href)
    for href in preferred_hrefs + fallback_hrefs:
        return normalize_post_url(href)
    raise FacebookCrawlerError("The post article did not contain a permalink.")


def get_href_snapshot(locator: Locator, source: str) -> list[str]:
    """Return a stable href snapshot without waiting on live nth locators.

    Facebook frequently replaces timeline nodes while the page is scrolling.  Reading
    all attributes in one browser-side evaluation avoids a stale ``nth(index)`` locator
    waiting for a node which no longer exists.
    """
    try:
        raw_hrefs = locator.evaluate_all(
            "elements => elements.map(element => element.getAttribute('href'))"
        )
    except Exception as error:  # Playwright may lose nodes while Facebook recycles DOM.
        LOGGER.warning("Could not snapshot %s hrefs; skipping this source: %s", source, error)
        return []

    if not isinstance(raw_hrefs, list):
        LOGGER.warning("Unexpected %s href snapshot result; skipping this source.", source)
        return []
    return [href for href in raw_hrefs if isinstance(href, str) and href]


def get_post_url(article: Locator) -> str:
    """Extract a canonical permalink from a Facebook post article."""
    return get_post_url_from_hrefs(
        get_href_snapshot(article.locator(POST_LINK_SELECTOR), "post container")
    )


def is_official_page_post_url(href: str) -> bool:
    """Return whether a link is a canonical post URL from the official page only."""
    parsed_url = urlsplit(urljoin("https://www.facebook.com", href))
    if parsed_url.netloc.lower() not in {"facebook.com", "www.facebook.com"}:
        return False
    return bool(
        re.fullmatch(rf"/{re.escape(OFFICIAL_PAGE_SLUG)}/posts/[^/]+/?", parsed_url.path)
    )


def merge_post_url_candidates(
    container_urls: list[str], page_anchor_urls: list[str]
) -> list[PostUrlCandidate]:
    """Canonicalize and merge candidate URLs without using timeline order as recency."""
    sources_by_url: dict[str, set[str]] = {}
    order: list[str] = []
    for source, urls in (("container", container_urls), ("page_anchor", page_anchor_urls)):
        for url in urls:
            if not is_official_page_post_url(url):
                continue
            canonical_url = normalize_post_url(url)
            if canonical_url not in sources_by_url:
                sources_by_url[canonical_url] = set()
                order.append(canonical_url)
            sources_by_url[canonical_url].add(source)
    return [
        PostUrlCandidate(url=url, sources=tuple(sorted(sources_by_url[url])))
        for url in order
    ]


def get_full_page_post_anchor_urls(page: Page) -> list[str]:
    """Collect official-page post permalinks from all anchors, not only articles."""
    return [
        href
        for href in get_href_snapshot(page.locator("a[href]"), "page-wide")
        if is_official_page_post_url(href)
    ]


def get_container_post_urls(page: Page) -> list[str]:
    """Collect post permalinks exposed inside current article or FeedUnit containers."""
    articles = page.locator(POST_ARTICLE_SELECTOR)
    try:
        raw_href_groups = articles.evaluate_all(
            """
            (elements, selector) => elements.map(
                article => Array.from(
                    article.querySelectorAll(selector),
                    link => link.getAttribute('href'),
                ),
            )
            """,
            POST_LINK_SELECTOR,
        )
    except Exception as error:  # Facebook can recycle FeedUnit nodes during evaluation.
        LOGGER.warning("Could not snapshot container hrefs; skipping this source: %s", error)
        return []

    if not isinstance(raw_href_groups, list):
        LOGGER.warning("Unexpected container href snapshot result; skipping this source.")
        return []

    post_urls: list[str] = []
    for raw_hrefs in raw_href_groups:
        if not isinstance(raw_hrefs, list):
            continue
        hrefs = [href for href in raw_hrefs if isinstance(href, str) and href]
        try:
            post_urls.append(get_post_url_from_hrefs(hrefs))
        except FacebookCrawlerError:
            continue
    return post_urls


def debug_page_post_anchors(page: Page) -> None:
    """Log DOM ancestry for official post anchors outside article/FeedUnit containers."""
    anchors = page.locator(f"a[href*='/{OFFICIAL_PAGE_SLUG}/posts/']")
    for index in range(anchors.count()):
        anchor = anchors.nth(index)
        href = anchor.get_attribute("href") or ""
        if not is_official_page_post_url(href):
            continue
        ancestry = anchor.evaluate(
            """
            element => {
                const nodes = [];
                let current = element;
                for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) {
                    nodes.push({
                        tag: current.tagName.toLowerCase(),
                        role: current.getAttribute('role'),
                        className: current.getAttribute('class'),
                        pagelet: current.getAttribute('data-pagelet'),
                        text: (current.innerText || '').replace(/\\s+/g, ' ').slice(0, 100),
                    });
                }
                return nodes;
            }
            """
        )
        LOGGER.info(
            "Page anchor index=%d canonical=%s ancestry=%s",
            index,
            normalize_post_url(href),
            ancestry,
        )


def get_post_id(post_url: str) -> str:
    """Extract Facebook's unique permalink identifier from a post URL."""
    parsed_url = urlsplit(post_url)
    query = parse_qs(parsed_url.query)
    for key in ("story_fbid", "fbid"):
        if query.get(key):
            page_id = query.get("id", [""])[0]
            return f"{page_id}_{query[key][0]}" if page_id else query[key][0]
    post_id = parsed_url.path.rstrip("/").split("/")[-1]
    if not post_id:
        raise FacebookCrawlerError(f"Could not derive a post ID from {post_url!r}.")
    return post_id


def get_post_article(page: Page) -> Locator:
    """Return the first article on the current page that has a post permalink."""
    articles = page.locator(POST_ARTICLE_SELECTOR)
    articles.first.wait_for(state="visible", timeout=PAGE_TIMEOUT_MS)

    for index in range(articles.count()):
        article = articles.nth(index)
        if article.locator(POST_LINK_SELECTOR).count():
            return article
    raise FacebookCrawlerError("Facebook loaded, but no post article was found.")


def debug_timeline_candidates(page: Page) -> list[TimelineCandidateDebug]:
    """Log every current timeline article to diagnose selector and permalink gaps."""
    articles = page.locator(POST_ARTICLE_SELECTOR)
    candidates: list[TimelineCandidateDebug] = []
    for index in range(articles.count()):
        article = articles.nth(index)
        try:
            text = article.inner_text().strip()
        except PlaywrightTimeoutError:
            text = ""
        try:
            permalink = get_post_url(article)
        except FacebookCrawlerError:
            permalink = None
        all_links = article.locator("a[href]")
        hrefs = [
            all_links.nth(link_index).get_attribute("href") or ""
            for link_index in range(all_links.count())
        ]
        is_pinned = bool(re.search(r"置頂|已置頂|pinned(?: post)?", text, re.I))
        candidate = TimelineCandidateDebug(
            index=index,
            text_preview=re.sub(r"\s+", " ", text)[:100],
            html_class=article.get_attribute("class"),
            permalink=permalink,
            is_pinned=is_pinned,
            hrefs=hrefs,
        )
        candidates.append(candidate)
        LOGGER.info(
            "Timeline candidate index=%d class=%r pinned=%s permalink_found=%s "
            "permalink=%s text=%r hrefs=%s",
            candidate.index,
            candidate.html_class,
            candidate.is_pinned,
            candidate.permalink is not None,
            candidate.permalink,
            candidate.text_preview,
            candidate.hrefs,
        )
    return candidates


def collect_post_url_candidates(
    page: Page, limit: int, debug: bool = False
) -> list[PostUrlCandidate]:
    """Collect official post candidates across repeated timeline scrolls.

    Facebook can defer ordinary posts and render pinned posts outside FeedUnit/article
    containers.  Every round therefore scans both container links and the complete page,
    retaining the first discovery order while tracking canonical URLs separately.
    """
    if limit <= 0:
        return []

    ordered_urls: list[str] = []
    seen_urls: set[str] = set()
    sources_by_url: dict[str, set[str]] = {}
    total_container_urls: set[str] = set()
    total_page_anchor_urls: set[str] = set()
    no_new_rounds = 0
    stop_reason = "maximum scroll rounds"

    if debug:
        debug_timeline_candidates(page)
        debug_page_post_anchors(page)

    # Facebook adds FeedUnit and pinned-post anchors after domcontentloaded.
    page.wait_for_timeout(SCROLL_WAIT_MS)

    for round_number in range(1, MAX_SCROLL_ATTEMPTS + 1):
        container_urls = get_container_post_urls(page)
        page_anchor_urls = get_full_page_post_anchor_urls(page)
        round_new = 0

        for source, urls, total_urls in (
            ("container", container_urls, total_container_urls),
            ("page_anchor", page_anchor_urls, total_page_anchor_urls),
        ):
            for url in urls:
                if not is_official_page_post_url(url):
                    continue
                canonical_url = normalize_post_url(url)
                total_urls.add(canonical_url)
                sources_by_url.setdefault(canonical_url, set()).add(source)
                if canonical_url in seen_urls:
                    continue
                seen_urls.add(canonical_url)
                ordered_urls.append(canonical_url)
                round_new += 1
                if len(ordered_urls) >= limit:
                    break
            if len(ordered_urls) >= limit:
                break

        no_new_rounds = 0 if round_new else no_new_rounds + 1
        LOGGER.info(
            "Facebook permalink scroll round=%d container_candidates=%d "
            "page_anchor_candidates=%d new=%d total=%d no_new_rounds=%d",
            round_number,
            len(container_urls),
            len(page_anchor_urls),
            round_new,
            len(ordered_urls),
            no_new_rounds,
        )

        if len(ordered_urls) >= limit:
            stop_reason = "reached limit"
            break
        if no_new_rounds >= MAX_CONSECUTIVE_NO_NEW_ROUNDS:
            stop_reason = "consecutive no-new rounds"
            break
        if round_number == MAX_SCROLL_ATTEMPTS:
            break

        page.mouse.wheel(0, SCROLL_DISTANCE)
        page.wait_for_timeout(SCROLL_WAIT_MS)

    candidates = [
        PostUrlCandidate(url=url, sources=tuple(sorted(sources_by_url[url])))
        for url in ordered_urls[:limit]
    ]
    LOGGER.info(
        "Facebook permalink collection stopped: reason=%s container_candidates=%d "
        "page_anchor_candidates=%d merged_candidates=%d",
        stop_reason,
        len(total_container_urls),
        len(total_page_anchor_urls),
        len(candidates),
    )
    if debug:
        for candidate in candidates:
            LOGGER.info("Candidate sources=%s canonical=%s", candidate.sources, candidate.url)
    if len(candidates) < limit:
        LOGGER.warning(
            "Facebook exposed %d of %d requested posts. "
            "A logged-in persistent browser session may expose more.",
            len(candidates),
            limit,
        )
    return candidates


def collect_post_urls(page: Page, limit: int, debug: bool = False) -> list[str]:
    """Return canonical candidate URLs while preserving existing public API shape."""
    return [candidate.url for candidate in collect_post_url_candidates(page, limit, debug)]


def get_published_at(page: Page) -> datetime:
    """Extract an absolute publication time from a post detail page."""
    time_elements = page.locator("time[datetime]")
    for index in range(time_elements.count()):
        value = time_elements.nth(index).get_attribute("datetime")
        if not value:
            continue
        try:
            published_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=DISPLAY_TIMEZONE)
        return published_at.astimezone(DISPLAY_TIMEZONE)

    unix_time_elements = page.locator("[data-utime], [data-timestamp]")
    for index in range(unix_time_elements.count()):
        value = unix_time_elements.nth(index).get_attribute("data-utime")
        value = value or unix_time_elements.nth(index).get_attribute("data-timestamp")
        if value and value.isdigit():
            return datetime.fromtimestamp(int(value), DISPLAY_TIMEZONE)

    timestamp = re.search(
        r'"(?:publish_time|creation_time)":(\d{10})', page.content()
    )
    if timestamp:
        return datetime.fromtimestamp(int(timestamp.group(1)), DISPLAY_TIMEZONE)

    raise FacebookCrawlerError(
        "Facebook did not expose an absolute publication time. "
        "Use a persistent Playwright context with a logged-in Facebook session."
    )


def get_image_urls(container: Page | Locator) -> list[str]:
    """Return unique announcement images from a post article in DOM order."""
    images = container.locator("img[src*='scontent']")
    urls: list[str] = []
    seen_urls: set[str] = set()

    for index in range(images.count()):
        image = images.nth(index)
        url = image.get_attribute("src")
        if not url:
            continue

        dimensions = image.evaluate("image => ({width: image.width, height: image.height})")
        if dimensions["width"] <= 64 and dimensions["height"] <= 64:
            continue

        parsed_url = urlsplit(url)
        image_key = f"{parsed_url.netloc}{parsed_url.path}"
        if image_key in seen_urls:
            continue

        seen_urls.add(image_key)
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


def get_full_post_content(container: Locator) -> str:
    """Return the full message text from a post detail article."""
    expanded = expand_post_content(container)
    content = first_text(container, MESSAGE_SELECTORS) or container.inner_text().strip()
    content = re.sub(r"\n\+\d+$", "", content).strip()
    if content and not content.endswith(("\u67e5\u770b\u66f4\u591a", "See more")):
        return content
    if not expanded:
        raise FacebookCrawlerError(
            "Facebook blocked expanding the full post in anonymous mode. "
            "Use a persistent Playwright context with a logged-in Facebook session."
        )
    raise FacebookCrawlerError(
        "Facebook did not expose the full post content. "
        "Use a persistent Playwright context with a logged-in Facebook session."
    )


def get_logged_in_message_container(page: Page) -> Locator:
    """Find the main post card in Facebook's logged-in post layout."""
    page_title = page.title()
    if " - " in page_title:
        title_hint = page_title.split(" - ", maxsplit=1)[1].split(" | Facebook", maxsplit=1)[0]
        title_hint = title_hint.strip()[:8]
        if title_hint:
            title_node = page.locator("div[dir='auto']").filter(
                has_text=title_hint
            ).first
            if title_node.count():
                post_card = title_node.locator("xpath=ancestor::div[8]")
                if post_card.count():
                    return post_card.nth(0)

    candidates = page.locator("div[dir='auto']")
    best_card: Locator | None = None
    best_score = -1
    for index in range(candidates.count()):
        candidate = candidates.nth(index)
        text = candidate.inner_text().strip()
        if not text:
            continue
        card = candidate.locator("xpath=ancestor::div[8]")
        if not card.count():
            continue
        card = card.nth(0)
        score = card.locator("img[src*='scontent']").count() * 10_000 + len(card.inner_text())
        if score > best_score:
            best_card = card
            best_score = score

    if best_card is None:
        raise FacebookCrawlerError("Facebook did not expose a post message container.")
    return best_card


def open_post_detail(page: Page, post_url: str) -> Locator:
    """Open a permalink and return the detail page's post article."""
    page.goto(post_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    dismiss_cookie_dialog(page)
    message = page.locator(
        "[data-ad-preview='message'], [data-ad-comet-preview='message']"
    ).first
    try:
        message.wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError:
        LOGGER.info("Using the logged-in Facebook message layout for %s", post_url)
        page.wait_for_timeout(2_000)
        return get_logged_in_message_container(page)

    page.wait_for_timeout(2_000)
    article = get_post_article(page)
    if first_text(article, MESSAGE_SELECTORS):
        return article

    LOGGER.info("Using the logged-in Facebook message layout for %s", post_url)
    return get_logged_in_message_container(page)


def parse_post(page: Page, post_url: str) -> Post:
    """Parse one post detail page into the crawler's raw data model."""
    article = open_post_detail(page, post_url)
    return Post(
        post_id=get_post_id(post_url),
        url=post_url,
        content=get_full_post_content(article),
        published_at=get_published_at(page),
        images=get_image_urls(article),
    )


def sort_posts_by_published_at(posts: list[Post]) -> list[Post]:
    """Sort parsed posts newest first only after absolute publish times are available."""
    return sorted(posts, key=lambda post: post.published_at, reverse=True)


def parse_post_candidates(
    page: Page, candidates: list[PostUrlCandidate], debug: bool = False
) -> list[Post]:
    """Parse every candidate, logging and continuing when an individual post fails."""
    posts: list[Post] = []
    for candidate in candidates:
        try:
            LOGGER.info("Parsing Facebook post sources=%s url=%s", candidate.sources, candidate.url)
            post = parse_post(page, candidate.url)
            posts.append(post)
            if debug:
                LOGGER.info(
                    "Parsed post success url=%s published_at=%s",
                    post.url,
                    post.published_at.isoformat(),
                )
        except FacebookCrawlerError as error:
            LOGGER.warning("Skipping Facebook post %s: %s", candidate.url, error)
    return posts


def get_latest_posts(limit: int, debug: bool = False) -> list[Post]:
    """Fetch up to ``limit`` newest posts from the official Facebook page."""
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = create_browser_context(browser)
        try:
            if has_storage_state() and not has_login_cookie(context):
                LOGGER.warning(
                    "Facebook storage state has no active login cookie. "
                    "It may be expired; run python crawler/facebook_login.py."
                )

            page = context.new_page()
            page.goto(
                FACEBOOK_PAGE_URL,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT_MS,
            )
            dismiss_cookie_dialog(page)
            candidates = collect_post_url_candidates(page, limit, debug=debug)
            if not candidates:
                raise FacebookCrawlerError("No Facebook post permalinks were found.")
            if has_storage_state() and len(candidates) < limit:
                LOGGER.warning(
                    "The saved Facebook session exposed fewer posts than requested. "
                    "It may be expired; run python crawler/facebook_login.py."
                )

            posts = parse_post_candidates(page, candidates, debug=debug)

            if not posts:
                raise FacebookCrawlerError("Facebook posts were found but none could be parsed.")
            return sort_posts_by_published_at(posts)[:limit]
        finally:
            context.close()
            browser.close()


def fetch_latest_post() -> dict[str, str | list[str]]:
    """Return the newest post in the legacy dictionary format."""
    post = get_latest_posts(1)[0]
    return {
        "publish_time": post.published_at.strftime("%Y/%m/%d %H:%M"),
        "content": post.content,
        "image_urls": post.images,
        "post_url": post.url,
    }


def main() -> None:
    """Fetch and print the newest post for command-line testing."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Miracle Nikki Facebook posts.")
    parser.add_argument("--limit", type=int, default=1, help="Number of posts to fetch.")
    parser.add_argument("--debug", action="store_true", help="Log all timeline article candidates.")
    args = parser.parse_args()
    post = get_latest_posts(args.limit, debug=args.debug)[0]
    print("======== \u6700\u65b0\u8cbc\u6587 ========")
    print(f"post_id:\n{post.post_id}")
    print(f"\u767c\u5e03\u65e5\u671f\uff1a\n{post.published_at:%Y/%m/%d %H:%M}")
    print(f"\n\u8cbc\u6587\u5167\u5bb9\uff1a\n{post.content}")
    print(f"\n\u5716\u7247\u7db2\u5740\uff1a\n{post.images}")
    print(f"\n\u8cbc\u6587\u7db2\u5740\uff1a\n{post.url}")
    print("==========================")


if __name__ == "__main__":
    main()
