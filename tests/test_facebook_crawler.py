import json
import logging
from datetime import datetime, timezone

import pytest
from playwright.sync_api import sync_playwright

from crawler import facebook_crawler
from crawler.facebook_crawler import (
    FacebookCrawlerError,
    GraphQLPermalinkCollector,
    POST_ARTICLE_SELECTOR,
    STORY_MESSAGE_SELECTOR,
    PostUrlCandidate,
    collect_post_url_candidates,
    get_full_post_content,
    get_container_post_urls,
    get_full_page_post_anchor_urls,
    get_graphql_permalink_urls,
    get_image_urls,
    get_main_post_article,
    get_post_id,
    get_post_url_from_hrefs,
    get_published_at,
    log_main_post_container_diagnostics,
    is_matching_main_post_container,
    is_official_page_post_url,
    merge_post_url_candidates,
    normalize_post_url,
    parse_post_candidates,
    open_post_detail,
    parse_facebook_time_value,
    sort_posts_by_published_at,
)
from crawler.models import Post
from database.raw_post_repository import RawPostRepository


PINNED_POST_URL = (
    "https://www.facebook.com/TwNikkiNikki/posts/"
    "pfbid0ZAnKybeGDVLcJb9mQr79KYPntaM7SxebX91d2okJt2U4UeJifHMi7qLVfwnT6BE2l"
)
SUMMER_LOGIN_POST_URL = (
    "https://www.facebook.com/TwNikkiNikki/posts/"
    "pfbid024fEMTnJULdMspSPnoB4LpTZAKj592wS1H3RQzeU12sbnyPZPdZELPiX5dVeKMb89l"
)
COMMENT_POLLUTION_POST_URL = (
    "https://www.facebook.com/TwNikkiNikki/posts/"
    "pfbid02p3edBBdE9sr6wqfz1QGNUwADh8QLUJ7NfYVcu3AshuQPUTNySi8oVVQVSrserLMZl"
)
LATER_REGULAR_POST_URL = (
    "https://www.facebook.com/TwNikkiNikki/posts/"
    "pfbid02RWjU2KzU2mTYFTSQXPcu2s6ujyif6FfpqFEBnTew7A6d8GL4zbWRBoxqen5z9pVLl"
)


class FakeMouse:
    """Minimal Playwright mouse replacement that advances a scripted page."""

    def __init__(self, page):
        self.page = page
        self.wheel_calls = 0

    def wheel(self, _x, _y):
        self.wheel_calls += 1
        self.page.advance_round()


class FakePage:
    """A scrollable mocked Facebook page with one DOM snapshot per round."""

    def __init__(self, rounds):
        self.rounds = rounds
        self.round_index = 0
        self.mouse = FakeMouse(self)
        self.waits = []

    @property
    def current_round(self):
        return self.rounds[min(self.round_index, len(self.rounds) - 1)]

    def advance_round(self):
        self.round_index += 1

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


class SnapshotLocator:
    """Locator mock that fails if collection tries to read a live nth element."""

    def __init__(self, snapshot, error=None):
        self.snapshot = snapshot
        self.error = error
        self.evaluate_calls = []

    def evaluate_all(self, script, *args):
        self.evaluate_calls.append((script, args))
        if self.error:
            raise self.error
        return self.snapshot

    def count(self):
        raise AssertionError("permalink collection must not call Locator.count()")

    def nth(self, _index):
        raise AssertionError("permalink collection must not call Locator.nth()")


class SnapshotPage:
    """Page mock exposing stable snapshots for page-wide and container anchors."""

    def __init__(self, page_hrefs, container_href_groups, page_error=None, container_error=None):
        self.page_anchors = SnapshotLocator(page_hrefs, page_error)
        self.containers = SnapshotLocator(container_href_groups, container_error)

    def locator(self, selector):
        if selector == "a[href]":
            return self.page_anchors
        if selector == POST_ARTICLE_SELECTOR:
            return self.containers
        raise AssertionError(f"unexpected selector: {selector}")


class FakeTextNode:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def count(self) -> int:
        return int(self.text is not None)

    def inner_text(self) -> str:
        assert self.text is not None
        return self.text

    def evaluate(self, _script: str) -> str:
        assert self.text is not None
        return self.text


class FakeTextSelector:
    def __init__(self, text: str | None) -> None:
        self.first = FakeTextNode(text)


class StrictMessageContainer:
    """Main-post fixture that fails if parser falls back to container-wide text."""

    def __init__(self, message: str | None) -> None:
        self.message = message

    def get_by_text(self, _pattern):
        return FakeTextSelector(None)

    def locator(self, _selector):
        return FakeTextSelector(self.message)

    def inner_text(self) -> str:
        raise AssertionError("detail parser must not read container-wide text")


