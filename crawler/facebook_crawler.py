"""Fetch raw posts from the official Miracle Nikki Facebook page."""

import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import (
    Locator,
    Page,
    Response,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

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
MAIN_POST_CONTAINER_SELECTORS: Final = (
    "div[role='article'], article",
    "div[data-pagelet^='FeedUnit_']",
)
STORY_MESSAGE_SELECTOR: Final = '[data-ad-rendering-role="story_message"]'
MAX_STORY_MESSAGE_ANCESTOR_DEPTH: Final = 10
OFFICIAL_PAGE_DISPLAY_NAMES: Final = ("奇迹暖暖", "奇蹟暖暖")
MESSAGE_SELECTORS: Final = (
    "[data-ad-preview='message']",
    "[data-ad-comet-preview='message']",
)
PROFILE_TIMELINE_FEED_OPERATION: Final = "ProfileCometTimelineFeedRefetchQuery"
GRAPHQL_PERMALINK_FIELDS: Final = ("permalink_url", "wwwURL")


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


def graphql_operation_name(post_data: str | None) -> str | None:
    """Return a GraphQL operation name without retaining request payload data."""
    if not post_data:
        return None
    form_values = parse_qs(post_data, keep_blank_values=True)
    values = form_values.get("fb_api_req_friendly_name")
    if values and values[0]:
        return values[0]
    try:
        payload = json.loads(post_data)
    except json.JSONDecodeError:
        return None
    value = payload.get("operationName") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


def iter_graphql_json_documents(body: str):
    """Yield Facebook's concatenated JSON documents without storing response bodies."""
    payload = body.lstrip().removeprefix("for (;;);").strip()
    decoder = json.JSONDecoder()
    index = 0
    while index < len(payload):
        while index < len(payload) and payload[index].isspace():
            index += 1
        if index >= len(payload):
            return
        try:
            document, index = decoder.raw_decode(payload, index)
        except json.JSONDecodeError:
            return
        yield document


def get_graphql_permalink_urls(document: object) -> list[str]:
    """Read only trusted permalink fields from one GraphQL JSON document."""
    urls: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in GRAPHQL_PERMALINK_FIELDS and isinstance(child, str):
                    if child.startswith("https://www.facebook.com/") and is_official_page_post_url(child):
                        urls.append(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    return urls


class GraphQLPermalinkCollector:
    """Collect official timeline permalinks emitted before Facebook renders DOM cards."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def attach(self, page: Page) -> None:
        page.on("response", self._handle_response)

    def _handle_response(self, response: Response) -> None:
        if "/api/graphql" not in urlsplit(response.url).path:
            return
        if graphql_operation_name(response.request.post_data) != PROFILE_TIMELINE_FEED_OPERATION:
            return
        try:
            body = response.text()
        except Exception as error:
            LOGGER.warning("Could not read Facebook timeline GraphQL response: %s", error)
            return
        for document in iter_graphql_json_documents(body):
            for url in get_graphql_permalink_urls(document):
                self.urls.append(url)


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


def is_official_page_author_href(href: str) -> bool:
    """Return whether an author/profile href belongs to the official page itself."""
    parsed_url = urlsplit(urljoin("https://www.facebook.com", href))
    return (
        parsed_url.netloc.lower() in {"facebook.com", "www.facebook.com"}
        and parsed_url.path.rstrip("/").casefold() == f"/{OFFICIAL_PAGE_SLUG}".casefold()
    )


def has_official_page_identity(container: Locator, hrefs: list[str]) -> bool:
    """Check official author identity from a card's links or visible author label."""
    if any(is_official_page_author_href(href) for href in hrefs):
        return True
    try:
        text = container.inner_text()
    except PlaywrightTimeoutError:
        return False
    return any(name in text for name in OFFICIAL_PAGE_DISPLAY_NAMES)


def has_post_time(container: Locator) -> bool:
    """Return whether a card exposes a visible or accessible post-time region."""
    try:
        candidates = get_time_attribute_candidates(container)
    except PlaywrightTimeoutError:
        return False
    if any(
        parse_facebook_time_value(candidate["value"]) is not None
        for candidate in candidates
    ):
        return True
    try:
        text = container.inner_text()
    except PlaywrightTimeoutError:
        return False
    return bool(re.search(r"(?:\d+\s*(?:分鐘|小時|天|週|周|月|年)|昨天|剛剛)", text))


def get_time_attribute_candidates(container: Locator) -> list[dict[str, str]]:
    """Return labelled timestamp candidates from one already-trusted post card."""
    return container.locator(
        "time[datetime], [data-utime], [data-timestamp], [aria-label], [title]"
    ).evaluate_all(
        """
        elements => elements.flatMap(element => [
            ['datetime', element.getAttribute('datetime')],
            ['data-utime', element.getAttribute('data-utime')],
            ['data-timestamp', element.getAttribute('data-timestamp')],
            ['aria-label', element.getAttribute('aria-label')],
            ['title', element.getAttribute('title')],
        ].filter(([, value]) => value).map(([source, value]) => ({source, value})))
        """
    )


def parse_facebook_time_value(value: str) -> datetime | None:
    """Parse an absolute Facebook timestamp from DOM attributes or labels."""
    value = value.strip()
    if value.isdigit() and len(value) >= 10:
        return datetime.fromtimestamp(int(value), DISPLAY_TIMEZONE)

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=DISPLAY_TIMEZONE)
        return parsed.astimezone(DISPLAY_TIMEZONE)

    matched = re.search(
        r"(?P<year>\d{4})(?:[/-]|年)(?P<month>\d{1,2})(?:[/-]|月)(?P<day>\d{1,2})(?:日)?"
        r"(?:\D+(?P<period>上午|下午|AM|PM|am|pm))?\D*"
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})",
        value,
    )
    if not matched:
        return None
    hour = int(matched.group("hour"))
    period = (matched.group("period") or "").casefold()
    if period in {"下午", "pm"} and hour < 12:
        hour += 12
    elif period in {"上午", "am"} and hour == 12:
        hour = 0
    try:
        return datetime(
            int(matched.group("year")),
            int(matched.group("month")),
            int(matched.group("day")),
            hour,
            int(matched.group("minute")),
            tzinfo=DISPLAY_TIMEZONE,
        )
    except ValueError:
        return None


