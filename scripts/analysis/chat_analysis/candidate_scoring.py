"""Explainable, deterministic candidate categorization and scoring."""

from __future__ import annotations

from collections import Counter

from .models import Candidate


GENERIC_PHRASES = frozenset({
    "哈哈", "哈哈哈", "可以", "不知道", "好可愛", "真的", "然後", "就是",
    "要不要", "看起來", "為什麼", "差不多", "很喜歡", "都沒有", "也沒有", "但我覺得",
})
GENERIC_PREFIXES = (
    "我", "你", "妳", "他", "她", "這", "那", "有", "沒", "是", "不",
    "真的", "所以", "應該", "的", "而且", "然後", "因為", "了",
)
GENERIC_SUFFIXES = ("哈哈", "的時候", "的")


def score_candidate(candidate: Candidate, total_months: int) -> Candidate:
    """Score = frequency + diversity + months + length + replies - burst - ambiguity.

    Frequency: min(freq, 10)/10*3; diversity: min(authors, 4)/4*2;
    stability: active_months/total_months*2; phrase length up to 1;
    replyability up to 1.5. A single-month burst and generic wording deduct points.
    """
    frequency_score = min(candidate.frequency, 10) / 10 * 3
    diversity_score = min(len(candidate.author_keys), 4) / 4 * 2
    stability_ratio = len(candidate.months) / total_months if total_months else 0.0
    stability_score = stability_ratio * 2
    length_score = min(len(candidate.text), 6) / 6
    reply_score = min(len(candidate.reply_evidence), 3) / 3 * 1.5
    month_counts = Counter(example.month for example in candidate.examples)
    peak = max(month_counts.values(), default=0)
    average = candidate.frequency / max(1, total_months)
    burst_ratio = peak / average if average else 0.0
    burst_penalty = 0.75 if burst_ratio >= 3 and len(candidate.months) <= 2 else 0.0
    ambiguous = (
        candidate.text in GENERIC_PHRASES
        or len(candidate.text) <= 2
        or candidate.text.startswith(GENERIC_PREFIXES)
        or candidate.text.endswith(GENERIC_SUFFIXES)
    )
    ambiguity_penalty = 1.5 if ambiguous else 0.0
    candidate.score = round(frequency_score + diversity_score + stability_score + length_score + reply_score - burst_penalty - ambiguity_penalty, 2)
    if ambiguous:
        candidate.flags.add("generic_or_ambiguous")
    # Candidate summaries may be reconstructed without their full example list;
    # a high-frequency one-month phrase is still a useful event-like signal.
    if burst_penalty or (len(candidate.months) == 1 and candidate.frequency >= 3):
        candidate.flags.add("event_like_candidate")
    if stability_ratio >= 0.5 and len(candidate.months) >= 2:
        candidate.flags.add("long_term_candidate")
    if "generic_or_ambiguous" in candidate.flags:
        candidate.category = "needs_review"
    elif "long_term_candidate" in candidate.flags:
        candidate.category = "long_term_candidate"
    elif "event_like_candidate" in candidate.flags:
        candidate.category = "event_like_candidate"
    elif candidate.reply_evidence:
        candidate.category = "conversational_replyable_candidate"
    else:
        candidate.category = "needs_review"
    return candidate