class FakeImage:
    def __init__(self, url: str, width: int = 100, height: int = 100) -> None:
        self.url, self.width, self.height = url, width, height

    def get_attribute(self, name: str) -> str | None:
        return self.url if name == "src" else None

    def evaluate(self, _script):
        return {"width": self.width, "height": self.height}


class FakeImageList:
    def __init__(self, images: list[FakeImage]) -> None:
        self.images = images

    def count(self) -> int:
        return len(self.images)

    def nth(self, index: int) -> FakeImage:
        return self.images[index]


class MainPostImageContainer:
    """Contains only main-post media; comment images are deliberately unavailable."""

    def __init__(self, images: list[FakeImage]) -> None:
        self.images = images

    def locator(self, selector: str) -> FakeImageList:
        assert selector == "img[src*='scontent']"
        return FakeImageList(self.images)


class RetryDetailPage:
    def __init__(self) -> None:
        self.goto_calls = 0
        self.reload_calls = 0
        self.waits: list[int] = []

    def goto(self, *_args, **_kwargs) -> None:
        self.goto_calls += 1

    def reload(self, **_kwargs) -> None:
        self.reload_calls += 1

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


class HrefContainer:
    def __init__(self, hrefs: list[str]) -> None:
        self.hrefs = hrefs

    def locator(self, selector: str) -> SnapshotLocator:
        assert selector == "a[href]"
        return SnapshotLocator(self.hrefs)


class HrefContainerList:
    def __init__(self, containers: list[HrefContainer]) -> None:
        self.containers = containers

    def count(self) -> int:
        return len(self.containers)

    def nth(self, index: int) -> HrefContainer:
        return self.containers[index]


class DetailContainerPage:
    def __init__(self, containers: list[HrefContainer]) -> None:
        self.containers = containers

    def locator(self, selector: str) -> HrefContainerList:
        if selector == STORY_MESSAGE_SELECTOR:
            return HrefContainerList([])
        return HrefContainerList(self.containers)


class DiagnosticImageLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class DiagnosticArticle(HrefContainer):
    def __init__(self, hrefs: list[str], text: str, image_count: int) -> None:
        super().__init__(hrefs)
        self.text = text
        self.image_count = image_count

    def locator(self, selector: str):
        if selector == "a[href]":
            return SnapshotLocator(self.hrefs)
        if selector == "img[src*='scontent']":
            return DiagnosticImageLocator(self.image_count)
        raise AssertionError(f"unexpected selector: {selector}")

    def inner_text(self) -> str:
        return self.text


class DiagnosticPage(DetailContainerPage):
    pass


class CountLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class AttributeSnapshotLocator(CountLocator):
    def __init__(self, values: list[str]) -> None:
        super().__init__(len(values))
        self.values = values

    def evaluate_all(self, _script):
        return [{"source": "data-utime", "value": value} for value in self.values]


class StoryCardNode:
    def __init__(
        self,
        *,
        hrefs: list[str],
        text: str,
        has_time: bool = False,
        image_count: int = 0,
        story_count: int = 1,
        parent: "StoryCardNode | None" = None,
        tag: str = "div",
    ) -> None:
        self.hrefs = hrefs
        self.text = text
        self.has_time = has_time
        self.image_count = image_count
        self.story_count = story_count
        self.parent = parent
        self.tag = tag

    def count(self) -> int:
        return 1

    def locator(self, selector: str):
        if selector == "xpath=..":
            return self.parent or CountLocator(0)
        if selector == "a[href]":
            return SnapshotLocator(self.hrefs)
        if selector == STORY_MESSAGE_SELECTOR:
            return CountLocator(self.story_count)
        if selector == "img[src*='scontent']":
            return CountLocator(self.image_count)
        if selector == "time[datetime]":
            return CountLocator(0)
        if "data-utime" in selector:
            return AttributeSnapshotLocator(["1780000000"] if self.has_time else [])
        raise AssertionError(f"unexpected selector: {selector}")

    def inner_text(self) -> str:
        return self.text

    def evaluate(self, _script):
        return {"tag": self.tag, "role": None, "className": "post-card"}


class StoryPage:
    def __init__(self, messages: list[StoryCardNode], url: str) -> None:
        self.messages = messages
        self.url = url

    def locator(self, selector: str):
        if selector == STORY_MESSAGE_SELECTOR:
            return HrefContainerList(self.messages)
        return HrefContainerList([])


