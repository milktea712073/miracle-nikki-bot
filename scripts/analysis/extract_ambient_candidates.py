"""Mine privacy-safe Ambient Nikki trigger and reply candidates from local exports."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

# Direct ``python scripts/analysis/extract_ambient_candidates.py`` execution
# places scripts/analysis on sys.path, not the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analysis.chat_analysis.models import ResearchMessage
from scripts.analysis.chat_analysis.report_writer import build_candidates, write_reports
from scripts.research.analyze_discord_chat import load_messages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Ambient Nikki corpus mining. No network, AI, or Bot interaction.")
    parser.add_argument("--input", required=True, type=Path, help="JSON created by export_discord_channel.py")
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--min-frequency", type=int, default=3)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--min-ngram", type=int, default=2)
    parser.add_argument("--max-ngram", type=int, default=6)
    parser.add_argument("--context-chars", type=int, default=20)
    parser.add_argument("--reply-window-seconds", type=int, default=300)
    parser.add_argument("--max-examples", type=int, default=10)
    parser.add_argument("--author-mode", choices=("all", "per-author"), default="all")
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--exclude-bots", action=argparse.BooleanOptionalAction, default=True)
    return parser


def load_research_messages(path: Path, *, exclude_bots: bool) -> list[ResearchMessage]:
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("chat export must be a JSON array")
    loaded = {message.message_id: message for message in load_messages(path)}
    messages: list[ResearchMessage] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        message = loaded.get(str(item.get("message_id") or ""))
        if message is None or (exclude_bots and bool(item.get("is_bot", False))):
            continue
        messages.append(ResearchMessage(
            message.message_id, message.author_id, message.timestamp, message.content,
            str(item.get("channel_id") or ""),
            str(item["reply_to_message_id"]) if item.get("reply_to_message_id") is not None else None,
            bool(item.get("is_bot", False)),
        ))
    return sorted(messages, key=lambda item: (item.timestamp, item.message_id))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if min(args.min_frequency, args.top, args.min_ngram, args.max_ngram, args.context_chars, args.reply_window_seconds, args.max_examples) < 1:
        raise SystemExit("all numeric limits must be at least 1")
    if args.min_ngram > args.max_ngram:
        raise SystemExit("--min-ngram must not exceed --max-ngram")
    try:
        messages = load_research_messages(args.input, exclude_bots=args.exclude_bots)
        if args.start_date:
            messages = [message for message in messages if message.timestamp.date() >= args.start_date]
        if args.end_date:
            messages = [message for message in messages if message.timestamp.date() <= args.end_date]
        candidates, _labels, _monthly = build_candidates(
            messages, minimum_frequency=args.min_frequency, top=args.top, minimum_ngram=args.min_ngram,
            maximum_ngram=args.max_ngram, context_chars=args.context_chars,
            reply_window_seconds=args.reply_window_seconds, maximum_examples=args.max_examples,
            author_mode=args.author_mode,
        )
        parameters = {key: value for key, value in vars(args).items() if key not in {"input", "output_dir"}}
        paths = write_reports(args.output_dir, candidates, messages, source_file=args.input, parameters=parameters, context_chars=args.context_chars, maximum_examples=args.max_examples)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 1
    print(f"Analyzed {len(messages)} message(s), found {len(candidates)} candidate(s).")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
