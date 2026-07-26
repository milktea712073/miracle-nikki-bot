"""Build privacy-safe deterministic Markdown and JSON research artifacts."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .candidate_scoring import score_candidate
from .kwic import kwic_examples
from .models import Candidate, ResearchMessage
from .ngrams import common_edge_patterns, mine_ngrams, repeated_short_phrases, suppress_overlapping_candidates
from .privacy import anonymize_authors, redact_text
from .reply_pairs import build_reply_index, find_replies


def build_candidates(
    messages: list[ResearchMessage],
    *,
    minimum_frequency: int,
    top: int,
    minimum_ngram: int,
    maximum_ngram: int,
    context_chars: int,
    reply_window_seconds: int,
    maximum_examples: int,
    author_mode: str,
) -> tuple[list[Candidate], dict[str, str], dict[str, Counter[str]]]:
    labels = anonymize_authors([message.author_id for message in messages])
    reply_index = build_reply_index(messages)
    total_months = len({message.month for message in messages})
    sources = [mine_ngrams(messages, minimum_ngram, maximum_ngram), repeated_short_phrases(messages)]
    occurrences: dict[str, dict[str, tuple[ResearchMessage, int]]] = defaultdict(dict)
    for source in sources:
        for phrase, examples in source.items():
            source_counts = Counter(message.message_id for message in examples)
            for message in examples:
                previous = occurrences[phrase].get(message.message_id)
                # A complete short sentence can also be an n-gram. Retain its
                # highest source count instead of double-counting that message.
                count = source_counts[message.message_id]
                if previous is None or count > previous[1]:
                    occurrences[phrase][message.message_id] = (message, count)
    phrase_counts = Counter({phrase: len(per_message) for phrase, per_message in occurrences.items()})
    # Avoid quadratic overlap suppression over every one-off n-gram in a large
    # private export.  Candidates below the requested threshold cannot appear
    # in the report, and 20x the requested output remains ample for ranking.
    eligible_counts = Counter({phrase: count for phrase, count in phrase_counts.items() if count >= minimum_frequency})
    bounded_counts = Counter(dict(sorted(eligible_counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))[: top * 20]))
    allowed = set(suppress_overlapping_candidates(bounded_counts))
    candidates: list[Candidate] = []
    for phrase in sorted(allowed):
        per_message = occurrences[phrase]
        examples = sorted((value[0] for value in per_message.values()), key=lambda message: (message.timestamp, message.message_id))
        frequency = sum(value[1] for value in per_message.values())
        if frequency < minimum_frequency:
            continue
        author_keys = {labels[message.author_id] for message in examples}
        if author_mode == "per-author" and len(author_keys) < 1:
            continue
        candidate = Candidate(
            text=phrase,
            normalized_text=phrase,
            frequency=frequency,
            message_count=len(examples),
            author_keys=author_keys,
            months={message.month for message in examples},
            examples=examples[:maximum_examples],
        )
        evidence = []
        for example in candidate.examples:
            evidence.extend(
                find_replies(
                    example,
                    messages,
                    labels,
                    window_seconds=reply_window_seconds,
                    index=reply_index,
                )
            )
        candidate.reply_evidence = evidence
        monthly = Counter(message.month for message in examples)
        average = candidate.frequency / total_months if total_months else 0
        candidate.burst_months = sorted(month for month, count in monthly.items() if average and count / average >= 3)
        score_candidate(candidate, total_months)
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item.score, -item.frequency, -len(item.text), item.text))
    return candidates[:top], labels, _monthly_phrase_counts(candidates)


def write_reports(
    output_dir: Path,
    candidates: list[Candidate],
    messages: list[ResearchMessage],
    *,
    source_file: Path,
    parameters: dict[str, Any],
    context_chars: int,
    maximum_examples: int,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trigger_path = output_dir / "ambient_trigger_candidates.md"
    reply_path = output_dir / "ambient_reply_candidates.md"
    json_path = output_dir / "ambient_candidate_data.json"
    trigger_path.write_text(render_trigger_report(candidates, messages, context_chars, maximum_examples), encoding="utf-8")
    reply_path.write_text(render_reply_report(candidates), encoding="utf-8")
    json_path.write_text(
        json.dumps(candidate_json(candidates, messages, source_file, parameters), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return trigger_path, reply_path, json_path


def render_trigger_report(candidates: list[Candidate], messages: list[ResearchMessage], context_chars: int, maximum_examples: int) -> str:
    months = sorted({message.month for message in messages})
    lines = [
        "# Ambient Nikki Trigger 候選", "", "> 僅供本地人工研究；作者、Discord ID、URL 與提及已匿名化或遮罩。", "",
        "## 分析摘要", "", f"- 分析訊息數：{len(messages)}", f"- 日期範圍：{months[0] if months else '無'} 至 {months[-1] if months else '無'}", f"- 候選數：{len(candidates)}", "",
        "## 候選評分方法", "", "分數 = 頻率（最多 3）+ 作者多樣性（最多 2）+ 穩定度（最多 2）+ 短語長度（最多 1）+ 回覆性（最多 1.5）− 單月爆發扣分 − 通用語扣分。", "",
    ]
    for title, category in (
        ("長期穩定候選", "long_term_candidate"),
        ("可回覆候選", "conversational_replyable_candidate"),
        ("活動型候選", "event_like_candidate"),
        ("模糊候選", "needs_review"),
    ):
        lines.extend([f"## {title}", ""])
        selected = [candidate for candidate in candidates if candidate.category == category]
        lines.extend(_candidate_summary(candidate) for candidate in selected)
        if not selected:
            lines.append("- 無")
        lines.append("")
    prefixes, suffixes = common_edge_patterns(candidate.text for candidate in candidates)
    lines.extend(["## 常見前綴／後綴片段", ""])
    lines.extend(f"- 前綴 {text}：{count}" for text, count in prefixes.most_common(10))
    lines.extend(f"- 後綴 {text}：{count}" for text, count in suffixes.most_common(10))
    if not prefixes and not suffixes:
        lines.append("- 無")
    lines.extend(["", "## 候選 KWIC", ""])
    for candidate in candidates:
        lines.extend([f"### 候選：{candidate.text}", "", f"- 頻率：{candidate.frequency}", f"- 作者數：{len(candidate.author_keys)}", f"- 首次／最後：{candidate.first_seen} / {candidate.last_seen}", f"- 活躍月份：{len(candidate.months)}", f"- 分類：{candidate.category}", f"- Flags：{', '.join(sorted(candidate.flags)) or '無'}", "", "#### 上下文", ""])
        contexts = kwic_examples(messages, candidate.text, context_chars=context_chars, maximum=maximum_examples)
        lines.extend(f"- {month}：{context}" for month, context in contexts)
        if not contexts:
            lines.append("- 無")
        lines.append("")
    lines.extend(["## Manual Review Template", ""])
    for candidate in candidates[:30]:
        lines.extend([f"- [ ] Candidate: {candidate.text}", "  - Keep as trigger:", "  - Merge with:", "  - Suggested id:", "  - Emotion:", "  - Notes:", ""])
    return "\n".join(lines)


def render_reply_report(candidates: list[Candidate]) -> str:
    lines = [
        "# Ambient Nikki Reply 候選", "", "> 回覆關聯優先採 Discord reply reference；否則僅保留同頻道、不同作者、時間窗內的前幾則訊息。所有內容已遮罩。", "",
        "## 最有回覆性的 Trigger 候選", "",
    ]
    selected = [candidate for candidate in candidates if candidate.reply_evidence]
    for candidate in selected:
        lines.extend([f"## Trigger 候選：{candidate.text}", "", "### 常見後續回覆", "", "| 回覆 | 次數 | 作者數 | Direct reply | Flags |", "|---|---:|---:|---:|---|"])
        grouped: dict[str, list] = defaultdict(list)
        for reply in candidate.reply_evidence:
            grouped[reply.text].append(reply)
        for text, replies in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))[:10]:
            flags = ", ".join(sorted({flag for reply in replies for flag in reply.flags}))
            lines.append(f"| {text} | {len(replies)} | {len({reply.author_key for reply in replies})} | {sum(reply.direct_reply for reply in replies)} | {flags} |")
        lines.extend(["", "### 真實匿名對話例", ""])
        for trigger in candidate.examples[:3]:
            trigger_text, _ = redact_text(trigger.content)
            lines.extend([f"Trigger：\n> {trigger_text}", ""])
            matching = candidate.reply_evidence[:1]
            if matching:
                lines.extend([f"Reply：\n> {matching[0].author_key}：{matching[0].text}", ""])
        lines.append("")
    if not selected:
        lines.append("- 無可安全配對的回覆候選。")
    lines.extend(["", "## 人工挑選提醒", "", "- 人類回覆並不代表適合 Bot；請人工檢查語境、語氣與私人資訊。", "- `too_generic`、`context_dependent` 與 `sensitive_or_private` 均不應直接轉入正式設定。", ""])
    return "\n".join(lines)


def candidate_json(candidates: list[Candidate], messages: list[ResearchMessage], source_file: Path, parameters: dict[str, Any]) -> dict[str, Any]:
    months = sorted({message.month for message in messages})
    return {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "source_file": source_file.name,
            "message_count": len(messages),
            "date_range": {"start": months[0] if months else None, "end": months[-1] if months else None},
            "parameters": parameters,
        },
        "trigger_candidates": [_candidate_json(candidate, messages, parameters.get("context_chars", 20), parameters.get("max_examples", 10)) for candidate in candidates],
    }


def _candidate_json(candidate: Candidate, messages: list[ResearchMessage], context_chars: int, maximum_examples: int) -> dict[str, Any]:
    top_replies = Counter(reply.text for reply in candidate.reply_evidence).most_common(10)
    return {
        "text": candidate.text,
        "normalized_text": candidate.normalized_text,
        "score": candidate.score,
        "category": candidate.category,
        "frequency": candidate.frequency,
        "message_count": candidate.message_count,
        "author_count": len(candidate.author_keys),
        "active_months": len(candidate.months),
        "first_seen": candidate.first_seen,
        "last_seen": candidate.last_seen,
        "stability_ratio": round(len(candidate.months) / len({message.month for message in messages}), 3) if messages else 0.0,
        "burst_months": candidate.burst_months,
        "examples": [redact_text(message.content)[0] for message in candidate.examples],
        "kwic": [context for _month, context in kwic_examples(messages, candidate.text, context_chars=context_chars, maximum=maximum_examples)],
        "reply_stats": {
            "reply_count": len(candidate.reply_evidence),
            "direct_reply_count": sum(reply.direct_reply for reply in candidate.reply_evidence),
            "unique_reply_count": len(top_replies),
            "top_replies": [{"text": text, "count": count} for text, count in top_replies],
        },
        "flags": sorted(candidate.flags),
    }


def _candidate_summary(candidate: Candidate) -> str:
    return f"- **{candidate.text}**：score {candidate.score:.2f}／頻率 {candidate.frequency}／作者 {len(candidate.author_keys)}／月份 {len(candidate.months)}／flags {', '.join(sorted(candidate.flags)) or '無'}"


def _monthly_phrase_counts(candidates: list[Candidate]) -> dict[str, Counter[str]]:
    values: dict[str, Counter[str]] = defaultdict(Counter)
    for candidate in candidates:
        for example in candidate.examples:
            values[example.month][candidate.text] += 1
    return dict(values)
