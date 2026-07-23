"""Read-only trace of historical-announcement search candidates and exclusions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from announcement.history_search import (
    DEFAULT_CANDIDATE_LIMIT,
    AnnouncementHistorySearchService,
    _deduplication_keys,
    _result_key,
    merge_search_results,
)
from announcement.models import CN_OFFICIAL, TW_OFFICIAL
from announcement.search import keyword_search_variants


DEFAULT_STATE_DATABASE_PATH = PROJECT_ROOT / "database" / "announcement_state.db"
SOURCE_FILTERS = {"all": None, "tw": TW_OFFICIAL, "cn": CN_OFFICIAL}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", required=True, help="Keyword to inspect in full title and content.")
    parser.add_argument("--source", choices=SOURCE_FILTERS, default="all")
    parser.add_argument("--limit", type=int, default=10, help="Final merged-result limit.")
    parser.add_argument("--database", type=Path, default=DEFAULT_STATE_DATABASE_PATH)
    return parser.parse_args()


def _rank_by_key(results: tuple[object, ...]) -> dict[tuple[str, int], int]:
    return {_result_key(result): index for index, result in enumerate(results, start=1)}


def _match_details(title: str, content: str, variants: tuple[str, ...]) -> tuple[str | None, str | None]:
    for field_name, value in (("title", title), ("content", content)):
        for variant in variants:
            index = value.casefold().find(variant.casefold())
            if index >= 0:
                return field_name, value[max(0, index - 60): index + len(variant) + 100]
    return None, None


def main() -> int:
    args = parse_args()
    keyword = args.keyword.strip()
    if not keyword:
        raise SystemExit("ERROR: --keyword must not be blank.")
    if args.limit < 1:
        raise SystemExit("ERROR: --limit must be positive.")

    history = AnnouncementHistorySearchService(state_database_path=args.database)
    source = SOURCE_FILTERS[args.source]
    desired_region = history._desired_region(source)
    state_source = TW_OFFICIAL if desired_region == "tw" else CN_OFFICIAL if desired_region == "cn" else None
    state_candidates, state_has_more = history._search_state_candidates(
        keyword, source=state_source, candidate_limit=DEFAULT_CANDIDATE_LIMIT
    )
    raw_candidates, raw_has_more = history._search_raw_candidates(
        keyword, desired_region=desired_region, candidate_limit=DEFAULT_CANDIDATE_LIMIT
    )
    candidates = (*state_candidates, *raw_candidates)
    merged, retained_keys = merge_search_results(candidates)
    final_results = merged[: args.limit]
    rank_by_key = _rank_by_key(merged)
    final_keys = {_result_key(result) for result in final_results}

    variants = keyword_search_variants(keyword)
    stage_counts = {
        "announcements_sql_candidates": len(state_candidates),
        "raw_posts_sql_candidates": len(raw_candidates),
        "after_source_filter": len(candidates),
        "after_deduplication": len(merged),
        "after_limit": len(final_results),
        "announcements_has_more": state_has_more,
        "raw_posts_has_more": raw_has_more,
        "discord_render_results": len(final_results),
    }
    print(f"announcement_state_database: {args.database}")
    print(f"source: {args.source}")
    print(f"keyword: {keyword}")
    print(f"search_variants: {', '.join(variants)}")
    print(json.dumps(stage_counts, ensure_ascii=False))
    for result in candidates:
        key = _result_key(result)
        kept = key in retained_keys
        rank = rank_by_key.get(key)
        final_included = key in final_keys
        exclusion_reason = None
        if not kept:
            exclusion_reason = "deduplicated"
        elif not final_included:
            exclusion_reason = "limit"
        matched_field, matched_excerpt = _match_details(result.title, result.content_text, variants)
        record = {
            "source_kind": result.source_kind,
            "id": result.source_record_id,
            "source": result.source,
            "region": result.region,
            "external_id": result.external_id,
            "title": result.title,
            "content_length": len(result.content_text),
            "published_at": result.published_at,
            "canonical_url": result.canonical_url,
            "search_variants": variants,
            "matched_field": matched_field,
            "matched_excerpt": matched_excerpt,
            "pre_filter_match": True,
            "source_filter_kept": True,
            "dedupe_key": _deduplication_keys(result),
            "dedupe_kept": kept,
            "final_rank": rank,
            "final_included": final_included,
            "exclusion_reason": exclusion_reason,
        }
        print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
