"""Produce a local Markdown report for Ambient Nikki language research.

The analysis intentionally uses only deterministic standard-library heuristics.
It does not send Discord messages, use AI services, or alter exported JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "收套": ("收", "收嗎", "收完", "全收"),
    "活動": ("大閣", "扭蛋", "福袋", "復刻"),
    "課金": ("648", "課", "儲值", "鑽"),
    "外觀喜好": ("2D", "Live2D", "跳", "喜歡", "好看", "好貴"),
}
DEFAULT_KEYWORD_PATH = PROJECT_ROOT / "config" / "chat_analysis_keywords.json"
MAX_KWIC_EXAMPLES = 50
MAX_NGRAMS = 30
EMOJI_RANGES = ((0x1F300, 0x1FAFF), (0x2600, 0x27BF))
GAME_TERMS = frozenset(term for terms in DEFAULT_KEYWORD_GROUPS.values() for term in terms)
EASY_AMBIENT_TERMS = frozenset({"收", "收嗎", "收完", "全收", "大閣", "扭蛋", "福袋", "復刻", "課", "儲值"})
NUMERIC_TERMS = frozenset({"648"})
TEMPORAL_TERMS = ("收", "課", "大閣", "復刻", "扭蛋", "福袋", "喜歡", "648")


@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    author_id: str
    author_name: str
    timestamp: datetime
    content: str


@dataclass(frozen=True)
class KeywordStat:
    occurrences: int
    message_count: int


@dataclass(frozen=True)
class KeywordLifetime:
    first_seen: str
    last_seen: str
    active_months: int
    total_months: int
    stability_stars: int
    average_per_month: float
    peak_count: int
    peak_month: str
    burst_stars: int


def load_messages(path: Path) -> list[ChatMessage]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("chat export must be a JSON array")
    messages: list[ChatMessage] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        timestamp = _parse_timestamp(item.get("timestamp"))
        content = item.get("content")
        if timestamp is None or not isinstance(content, str) or not content.strip():
            continue
        messages.append(
            ChatMessage(
                message_id=str(item.get("message_id") or ""),
                author_id=str(item.get("author_id") or ""),
                author_name=str(item.get("author_name") or "unknown"),
                timestamp=timestamp,
                content=content.strip(),
            )
        )
    return sorted(messages, key=lambda message: message.timestamp)


def load_keyword_groups(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    if path is None:
        path = DEFAULT_KEYWORD_PATH
        if not path.exists():
            return dict(DEFAULT_KEYWORD_GROUPS)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("keyword configuration must be a non-empty JSON object")
    groups: dict[str, tuple[str, ...]] = {}
    known_terms: set[str] = set()
    for group, values in payload.items():
        if not isinstance(group, str) or not group.strip() or not isinstance(values, list):
            raise ValueError("each keyword group must have a name and JSON array")
        terms: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("keywords must be non-empty strings")
            term = value.strip()
            if term not in known_terms:
                known_terms.add(term)
                terms.append(term)
        groups[group.strip()] = tuple(terms)
    return groups


def load_keywords(path: Path | None = None) -> tuple[str, ...]:
    """Compatibility helper returning the unique, configured terms in group order."""
    return tuple(term for terms in load_keyword_groups(path).values() for term in terms)


def load_stopwords(path: Path | None) -> frozenset[str]:
    if path is None:
        return frozenset()
    return frozenset(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def load_event_markers(path: Path | None) -> dict[str, tuple[str, ...]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("event marker configuration must be a JSON array")
    markers: dict[str, list[str]] = defaultdict(list)
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("date"), str) or not isinstance(item.get("label"), str):
            raise ValueError("each event marker needs string date and label fields")
        month = item["date"].strip()
        label = item["label"].strip()
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError as error:
            raise ValueError("event marker date must use YYYY-MM") from error
        if not label:
            raise ValueError("event marker label must not be blank")
        markers[month].append(label)
    return {month: tuple(labels) for month, labels in markers.items()}


def filter_game_messages(messages: Iterable[ChatMessage]) -> tuple[list[ChatMessage], int]:
    """Exclude code, links, quotes, long posts, and markup from analysis only."""
    kept: list[ChatMessage] = []
    excluded = 0
    for message in messages:
        if game_filter_reason(message.content) is None:
            kept.append(message)
        else:
            excluded += 1
    return kept, excluded


def game_filter_reason(content: str) -> str | None:
    stripped = content.strip()
    if len(stripped) > 150:
        return "long_message"
    if re.search(r"https?://|www\.|discord(?:app)?\.com/invite/|discord\.gg/", stripped, re.IGNORECASE):
        return "url_or_invite"
    if "```" in stripped:
        return "code_block"
    if any(line.lstrip().startswith(">") for line in stripped.splitlines()):
        return "quote"
    if re.search(r"<\/?[A-Za-z][^>]*>", stripped):
        return "html"
    if re.search(r"Traceback|File \".*\", line \d+|(?:[A-Za-z]+Error|Exception):", stripped):
        return "stack_trace"
    if re.search(r"\b(?:def|class|import|from)\s+[A-Za-z_]", stripped) or "print(" in stripped:
        return "python_code"
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            return "json"
    return None


def keyword_statistics(messages: Iterable[ChatMessage], keywords: Iterable[str]) -> dict[str, KeywordStat]:
    materialized = list(messages)
    result: dict[str, KeywordStat] = {}
    for keyword in keywords:
        matching = [message.content for message in materialized if keyword in message.content]
        result[keyword] = KeywordStat(
            occurrences=sum(content.count(keyword) for content in matching),
            message_count=len(matching),
        )
    return result


def keyword_in_context(messages: Iterable[ChatMessage], keyword: str, limit: int = MAX_KWIC_EXAMPLES) -> list[str]:
    contexts: list[str] = []
    for message in messages:
        start = 0
        while len(contexts) < limit:
            index = message.content.find(keyword, start)
            if index < 0:
                break
            contexts.append(_kwic_window(message.content, index, len(keyword)))
            start = index + len(keyword)
        if len(contexts) >= limit:
            break
    return contexts


def keyword_cooccurrence(messages: Iterable[ChatMessage], keywords: Iterable[str]) -> dict[str, Counter[str]]:
    terms = tuple(keywords)
    counts = {term: Counter() for term in terms}
    for message in messages:
        present = [term for term in terms if term in message.content]
        for term in present:
            counts[term].update(other for other in present if other != term)
    return counts


def monthly_keyword_counts(messages: Iterable[ChatMessage], keywords: Iterable[str]) -> tuple[dict[str, Counter[str]], Counter[str]]:
    """Count every keyword occurrence by calendar month without date inference."""
    terms = tuple(keywords)
    by_month: dict[str, Counter[str]] = defaultdict(Counter)
    message_counts: Counter[str] = Counter()
    for message in messages:
        month = message.timestamp.strftime("%Y-%m")
        message_counts[month] += 1
        for term in terms:
            by_month[month][term] += message.content.count(term)
    return dict(by_month), message_counts


def keyword_lifetime(monthly_counts: Mapping[str, Counter[str]], keyword: str) -> KeywordLifetime | None:
    months = sorted(monthly_counts)
    active = [month for month in months if monthly_counts[month][keyword] > 0]
    if not active:
        return None
    counts = [monthly_counts[month][keyword] for month in months]
    average = sum(counts) / len(months)
    peak = max(counts)
    peak_month = next(month for month in months if monthly_counts[month][keyword] == peak)
    stability = math.ceil(len(active) / len(months) * 5)
    burst_ratio = peak / average if average else 0.0
    if burst_ratio <= 1.5:
        burst_stars = 1
    elif burst_ratio <= 2.5:
        burst_stars = 2
    elif burst_ratio <= 4:
        burst_stars = 3
    elif burst_ratio <= 6:
        burst_stars = 4
    else:
        burst_stars = 5
    return KeywordLifetime(
        first_seen=active[0],
        last_seen=active[-1],
        active_months=len(active),
        total_months=len(months),
        stability_stars=stability,
        average_per_month=average,
        peak_count=peak,
        peak_month=peak_month,
        burst_stars=burst_stars,
    )


def chinese_ngrams(messages: Iterable[ChatMessage], size: int, stopwords: Iterable[str] = ()) -> Counter[str]:
    counts: Counter[str] = Counter()
    ordered_stopwords = sorted(set(stopwords), key=len, reverse=True)
    for message in messages:
        content = message.content
        for stopword in ordered_stopwords:
            content = content.replace(stopword, "")
        characters = "".join(character for character in content if _is_chinese(character))
        counts.update(characters[index:index + size] for index in range(max(0, len(characters) - size + 1)))
    return counts


def emoji_statistics(messages: Iterable[ChatMessage]) -> tuple[Counter[str], dict[str, Counter[str]]]:
    overall: Counter[str] = Counter()
    by_author: dict[str, Counter[str]] = defaultdict(Counter)
    for message in messages:
        emojis = extract_emojis(message.content)
        overall.update(emojis)
        by_author[message.author_id].update(emojis)
    return overall, dict(by_author)


def extract_emojis(content: str) -> list[str]:
    return [character for character in content if any(start <= ord(character) <= end for start, end in EMOJI_RANGES)]


def repeated_short_messages(messages: Iterable[ChatMessage]) -> Counter[str]:
    return Counter(message.content for message in messages if 2 <= len(message.content) <= 20)


def collect_analysis(messages: Iterable[ChatMessage]) -> tuple[Counter[str], Counter[str], Counter[str]]:
    prefixes: Counter[str] = Counter()
    suffixes: Counter[str] = Counter()
    patterns: Counter[str] = Counter()
    expression = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{0,2})收([\u4e00-\u9fffA-Za-z0-9]{0,3})")
    for message in messages:
        if "收" not in message.content:
            continue
        patterns[message.content] += 1
        for match in expression.finditer(message.content):
            if match.group(1):
                prefixes[match.group(1)] += 1
            if match.group(2):
                suffixes[match.group(2)] += 1
    return prefixes, suffixes, patterns


def render_report(
    messages: list[ChatMessage],
    keyword_groups: Mapping[str, tuple[str, ...]] | tuple[str, ...],
    *,
    stopwords: frozenset[str] = frozenset(),
    compare: bool = False,
    mode: str = "all",
    excluded_count: int = 0,
    event_markers: Mapping[str, tuple[str, ...]] | None = None,
) -> str:
    if not isinstance(keyword_groups, Mapping):
        keyword_groups = {"暖暖關鍵字": tuple(keyword_groups)}
    keywords = tuple(term for terms in keyword_groups.values() for term in terms)
    stats = keyword_statistics(messages, keywords)
    cooccurrence = keyword_cooccurrence(messages, keywords)
    author_labels = _author_labels(messages)
    lines = ["# 玩家聊天語言研究報告", "", "> 本報告僅供本地研究，玩家名稱已匿名化。", ""]
    lines.extend(_render_basic_stats(messages, author_labels, mode, excluded_count))
    lines.extend(_render_keywords(messages, keyword_groups, stats))
    lines.extend(_render_kwic(messages, keyword_groups))
    lines.extend(_render_cooccurrence(cooccurrence))
    lines.extend(_render_emoji_statistics(messages, author_labels))
    lines.extend(_render_repeated_short_messages(messages))
    lines.extend(_render_ngrams(messages, stopwords))
    lines.extend(_render_collect_analysis(messages))
    lines.extend(_render_player_phrases(messages, author_labels, keywords))
    if compare:
        lines.extend(_render_comparison(messages, author_labels, keywords))
    lines.extend(_render_ambient_candidates(stats, cooccurrence, messages, stopwords))
    lines.extend(_render_temporal_analysis(messages, keyword_groups, event_markers or {}, compare, author_labels))
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a local Discord chat export without AI services.")
    parser.add_argument("input", type=Path, help="JSON created by export_discord_channel.py")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--keywords", type=Path, help="Optional grouped keyword JSON configuration")
    parser.add_argument("--stopwords", type=Path, help="Optional stop word list used only for N-Grams")
    parser.add_argument("--events", type=Path, help="Optional YYYY-MM event marker JSON configuration")
    parser.add_argument("--mode", choices=("all", "game"), default="all")
    parser.add_argument("--compare", action="store_true", help="Compare the two most active anonymous players")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_messages = load_messages(args.input)
        messages, excluded_count = (
            filter_game_messages(source_messages) if args.mode == "game" else (source_messages, 0)
        )
        report = render_report(
            messages,
            load_keyword_groups(args.keywords),
            stopwords=load_stopwords(args.stopwords),
            compare=args.compare,
            mode=args.mode,
            excluded_count=excluded_count,
            event_markers=load_event_markers(args.events),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Analyzed {len(messages)} message(s) and wrote {args.output}.")
    return 0


def _render_basic_stats(
    messages: list[ChatMessage], labels: dict[str, str], mode: str, excluded_count: int
) -> list[str]:
    lines = ["## 1. 基本統計", "", f"- 分析模式：{mode}", f"- 訊息數：{len(messages)}"]
    if mode == "game":
        lines.append(f"- 已排除非遊戲聊天內容：{excluded_count}")
    if messages:
        lines.extend([
            f"- 日期範圍：{messages[0].timestamp.date()} 至 {messages[-1].timestamp.date()}",
            f"- 平均長度：{sum(len(message.content) for message in messages) / len(messages):.1f} 字",
        ])
    else:
        lines.extend(["- 日期範圍：無", "- 平均長度：0.0 字"])
    counts = Counter(message.author_id for message in messages)
    lines.extend(["", "### 每位使用者訊息數", ""])
    lines.extend(f"- {labels[author_id]}：{count}" for author_id, count in counts.most_common())
    return lines + [""]


def _render_keywords(
    messages: list[ChatMessage], groups: Mapping[str, tuple[str, ...]], stats: Mapping[str, KeywordStat]
) -> list[str]:
    total = len(messages)
    lines = ["## 2. 暖暖關鍵字統計", ""]
    for group, terms in groups.items():
        total_occurrences = sum(stats[term].occurrences for term in terms)
        lines.extend([f"### {group}", "", f"共 {total_occurrences} 次", "", "| 關鍵字 | 次數 | 含有該詞的訊息比例 |", "|---|---:|---:|"])
        for term in terms:
            stat = stats[term]
            percentage = stat.message_count / total * 100 if total else 0
            lines.append(f"| {term} | {stat.occurrences} | {percentage:.1f}% |")
        lines.append("")
    return lines


def _render_kwic(messages: list[ChatMessage], groups: Mapping[str, tuple[str, ...]]) -> list[str]:
    lines = ["## 3. Keyword In Context", ""]
    for group, terms in groups.items():
        lines.extend([f"### {group}", ""])
        for term in terms:
            contexts = keyword_in_context(messages, term)
            lines.extend([f"#### {term}", ""])
            lines.extend(f"- {context}" for context in contexts)
            if not contexts:
                lines.append("- 無")
            lines.append("")
    return lines


def _render_cooccurrence(cooccurrence: Mapping[str, Counter[str]]) -> list[str]:
    lines = ["## 4. 關鍵字共現", ""]
    for term, counts in cooccurrence.items():
        lines.extend([f"### {term}", "", "最常一起出現：", ""])
        lines.extend(f"- {other}：{count}" for other, count in counts.most_common(5))
        if not counts:
            lines.append("- 無")
        lines.append("")
    return lines


def _render_emoji_statistics(messages: list[ChatMessage], labels: Mapping[str, str]) -> list[str]:
    overall, by_author = emoji_statistics(messages)
    lines = ["## 5. Emoji 統計", "", "### 全體", ""]
    lines.extend(f"- {emoji}：{count}" for emoji, count in overall.most_common(20))
    if not overall:
        lines.append("- 無")
    lines.append("")
    for author_id, counts in by_author.items():
        lines.extend([f"### {labels[author_id]}", ""])
        lines.extend(f"- {emoji}：{count}" for emoji, count in counts.most_common(10))
        if not counts:
            lines.append("- 無")
        lines.append("")
    return lines


def _render_repeated_short_messages(messages: list[ChatMessage]) -> list[str]:
    repeated = repeated_short_messages(messages)
    lines = ["## 6. 重複短句（2～20 字）", ""]
    entries = [(text, count) for text, count in repeated.most_common() if count > 1]
    lines.extend(f"- {_safe_inline(text)}：{count}" for text, count in entries[:30])
    return lines + ([""] if entries else ["- 無重複短句", ""])


def _render_ngrams(messages: list[ChatMessage], stopwords: frozenset[str]) -> list[str]:
    suffix = "（已排除 stop words）" if stopwords else ""
    lines = [f"## 7. 中文字元 N-Gram{suffix}", ""]
    for size in (2, 3, 4):
        lines.extend([f"### {size}-gram", ""])
        counts = chinese_ngrams(messages, size, stopwords)
        lines.extend(f"- {gram}：{count}" for gram, count in counts.most_common(MAX_NGRAMS))
        if not counts:
            lines.append("- 無")
        lines.append("")
    return lines


def _render_collect_analysis(messages: list[ChatMessage]) -> list[str]:
    prefixes, suffixes, patterns = collect_analysis(messages)
    lines = ["## 8. 「收」專題分析", ""]
    for title, counts in (("常見前綴", prefixes), ("常見後綴", suffixes), ("常見句型", patterns)):
        lines.extend([f"### {title}", ""])
        lines.extend(f"- {_safe_inline(value)}：{count}" for value, count in counts.most_common(20))
        if not counts:
            lines.append("- 無")
        lines.append("")
    return lines


def _render_player_phrases(
    messages: list[ChatMessage], labels: Mapping[str, str], keywords: tuple[str, ...]
) -> list[str]:
    by_author: dict[str, list[ChatMessage]] = defaultdict(list)
    for message in messages:
        by_author[message.author_id].append(message)
    lines = ["## 9. 每位玩家常用語", ""]
    for author_id, authored_messages in by_author.items():
        counts = Counter(message.content for message in authored_messages if 2 <= len(message.content) <= 20)
        keyword_counts = Counter(
            keyword for message in authored_messages for keyword in keywords if keyword in message.content
        )
        phrases = [value for value, _count in counts.most_common(3)]
        phrases.extend(value for value, _count in keyword_counts.most_common(3) if value not in phrases)
        lines.extend([f"### {labels[author_id]}", ""])
        lines.extend(f"- {_safe_inline(phrase)}" for phrase in phrases[:5])
        if not phrases:
            lines.append("- 無足夠短句")
        lines.append("")
    return lines


def _render_comparison(messages: list[ChatMessage], labels: Mapping[str, str], keywords: tuple[str, ...]) -> list[str]:
    by_author: dict[str, list[ChatMessage]] = defaultdict(list)
    for message in messages:
        by_author[message.author_id].append(message)
    authors = [author_id for author_id, _messages in sorted(by_author.items(), key=lambda item: len(item[1]), reverse=True)[:2]]
    lines = ["## 10. 玩家比較", ""]
    if len(authors) < 2:
        return lines + ["- 至少需要兩位玩家的訊息。", ""]
    first, second = authors
    lines.extend([f"| 項目 | {labels[first]} | {labels[second]} |", "|---|---|---|"])
    lines.append(f"| 平均長度 | {_average_length(by_author[first]):.1f} | {_average_length(by_author[second]):.1f} |")
    lines.append(f"| 常用詞 | {_top_short_phrase(by_author[first])} | {_top_short_phrase(by_author[second])} |")
    lines.append(f"| Emoji | {_top_emojis(by_author[first])} | {_top_emojis(by_author[second])} |")
    lines.append(f"| 暖暖詞 | {_top_keywords(by_author[first], keywords)} | {_top_keywords(by_author[second], keywords)} |")
    return lines + [""]


def _render_ambient_candidates(
    stats: Mapping[str, KeywordStat], cooccurrence: Mapping[str, Counter[str]], messages: list[ChatMessage], stopwords: frozenset[str]
) -> list[str]:
    rankings = sorted(
        ((term, *_trigger_score(term, stat, cooccurrence[term])) for term, stat in stats.items() if stat.message_count),
        key=lambda item: (-item[1], -stats[item[0]].occurrences, item[0]),
    )
    lines = ["## 11. Ambient Trigger 排名", ""]
    for term, score, _reasons in rankings:
        lines.extend([_stars(score), "", term, ""])
    if not rankings:
        lines.append("- 尚無候選")
    lines.extend(["## 12. Ambient 建議", "", "### 可能適合", ""])
    recommended = [(term, reasons) for term, score, reasons in rankings if score >= 3 and term not in NUMERIC_TERMS]
    for term, reasons in recommended:
        lines.extend([f"✔ {term}", "", "原因：", "", *[f"- {reason}" for reason in reasons], ""])
    if not recommended:
        lines.append("- 尚無足夠穩定的候選")
    lines.extend(["### 不建議", ""])
    not_recommended = [(term, reasons) for term, score, reasons in rankings if score < 3 or term in NUMERIC_TERMS]
    for term, reasons in not_recommended:
        lines.extend([f"- {term}：{'；'.join(reasons)}"])
    if not not_recommended:
        lines.append("- 無")
    ignored = [word for word in stopwords if any(word in message.content for message in messages)]
    lines.extend(["", "## 13. 下一步建議", "", "### 建議新增 Trigger", ""])
    lines.extend(f"- {term}" for term, _reasons in recommended[:10])
    if not recommended:
        lines.append("- 先累積更多遊戲聊天語料")
    lines.extend(["", "### 建議忽略", ""])
    lines.extend(f"- {word}" for word in sorted(ignored))
    if not ignored:
        lines.append("- 尚未提供或命中 stop words")
    return lines + [""]


def _render_temporal_analysis(
    messages: list[ChatMessage],
    groups: Mapping[str, tuple[str, ...]],
    event_markers: Mapping[str, tuple[str, ...]],
    compare: bool,
    labels: Mapping[str, str],
) -> list[str]:
    keywords = tuple(term for terms in groups.values() for term in terms)
    monthly_counts, message_counts = monthly_keyword_counts(messages, keywords)
    terms = tuple(term for term in TEMPORAL_TERMS if term in keywords)
    lifetimes = {term: keyword_lifetime(monthly_counts, term) for term in keywords}
    lines = ["## 14. 時間分析", ""]
    lines.extend(_render_monthly_table(monthly_counts, message_counts, terms))
    lines.extend(_render_trigger_timeline(monthly_counts, keywords))
    lines.extend(_render_keyword_lifetime(lifetimes))
    lines.extend(_render_monthly_top_triggers(monthly_counts, keywords))
    lines.extend(_render_event_markers(monthly_counts, event_markers, terms))
    lines.extend(_render_trigger_evolution(lifetimes))
    lines.extend(_render_temporal_ambient_triggers(lifetimes))
    if compare:
        lines.extend(_render_compare_by_month(messages, labels, terms))
    lines.extend(_render_language_evolution(monthly_counts, groups))
    return lines


def _render_monthly_table(
    monthly_counts: Mapping[str, Counter[str]], message_counts: Counter[str], terms: tuple[str, ...]
) -> list[str]:
    lines = ["### 每月 Trigger 統計", ""]
    headers = ["月份", "訊息數", *terms]
    lines.extend(["| " + " | ".join(headers) + " |", "|" + "|".join("---:" for _ in headers) + "|"])
    for month in sorted(monthly_counts):
        values = [month, str(message_counts[month]), *(str(monthly_counts[month][term]) for term in terms)]
        lines.append("| " + " | ".join(values) + " |")
    if not monthly_counts:
        lines.append("| 無 | 0 |" + " |" * len(terms))
    return lines + [""]


def _render_trigger_timeline(monthly_counts: Mapping[str, Counter[str]], keywords: tuple[str, ...]) -> list[str]:
    lines = ["### Trigger Timeline", ""]
    months = sorted(monthly_counts)
    for term in keywords:
        lifetime = keyword_lifetime(monthly_counts, term)
        if lifetime is None:
            continue
        peak = lifetime.peak_count
        lines.extend([f"#### {term}", ""])
        for month in months:
            count = monthly_counts[month][term]
            bar = _timeline_bar(count, peak)
            lines.append(f"- {month} {bar} ({count})")
        lines.append("")
    if len(lines) == 2:
        lines.append("- 無")
    return lines


def _render_keyword_lifetime(lifetimes: Mapping[str, KeywordLifetime | None]) -> list[str]:
    lines = ["### Keyword Lifetime / Stability / Burst", ""]
    for term, lifetime in lifetimes.items():
        if lifetime is None:
            continue
        lines.extend([
            f"#### {term}", "",
            f"- First Seen：{lifetime.first_seen}",
            f"- Last Seen：{lifetime.last_seen}",
            f"- Active Months：{lifetime.active_months} / {lifetime.total_months}",
            f"- Stability：{_stars(lifetime.stability_stars)}",
            f"- 平均：{lifetime.average_per_month:.1f} / 月",
            f"- 最高：{lifetime.peak_count}（{lifetime.peak_month}）",
            f"- Burst：{_stars(lifetime.burst_stars)}",
            "",
        ])
    if len(lines) == 2:
        lines.append("- 無")
    return lines


def _render_monthly_top_triggers(monthly_counts: Mapping[str, Counter[str]], keywords: tuple[str, ...]) -> list[str]:
    lines = ["### Monthly Top Trigger", ""]
    for month in sorted(monthly_counts):
        top = [(term, monthly_counts[month][term]) for term in keywords if monthly_counts[month][term] > 0]
        top.sort(key=lambda item: (-item[1], item[0]))
        lines.extend([f"#### {month}", "", "Top Trigger", ""])
        lines.extend(f"{index}. {term}（{count}）" for index, (term, count) in enumerate(top[:3], start=1))
        if not top:
            lines.append("- 無")
        lines.append("")
    return lines


def _render_event_markers(
    monthly_counts: Mapping[str, Counter[str]], event_markers: Mapping[str, tuple[str, ...]], terms: tuple[str, ...]
) -> list[str]:
    lines = ["### Event Marker", ""]
    if not event_markers:
        return lines + ["- 未提供 Event Marker。", ""]
    for month in sorted(event_markers):
        lines.extend([f"#### {month}", "", f"Event：{'、'.join(event_markers[month])}", "", "當月 Trigger：", ""])
        if month not in monthly_counts:
            lines.append("- 此月份沒有匯出聊天資料")
        else:
            active = [(term, monthly_counts[month][term]) for term in terms if monthly_counts[month][term] > 0]
            lines.extend(f"- {term}：{count}" for term, count in active)
            if not active:
                lines.append("- 無")
        lines.append("")
    return lines


def _render_trigger_evolution(lifetimes: Mapping[str, KeywordLifetime | None]) -> list[str]:
    long_term: list[tuple[str, KeywordLifetime]] = []
    short_term: list[tuple[str, KeywordLifetime]] = []
    for term, lifetime in lifetimes.items():
        if lifetime is None:
            continue
        if lifetime.stability_stars >= 4 and lifetime.burst_stars <= 3:
            long_term.append((term, lifetime))
        elif lifetime.stability_stars <= 2 or lifetime.burst_stars >= 4:
            short_term.append((term, lifetime))
    lines = ["### Trigger Evolution", "", "#### 長期 Trigger", ""]
    lines.extend(f"- {_stars(lifetime.stability_stars)} {term}" for term, lifetime in long_term)
    if not long_term:
        lines.append("- 無")
    lines.extend(["", "#### 短期 Trigger", ""])
    lines.extend(f"- {_stars(lifetime.stability_stars)} {term}" for term, lifetime in short_term)
    if not short_term:
        lines.append("- 無")
    return lines + [""]


def _render_temporal_ambient_triggers(lifetimes: Mapping[str, KeywordLifetime | None]) -> list[str]:
    long_term = [
        (term, lifetime) for term, lifetime in lifetimes.items()
        if lifetime is not None and lifetime.stability_stars >= 4 and lifetime.burst_stars <= 3
    ]
    activity_term = [
        (term, lifetime) for term, lifetime in lifetimes.items()
        if lifetime is not None and (lifetime.stability_stars <= 3 or lifetime.burst_stars >= 4)
    ]
    lines = ["## 建議長期 Trigger", ""]
    lines.extend(f"- {_stars(lifetime.stability_stars)} {term}" for term, lifetime in long_term)
    if not long_term:
        lines.append("- 無")
    lines.extend(["", "## 建議活動 Trigger", ""])
    lines.extend(f"- {_stars(lifetime.burst_stars)} {term}" for term, lifetime in activity_term)
    if not activity_term:
        lines.append("- 無")
    return lines + [""]


def _render_compare_by_month(
    messages: list[ChatMessage], labels: Mapping[str, str], terms: tuple[str, ...]
) -> list[str]:
    by_author: dict[str, list[ChatMessage]] = defaultdict(list)
    for message in messages:
        by_author[message.author_id].append(message)
    authors = [author_id for author_id, values in sorted(by_author.items(), key=lambda item: len(item[1]), reverse=True)[:2]]
    lines = ["### Compare by Month", ""]
    if len(authors) < 2:
        return lines + ["- 至少需要兩位玩家的訊息。", ""]
    for author_id in authors:
        counts, _message_counts = monthly_keyword_counts(by_author[author_id], terms)
        lines.extend([f"#### {labels[author_id]}", ""])
        headers = ["月份", *terms]
        lines.extend(["| " + " | ".join(headers) + " |", "|" + "|".join("---:" for _ in headers) + "|"])
        for month in sorted(counts):
            lines.append("| " + " | ".join([month, *(str(counts[month][term]) for term in terms)]) + " |")
        lines.append("")
    return lines


def _render_language_evolution(monthly_counts: Mapping[str, Counter[str]], groups: Mapping[str, tuple[str, ...]]) -> list[str]:
    by_year: dict[str, Counter[str]] = defaultdict(Counter)
    for month, counts in monthly_counts.items():
        for group, terms in groups.items():
            by_year[month[:4]][group] += sum(counts[term] for term in terms)
    lines = ["## 玩家語言演變", ""]
    for year in sorted(by_year):
        discussions = [(group, count) for group, count in by_year[year].most_common() if count > 0]
        lines.extend([f"### {year}", "", "主要討論：", ""])
        lines.extend(f"- {group}（{count}）" for group, count in discussions[:3])
        if not discussions:
            lines.append("- 無")
        lines.append("")
    if not by_year:
        lines.append("- 無")
    return lines


def _timeline_bar(count: int, peak: int) -> str:
    if count <= 0 or peak <= 0:
        return ""
    return "█" * max(1, math.ceil(count / peak * 10))


def _trigger_score(term: str, stat: KeywordStat, cooccurrence: Counter[str]) -> tuple[int, tuple[str, ...]]:
    score = 1
    reasons = [f"出現 {stat.occurrences} 次"]
    if stat.occurrences >= 3:
        score += 1
    if stat.occurrences >= 10:
        score += 1
    if cooccurrence:
        score += 1
        reasons.append("與其他暖暖詞有共同語境")
    if term in GAME_TERMS:
        reasons.append("屬於暖暖玩家術語")
    if term in EASY_AMBIENT_TERMS:
        score += 1
        reasons.append("適合設計簡短 NPC 插話")
    if term in NUMERIC_TERMS:
        score = min(score, 2)
        reasons.append("純數值且語境較敏感，建議人工保守使用")
    return min(5, score), tuple(reasons)


def _stars(score: int) -> str:
    return "★" * score + "☆" * (5 - score)


def _kwic_window(content: str, index: int, length: int) -> str:
    start = _walk_cjk(content, index, -1, 12)
    end = _walk_cjk(content, index + length, 1, 12)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{_safe_inline(content[start:end])}{suffix}"


def _walk_cjk(content: str, position: int, direction: int, maximum: int) -> int:
    count = 0
    cursor = position
    while 0 <= cursor + (direction if direction < 0 else 0) < len(content) and count < maximum:
        if direction < 0:
            cursor -= 1
            character = content[cursor]
        else:
            character = content[cursor]
            cursor += 1
        if _is_chinese(character):
            count += 1
    return cursor


def _author_labels(messages: Iterable[ChatMessage]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for message in messages:
        if message.author_id not in labels:
            labels[message.author_id] = f"玩家 {len(labels) + 1}"
    return labels


def _average_length(messages: list[ChatMessage]) -> float:
    return sum(len(message.content) for message in messages) / len(messages) if messages else 0.0


def _top_short_phrase(messages: list[ChatMessage]) -> str:
    counts = Counter(message.content for message in messages if 2 <= len(message.content) <= 20)
    return _safe_inline(counts.most_common(1)[0][0]) if counts else "無"


def _top_emojis(messages: list[ChatMessage]) -> str:
    counts = Counter(emoji for message in messages for emoji in extract_emojis(message.content))
    return " ".join(emoji for emoji, _count in counts.most_common(3)) or "無"


def _top_keywords(messages: list[ChatMessage], keywords: tuple[str, ...]) -> str:
    counts = Counter(keyword for message in messages for keyword in keywords if keyword in message.content)
    return "、".join(keyword for keyword, _count in counts.most_common(3)) or "無"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_chinese(character: str) -> bool:
    return "\u4e00" <= character <= "\u9fff"


def _safe_inline(value: str) -> str:
    return value.replace("\n", " ").replace("`", "\\`")


if __name__ == "__main__":
    raise SystemExit(main())
