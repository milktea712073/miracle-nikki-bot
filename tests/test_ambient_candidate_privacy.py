from scripts.analysis.chat_analysis.privacy import anonymize_authors, redact_text


def test_private_values_are_redacted_before_reports() -> None:
    result, private = redact_text("找 <@123> https://example.test 寫信 a@example.com 電話 0912-345-678")

    assert private is True
    assert "123" not in result
    assert "example.com" not in result
    assert "0912" not in result


def test_author_labels_are_anonymous_and_stable() -> None:
    assert anonymize_authors(["99", "42", "99"]) == {"99": "player_1", "42": "player_2"}