def collect_from_rounds(monkeypatch, rounds, limit, graphql_urls=None):
    """Run collection with mocked container and whole-page anchor scans."""
    page = FakePage(rounds)
    monkeypatch.setattr(
        facebook_crawler,
        "get_container_post_urls",
        lambda current_page: current_page.current_round["container"],
    )
    monkeypatch.setattr(
        facebook_crawler,
        "get_full_page_post_anchor_urls",
        lambda current_page: current_page.current_round["page_anchor"],
    )
    collector = None
    if graphql_urls is not None:
        collector = type("GraphQLCollector", (), {"urls": graphql_urls})()
    return page, collect_post_url_candidates(page, limit, graphql_collector=collector)


def post_url(post_id):
    return f"/TwNikkiNikki/posts/{post_id}"


class FakeGraphQLRequest:
    def __init__(self, post_data: str) -> None:
        self.post_data = post_data


class FakeGraphQLResponse:
    def __init__(self, body: str, post_data: str, url: str = "https://www.facebook.com/api/graphql/") -> None:
        self.url = url
        self.request = FakeGraphQLRequest(post_data)

        self._body = body

    def text(self) -> str:
        return self._body


def make_post(post_url: str) -> Post:
    return Post(
        post_id=get_post_id(post_url),
        url=post_url,
        content="post content",
        published_at=datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc),
        images=[],
    )


def test_pinned_story_fbid_permalink_preserves_identity_query_parameters():
    url = normalize_post_url(
        "/permalink.php?story_fbid=987654321&id=123456789&__cft__[0]=tracking"
    )

    assert url == "https://www.facebook.com/permalink.php?story_fbid=987654321&id=123456789"
    assert get_post_id(url) == "123456789_987654321"


def test_regular_and_pinned_permalink_use_the_same_extraction_function():
    regular_url = get_post_url_from_hrefs(["/TwNikkiNikki/posts/111222333?tracking=value"])
    pinned_url = get_post_url_from_hrefs(["/permalink.php?story_fbid=444555&id=123456"])

    assert regular_url == "https://www.facebook.com/TwNikkiNikki/posts/111222333"
    assert pinned_url == "https://www.facebook.com/permalink.php?story_fbid=444555&id=123456"


def test_preferred_post_permalink_wins_over_a_non_post_fbid_image_link():
    post_url = get_post_url_from_hrefs(
        [
            "/photo/?fbid=999&id=123456",
            "/TwNikkiNikki/posts/111222333",
        ]
    )

    assert post_url == "https://www.facebook.com/TwNikkiNikki/posts/111222333"


def test_timeline_container_selector_includes_pinned_feed_units():
    assert "div[role='article']" in POST_ARTICLE_SELECTOR
    assert "div[data-pagelet^='FeedUnit_']" in POST_ARTICLE_SELECTOR


def test_official_page_anchor_permalink_is_accepted_and_external_posts_are_rejected():
    assert is_official_page_post_url("/TwNikkiNikki/posts/pfbid-target?comment_id=1")
    assert not is_official_page_post_url("/OtherPage/posts/pfbid-target")
    assert not is_official_page_post_url("/TwNikkiNikki/reel/123")
    assert not is_official_page_post_url("/TwNikkiNikki/photos/123")
    assert not is_official_page_post_url("https://example.test/TwNikkiNikki/posts/pfbid-target")


def test_container_and_page_anchor_sources_merge_without_duplicate_queries():
    candidates = merge_post_url_candidates(
        ["/TwNikkiNikki/posts/pfbid-target?comment_id=1"],
        [
            "https://www.facebook.com/TwNikkiNikki/posts/pfbid-target?tracking=value",
            "/TwNikkiNikki/posts/pfbid-regular",
        ],
    )

    assert [(candidate.url, candidate.sources) for candidate in candidates] == [
        ("https://www.facebook.com/TwNikkiNikki/posts/pfbid-target", ("container", "page_anchor")),
        ("https://www.facebook.com/TwNikkiNikki/posts/pfbid-regular", ("page_anchor",)),
    ]


def test_query_string_variants_of_an_official_anchor_are_deduplicated():
    candidates = merge_post_url_candidates(
        [],
        [
            "/TwNikkiNikki/posts/pfbid-target?comment_id=1",
            "/TwNikkiNikki/posts/pfbid-target?__cft__[0]=tracking",
        ],
    )

    assert len(candidates) == 1


def test_graphql_official_permalink_is_collected_from_trusted_fields_only():
    document = {
        "data": {
            "node": {
                "permalink_url": SUMMER_LOGIN_POST_URL,
                "comet_sections": {"content": {"story": {"wwwURL": LATER_REGULAR_POST_URL}}},
                "message": "This field is intentionally ignored.",
            }
        }
    }

    assert get_graphql_permalink_urls(document) == [
        SUMMER_LOGIN_POST_URL,
        LATER_REGULAR_POST_URL,
    ]


