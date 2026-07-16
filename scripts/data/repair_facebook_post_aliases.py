"""Review and repair legacy duplicate Facebook raw posts caused by pfbid aliases."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH
from database.facebook_alias_repository import FacebookAliasRepository, FacebookDuplicateGroup


def print_group(index: int, group: FacebookDuplicateGroup) -> None:
    """Print enough evidence for an operator to review one candidate group."""
    print(f"[{index}] raw_posts: {', '.join(map(str, group.raw_post_ids))}")
    print(f"  published_at: {group.published_at}")
    print(f"  stable images: {', '.join(group.image_filenames) or '(none)'}")
    print(f"  source IDs: {', '.join(group.source_post_ids)}")
    print(f"  URLs: {' | '.join(group.urls)}")
    print(f"  content: {group.content_preview}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review duplicate Facebook pfbid raw posts before manually merging aliases."
    )
    parser.add_argument("--database-path", type=Path, default=DATABASE_PATH)
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input
) -> int:
    args = parse_args(argv)
    repository = FacebookAliasRepository(args.database_path)
    groups = repository.list_duplicate_groups()
    if not groups:
        print("No Facebook alias repair candidates found.")
        return 0
    print(f"Found {len(groups)} Facebook duplicate candidate group(s):")
    for index, group in enumerate(groups, start=1):
        print_group(index, group)
    if input_fn("Type YES to merge these reviewed groups: ").strip() != "YES":
        print("Facebook alias repair cancelled.")
        return 0
    for group in groups:
        result = repository.merge_group(group)
        print(
            "Merged raw posts "
            f"{', '.join(map(str, result.merged_raw_post_ids))} into {result.survivor_raw_post_id}; "
            f"aliases created: {result.aliases_created}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