def describe_container(container: Locator) -> dict[str, str | None]:
    """Return minimal DOM metadata for debug logging without serialising page HTML."""
    try:
        return container.evaluate(
            """
            element => ({
                tag: element.tagName.toLowerCase(),
                role: element.getAttribute('role'),
                className: element.getAttribute('class'),
            })
            """
        )
    except PlaywrightTimeoutError:
        return {"tag": None, "role": None, "className": None}


def is_story_message_card(
    container: Locator,
    post_url: str,
    page_url: str,
) -> tuple[bool, dict[str, bool | int]]:
    """Validate a smallest story-message ancestor as the official post card."""
    hrefs = get_href_snapshot(container.locator("a[href]"), "detail story card")
    expected_url = normalize_post_url(post_url)
    has_permalink = any(
        is_official_page_post_url(href) and normalize_post_url(href) == expected_url
        for href in hrefs
    )
    has_author = has_official_page_identity(container, hrefs)
    has_time = has_post_time(container)
    try:
        story_count = container.locator(STORY_MESSAGE_SELECTOR).count()
    except PlaywrightTimeoutError:
        story_count = 0
    try:
        image_count = container.locator("img[src*='scontent']").count()
    except PlaywrightTimeoutError:
        image_count = 0

    # A detail URL may omit a canonical anchor in its rendered card.  It is only
    # accepted as supporting evidence after author, time, and a single message
    # establish that this is the main card rather than a comment aggregate.
    page_matches_target = normalize_post_url(page_url) == expected_url
    trusted = (
        story_count == 1
        and has_author
        and has_time
        and (has_permalink or page_matches_target)
    )
    return trusted, {
        "official_author": has_author,
        "permalink": has_permalink,
        "time": has_time,
        "images": image_count,
        "story_count": story_count,
    }


