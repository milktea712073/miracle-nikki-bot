"""Capture non-sensitive Facebook feed response metadata for two Playwright contexts.

This diagnostic tool never writes application data, sends Discord messages, or changes
the production crawler. Response bodies are inspected only in memory to extract pfbid
identifiers; no response payload, headers, cookies, or tokens are persisted.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, Response, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.facebook_session import (  # noqa: E402
    FACEBOOK_BROWSER_PROFILE_PATH,
    create_browser_context,
    ensure_browser_profile_dir,
    has_login_cookie,
)
from scripts.diagnostic.facebook_feed_diagnostic import (  # noqa: E402
    DIAGNOSTIC_OUTPUT_DIR,
    TARGET_POST_IDS,
    collect_feed_diagnosis,
)


LOGGER = logging.getLogger(__name__)
NETWORK_OUTPUT_DIR = DIAGNOSTIC_OUTPUT_DIR / "network"
PFBID_PATTERN = re.compile(r"\bpfbid[A-Za-z0-9]+\b")


@dataclass(frozen=True, slots=True)
class NetworkResponseRecord:
    """Sanitized metadata from one Facebook feed-related response."""

    url: str
    operation_name: str | None
    status: int
    pfbids: list[str]
    pfbid_paths: dict[str, list[str]]


def is_facebook_feed_response(url: str) -> bool:
    """Limit capture to Facebook GraphQL or Feed endpoints."""
    parsed = urlsplit(url)
    host = parsed.netloc.casefold()
    path = parsed.path.casefold()
    return host.endswith("facebook.com") and (
        "/api/graphql" in path or "/graphql" in path or "feed" in path
    )


def operation_name_from_post_data(post_data: str | None) -> str | None:
    """Extract only the public GraphQL operation name from JSON or form data."""
    if not post_data:
        return None
    try:
        decoded = json.loads(post_data)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        for key in ("operationName", "fb_api_req_friendly_name", "friendly_name"):
            value = decoded.get(key)
            if isinstance(value, str) and value:
                return value

    form_data = parse_qs(post_data, keep_blank_values=True)
    for key in ("fb_api_req_friendly_name", "friendly_name", "operationName"):
        values = form_data.get(key)
        if values and values[0]:
            return values[0]
    return None


def extract_pfbids(body: str) -> list[str]:
    """Return unique pfbid identifiers in their response-body discovery order."""
    return list(dict.fromkeys(PFBID_PATTERN.findall(body)))


def pfbid_json_paths(body: str, pfbids: list[str]) -> dict[str, list[str]]:
    """Return JSON paths containing pfbids without retaining response values."""
    paths = {pfbid: [] for pfbid in pfbids}
    payload = body.removeprefix("for (;;);").strip()

    def visit(value: object, path: str) -> None:
        if isinstance(value, str):
            for pfbid in pfbids:
                if pfbid in value:
                    paths[pfbid].append(path)
            return
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                for pfbid in pfbids:
                    if pfbid in key:
                        paths[pfbid].append(child_path)
                visit(child, child_path)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    decoder = json.JSONDecoder()
    index = 0
    document_index = 0
    while index < len(payload):
        while index < len(payload) and payload[index].isspace():
            index += 1
        if index >= len(payload):
            break
        try:
            decoded, index = decoder.raw_decode(payload, index)
        except json.JSONDecodeError:
            break
        visit(decoded, f"$[{document_index}]")
        document_index += 1
    return paths


class FeedResponseRecorder:
    """Collect filtered response metadata without persisting bodies or sensitive data."""

    def __init__(self) -> None:
        self.records: list[NetworkResponseRecord] = []

    def attach(self, page: Page) -> None:
        page.on("response", self._record_response)

    def _record_response(self, response: Response) -> None:
        if not is_facebook_feed_response(response.url):
            return
        try:
            body = response.text()
        except Exception as error:
            LOGGER.warning("Could not read feed response body url=%s: %s", response.url, error)
            body = ""
        pfbids = extract_pfbids(body)
        self.records.append(
            NetworkResponseRecord(
                url=response.url,
                operation_name=operation_name_from_post_data(response.request.post_data),
                status=response.status,
                pfbids=pfbids,
                pfbid_paths=pfbid_json_paths(body, pfbids),
            )
        )

    def write(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "responses.json").write_text(
            json.dumps([asdict(record) for record in self.records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def summarize_records(records: list[NetworkResponseRecord]) -> dict[str, Any]:
    """Summarize response and target visibility without exposing response bodies."""
    pfbid_records = [record for record in records if record.pfbids]
    return {
        "response_count": len(records),
        "responses_with_pfbids": len(pfbid_records),
        "targets": {
            target: [
                {
                    "url": record.url,
                    "operation_name": record.operation_name,
                    "status": record.status,
                    "paths": record.pfbid_paths.get(target, []),
                }
                for record in records
                if target in record.pfbids
            ]
            for target in TARGET_POST_IDS
        },
    }


def record_context(
    page: Page,
    context_name: str,
    rounds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run bounded feed loading with a response recorder attached before navigation."""
    recorder = FeedResponseRecorder()
    recorder.attach(page)
    diagnosis = collect_feed_diagnosis(page, NETWORK_OUTPUT_DIR / context_name / "feed", rounds)
    recorder.write(NETWORK_OUTPUT_DIR / context_name)
    return asdict(diagnosis), summarize_records(recorder.records)


def run_network_diagnostic(rounds: int) -> dict[str, Any]:
    """Compare GraphQL/feed response visibility for the two isolated contexts."""
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    NETWORK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        state_context = create_browser_context(browser)
        try:
            storage_feed, storage_network = record_context(
                state_context.new_page(), "storage_state", rounds
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
            if not has_login_cookie(persistent_context):
                raise RuntimeError(
                    "專用 Facebook profile 尚未登入。請先執行 "
                    "python scripts/diagnostic/facebook_feed_diagnostic.py --rounds 1"
                )
            page = persistent_context.pages[0] if persistent_context.pages else persistent_context.new_page()
            persistent_feed, persistent_network = record_context(
                page, "persistent_profile", rounds
            )
        finally:
            persistent_context.close()

    result = {
        "profile_path": str(FACEBOOK_BROWSER_PROFILE_PATH),
        "storage_state": {"feed": storage_feed, "network": storage_network},
        "persistent_profile": {"feed": persistent_feed, "network": persistent_network},
    }
    (NETWORK_OUTPUT_DIR / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Facebook feed network responses.")
    parser.add_argument("--rounds", type=int, default=8, help="Bounded homepage scroll rounds.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = run_network_diagnostic(parse_args().rounds)
    for context_name in ("storage_state", "persistent_profile"):
        summary = result[context_name]["network"]
        print(
            f"{context_name}: responses={summary['response_count']}, "
            f"with_pfbid={summary['responses_with_pfbids']}"
        )
        for target, matches in summary["targets"].items():
            print(f"  {target}: {bool(matches)}")
    print(f"診斷輸出：{NETWORK_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
