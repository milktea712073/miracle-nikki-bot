"""Conservative reply evidence extraction from local Discord exports."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import ReplyEvidence, ResearchMessage
from .privacy import redact_text


GENERIC_REPLIES = frozenset({"喔", "嗯", "笑死", "哈哈", "哈哈哈", "好", "可以", "真的"})


@dataclass(frozen=True)
class ReplyIndex:
    by_channel: dict[str, tuple[ResearchMessage, ...]]
    timestamps_by_channel: dict[str, tuple[datetime, ...]]
    direct_by_message_id: dict[str, tuple[ResearchMessage, ...]]


def build_reply_index(messages: Iterable[ResearchMessage]) -> ReplyIndex:
    by_channel: dict[str, list[ResearchMessage]] = defaultdict(list)
    direct: dict[str, list[ResearchMessage]] = defaultdict(list)
    for message in messages:
        by_channel[message.channel_id].append(message)
        if message.reply_to_message_id:
            direct[message.reply_to_message_id].append(message)
    ordered = {channel: tuple(sorted(values, key=lambda item: (item.timestamp, item.message_id))) for channel, values in by_channel.items()}
    return ReplyIndex(
        by_channel=ordered,
        timestamps_by_channel={channel: tuple(item.timestamp for item in values) for channel, values in ordered.items()},
        direct_by_message_id={identifier: tuple(sorted(values, key=lambda item: (item.timestamp, item.message_id))) for identifier, values in direct.items()},
    )


def find_replies(
    trigger: ResearchMessage,
    messages: Iterable[ResearchMessage],
    author_labels: dict[str, str],
    *,
    window_seconds: int,
    maximum: int = 3,
    index: ReplyIndex | None = None,
) -> list[ReplyEvidence]:
    """Prefer direct references; otherwise retain only the first other-author messages."""
    direct: list[ReplyEvidence] = []
    fallback: list[ReplyEvidence] = []
    if index is not None:
        direct_messages = index.direct_by_message_id.get(trigger.message_id, ())
        channel_messages = index.by_channel.get(trigger.channel_id, ())
        positions = index.timestamps_by_channel.get(trigger.channel_id, ())
        start = bisect_right(positions, trigger.timestamp)
        end = bisect_right(positions, trigger.timestamp + timedelta(seconds=window_seconds))
        candidates = (*direct_messages, *channel_messages[start:end])
    else:
        candidates = tuple(messages)
    seen_ids: set[str] = set()
    for candidate in candidates:
        if candidate.message_id in seen_ids:
            continue
        seen_ids.add(candidate.message_id)
        if candidate.message_id == trigger.message_id or candidate.channel_id != trigger.channel_id:
            continue
        delay = (candidate.timestamp - trigger.timestamp).total_seconds()
        if delay < 0 or delay > window_seconds or candidate.author_id == trigger.author_id:
            continue
        direct_reply = candidate.reply_to_message_id == trigger.message_id
        text, private = redact_text(candidate.content)
        flags = set(reply_quality_flags(text))
        if private:
            flags.add("sensitive_or_private")
        evidence = ReplyEvidence(text, author_labels[candidate.author_id], delay, direct_reply, tuple(sorted(flags)))
        if direct_reply:
            direct.append(evidence)
        elif len(fallback) < maximum:
            fallback.append(evidence)
    return (direct[:maximum] or fallback[:maximum])


def reply_quality_flags(text: str) -> tuple[str, ...]:
    flags: set[str] = set()
    if len(text) <= 4 or text in GENERIC_REPLIES:
        flags.add("too_generic")
    if any(marker in text for marker in ("哈哈", "笑死", "你", "妳")):
        flags.add("teasing")
    if any(marker in text for marker in ("恭喜", "加油", "好看", "可以")):
        flags.add("supportive")
    if not flags:
        flags.add("standalone_reply")
    elif "too_generic" not in flags:
        flags.add("context_dependent")
    return tuple(sorted(flags))
