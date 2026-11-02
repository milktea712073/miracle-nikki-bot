from __future__ import annotations

import gzip
import shutil
import sqlite3
from pathlib import Path

import pytest

from scripts.announcement import backup_announcement_state as backup_script


def open_state_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("CREATE TABLE notices (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
    connection.execute("INSERT INTO notices (title) VALUES ('官方公告')")
    connection.commit()
    return connection


def restore_archive(archive_path: Path, destination: Path) -> None:
    with gzip.open(archive_path, "rb") as archive_file, destination.open("wb") as restored_file:
        shutil.copyfileobj(archive_file, restored_file)


def test_backup_uses_sqlite_backup_api_and_restores_a_valid_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "announcement_state.db"
    output_dir = tmp_path / "backups"
    writer = open_state_database(source)

    try:
        result = backup_script.backup_announcement_state(source, output_dir)
    finally:
        writer.close()

    assert result.archive_path.parent == output_dir
    assert result.archive_path.suffixes == [".db", ".gz"]
    assert result.archive_size > 0
    assert result.snapshot_size > 0

    restored = tmp_path / "restored.db"
    restore_archive(result.archive_path, restored)
    backup_script.verify_integrity(restored)
    connection = sqlite3.connect(restored)
    try:
        assert connection.execute("SELECT title FROM notices").fetchall() == [("官方公告",)]
    finally:
        connection.close()


def test_failed_integrity_check_removes_partial_and_final_backup_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "announcement_state.db"
    output_dir = tmp_path / "backups"
    writer = open_state_database(source)

    def fail_integrity(_path: Path) -> None:
        raise RuntimeError("integrity check failed")

    monkeypatch.setattr(backup_script, "verify_integrity", fail_integrity)

    try:
        with pytest.raises(RuntimeError, match="integrity check failed"):
            backup_script.backup_announcement_state(source, output_dir)
    finally:
        writer.close()

    assert list(output_dir.glob("*")) == []


def test_backup_never_accepts_a_missing_source_database(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Announcement state database"):
        backup_script.backup_announcement_state(tmp_path / "missing.db", tmp_path / "backups")
