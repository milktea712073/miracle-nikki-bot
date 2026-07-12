from datetime import datetime, timezone

from crawler import facebook_crawler
from crawler.facebook_crawler import (
    FacebookCrawlerError,
    POST_ARTICLE_SELECTOR,
    PostUrlCandidate,
    collect_post_url_candidates,
    get_container_post_urls,
    get_full_page_post_anchor_urls,
    get_post_id,
    get_post_url_from_hrefs,
    is_official_page_post_url,
    merge_post_url_candidates,
    normalize_post_url,
    parse_post_candidates,
    sort_posts_by_published_at,
)
from crawler.models import Post
from database.raw_post_repository import RawPostRepository


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


def collect_from_rounds(monkeypatch, rounds, limit):
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
    return page, collect_post_url_candidates(page, limit)


def post_url(post_id):
    return f"/TwNikkiNikki/posts/{post_id}"


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
