from scripts.analysis.chat_analysis.normalization import is_emoji_or_punctuation_only, normalize_for_analysis


def test_normalization_uses_nfkc_and_masks_url_and_mentions() -> None:
    result = normalize_for_analysis("　收　２Ｄ <@123> https://example.test/x　")

    assert result == "收 2D [提及] [網址]"


def test_emoji_and_punctuation_only_values_are_not_candidate_text() -> None:
    assert is_emoji_or_punctuation_only("🤣！！") is True
    assert is_emoji_or_punctuation_only("想收") is False
