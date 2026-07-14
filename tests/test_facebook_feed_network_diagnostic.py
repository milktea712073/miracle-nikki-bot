from scripts.facebook_feed_diagnostic import TARGET_POST_IDS
from scripts.facebook_feed_network_diagnostic import (
    NetworkResponseRecord,
    extract_pfbids,
    is_facebook_feed_response,
    operation_name_from_post_data,
    pfbid_json_paths,
    summarize_records,
)


def test_feed_response_filter_accepts_graphql_and_rejects_unrelated_urls():
    assert is_facebook_feed_response("https://www.facebook.com/api/graphql/")
    assert is_facebook_feed_response("https://www.facebook.com/feed/update")
    assert not is_facebook_feed_response("https://www.facebook.com/images/example.png")
    assert not is_facebook_feed_response("https://example.test/api/graphql/")


def test_operation_name_is_read_without_persisting_post_data():
    assert operation_name_from_post_data(
        "fb_api_req_friendly_name=CometPageFeedPaginationQuery&doc_id=123"
    ) == "CometPageFeedPaginationQuery"
    assert operation_name_from_post_data('{"operationName": "PageFeedQuery"}') == "PageFeedQuery"


def test_pfbid_extraction_deduplicates_in_response_discovery_order():
    body = "pfbidFirst xx pfbidSecond pfbidFirst"

    assert extract_pfbids(body) == ["pfbidFirst", "pfbidSecond"]


def test_pfbid_json_paths_keeps_only_structural_paths_not_response_values():
    body = (
        '{"data":{"feed":{"edges":[{"node":{"url":"/posts/pfbidFirst"}}]}}}'
        '\n{"data":{}}'
    )

    assert pfbid_json_paths(body, ["pfbidFirst"]) == {
        "pfbidFirst": ["$[0].data.feed.edges[0].node.url"]
    }


def test_summary_reports_target_response_without_response_body():
    records = [
        NetworkResponseRecord(
            url="https://www.facebook.com/api/graphql/",
            operation_name="CometPageFeedPaginationQuery",
            status=200,
            pfbids=[TARGET_POST_IDS[0]],
            pfbid_paths={TARGET_POST_IDS[0]: ["$[0].data.feed.edges[0].node.url"]},
        ),
        NetworkResponseRecord(
            url="https://www.facebook.com/api/graphql/",
            operation_name="OtherQuery",
            status=200,
            pfbids=[],
            pfbid_paths={},
        ),
    ]

    summary = summarize_records(records)

    assert summary["response_count"] == 2
    assert summary["responses_with_pfbids"] == 1
    assert summary["targets"][TARGET_POST_IDS[0]] == [
        {
            "url": "https://www.facebook.com/api/graphql/",
            "operation_name": "CometPageFeedPaginationQuery",
            "status": 200,
            "paths": ["$[0].data.feed.edges[0].node.url"],
        }
    ]
    assert summary["targets"][TARGET_POST_IDS[1]] == []