def test_graphql_non_official_or_non_post_permalink_is_ignored():
    document = {
        "data": {
            "node": {
                "permalink_url": "https://www.facebook.com/OtherPage/posts/not-ours",
                "wwwURL": "https://www.facebook.com/TwNikkiNikki/reel/123",
            }
        }
    }

    assert get_graphql_permalink_urls(document) == []


def test_graphql_response_collector_uses_only_timeline_operation():
    collector = GraphQLPermalinkCollector()
    response = FakeGraphQLResponse(
        json.dumps({"data": {"node": {"permalink_url": SUMMER_LOGIN_POST_URL}}}),
        "fb_api_req_friendly_name=ProfileCometTimelineFeedRefetchQuery",
    )

    collector._handle_response(response)
    collector._handle_response(
        FakeGraphQLResponse(
            json.dumps({"data": {"node": {"permalink_url": LATER_REGULAR_POST_URL}}}),
            "fb_api_req_friendly_name=OtherQuery",
        )
    )

    assert collector.urls == [SUMMER_LOGIN_POST_URL]


def test_graphql_and_dom_duplicate_permalink_uses_existing_canonical_dedupe(monkeypatch):
    _, candidates = collect_from_rounds(
        monkeypatch,
        [{"container": [f"{SUMMER_LOGIN_POST_URL}?tracking=value"], "page_anchor": []}],
        limit=1,
        graphql_urls=[SUMMER_LOGIN_POST_URL],
    )

    assert candidates == [
        PostUrlCandidate(SUMMER_LOGIN_POST_URL, ("container", "graphql"))
    ]


def test_graphql_permalink_missing_from_dom_enters_existing_detail_parser_flow(monkeypatch):
    _, candidates = collect_from_rounds(
        monkeypatch,
        [{"container": [], "page_anchor": []}],
        limit=1,
        graphql_urls=[SUMMER_LOGIN_POST_URL],
    )
    parsed_urls: list[str] = []

    def fake_parse_post(_page, url):
        parsed_urls.append(url)
        return make_post(url)

    monkeypatch.setattr(facebook_crawler, "parse_post", fake_parse_post)

    posts = parse_post_candidates(None, candidates)

    assert [post.url for post in posts] == [SUMMER_LOGIN_POST_URL]
    assert parsed_urls == [SUMMER_LOGIN_POST_URL]


def test_pinned_candidate_is_not_removed_for_having_an_older_publish_time():
    older_pinned = Post(
        post_id="pinned",
        url="https://www.facebook.com/TwNikkiNikki/posts/pinned",
        content="older pinned",
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        images=[],
    )
    newer_regular = make_post("https://www.facebook.com/TwNikkiNikki/posts/newer")

    sorted_posts = sort_posts_by_published_at([newer_regular, older_pinned])

    assert [post.post_id for post in sorted_posts] == ["newer", "pinned"]


def test_limit_is_applied_only_after_publish_time_sorting():
    older = Post(
        post_id="older",
        url="https://www.facebook.com/TwNikkiNikki/posts/older",
        content="older",
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        images=[],
    )
    newer = Post(
        post_id="newer",
        url="https://www.facebook.com/TwNikkiNikki/posts/newer",
        content="newer",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        images=[],
    )

    assert sort_posts_by_published_at([older, newer])[:1] == [newer]


def test_parse_failure_does_not_stop_other_candidates(monkeypatch):
    candidates = [
        PostUrlCandidate("https://www.facebook.com/TwNikkiNikki/posts/fail", ("page_anchor",)),
        PostUrlCandidate("https://www.facebook.com/TwNikkiNikki/posts/good", ("container",)),
    ]

    def fake_parse_post(_page, post_url):
        if post_url.endswith("/fail"):
            raise FacebookCrawlerError("detail unavailable")
        return make_post(post_url)

    monkeypatch.setattr("crawler.facebook_crawler.parse_post", fake_parse_post)

    posts = parse_post_candidates(None, candidates)

    assert [post.post_id for post in posts] == ["good"]


def test_pinned_and_regular_posts_are_saved_once_by_permalink_derived_post_id(tmp_path):
    repository = RawPostRepository(tmp_path / "pinned-posts.db")
    pinned_url = get_post_url_from_hrefs(["/permalink.php?story_fbid=444555&id=123456"])
    regular_url = get_post_url_from_hrefs(["/TwNikkiNikki/posts/111222333"])

    result = repository.save_raw_posts(
        [make_post(pinned_url), make_post(regular_url), make_post(pinned_url)]
    )

    assert result.inserted == 2
    assert result.unchanged == 1
    assert repository.raw_post_exists(get_post_id(pinned_url))
    assert repository.raw_post_exists(get_post_id(regular_url))


