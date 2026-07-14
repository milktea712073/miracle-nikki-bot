from scripts.facebook_feed_diagnostic import (
    FeedDiagnosis,
    FeedRound,
    TARGET_POST_IDS,
    canonical_official_post_urls,
    compare_diagnoses,
)


def test_canonical_official_post_urls_filters_and_preserves_discovery_order():
    urls = canonical_official_post_urls(
        [
            "/TwNikkiNikki/posts/first?tracking=value",
            "/OtherPage/posts/external",
            "/TwNikkiNikki/reel/123",
            "/TwNikkiNikki/posts/first?comment_id=2",
            "https://www.facebook.com/TwNikkiNikki/posts/second",
        ]
    )

    assert urls == [
        "https://www.facebook.com/TwNikkiNikki/posts/first",
        "https://www.facebook.com/TwNikkiNikki/posts/second",
    ]


def test_compare_diagnoses_reports_counts_differences_and_target_visibility():
    storage = FeedDiagnosis(
        context_type="storage_state",
        canonical_permalinks=["https://www.facebook.com/TwNikkiNikki/posts/shared"],
        target_post_ids_found=[],
        rounds=[],
    )
    persistent = FeedDiagnosis(
        context_type="persistent_profile",
        canonical_permalinks=[
            "https://www.facebook.com/TwNikkiNikki/posts/shared",
            f"https://www.facebook.com/TwNikkiNikki/posts/{TARGET_POST_IDS[0]}",
        ],
        target_post_ids_found=[TARGET_POST_IDS[0]],
        rounds=[FeedRound(1, [], [TARGET_POST_IDS[0]], [])],
    )

    result = compare_diagnoses(storage, persistent)

    assert result["storage_state_count"] == 1
    assert result["persistent_profile_count"] == 2
    assert result["only_storage_state"] == []
    assert result["only_persistent_profile"] == [
        f"https://www.facebook.com/TwNikkiNikki/posts/{TARGET_POST_IDS[0]}"
    ]
    assert result["targets"][TARGET_POST_IDS[0]] == {
        "storage_state": False,
        "persistent_profile": True,
    }
