from scripts.analysis.chat_analysis.candidate_scoring import score_candidate
from scripts.analysis.chat_analysis.models import Candidate


def test_scoring_is_deterministic_and_separates_long_term_from_event_like() -> None:
    stable = Candidate("終於復刻", "終於復刻", 8, 8, {"player_1", "player_2"}, {"2026-01", "2026-02", "2026-03"})
    burst = Candidate("限定活動", "限定活動", 8, 8, {"player_1"}, {"2026-03"})

    score_candidate(stable, 3)
    score_candidate(burst, 3)

    assert stable.category == "long_term_candidate"
    assert burst.category == "event_like_candidate"
    assert stable.score > burst.score


def test_short_generic_ngram_is_kept_for_review_not_promoted_to_trigger() -> None:
    generic = Candidate("看到", "看到", 12, 12, {"player_1", "player_2"}, {"2026-01", "2026-02"})

    score_candidate(generic, 2)

    assert generic.category == "needs_review"
    assert "generic_or_ambiguous" in generic.flags