def find_main_post_story_container(page: Page, post_url: str, debug: bool = False) -> Locator | None:
    """Find the smallest verified card surrounding a rendered story message."""
    story_messages = page.locator(STORY_MESSAGE_SELECTOR)
    if debug:
        LOGGER.info("Facebook detail story_message_count=%d", story_messages.count())

    for message_index in range(story_messages.count()):
        container = story_messages.nth(message_index)
        text_only_fallback: Locator | None = None
        for depth in range(1, MAX_STORY_MESSAGE_ANCESTOR_DEPTH + 1):
            container = container.locator("xpath=..")
            if not container.count():
                break
            trusted, details = is_story_message_card(container, post_url, page.url)
            if debug:
                metadata = describe_container(container)
                LOGGER.info(
                    "Facebook detail story_message index=%d depth=%d tag=%s role=%s "
                    "class=%r author=%s permalink=%s time=%s images=%d "
                    "story_count=%d selected=%s",
                    message_index,
                    depth,
                    metadata["tag"],
                    metadata["role"],
                    metadata["className"],
                    details["official_author"],
                    details["permalink"],
                    details["time"],
                    details["images"],
                    details["story_count"],
                    trusted and bool(details["images"]),
                )
            if trusted:
                if details["images"]:
                    if debug:
                        LOGGER.info(
                            "Facebook detail selected story-message card index=%d depth=%d url=%s",
                            message_index,
                            depth,
                            post_url,
                        )
                    return container
                text_only_fallback = text_only_fallback or container
        if text_only_fallback is not None:
            if debug:
                LOGGER.info(
                    "Facebook detail selected text-only story-message card index=%d url=%s",
                    message_index,
                    post_url,
                )
            return text_only_fallback
    return None


def is_matching_main_post_container(hrefs: list[str], post_url: str) -> bool:
    """Require both the requested permalink and the official page author link."""
    expected_url = normalize_post_url(post_url)
    has_permalink = any(
        is_official_page_post_url(href) and normalize_post_url(href) == expected_url
        for href in hrefs
    )
    return has_permalink and any(is_official_page_author_href(href) for href in hrefs)


def log_main_post_container_diagnostics(page: Page, post_url: str) -> None:
    """Log why each detail-page article is or is not the requested main post."""
    expected_url = normalize_post_url(post_url)
    articles = page.locator(POST_ARTICLE_SELECTOR)
    LOGGER.info(
        "Facebook detail diagnostics url=%s article_count=%d", post_url, articles.count()
    )
    for index in range(articles.count()):
        article = articles.nth(index)
        hrefs = get_href_snapshot(article.locator("a[href]"), f"detail article {index}")
        has_official_author = any(is_official_page_author_href(href) for href in hrefs)
        has_permalink = any(
            is_official_page_post_url(href) and normalize_post_url(href) == expected_url
            for href in hrefs
        )
        try:
            text_length = len(article.inner_text().strip())
        except PlaywrightTimeoutError:
            text_length = 0
        try:
            image_count = article.locator("img[src*='scontent']").count()
        except PlaywrightTimeoutError:
            image_count = 0
        if not has_permalink:
            reason = "missing_requested_permalink"
        elif not has_official_author:
            reason = "missing_official_author"
        else:
            reason = "eligible"
        LOGGER.info(
            "Facebook detail article index=%d official_author=%s permalink=%s "
            "text_length=%d image_count=%d result=%s",
            index,
            has_official_author,
            has_permalink,
            text_length,
            image_count,
            reason,
        )


