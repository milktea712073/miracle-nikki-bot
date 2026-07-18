"""Refresh existing JoyBomb parser input from saved Wayback HTML fragments.

This offline maintenance tool never queries Wayback, creates raw posts, or
touches announcement/Knowledge tables.  It only updates ``raw_posts.content``
for existing ``joybomb_archive`` rows whose metadata contains ``content_html``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.joybomb_archive_crawler import CdxSnapshot, JoyBombArchiveError, parse_notice_document
from database.raw_post_repository import RawPostRepository


LOGGER = logging.getLogger(__name__)
JOYBOMB_ARCHIVE_SOURCE = "joybomb_archive"


@dataclass(slots=True)
class JoyBombRawContentRefreshResult:
    scanned: int = 0
    content_html_missing: int = 0
    changed: int = 0
    unchanged: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def _clean_content_from_metadata(row: dict[str, object]) -> str:
    try:
        metadata = json.loads(str(row["metadata_json"])) if row["metadata_json"] else {}
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("metadata_json is invalid") from error
    content_html = metadata.get("content_html")
    if not isinstance(content_html, str) or not content_html.strip():
        raise LookupError("content_html is missing")
    original_url = metadata.get("original_url") or row["url"]
    archive_timestamp = metadata.get("archive_timestamp") or "00000000000000"
    if not isinstance(original_url, str) or not original_url.strip():
        raise ValueError("original_url is missing")
    notice = parse_notice_document(
        CdxSnapshot(
            timestamp=str(archive_timestamp),
            original_url=original_url,
            status_code="200",
            mimetype="text/html",
            digest="offline-refresh",
        ),
        content_html,
    )
    if not notice.content_text.strip():
        raise ValueError("cleaned content_text is empty")
    return notice.content_text.strip()


def refresh_joybomb_raw_content(
    database_path: Path | None = None,
    *,
    dry_run: bool = False,
) -> JoyBombRawContentRefreshResult:
    """Rebuild saved JoyBomb parser input from metadata HTML without network I/O."""
    repository = RawPostRepository(database_path)
    result = JoyBombRawContentRefreshResult()
    for row in repository.list_raw_posts_for_content_refresh(source=JOYBOMB_ARCHIVE_SOURCE):
        result.scanned += 1
        try:
            content = _clean_content_from_metadata(row)
        except LookupError:
            result.content_html_missing += 1
            continue
        except (JoyBombArchiveError, ValueError) as error:
            result.failed += 1
            result.failures.append(f"raw_post_id={row['id']}: {error}")
            LOGGER.warning("Skipping JoyBomb raw_post_id=%s: %s", row["id"], error)
            continue

        if content == row["content"]:
            result.unchanged += 1
            continue
        if dry_run:
            result.changed += 1
            continue
        try:
            saved = repository.refresh_existing_raw_content(
                int(row["id"]), content, expected_source=JOYBOMB_ARCHIVE_SOURCE
            )
        except (ValueError, json.JSONDecodeError) as error:
            result.failed += 1
            result.failures.append(f"raw_post_id={row['id']}: {error}")
            LOGGER.warning("Failed to refresh JoyBomb raw_post_id=%s: %s", row["id"], error)
            continue
        if saved.action == "updated":
            result.changed += 1
        else:
            result.unchanged += 1
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh JoyBomb raw content from saved metadata HTML without network access."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing raw_posts.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    result = refresh_joybomb_raw_content(dry_run=args.dry_run)
    print(f"Scanned JoyBomb raw posts: {result.scanned}")
    print(f"Content HTML missing: {result.content_html_missing}")
    print(f"Content changed: {result.changed}")
    print(f"Content unchanged: {result.unchanged}")
    print(f"Failed: {result.failed}")
    for failure in result.failures:
        print(f"- {failure}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
