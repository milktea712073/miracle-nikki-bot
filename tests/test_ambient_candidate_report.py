import json
from pathlib import Path

from scripts.analysis.extract_ambient_candidates import main


def _write_export(path: Path) -> None:
    path.write_text(json.dumps([
        {"message_id": "1", "author_id": "a", "timestamp": "2026-01-01T00:00:00Z", "content": "終於復刻了", "channel_id": "1", "is_bot": False},
        {"message_id": "2", "author_id": "b", "timestamp": "2026-01-01T00:00:10Z", "content": "恭喜你", "channel_id": "1", "reply_to_message_id": "1", "is_bot": False},
        {"message_id": "3", "author_id": "a", "timestamp": "2026-02-01T00:00:00Z", "content": "終於復刻了", "channel_id": "1", "is_bot": False},
        {"message_id": "4", "author_id": "b", "timestamp": "2026-02-01T00:00:10Z", "content": "終於復刻了", "channel_id": "1", "is_bot": False},
    ], ensure_ascii=False), encoding="utf-8")


def test_cli_writes_anonymized_markdown_and_deterministic_candidate_json(tmp_path: Path) -> None:
    source = tmp_path / "chat.json"
    output = tmp_path / "reports"
    _write_export(source)

    assert main(["--input", str(source), "--output-dir", str(output), "--min-frequency", "2", "--top", "10"]) == 0

    trigger = (output / "ambient_trigger_candidates.md").read_text(encoding="utf-8")
    data = json.loads((output / "ambient_candidate_data.json").read_text(encoding="utf-8"))
    assert "## Manual Review Template" in trigger
    assert "author_id" not in trigger and "message_id" not in trigger
    assert data["trigger_candidates"]
    assert all("author_id" not in candidate for candidate in data["trigger_candidates"])


def test_empty_and_malformed_input_are_safe(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    assert main(["--input", str(empty), "--output-dir", str(tmp_path / "out")]) == 0
    malformed = tmp_path / "bad.json"
    malformed.write_text("{}", encoding="utf-8")
    assert main(["--input", str(malformed), "--output-dir", str(tmp_path / "out2")]) == 1