def test_page_anchor_collection_uses_a_single_snapshot_and_ignores_missing_hrefs():
    page = SnapshotPage(
        page_hrefs=[None, "", 42, post_url("page-post"), "/OtherPage/posts/not-ours"],
        container_href_groups=[],
    )

    assert get_full_page_post_anchor_urls(page) == [post_url("page-post")]
    assert len(page.page_anchors.evaluate_calls) == 1


def test_container_anchor_collection_uses_a_single_snapshot_without_nth_reads():
    page = SnapshotPage(
        page_hrefs=[],
        container_href_groups=[
            [None, "", "/TwNikkiNikki/photos/ignored", post_url("container-post")],
            [post_url("second-container-post")],
        ],
    )

    assert get_container_post_urls(page) == [
        "https://www.facebook.com/TwNikkiNikki/posts/container-post",
        "https://www.facebook.com/TwNikkiNikki/posts/second-container-post",
    ]
    assert len(page.containers.evaluate_calls) == 1


def test_snapshot_failure_skips_only_the_failed_anchor_source():
    page = SnapshotPage(
        page_hrefs=[],
        container_href_groups=[[post_url("container-still-works")]],
        page_error=RuntimeError("DOM node was replaced"),
    )

    assert get_full_page_post_anchor_urls(page) == []
    assert get_container_post_urls(page) == [
        "https://www.facebook.com/TwNikkiNikki/posts/container-still-works"
    ]


def test_scroll_re_scans_both_sources_and_collects_new_posts(monkeypatch):
    page, candidates = collect_from_rounds(
        monkeypatch,
        [
            {"container": [post_url("regular-1")], "page_anchor": [post_url("pinned-1")]},
            {"container": [post_url("regular-2")], "page_anchor": [post_url("pinned-2")]},
        ],
        limit=4,
    )

    assert [candidate.url.rsplit("/", 1)[-1] for candidate in candidates] == [
        "regular-1",
        "pinned-1",
        "regular-2",
        "pinned-2",
    ]
    assert page.mouse.wheel_calls == 1


def test_multiple_pinned_page_anchors_are_collected_in_their_discovery_order(monkeypatch):
    _, candidates = collect_from_rounds(
        monkeypatch,
        [
            {
                "container": [post_url("regular")],
                "page_anchor": [post_url("pinned-old"), post_url("pinned-new")],
            }
        ],
        limit=3,
    )

    assert [candidate.url.rsplit("/", 1)[-1] for candidate in candidates] == [
        "regular",
        "pinned-old",
        "pinned-new",
    ]


def test_scroll_collection_deduplicates_container_page_anchor_and_query_variants(monkeypatch):
    _, candidates = collect_from_rounds(
        monkeypatch,
        [
            {
                "container": [f"{post_url('same')}?comment_id=1"],
                "page_anchor": [f"{post_url('same')}?tracking=value", post_url("next")],
            }
        ],
        limit=2,
    )

    assert [(candidate.url.rsplit("/", 1)[-1], candidate.sources) for candidate in candidates] == [
        ("same", ("container", "page_anchor")),
        ("next", ("page_anchor",)),
    ]


def test_one_empty_round_does_not_stop_scroll_collection(monkeypatch):
    monkeypatch.setattr(facebook_crawler, "MAX_CONSECUTIVE_NO_NEW_ROUNDS", 3)
    page, candidates = collect_from_rounds(
        monkeypatch,
        [
            {"container": [post_url("first")], "page_anchor": []},
            {"container": [], "page_anchor": []},
            {"container": [], "page_anchor": [post_url("after-empty-round")]},
        ],
        limit=2,
    )

    assert [candidate.url.rsplit("/", 1)[-1] for candidate in candidates] == [
        "first",
        "after-empty-round",
    ]
    assert page.mouse.wheel_calls == 2


def test_consecutive_empty_rounds_stop_scroll_collection(monkeypatch):
    monkeypatch.setattr(facebook_crawler, "MAX_CONSECUTIVE_NO_NEW_ROUNDS", 3)
    monkeypatch.setattr(facebook_crawler, "MAX_SCROLL_ATTEMPTS", 10)
    page, candidates = collect_from_rounds(
        monkeypatch,
        [{"container": [post_url("first")], "page_anchor": []}] + [
            {"container": [], "page_anchor": []}
        ] * 4,
        limit=10,
    )

    assert [candidate.url.rsplit("/", 1)[-1] for candidate in candidates] == ["first"]
    assert page.mouse.wheel_calls == 3


