from datetime import datetime, timezone

from crawler.facebook_crawler import (
    FacebookCrawlerError,
    POST_ARTICLE_SELECTOR,
    PostUrlCandidate,
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