def get_main_post_article(page: Page, post_url: str, debug: bool = False) -> Locator:
    """Locate only the official main-post container for the requested permalink."""
    if debug:
        log_main_post_container_diagnostics(page, post_url)
    story_container = find_main_post_story_container(page, post_url, debug=debug)
    if story_container is not None:
        return story_container
    # Prefer the smallest article-level container. FeedUnit is only a fallback for
    # layouts which do not expose role=article around the primary post.
    for selector in MAIN_POST_CONTAINER_SELECTORS:
        containers = page.locator(selector)
        for index in range(containers.count()):
            container = containers.nth(index)
            hrefs = get_href_snapshot(
                container.locator("a[href]"), f"detail container {index}"
            )
            if is_matching_main_post_container(hrefs, post_url):
                if debug:
                    LOGGER.info(
                        "Facebook detail selected trusted main-post container url=%s", post_url
                    )
                return container
    if debug:
        LOGGER.info(
            "Facebook detail rejected url=%s reason=no_trusted_main_post_container", post_url
        )
    raise FacebookCrawlerError(
        "Facebook did not expose a trusted official main-post container for this permalink."
    )


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
    page: Page,
    limit: int,
    debug: bool = False,
    graphql_collector: GraphQLPermalinkCollector | None = None,
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
    total_graphql_urls: set[str] = set()
    accepted_source_urls = 0
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
        graphql_urls = graphql_collector.urls if graphql_collector is not None else []
        round_new = 0

        for source, urls, total_urls in (
            ("graphql", graphql_urls, total_graphql_urls),
            ("container", container_urls, total_container_urls),
            ("page_anchor", page_anchor_urls, total_page_anchor_urls),
        ):
            for url in urls:
                if not is_official_page_post_url(url):
                    continue
                canonical_url = normalize_post_url(url)
                accepted_source_urls += 1
                total_urls.add(canonical_url)
                sources_by_url.setdefault(canonical_url, set()).add(source)
                if canonical_url in seen_urls:
                    continue
                if len(ordered_urls) >= limit:
                    continue
                seen_urls.add(canonical_url)
                ordered_urls.append(canonical_url)
                if debug and source == "graphql":
                    LOGGER.info("Facebook GraphQL added permalink: %s", canonical_url)
                round_new += 1

        no_new_rounds = 0 if round_new else no_new_rounds + 1
        LOGGER.info(
            "Facebook permalink scroll round=%d container_candidates=%d "
            "page_anchor_candidates=%d graphql_candidates=%d new=%d total=%d "
            "no_new_rounds=%d",
            round_number,
            len(container_urls),
            len(page_anchor_urls),
            len(graphql_urls),
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
        "page_anchor_candidates=%d graphql_candidates=%d merged_candidates=%d "
        "deduped_candidates=%d returned_candidates=%d",
        stop_reason,
        len(total_container_urls),
        len(total_page_anchor_urls),
        len(total_graphql_urls),
        len(sources_by_url),
        accepted_source_urls - len(sources_by_url),
        len(candidates),
    )
    if debug:
        LOGGER.info(
            "Facebook permalink debug DOM permalink=%d GraphQL permalink=%d Merge=%d Dedupe=%d",
            len(total_container_urls | total_page_anchor_urls),
            len(total_graphql_urls),
            len(sources_by_url),
            accepted_source_urls - len(sources_by_url),
        )
        for candidate in candidates:
            source = "+".join(candidate.sources)
            LOGGER.info("Facebook permalink source=%s canonical=%s", source, candidate.url)
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


