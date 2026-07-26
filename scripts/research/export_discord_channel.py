"""Export one Discord channel through the REST API for local research only."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as datetime_time, timedelta
from pathlib import Path
from collections.abc import Callable
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DISCORD_API_BASE = "https://discord.com/api/v10"
PAGE_SIZE = 100
DEFAULT_LIMIT = 1000


class DiscordApiError(RuntimeError):
    """A clear, non-sensitive REST API failure."""


@dataclass(frozen=True)
class ExportResult:
    messages: list[dict[str, object]]
    pages_fetched: int


class DiscordChannelExporter:
    """Read-only Discord REST exporter with pagination and rate-limit handling."""

    def __init__(
        self,
        token: str,
        *,
        session: requests.Session | Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        api_base: str = DISCORD_API_BASE,
    ) -> None:
        self.token = token
        self.session = session or requests.Session()
        self.sleep = sleep
        self.api_base = api_base.rstrip("/")

    def export(
        self,
        channel_id: int,
        *,
        limit: int | None = DEFAULT_LIMIT,
        after: date | None = None,
        before: date | None = None,
        include_bots: bool = False,
        include_system: bool = False,
    ) -> ExportResult:
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1 when set")
        after_boundary = _start_of_day(after) if after else None
        before_boundary = _start_of_day(before + timedelta(days=1)) if before else None
        before_message_id: str | None = None
        seen_message_ids: set[str] = set()
        exported: list[dict[str, object]] = []
        pages_fetched = 0

        while limit is None or len(exported) < limit:
            page = self._fetch_page(channel_id, before_message_id)
            pages_fetched += 1
            if not page:
                break

            oldest_timestamp: datetime | None = None
            for message in page:
                timestamp = _parse_timestamp(str(message.get("timestamp", "")))
                if timestamp is not None and (oldest_timestamp is None or timestamp < oldest_timestamp):
                    oldest_timestamp = timestamp
                record = _to_export_record(
                    message,
                    timestamp=timestamp,
                    after=after_boundary,
                    before=before_boundary,
                    include_bots=include_bots,
                    include_system=include_system,
                )
                if record is None or str(record["message_id"]) in seen_message_ids:
                    continue
                seen_message_ids.add(str(record["message_id"]))
                exported.append(record)
                if limit is not None and len(exported) >= limit:
                    break

            last_message_id = str(page[-1].get("id", ""))
            if not last_message_id or last_message_id == before_message_id:
                break
            before_message_id = last_message_id
            if after_boundary is not None and oldest_timestamp is not None and oldest_timestamp < after_boundary:
                break

        exported.sort(key=lambda item: str(item["timestamp"]))
        return ExportResult(messages=exported, pages_fetched=pages_fetched)

    def _fetch_page(self, channel_id: int, before_message_id: str | None) -> list[dict[str, Any]]:
        url = f"{self.api_base}/channels/{channel_id}/messages"
        params: dict[str, object] = {"limit": PAGE_SIZE}
        if before_message_id:
            params["before"] = before_message_id
        headers = {"Authorization": f"Bot {self.token}"}

        while True:
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=30)
            except requests.RequestException as error:
                raise DiscordApiError(f"Discord API request failed: {error}") from error
            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
                self.sleep(retry_after)
                continue
            if response.status_code in {401, 403, 404}:
                detail = {
                    401: "Discord token was rejected (401).",
                    403: "Bot cannot read this channel (403).",
                    404: "Discord channel was not found (404).",
                }[response.status_code]
                raise DiscordApiError(detail)
            if not response.ok:
                raise DiscordApiError(f"Discord API returned HTTP {response.status_code}.")
            payload = response.json()
            if not isinstance(payload, list):
                raise DiscordApiError("Discord API returned an unexpected messages payload.")
            return [item for item in payload if isinstance(item, dict)]


def load_discord_token() -> str:
    """Read DISCORD_TOKEN from the environment or the local, ignored .env file."""
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if token:
        return token
    dotenv_path = PROJECT_ROOT / ".env"
    if dotenv_path.exists():
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DISCORD_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("\"'")
                if token:
                    return token
    raise DiscordApiError("DISCORD_TOKEN is not configured in the environment or local .env.")


def parse_cli_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a Discord channel to a local JSON research file.")
    parser.add_argument("--channel-id", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    pagination = parser.add_mutually_exclusive_group()
    pagination.add_argument("--limit", type=int, help="Maximum exported messages (default: 1000).")
    pagination.add_argument("--all", action="store_true", help="Export all available channel history.")
    parser.add_argument("--after", type=parse_cli_date, help="Include messages on or after this UTC date.")
    parser.add_argument("--before", type=parse_cli_date, help="Include messages on or before this UTC date.")
    parser.add_argument("--include-bots", action="store_true")
    parser.add_argument("--include-system", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.before and args.after and args.before < args.after:
        raise SystemExit("--before must not be earlier than --after")
    try:
        result = DiscordChannelExporter(load_discord_token()).export(
            args.channel_id,
            limit=None if args.all else (args.limit or DEFAULT_LIMIT),
            after=args.after,
            before=args.before,
            include_bots=args.include_bots,
            include_system=args.include_system,
        )
    except DiscordApiError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(result.messages)} message(s) from {result.pages_fetched} page(s) to {args.output}.")
    return 0


def _to_export_record(
    message: dict[str, Any],
    *,
    timestamp: datetime | None,
    after: datetime | None,
    before: datetime | None,
    include_bots: bool,
    include_system: bool,
) -> dict[str, object] | None:
    content = str(message.get("content") or "").strip()
    author = message.get("author") if isinstance(message.get("author"), dict) else {}
    if not content or timestamp is None:
        return None
    if after is not None and timestamp < after:
        return None
    if before is not None and timestamp >= before:
        return None
    if not include_bots and bool(author.get("bot", False)):
        return None
    if not include_system and message.get("type", 0) != 0:
        return None
    message_id = str(message.get("id") or "")
    if not message_id:
        return None
    attachments = message.get("attachments") if isinstance(message.get("attachments"), list) else []
    return {
        "message_id": message_id,
        "author_id": str(author.get("id") or ""),
        "author_name": str(author.get("global_name") or author.get("username") or "unknown"),
        "timestamp": str(message["timestamp"]),
        "content": content,
        "is_bot": bool(author.get("bot", False)),
        "attachment_count": len(attachments),
    }


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _start_of_day(value: date) -> datetime:
    return datetime.combine(value, datetime_time.min, tzinfo=UTC)


def _retry_after_seconds(response: Any) -> float:
    try:
        payload = response.json()
        retry_after = float(payload.get("retry_after", 1.0)) if isinstance(payload, dict) else 1.0
    except (TypeError, ValueError):
        retry_after = 1.0
    return max(0.0, retry_after)


if __name__ == "__main__":
    raise SystemExit(main())