def test_limit_is_enforced_during_collection_and_preserves_first_discovery_order(monkeypatch):
    page, candidates = collect_from_rounds(
        monkeypatch,
        [
            {
                "container": [post_url("first"), post_url("second")],
                "page_anchor": [post_url("third"), post_url("fourth")],
            }
        ],
        limit=3,
    )

    assert [candidate.url.rsplit("/", 1)[-1] for candidate in candidates] == [
        "first",
        "second",
        "third",
    ]
    assert page.mouse.wheel_calls == 0


def test_scroll_collection_rejects_non_official_and_non_post_anchors(monkeypatch):
    _, candidates = collect_from_rounds(
        monkeypatch,
        [
            {
                "container": [],
                "page_anchor": [
                    "/OtherPage/posts/not-ours",
                    "/TwNikkiNikki/reel/123",
                    "/TwNikkiNikki/photos/123",
                    "/TwNikkiNikki/videos/123",
                    "/share/123",
                    "https://example.test/TwNikkiNikki/posts/external",
                    post_url("official"),
                ],
            }
        ],
        limit=1,
    )

    assert [candidate.url.rsplit("/", 1)[-1] for candidate in candidates] == ["official"]


def test_maximum_scroll_rounds_prevents_unbounded_collection(monkeypatch):
    monkeypatch.setattr(facebook_crawler, "MAX_SCROLL_ATTEMPTS", 3)
    monkeypatch.setattr(facebook_crawler, "MAX_CONSECUTIVE_NO_NEW_ROUNDS", 10)
    page, candidates = collect_from_rounds(
        monkeypatch,
        [
            {"container": [post_url("one")], "page_anchor": []},
            {"container": [post_url("two")], "page_anchor": []},
            {"container": [post_url("three")], "page_anchor": []},
            {"container": [post_url("four")], "page_anchor": []},
        ],
        limit=10,
    )

    assert [candidate.url.rsplit("/", 1)[-1] for candidate in candidates] == ["one", "two", "three"]
    assert page.mouse.wheel_calls == 2


def test_real_pinned_permalink_and_later_regular_permalink_are_collected(monkeypatch):
    _, candidates = collect_from_rounds(
        monkeypatch,
        [
            {
                "container": [],
                "page_anchor": [PINNED_POST_URL, post_url("another-pinned-post")],
            },
            {"container": [LATER_REGULAR_POST_URL], "page_anchor": [PINNED_POST_URL]},
        ],
        limit=3,
    )

    assert [(candidate.url, candidate.sources) for candidate in candidates] == [
        (PINNED_POST_URL, ("page_anchor",)),
        ("https://www.facebook.com/TwNikkiNikki/posts/another-pinned-post", ("page_anchor",)),
        (LATER_REGULAR_POST_URL, ("container",)),
    ]


def test_reported_homepage_permalink_shapes_are_collected_from_both_sources(monkeypatch):
    _, candidates = collect_from_rounds(
        monkeypatch,
        [
            {"container": [], "page_anchor": [SUMMER_LOGIN_POST_URL]},
            {"container": [LATER_REGULAR_POST_URL], "page_anchor": []},
        ],
        limit=2,
    )

    assert [(candidate.url, candidate.sources) for candidate in candidates] == [
        (SUMMER_LOGIN_POST_URL, ("page_anchor",)),
        (LATER_REGULAR_POST_URL, ("container",)),
    ]


def test_main_post_container_requires_requested_permalink_and_official_author():
    official_hrefs = [
        COMMENT_POLLUTION_POST_URL,
        "/TwNikkiNikki/",
        "/TwNikkiNikki/posts/other-post",
    ]
    comment_hrefs = [COMMENT_POLLUTION_POST_URL, "/SomeOtherUser/"]

    assert is_matching_main_post_container(official_hrefs, COMMENT_POLLUTION_POST_URL)
    assert not is_matching_main_post_container(comment_hrefs, COMMENT_POLLUTION_POST_URL)


def test_detail_locator_skips_comment_article_and_selects_official_main_article():
    comment_article = HrefContainer([COMMENT_POLLUTION_POST_URL, "/SomeOtherUser/"])
    official_article = HrefContainer([COMMENT_POLLUTION_POST_URL, "/TwNikkiNikki/"])
    page = DetailContainerPage([comment_article, official_article])

    assert get_main_post_article(page, COMMENT_POLLUTION_POST_URL) is official_article


def test_detail_locator_selects_main_story_card_outside_article():
    main_card = StoryCardNode(
        hrefs=["/TwNikkiNikki/?ref=page_internal"],
        text="奇迹暖暖 官方主貼文",
        has_time=True,
        image_count=1,
    )
    message = StoryCardNode(hrefs=[], text="官方主貼文", parent=main_card)
    page = StoryPage([message], COMMENT_POLLUTION_POST_URL)

    assert get_main_post_article(page, COMMENT_POLLUTION_POST_URL) is main_card