def get_published_at(container: Locator, debug: bool = False) -> datetime:
    """Extract an absolute publication time from a post detail page."""
    for candidate in get_time_attribute_candidates(container):
        published_at = parse_facebook_time_value(candidate["value"])
        if debug:
            LOGGER.info(
                "Facebook detail time candidate source=%s value=%r selected_main_card=true "
                "accepted=%s",
                candidate["source"],
                candidate["value"],
                published_at is not None,
            )
        if published_at is not None:
            return published_at

    if debug:
        LOGGER.info(
            "Facebook detail time rejected reason=no_absolute_candidate_in_selected_main_card"
        )

    raise FacebookCrawlerError(
        "Facebook did not expose an absolute publication time in the main post container. "
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


def get_message_text(message: Locator) -> str:
    """Read one message node while restoring Facebook emoji images in DOM order.

    Facebook renders inline emoji as small ``img`` nodes whose ``alt`` contains the
    emoji. Playwright's ``inner_text`` omits those nodes, while ``text_content`` also
    loses the rendered line breaks. Clone only the selected message node, replace
    Facebook's emoji images with text nodes, then read its rendered text. Regular
    post images and accessibility labels are deliberately left untouched.
    """
    text = message.evaluate(
        r"""
        element => {
            const clone = element.cloneNode(true);
            for (const image of clone.querySelectorAll('img[alt]')) {
                const source = image.getAttribute('src') || '';
                const alt = (image.getAttribute('alt') || '').trim();
                const isFacebookEmoji = /\/images\/emoji\.php(?:[/?]|$)/.test(source);
                if (isFacebookEmoji && alt && alt.length <= 16) {
                    image.replaceWith(document.createTextNode(alt));
                }
            }
            const sandbox = document.createElement('div');
            sandbox.style.cssText = 'position:fixed;left:-99999px;top:0;opacity:0;pointer-events:none;';
            sandbox.append(clone);
            document.body.append(sandbox);
            const text = clone.innerText || '';
            sandbox.remove();
            return text;
        }
        """
    )
    return text.strip() if isinstance(text, str) else ""


def get_full_post_content(container: Locator) -> str:
    """Return the full message text from a post detail article."""
    expanded = expand_post_content(container)
    content = ""
    for selector in MESSAGE_SELECTORS:
        message = container.locator(selector).first
        if not message.count():
            continue
        content = get_message_text(message)
        if content:
            break
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


def open_post_detail(page: Page, post_url: str, debug: bool = False) -> Locator:
    """Open a permalink and return its trusted official main-post container."""
    page.goto(post_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    dismiss_cookie_dialog(page)
    for attempt in range(2):
        page.wait_for_timeout(2_000)
        try:
            # Keep the normal call shape for existing integrations and test doubles.
            # Diagnostic output is opt-in through the debug path only.
            return (
                get_main_post_article(page, post_url, debug=True)
                if debug
                else get_main_post_article(page, post_url)
            )
        except FacebookCrawlerError:
            if attempt == 0:
                LOGGER.info("Reloading Facebook detail page to locate main post: %s", post_url)
                page.reload(wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                dismiss_cookie_dialog(page)
                continue
            raise

    raise FacebookCrawlerError("Facebook did not expose a trusted main post.")


def parse_post(page: Page, post_url: str, debug: bool = False) -> Post:
    """Parse one post detail page into the crawler's raw data model."""
    article = (
        open_post_detail(page, post_url, debug=True)
        if debug
        else open_post_detail(page, post_url)
    )
    try:
        published_at = get_published_at(article, debug=debug)
    except FacebookCrawlerError:
        LOGGER.warning(
            "Facebook did not expose an absolute publication time for %s; "
            "saving the trusted post without published_at.",
            post_url,
        )
        published_at = None
    return Post(
        post_id=get_post_id(post_url),
        url=post_url,
        content=get_full_post_content(article),
        published_at=published_at,
        images=get_image_urls(article),
    )


def sort_posts_by_published_at(posts: list[Post]) -> list[Post]:
    """Sort parsed posts newest first only after absolute publish times are available."""
    return sorted(
        posts,
        key=lambda post: post.published_at or datetime.min.replace(tzinfo=DISPLAY_TIMEZONE),
        reverse=True,
    )


def parse_post_candidates(
    page: Page, candidates: list[PostUrlCandidate], debug: bool = False
) -> list[Post]:
    """Parse every candidate, logging and continuing when an individual post fails."""
    posts: list[Post] = []
    for candidate in candidates:
        try:
            LOGGER.info("Parsing Facebook post sources=%s url=%s", candidate.sources, candidate.url)
            post = (
                parse_post(page, candidate.url, debug=True)
                if debug
                else parse_post(page, candidate.url)
            )
            posts.append(post)
            if debug:
                LOGGER.info(
                    "Parsed post success url=%s published_at=%s",
                    post.url,
                    post.published_at.isoformat() if post.published_at else None,
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
            graphql_collector = GraphQLPermalinkCollector()
            graphql_collector.attach(page)
            page.goto(
                FACEBOOK_PAGE_URL,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT_MS,
            )
            dismiss_cookie_dialog(page)
            candidates = collect_post_url_candidates(
                page,
                limit,
                debug=debug,
                graphql_collector=graphql_collector,
            )
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
            # Discovery order is the only available ordering when Facebook omits
            # publication metadata. Permanent de-duplication remains permalink-based.
            return posts[:limit]
        finally:
            context.close()
            browser.close()


def fetch_latest_post() -> dict[str, str | list[str] | None]:
    """Return the newest post in the legacy dictionary format."""
    post = get_latest_posts(1)[0]
    return {
        "publish_time": (
            post.published_at.strftime("%Y/%m/%d %H:%M")
            if post.published_at is not None
            else None
        ),
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
    publish_time = (
        post.published_at.strftime("%Y/%m/%d %H:%M")
        if post.published_at is not None
        else "未提供"
    )
    print(f"\u767c\u5e03\u65e5\u671f\uff1a\n{publish_time}")
    print(f"\n\u8cbc\u6587\u5167\u5bb9\uff1a\n{post.content}")
    print(f"\n\u5716\u7247\u7db2\u5740\uff1a\n{post.images}")
    print(f"\n\u8cbc\u6587\u7db2\u5740\uff1a\n{post.url}")
    print("==========================")


if __name__ == "__main__":
    main()
