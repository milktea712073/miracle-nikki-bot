from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCRIPT_MODULES = (
    "scripts.data.fetch_raw_posts",
    "scripts.data.fetch_website_posts",
    "scripts.data.parse_raw_posts",
    "scripts.data.reset_database",
    "scripts.data.rebuild_database",
    "scripts.data.cleanup_auto_suits",
    "scripts.data.repair_facebook_post_aliases",
    "scripts.announcement.initialize_announcement_queue",
    "scripts.announcement.baseline_announcements",
    "scripts.announcement.migrations.migrate_announcement_baseline",
    "scripts.announcement.requeue_announcement",
    "scripts.announcement.requeue_latest",
    "scripts.announcement.repair_rebuild_queue",
    "scripts.diagnostic.facebook_feed_diagnostic",
    "scripts.diagnostic.facebook_feed_network_diagnostic",
    "scripts.diagnostic.debug_facebook_mobile",
    "scripts.diagnostic.debug_facebook_post_sources",
    "scripts.legacy.review_drafts",
)

SCRIPT_PATHS = tuple(
    Path(module.replace(".", "/") + ".py") for module in SCRIPT_MODULES
)


@pytest.mark.parametrize("module_name", SCRIPT_MODULES)
def test_script_modules_import_without_running_a_database_operation(module_name: str) -> None:
    assert importlib.import_module(module_name) is not None


@pytest.mark.parametrize("script_path", SCRIPT_PATHS)
def test_script_help_runs_from_outside_the_project(script_path: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / script_path), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_documented_script_paths_exist() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    for script_path in SCRIPT_PATHS:
        if str(script_path).replace("\\", "/") in readme:
            assert (PROJECT_ROOT / script_path).is_file()


def test_deprecated_migration_warns_before_any_database_operation(monkeypatch, capsys) -> None:
    from scripts.announcement.migrations import migrate_announcement_baseline

    monkeypatch.setattr("builtins.input", lambda _: "NO")
    monkeypatch.setattr(
        migrate_announcement_baseline,
        "init_database",
        lambda: (_ for _ in ()).throw(AssertionError("database must not initialize")),
    )

    assert migrate_announcement_baseline.main([]) == 1
    assert "DEPRECATED" in capsys.readouterr().out