def test_story_locator_rejects_comment_message_even_with_target_permalink():
    comment_card = StoryCardNode(
        hrefs=[COMMENT_POLLUTION_POST_URL, "/SomeOtherUser/?comment_id=1"],
        text="其他玩家 留言",
        has_time=True,
    )
    message = StoryCardNode(hrefs=[], text="留言", parent=comment_card)
    page = StoryPage([message], COMMENT_POLLUTION_POST_URL)

    with pytest.raises(FacebookCrawlerError, match="trusted official main-post"):
        get_main_post_article(page, COMMENT_POLLUTION_POST_URL)


def test_story_locator_accepts_official_author_href_with_query_parameters():
    main_card = StoryCardNode(
        hrefs=["https://www.facebook.com/TwNikkiNikki/?ref=bookmarks"],
        text="官方貼文",
        has_time=True,
    )
    message = StoryCardNode(hrefs=[], text="官方貼文", parent=main_card)
    page = StoryPage([message], COMMENT_POLLUTION_POST_URL)

    assert get_main_post_article(page, COMMENT_POLLUTION_POST_URL) is main_card


def test_story_locator_requires_outer_time_metadata_and_keeps_main_card_images_only():
    main_card = StoryCardNode(
        hrefs=["/TwNikkiNikki/?ref=profile"],
        text="奇蹟暖暖 主貼文",
        has_time=True,
        image_count=1,
    )
    main_message = StoryCardNode(hrefs=[], text="主貼文", parent=main_card)
    comment_card = StoryCardNode(
        hrefs=["/SomeOtherUser/"],
        text="留言",
        has_time=True,
        image_count=3,
    )
    comment_message = StoryCardNode(hrefs=[], text="留言", parent=comment_card)
    page = StoryPage([comment_message, main_message], COMMENT_POLLUTION_POST_URL)

    selected = get_main_post_article(page, COMMENT_POLLUTION_POST_URL)

    assert selected is main_card
    assert selected.locator("img[src*='scontent']").count() == 1


def test_story_locator_prefers_smallest_trusted_ancestor_with_main_post_images():
    complete_card = StoryCardNode(
        hrefs=["/TwNikkiNikki/?ref=profile"],
        text="奇迹暖暖 主貼文 2天",
        has_time=True,
        image_count=2,
    )
    shallow_card = StoryCardNode(
        hrefs=["/TwNikkiNikki/?ref=profile"],
        text="奇迹暖暖 主貼文 2天",
        has_time=True,
        parent=complete_card,
    )
    message = StoryCardNode(hrefs=[], text="主貼文", parent=shallow_card)
    page = StoryPage([message], COMMENT_POLLUTION_POST_URL)

    assert get_main_post_article(page, COMMENT_POLLUTION_POST_URL) is complete_card


def test_published_at_reads_outer_accessibility_timestamp():
    card = StoryCardNode(
        hrefs=[],
        text="官方貼文",
        has_time=True,
    )

    published_at = get_published_at(card)

    assert published_at.year == 2026


def test_absolute_chinese_aria_label_time_is_parsed_without_page_wide_fallback():
    parsed = parse_facebook_time_value("2026年7月13日 下午 05:00")

    assert parsed is not None
    assert parsed.isoformat() == "2026-07-13T17:00:00+08:00"


def test_trusted_post_without_absolute_facebook_time_is_not_skipped(monkeypatch):
    container = object()
    monkeypatch.setattr(facebook_crawler, "open_post_detail", lambda *_args, **_kwargs: container)
    monkeypatch.setattr(facebook_crawler, "get_full_post_content", lambda _container: "官方公告")
    monkeypatch.setattr(facebook_crawler, "get_image_urls", lambda _container: ["official.jpg"])
    monkeypatch.setattr(
        facebook_crawler,
        "get_published_at",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FacebookCrawlerError("no time")),
    )

    post = facebook_crawler.parse_post(object(), COMMENT_POLLUTION_POST_URL)

    assert post.content == "官方公告"
    assert post.images == ["official.jpg"]
    assert post.published_at is None


