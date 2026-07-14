"""Compare Facebook page-feed visibility across isolated browser contexts.

This is intentionally a diagnostic-only tool. It never writes the SQLite database,
does not invoke Discord, and does not change the production crawler context.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from playwright.sync_api import BrowserContext, Page, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_crawler import (  # noqa: E402
    FACEBOOK_PAGE_URL,
    PAGE_TIMEOUT_MS,
    SCROLL_DISTANCE,
    SCROLL_WAIT_MS,
    dismiss_cookie_dialog,
    is_official_page_post_url,
    normalize_post_url,
)
from crawler.facebook_session import (  # noqa: E402
    FACEBOOK_BROWSER_PROFILE_PATH,
    create_browser_context,
    ensure_browser_profile_dir,
    has_login_cookie,
)


LOGGER = logging.getLogger(__name__)
DIAGNOSTIC_OUTPUT_DIR = PROJECT_ROOT / "debug" / "facebook_feed_diagnostic"
TARGET_POST_IDS = (
    "pfbid024fEMTnJULdMspSPnoB4LpTZAKj592wS1H3RQzeU12sbnyPZPdZELPiX5dVeKMb89l",
    "pfbid02RWjU2KzU2mTYFTSQXPcu2s6ujyif6FfpqFEBnTew7A6d8GL4zbWRBoxqen5z9pVLl",
)
LOGIN_TIMEOUT_SECONDS = 600


@dataclass(frozen=True, slots=True)
class FeedRound:
    """One non-sensitive homepage snapshot."""

    round_number: int
    canonical_permalinks: list[str]
    target_post_ids_found: list[str]
    visible_posts: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class FeedDiagnosis:
    """Aggregated result from one browser-context type."""

    context_type: str
    canonical_permalinks: list[str]
    target_post_ids_found: list[str]
    rounds: list[FeedRound]


def canonical_official_post_urls(hrefs: Iterable[object]) -> list[str]:
    """Filter and canonicalize only official page post links in first-seen order."""
    urls: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        if not isinstance(href, str) or not href or not is_official_page_post_url(href):
            continue
        canonical = normalize_post_url(href)
        if canonical not in seen:
            seen.add(canonical)
            urls.append(canonical)
    return urls


def _visible_post_summaries(page: Page) -> list[dict[str, object]]:
    """Return only current viewport article summaries; no full HTML or credentials."""
    try:
        result = page.locator("div[role='article'], article, div[data-pagelet^='FeedUnit_']").evaluate_all(
            """
            elements => elements.filter(element => {
                const rect = element.getBoundingClientRect();
                return rect.bottom > 0 && rect.top < window.innerHeight;
            }).map((element, index) => ({
                index,
                text_preview: (element.innerText || '').replace(/\\s+/g, ' ').slice(0, 180),
                official_author_links: Array.from(element.querySelectorAll('a[href]'), link => link.getAttribute('href') || '')
                    .filter(href => /\\/TwNikkiNikki(?:[/?]|$)/.test(href))
                    .slice(0, 3),
            }))
            """
        )
    except Exception as error:
        LOGGER.warning("Could not snapshot visible feed summaries: %s", error)
        return []
    return result if isinstance(result, list) else []


def capture_feed_round(page: Page, output_dir: Path, round_number: int) -> FeedRound:
    """Persist one homepage screenshot and JSON snapshot without touching application data."""
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        hrefs = page.locator("a[href]").evaluate_all(
            "elements => elements.map(element => element.getAttribute('href'))"
        )
    except Exception as error:
        LOGGER.warning("Could not snapshot page anchors in round %d: %s", round_number, error)
        hrefs = []
    urls = canonical_official_post_urls(hrefs if isinstance(hrefs, list) else [])
    found_targets = [target for target in TARGET_POST_IDS if any(target in url for url in urls)]
    snapshot = FeedRound(
        round_number=round_number,
        canonical_permalinks=urls,
        target_post_ids_found=found_targets,
        visible_posts=_visible_post_summaries(page),
    )
    page.screenshot(path=str(output_dir / f"round-{round_number:02d}.png"), full_page=False)
    (output_dir / f"round-{round_number:02d}.json").write_text(
        json.dumps(asdict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return snapshot


def collect_feed_diagnosis(page: Page, output_dir: Path, rounds: int) -> FeedDiagnosis:
    """Open the official page and record bounded, first-seen permalink snapshots."""
    page.goto(FACEBOOK_PAGE_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    dismiss_cookie_dialog(page)
    page.wait_for_timeout(SCROLL_WAIT_MS)

    snapshots: list[FeedRound] = []
    all_urls: list[str] = []
    seen_urls: set[str] = set()
    for round_number in range(1, rounds + 1):
        snapshot = capture_feed_round(page, output_dir, round_number)
        snapshots.append(snapshot)
        for url in snapshot.canonical_permalinks:
            if url not in seen_urls:
                seen_urls.add(url)
                all_urls.append(url)
        if round_number < rounds:
            page.mouse.wheel(0, SCROLL_DISTANCE)
            page.wait_for_timeout(SCROLL_WAIT_MS)

    found_targets = [target for target in TARGET_POST_IDS if any(target in url for url in all_urls)]
    return FeedDiagnosis(
        context_type=output_dir.name,
        canonical_permalinks=all_urls,
        target_post_ids_found=found_targets,
        rounds=snapshots,
    )


def wait_for_manual_login(context: BrowserContext, page: Page) -> None:
    """Wait for manual Facebook login in the dedicated persistent profile."""
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if has_login_cookie(context):
            return
        page.wait_for_timeout(1_000)
    raise TimeoutError("Facebook login was not completed within 10 minutes.")


def compare_diagnoses(storage_state: FeedDiagnosis, persistent_profile: FeedDiagnosis) -> dict[str, object]:
    """Return counts and bounded set differences for the two independent contexts."""
    storage_urls = set(storage_state.canonical_permalinks)
    profile_urls = set(persistent_profile.canonical_permalinks)
    return {
        "storage_state_count": len(storage_urls),
        "persistent_profile_count": len(profile_urls),
        "only_storage_state": sorted(storage_urls - profile_urls),
        "only_persistent_profile": sorted(profile_urls - storage_urls),
        "targets": {
            target: {
                "storage_state": target in storage_state.target_post_ids_found,
                "persistent_profile": target in persistent_profile.target_post_ids_found,
            }
            for target in TARGET_POST_IDS
        },
    }


def run_diagnostic(rounds: int) -> dict[str, object]:
    """Compare the production-like storage state with the dedicated persistent profile."""
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    DIAGNOSTIC_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        state_context = create_browser_context(browser)
        try:
            storage_state = collect_feed_diagnosis(
                state_context.new_page(), DIAGNOSTIC_OUTPUT_DIR / "storage_state", rounds
            )
        finally:
            state_context.close()
            browser.close()

        profile_path = ensure_browser_profile_dir()
        persistent_context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=False,
            locale="zh-TW",
            viewport={"width": 1280, "height": 720},
        )
        try:
            page = persistent_context.pages[0] if persistent_context.pages else persistent_context.new_page()
            if not has_login_cookie(persistent_context):
                page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
                print("請在開啟的專案專用 Chromium 視窗完成 Facebook 登入。")
                wait_for_manual_login(persistent_context, page)
            persistent_profile = collect_feed_diagnosis(
                page, DIAGNOSTIC_OUTPUT_DIR / "persistent_profile", rounds
            )
        finally:
            persistent_context.close()

    comparison = compare_diagnoses(storage_state, persistent_profile)
    result = {
        "profile_path": str(FACEBOOK_BROWSER_PROFILE_PATH),
        "output_dir": str(DIAGNOSTIC_OUTPUT_DIR),
        "storage_state": asdict(storage_state),
        "persistent_profile": asdict(persistent_profile),
        "comparison": comparison,
    }
    (DIAGNOSTIC_OUTPUT_DIR / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Facebook feed visibility by context.")
    parser.add_argument("--rounds", type=int, default=8, help="Bounded homepage scroll rounds.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = run_diagnostic(parse_args().rounds)
    comparison = result["comparison"]
    print(f"storage_state permalink：{comparison['storage_state_count']}")
    print(f"persistent profile permalink：{comparison['persistent_profile_count']}")
    for target, status in comparison["targets"].items():
        print(f"{target}: storage_state={status['storage_state']}, persistent_profile={status['persistent_profile']}")
    print(f"診斷輸出：{result['output_dir']}")


if __name__ == "__main__":
    main()
