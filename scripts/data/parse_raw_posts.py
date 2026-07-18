"""Parse source-neutral raw posts, optionally stopping at section-level drafts."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.auto_import_service import auto_import_parse_draft
from database.database import init_database
from database.parse_draft_repository import ParseDraftRepository
from content.section_splitter import split_notice_sections
from parser.shared_parser import parse_notice_section
from parser.announcement_parser import parse_announcement


LOGGER = logging.getLogger(__name__)
DEFAULT_PARSER_VERSION = "rules-v1"


@dataclass(frozen=True, slots=True)
class ParseRawPostsResult:
    selected: int
    succeeded: int
    failed: int
    skipped: int
    needs_review: int
    sections: int = 0
    drafts: int = 0
    multi_section_raw_posts: int = 0
    story_matches: int = 0
    diagnostics: tuple[dict[str, object], ...] = ()


def parse_pending_raw_posts(
    limit: int,
    database_path: Path | None = None,
    *,
    raw_post_id: int | None = None,
    force: bool = False,
    parser_version: str = DEFAULT_PARSER_VERSION,
    source: str | None = None,
    draft_only: bool = False,
) -> ParseRawPostsResult:
    """Parse raw posts into section-level drafts and optionally auto-import them."""
    init_database(database_path)
    if force and raw_post_id is None:
        raise ValueError("--force requires --raw-post-id.")
    repository = ParseDraftRepository(database_path)
    raw_posts = repository.list_raw_posts_for_parsing(limit, raw_post_id, force, source)
    succeeded = failed = needs_review = sections = drafts = multi_section_raw_posts = story_matches = 0
    diagnostics: list[dict[str, object]] = []
    for raw_post in raw_posts:
        try:
            metadata = json.loads(str(raw_post["metadata_json"])) if raw_post["metadata_json"] else {}
            content_type_hint = metadata.get("content_type_candidate")
            raw_title = metadata.get("title")
            split_result = split_notice_sections(
                str(raw_post["content"]),
                source=str(raw_post["source"]),
                source_post_id=str(raw_post["source_post_id"]),
                raw_post_id=int(raw_post["id"]),
                title=str(raw_title) if raw_title else None,
            )
            sections += split_result.section_count
            multi_section_raw_posts += int(split_result.section_count > 1)
            raw_post_failed = False
            parsed_sections = []
            for section in split_result.sections:
                try:
                    parsed = parse_notice_section(
                        section,
                        raw_title=str(raw_title) if raw_title else None,
                        source=str(raw_post["source"]),
                        content_type_hint=str(content_type_hint) if content_type_hint else None,
                        parser=parse_announcement,
                    )
                    parsed_sections.append((section, parsed))
                except Exception as error:
                    LOGGER.exception("Failed to parse raw post %s section %s", raw_post["source_post_id"], section.section_index)
                    repository.save_failed_draft(int(raw_post["id"]), parser_version, str(error), section=section)
                    raw_post_failed = True
                    failed += 1
            if raw_post_failed:
                continue
            if str(raw_post["source"]) == "joybomb_archive":
                saved_drafts = repository.sync_joybomb_section_drafts(
                    int(raw_post["id"]),
                    parser_version,
                    [(section, parsed.draft) for section, parsed in parsed_sections],
                ).saved
            else:
                saved_drafts = tuple(
                    repository.save_parse_draft(
                        int(raw_post["id"]), parser_version, parsed.draft, section=section
                    )
                    for section, parsed in parsed_sections
                )
            for (section, parsed), saved in zip(parsed_sections, saved_drafts, strict=True):
                drafts += 1
                story_matches += len(parsed.story_event_matches)
                status = "pending"
                if not draft_only:
                    imported = auto_import_parse_draft(saved.parse_draft_id, database_path)
                    status = imported.status
                    needs_review += int(imported.status == "needs_review")
                diagnostics.append({
                    "raw_post_id": raw_post["id"], "source": raw_post["source"],
                    "source_post_id": raw_post["source_post_id"], "raw_title": raw_title,
                    "section_index": section.section_index, "section_heading": section.heading,
                    "section_hash": section.section_hash, "splitter_version": section.splitter_version,
                    "parse_draft_id": saved.parse_draft_id,
                    "event_name_candidate": parsed.draft.event_name_candidate,
                    "content_type_candidate": parsed.draft.content_type_candidate,
                    "suit_candidates": [suit.name for suit in parsed.draft.suits],
                    "story_event_matches": [match.canonical_name for match in parsed.story_event_matches],
                    "status": status,
                })
            succeeded += 1
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower():
                raise
            LOGGER.exception("Failed to parse raw post %s", raw_post["source_post_id"])
            repository.save_failed_draft(int(raw_post["id"]), parser_version, str(error))
            failed += 1
        except Exception as error:
            LOGGER.exception("Failed to parse raw post %s", raw_post["source_post_id"])
            repository.save_failed_draft(int(raw_post["id"]), parser_version, str(error))
            failed += 1
    return ParseRawPostsResult(
        len(raw_posts), succeeded, failed, 0, needs_review, sections, drafts,
        multi_section_raw_posts, story_matches, tuple(diagnostics),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse pending raw posts and update derived knowledge data in the local database."
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--raw-post-id", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--parser-version", default=DEFAULT_PARSER_VERSION)
    parser.add_argument("--source")
    parser.add_argument("--draft-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    try:
        result = parse_pending_raw_posts(
            args.limit,
            raw_post_id=args.raw_post_id,
            force=args.force,
            parser_version=args.parser_version,
            source=args.source,
            draft_only=args.draft_only,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"\u5f85\u89e3\u6790\uff1a{result.selected}")
    print(f"\u6210\u529f\uff1a{result.succeeded}")
    print(f"\u5931\u6557\uff1a{result.failed}")
    print(f"\u7565\u904e\uff1a{result.skipped}")
    print(f"\u6bb5\u843d\uff1a{result.sections}")
    print(f"Parse Draft\uff1a{result.drafts}")
    print(f"\u591a\u6bb5\u516c\u544a\uff1a{result.multi_section_raw_posts}")
    print(f"\u6545\u4e8b\u5957\u88dd\u547d\u4e2d\uff1a{result.story_matches}")
    for diagnostic in result.diagnostics:
        print(json.dumps(diagnostic, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