def test_detail_diagnostics_logs_reason_for_every_article(caplog):
    page = DiagnosticPage(
        [
            DiagnosticArticle(
                [COMMENT_POLLUTION_POST_URL, "/SomeOtherUser/"],
                "留言文字",
                1,
            ),
            DiagnosticArticle(
                [COMMENT_POLLUTION_POST_URL, "/TwNikkiNikki/"],
                "官方貼文文字",
                2,
            ),
        ]
    )

    caplog.set_level(logging.INFO, logger="crawler.facebook_crawler")
    log_main_post_container_diagnostics(page, COMMENT_POLLUTION_POST_URL)

    messages = "\n".join(caplog.messages)
    assert "article_count=2" in messages
    assert "index=0 official_author=False permalink=True text_length=4 image_count=1" in messages
    assert "result=missing_official_author" in messages
    assert "index=1 official_author=True permalink=True text_length=6 image_count=2" in messages
    assert "result=eligible" in messages


def test_detail_content_uses_main_message_only_and_never_container_wide_text():
    container = StrictMessageContainer("官方主貼文內容")

    assert get_full_post_content(container) == "官方主貼文內容"


@pytest.mark.parametrize(
    "message",
    [
        "⛱️暑期登入送",
        "暑期⛱️登入送",
        "【⛱️暑期登入送⛱️】",
        "✨🎁暑期登入送",
        "沒有 emoji 的既有主文",
    ],
)
def test_detail_content_uses_dom_ordered_emoji_text(message):
    assert get_full_post_content(StrictMessageContainer(message)) == message


def test_detail_content_does_not_use_image_accessibility_labels_as_message_text():
    container = StrictMessageContainer("【⛱️暑期登入送⛱️】")

    content = get_full_post_content(container)

    assert "可能是文字的圖像" not in content
    assert content == "【⛱️暑期登入送⛱️】"


def test_detail_content_rebuilds_real_facebook_emoji_nodes_in_dom_order():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(
            "<div data-ad-preview=\"message\">"
            "<div>【<img src=\"https://static.xx.fbcdn.net/images/emoji.php/v9/t78/1/16/26f1.png\" alt=\"⛱️\" aria-label=\"可能是文字的圖像\">暑期登入送<img src=\"https://static.xx.fbcdn.net/images/emoji.php/v9/t78/1/16/26f1.png\" alt=\"⛱️\">】</div>"
            "<div>暑期<img src=\"https://static.xx.fbcdn.net/images/emoji.php/v9/tf4/1/16/2728.png\" alt=\"✨\">登入送</div>"
            "<div><img src=\"https://static.xx.fbcdn.net/images/emoji.php/v9/t84/1/16/1f381.png\" alt=\"🎁\"><img src=\"https://static.xx.fbcdn.net/images/emoji.php/v9/tf4/1/16/2728.png\" alt=\"✨\">連續 emoji</div>"
            "<img src=\"https://scontent.example.test/announcement.jpg\" alt=\"公告圖片\" aria-label=\"可能是文字的圖像\">"
            "</div>"
        )

        content = get_full_post_content(page.locator("body"))

        browser.close()

    assert content == "【⛱️暑期登入送⛱️】\n暑期✨登入送\n🎁✨連續 emoji"
    assert "可能是文字的圖像" not in content


def test_detail_content_does_not_fallback_to_comment_or_page_text_when_message_is_missing():
    with pytest.raises(FacebookCrawlerError, match="full post content"):
        get_full_post_content(StrictMessageContainer(None))


def test_detail_images_are_limited_to_the_trusted_main_post_container():
    official_image = "https://scontent.example.test/main-photo.jpg"
    comment_image = "https://scontent.example.test/comment-photo.jpg"
    container = MainPostImageContainer([FakeImage(official_image)])

    image_urls = get_image_urls(container)

    assert image_urls == [official_image]
    assert comment_image not in image_urls


def test_detail_page_retries_until_the_trusted_main_post_container_appears(monkeypatch):
    page = RetryDetailPage()
    trusted_container = object()
    attempts = 0

    def find_main_container(_page, _post_url):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FacebookCrawlerError("main post still loading")
        return trusted_container

    monkeypatch.setattr(facebook_crawler, "dismiss_cookie_dialog", lambda _page: None)
    monkeypatch.setattr(facebook_crawler, "get_main_post_article", find_main_container)

    assert open_post_detail(page, COMMENT_POLLUTION_POST_URL) is trusted_container
    assert page.goto_calls == 1
    assert page.reload_calls == 1


def test_detail_page_never_falls_back_when_no_trusted_main_post_container_exists(monkeypatch):
    page = RetryDetailPage()
    monkeypatch.setattr(facebook_crawler, "dismiss_cookie_dialog", lambda _page: None)
    monkeypatch.setattr(
        facebook_crawler,
        "get_main_post_article",
        lambda _page, _post_url: (_ for _ in ()).throw(FacebookCrawlerError("missing")),
    )

    with pytest.raises(FacebookCrawlerError, match="missing"):
        open_post_detail(page, COMMENT_POLLUTION_POST_URL)
    assert page.reload_calls == 1
