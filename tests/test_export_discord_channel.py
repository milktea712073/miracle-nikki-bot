"""Tests for the standalone, read-only Discord REST export tool."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.research.export_discord_channel import DiscordApiError, DiscordChannelExporter, build_parser


class FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(self, _url: str, *, params: dict[str, object], headers: dict[str, str], timeout: int):
        self.calls.append({"params": params, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)


def message(
    message_id: str,
    timestamp: str,
    content: str,
    *,
    bot: bool = False,
    message_type: int = 0,
) -> dict[str, object]:
    return {
        "id": message_id,
        "timestamp": timestamp,
        "content": content,
        "type": message_type,
        "author": {"id": f"author-{message_id}", "username": f"User {message_id}", "bot": bot},
        "attachments": [{"id": "attachment"}],
    }


def test_export_paginates_and_excludes_bot_system_and_blank_messages() -> None:
    session = FakeSession([
        FakeResponse(200, [
            message("3", "2026-01-03T12:00:00Z", "最新訊息"),
            message("2", "2026-01-02T12:00:00Z", "Bot 訊息", bot=True),
        ]),
        FakeResponse(200, [
            message("1", "2026-01-01T12:00:00Z", "舊訊息"),
            message("system", "2026-01-01T11:00:00Z", "系統", message_type=7),
            message("blank", "2026-01-01T10:00:00Z", "   "),
        ]),
        FakeResponse(200, []),
    ])

    result = DiscordChannelExporter("token", session=session).export(123, limit=None)

    assert [item["message_id"] for item in result.messages] == ["1", "3"]
    assert result.messages[0]["attachment_count"] == 1
    assert result.messages[0]["channel_id"] == "123"
    assert result.messages[0]["reply_to_message_id"] is None
    assert result.pages_fetched == 3
    assert session.calls[1]["params"] == {"limit": 100, "before": "2"}


def test_export_retries_429_using_retry_after() -> None:
    slept: list[float] = []
    session = FakeSession([
        FakeResponse(429, {"retry_after": 1.25}),
        FakeResponse(200, [message("1", "2026-01-01T12:00:00Z", "收嗎")]),
    ])

    result = DiscordChannelExporter("token", session=session, sleep=slept.append).export(123, limit=1)

    assert [item["message_id"] for item in result.messages] == ["1"]
    assert slept == [1.25]
    assert len(session.calls) == 2


def test_export_preserves_reply_reference_for_offline_research() -> None:
    reply = message("2", "2026-01-02T12:00:00Z", "我也想收")
    reply["message_reference"] = {"message_id": "1"}
    session = FakeSession([FakeResponse(200, [reply])])

    result = DiscordChannelExporter("token", session=session).export(123, limit=1)

    assert result.messages[0]["reply_to_message_id"] == "1"


def test_all_mode_is_mutually_exclusive_with_limit_and_allows_unbounded_export() -> None:
    parser = build_parser()
    args = parser.parse_args(["--channel-id", "123", "--output", "chat.json", "--all"])

    assert args.all is True
    assert args.limit is None
    with pytest.raises(SystemExit):
        parser.parse_args(["--channel-id", "123", "--output", "chat.json", "--all", "--limit", "20"])


def test_export_filters_dates_inclusively_by_utc_calendar_day() -> None:
    session = FakeSession([
        FakeResponse(200, [
            message("3", "2026-01-03T00:00:00Z", "第三天"),
            message("2", "2026-01-02T12:00:00Z", "第二天"),
            message("1", "2026-01-01T23:59:00Z", "第一天"),
        ]),
    ])

    result = DiscordChannelExporter("token", session=session).export(
        123, limit=None, after=date(2026, 1, 2), before=date(2026, 1, 2)
    )

    assert [item["message_id"] for item in result.messages] == ["2"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "token"), (403, "cannot read"), (404, "not found")],
)
def test_export_reports_clear_auth_and_channel_errors(status: int, expected: str) -> None:
    session = FakeSession([FakeResponse(status, {})])

    with pytest.raises(DiscordApiError, match=expected):
        DiscordChannelExporter("token", session=session).export(123)
