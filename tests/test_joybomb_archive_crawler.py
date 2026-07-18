"""Unit tests for the isolated, read-only JoyBomb Wayback spike."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawler import joybomb_archive_crawler as crawler


CDX_PAYLOAD = [
    ["timestamp", "original", "statuscode", "mimetype", "digest"],
    ["20180101010101", "http://nu3.joybomb.com.tw:80/notice/noticecontent/1/12581/0?lang=zh", "200", "text/html", "a"],
    ["20190101010101", "https://www.nu3.joybomb.com.tw/notice/noticecontent/1/12581/0?lang=en", "200", "text/html", "b"],
    ["20200101010101", "https://nu3.joybomb.com.tw/notice/noticecontent/1/13000/0", "200", "text/html", "c"],
    ["20200101010102", "https://other.example/notice/noticecontent/1/1/0", "200", "text/html", "d"],
]

V1_HTML = """
<html><body><div id='wm-ipp'>Wayback toolbar text</div>
<div class='notice-wrap'><h1 class='notice-title'>Summer Notice</h1><span class='notice-date'>2019/08/21</span>
<div class='notice-content'><p>Hello <strong>world</strong>.</p><img src='/images/a.jpg'><p>Final line</p><img src='https://img.example/b.jpg'></div></div>
<footer>Footer</footer></body></html>
"""
V2_HTML = """
<html><body><article class='notice-detail'><h2>Version Two</h2><time>2020-01-03</time>
<section class='article-content'><p>Second template content.</p><img src='assets/c.jpg'></section></article></body></html>
"""
ARCHIVED_V1_HTML = """
<html><body><div class='nav'>Navigation</div><div class='content_bg'>
<div class='news_bg_title'></div><h1>Archived Official Notice</h1><span>2019.08.21 18:00</span>
<p>Official body text.</p><p>活動期間：2019.08.22 05:00 至 2019.08.28 23:59</p>
<a href='/notice/noticelist'>返回公告列表</a><div class='notice-footer'><span>Fixed notice footer</span></div>
<img src='/upload/notice.jpg'></div><footer>Footer</footer></body></html>
"""


def test_cdx_parsing_canonicalization_and_notice_id() -> None:
    rows = crawler.parse_cdx_payload(CDX_PAYLOAD)
    assert crawler.parse_notice_id(rows[0].original_url) == "12581"
    assert crawler.canonicalize_original_url(rows[0].original_url) == "https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=12581"
    selected = crawler.select_notice_snapshots(rows)
    assert [row.timestamp for row in selected] == ["20180101010101", "20200101010101"]
    assert crawler.parse_notice_id("https://nu3.joybomb.com.tw/notice/noticecontent/1/12581/0/1") == "12581"


def test_legacy_query_and_mobile_notice_identity_preserve_n_and_k() -> None:
    desktop = "http://nu3.joybomb.com.tw:80/notice/noticecontent?N=1&K=10061&lang=zh"
    mobile = "https://www.nu3.joybomb.com.tw/mobile/noticecontent?K=10061&N=1"
    expected = "https://nu3.joybomb.com.tw/notice/noticecontent?N=1&K=10061"
    assert crawler.parse_notice_identity(desktop) == ("1", "10061")
    assert crawler.parse_notice_identity(mobile) == ("1", "10061")
    assert crawler.parse_notice_id(desktop) == "10061"
    assert crawler.parse_notice_id(mobile) == "10061"
    assert crawler.canonicalize_original_url(desktop) == expected
    assert crawler.canonicalize_original_url(mobile) == expected


def test_desktop_and_mobile_variants_of_same_legacy_notice_deduplicate() -> None:
    snapshots = [
        crawler.CdxSnapshot("20170623052813", "http://nu3.joybomb.com.tw:80/notice/noticecontent?N=1&K=10061", "200", "text/html", "desktop"),
        crawler.CdxSnapshot("20170903065128", "http://nu3.joybomb.com.tw:80/mobile/noticecontent?N=1&K=10061", "200", "text/html", "mobile"),
    ]
    selected = crawler.select_notice_snapshots(snapshots)
    assert len(selected) == 1
    assert selected[0].digest == "desktop"


def test_cdx_fetch_queries_all_known_legacy_url_families() -> None:
    session = _Session([_Response(200) for _ in crawler.CDX_URL_PATTERNS])
    result = crawler.fetch_cdx_index(from_year=2017, to_year=2018, timeout=1, request_delay=0, session=session)
    assert result.query_failures == {}
    assert len(session.urls) == len(crawler.CDX_URL_PATTERNS)
    for pattern in crawler.CDX_URL_PATTERNS:
        assert any(f"url={pattern}" in url for url in session.urls)


def test_index_summary_reports_collapsed_variants() -> None:
    summary = crawler.index_summary(crawler.parse_cdx_payload(CDX_PAYLOAD))
    assert summary["unique_detail_url_count"] == 2
    assert summary["collapsed_duplicate_count"] == 1
    assert summary["url_variations"]["http"] == 1
    assert summary["url_variations"]["port_80"] == 1
    assert summary["capture_year_distribution"] == {"2018": 1, "2019": 1, "2020": 1}
    assert summary["unique_notice_capture_year_distribution"] == {"2018": 1, "2020": 1}


def test_parse_v1_removes_wayback_toolbar_and_keeps_images_in_order() -> None:
    snapshot = crawler.CdxSnapshot("20190821182603", "https://nu3.joybomb.com.tw/notice/noticecontent/1/12581/0?lang=zh", "200", "text/html", "digest")
    notice = crawler.parse_notice_document(snapshot, V1_HTML)
    assert notice.template_signature == "joybomb_notice_v1"
    assert notice.title == "Summer Notice"
    assert notice.published_at == "2019-08-21T00:00:00+00:00"
    assert "Wayback toolbar" not in notice.content_text
    assert notice.image_original_urls == [
        "https://nu3.joybomb.com.tw/images/a.jpg",
        "https://img.example/b.jpg",
    ]
    assert notice.image_archive_urls[0].startswith("https://web.archive.org/web/20190821182603id_/")


def test_wayback_rewritten_images_are_unwrapped_before_archive_url_generation() -> None:
    snapshot = crawler.CdxSnapshot("20190821182603", "https://nu3.joybomb.com.tw/notice/noticecontent/1/12581/0", "200", "text/html", "digest")
    html = "<div class='content_bg'><h1>Title</h1><img src='https://web.archive.org/web/20190821182603im_/https://img.example/a.jpg'></div>"
    notice = crawler.parse_notice_document(snapshot, html)
    assert notice.image_original_urls == ["https://img.example/a.jpg"]
    assert notice.image_archive_urls == ["https://web.archive.org/web/20190821182603id_/https://img.example/a.jpg"]


def test_parse_actual_joybomb_content_bg_template() -> None:
    snapshot = crawler.CdxSnapshot("20190821182603", "https://nu3.joybomb.com.tw/notice/noticecontent/1/12581/0?lang=zh", "200", "text/html", "digest")
    notice = crawler.parse_notice_document(snapshot, ARCHIVED_V1_HTML)
    assert notice.template_signature == "joybomb_notice_v1"
    assert notice.title == "Archived Official Notice"
    assert notice.published_at == "2019-08-21T00:00:00+00:00"
    assert "Archived Official Notice" in notice.content_html
    assert notice.content_text == "Official body text.\n活動期間：2019.08.22 05:00 至 2019.08.28 23:59"
    assert "返回公告列表" not in notice.content_text
    assert "Fixed notice footer" not in notice.content_text


def test_parse_v2_and_unknown_template_are_explicit() -> None:
    snapshot = crawler.CdxSnapshot("20200101000000", "https://nu3.joybomb.com.tw/notice/noticecontent/1/13000/0", "200", "text/html", "digest")
    notice = crawler.parse_notice_document(snapshot, V2_HTML)
    assert notice.template_signature == "joybomb_notice_v2"
    assert notice.content_text == "Second template content."
    unknown = crawler.parse_notice_document(snapshot, "<html><body><p>Do not parse whole page</p></body></html>")
    assert unknown.content_text == ""
    assert "unknown_template" in unknown.parse_warnings[0]


class _Response:
    def __init__(self, status_code: int, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self) -> object:
        return CDX_PAYLOAD


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls = 0
        self.urls: list[str] = []

    def request(self, _method: object, url: object, **_kwargs: object) -> _Response:
        self.calls += 1
        self.urls.append(str(url))
        return self.responses.pop(0)


class _FailingSession:
    def request(self, *_args: object, **_kwargs: object) -> _Response:
        raise crawler.requests.ConnectionError("temporary refusal")


def test_request_retry_and_image_statuses() -> None:
    session = _Session([_Response(503), _Response(200)])
    response = crawler.request_with_retry(session, "GET", "https://example.test", timeout=1, request_delay=0, sleep=lambda _seconds: None)
    assert response.status_code == 200
    assert session.calls == 2
    assert crawler.check_archived_image(_Session([_Response(405), _Response(404)]), "https://example.test/a", timeout=1, request_delay=0) == "missing"
    assert crawler.check_archived_image(_Session([_Response(302)]), "https://example.test/a", timeout=1, request_delay=0) == "redirect"
    assert crawler.check_archived_image(_Session([_Response(200)]), "https://example.test/a", timeout=1, request_delay=0) == "archived"
    assert crawler.check_archived_image(_Session([_Response(418)]), "https://example.test/a", timeout=1, request_delay=0) == "invalid"


def test_retry_honors_retry_after_without_real_sleep() -> None:
    sleeps: list[float] = []
    session = _Session([_Response(429, headers={"Retry-After": "2"}), _Response(200)])
    response = crawler.request_with_retry(
        session,
        "GET",
        "https://example.test",
        timeout=1,
        request_delay=0.5,
        sleep=sleeps.append,
    )
    assert response.status_code == 200
    assert sleeps == [2.0]


def test_one_failed_snapshot_is_reported_without_stopping_remaining_samples() -> None:
    failed = crawler.CdxSnapshot("20190101000000", "https://nu3.joybomb.com.tw/notice/noticecontent/1/1/0", "200", "text/html", "a")
    results = crawler.crawl_samples([failed], timeout=1, request_delay=0, session=_FailingSession(), check_images=False)
    assert len(results) == 1
    assert results[0].template_signature == "request_failed"
    assert results[0].parse_warnings == ["request_failed: JoyBombArchiveError"]


def test_sample_selection_is_bounded_per_year() -> None:
    snapshots = [
        crawler.CdxSnapshot(f"{year}0101000000", f"https://nu3.joybomb.com.tw/notice/noticecontent/1/{year}/0", "200", "text/html", str(year))
        for year in range(2017, 2025)
    ]
    assert len(crawler.select_samples_by_year(snapshots, 3)) == 8


def test_cross_year_sampling_stays_bounded_but_includes_2017_through_2024() -> None:
    snapshots = [
        crawler.CdxSnapshot(f"{year}0101000000", f"https://nu3.joybomb.com.tw/notice/noticecontent/1/{year}/0", "200", "text/html", str(year))
        for year in range(2017, 2025)
        for _ in range(3)
    ]
    selected = crawler.select_samples_by_year(snapshots, 3)
    assert len(selected) == 24
    assert {snapshot.year for snapshot in selected} == set(range(2017, 2025))


def test_spike_has_no_database_or_queue_side_effects(tmp_path: Path) -> None:
    snapshots = crawler.select_notice_snapshots(crawler.parse_cdx_payload(CDX_PAYLOAD))
    crawler.write_reports(output_dir=tmp_path, snapshots=snapshots, notices=[])
    assert (tmp_path / "joybomb_archive_index_report.json").exists()
    assert (tmp_path / "joybomb_archive_sample_report.json").exists()
    source = Path(crawler.__file__).read_text(encoding="utf-8")
    assert "raw_post_repository" not in source
    assert "announcement_job" not in source


def test_summary_includes_image_results_and_explicit_deferred_integration_decision(tmp_path: Path) -> None:
    snapshot = crawler.CdxSnapshot("20190821182603", "https://nu3.joybomb.com.tw/notice/noticecontent/1/12581/0", "200", "text/html", "digest")
    notice = crawler.parse_notice_document(snapshot, V1_HTML)
    notice = crawler.JoyBombArchiveNotice(**{**crawler.asdict(notice), "images": [
        crawler.ArchiveImage("https://img.example/a.jpg", "https://archive/a.jpg", "archived"),
        crawler.ArchiveImage("https://img.example/b.jpg", "https://archive/b.jpg", "missing"),
    ]})
    crawler.write_reports(output_dir=tmp_path, snapshots=[snapshot], notices=[notice])
    summary = (tmp_path / "joybomb_archive_summary.md").read_text(encoding="utf-8")
    assert "Image availability" in summary
    assert "Formal Integration Decision" in summary
    assert "defer production integration" in summary


def test_capture_year_and_sampled_published_year_are_separate(tmp_path: Path) -> None:
    snapshot = crawler.CdxSnapshot("20190101000000", "https://nu3.joybomb.com.tw/notice/noticecontent/1/12581/0", "200", "text/html", "digest")
    notice = crawler.JoyBombArchiveNotice(
        archive_timestamp=snapshot.timestamp,
        original_url=snapshot.original_url,
        archive_url="https://archive.example/notice",
        notice_id="12581",
        title="Historical Notice",
        published_at="2017-06-23T00:00:00+00:00",
        content_html="<p>content</p>",
        content_text="content",
        image_original_urls=[],
        image_archive_urls=[],
        template_signature="joybomb_notice_v1",
        parse_warnings=[],
    )
    crawler.write_reports(output_dir=tmp_path, snapshots=[snapshot], notices=[notice])
    index = json.loads((tmp_path / "joybomb_archive_index_report.json").read_text(encoding="utf-8"))
    assert index["capture_year_distribution"] == {"2019": 1}
    assert index["sampled_published_year_distribution"] == {"2017": 1}
