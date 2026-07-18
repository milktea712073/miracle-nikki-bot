"""Export JoyBomb section drafts as one self-contained, read-only HTML report."""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.database import DATABASE_PATH
from content.section_splitter import split_notice_sections
from knowledge.story_event_reference import match_story_events


JOYBOMB_SOURCE = "joybomb_archive"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "joybomb_draft_report.html"
SKIP_CONTENT_TYPES = {"system", "notice"}
HIGH_CONFIDENCE_CONTENT_TYPES = {"event", "suit_event", "welfare"}


@dataclass(frozen=True, slots=True)
class ReportSummary:
    raw_posts: int
    sections: int
    drafts: int
    multi_section_raw_posts: int
    failed: int
    content_types: dict[str, int]
    event_name_present: int
    event_name_missing: int
    suit_present: int
    suit_missing: int
    story_matches: int
    high_confidence: int
    needs_review: int
    skip: int


def _readonly_connection(database_path: Path) -> sqlite3.Connection:
    """Open SQLite strictly read-only so report generation cannot change project data."""
    resolved = database_path.resolve()
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _metadata(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _section_text(content: str, start_line: int, end_line: int) -> str:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(lines[max(0, start_line - 1) : max(0, end_line)]).strip()


def recommendation_for(draft: dict[str, object], story_matches: list[str]) -> str:
    """Return report-only triage; it never changes parse-draft status."""
    if draft["status"] == "failed":
        return "needs_review"
    content_type = str(draft["content_type_candidate"] or "other")
    has_event = bool(draft["event_name_candidate"])
    has_suits = bool(draft["suits"])
    if content_type in SKIP_CONTENT_TYPES and not has_event and not has_suits and not story_matches:
        return "skip"
    if (
        float(draft["confidence"] or 0) >= 0.9
        and has_event
        and content_type in HIGH_CONFIDENCE_CONTENT_TYPES
    ):
        return "high_confidence"
    return "needs_review"


def load_report_data(database_path: Path = DATABASE_PATH) -> tuple[list[dict[str, object]], ReportSummary]:
    """Read JoyBomb raws and their current section-level drafts without writing SQLite."""
    connection = _readonly_connection(database_path)
    try:
        raw_rows = connection.execute(
            "SELECT id, source_post_id, url, content, published_at, metadata_json "
            "FROM raw_posts WHERE source = ? ORDER BY published_at DESC, id DESC",
            (JOYBOMB_SOURCE,),
        ).fetchall()
        draft_rows = connection.execute(
            "SELECT d.id, d.raw_post_id, d.section_index, d.section_heading, d.section_start_line, "
            "d.section_end_line, d.section_hash, d.splitter_version, d.status, d.title, "
            "d.content_type_candidate, d.event_name_candidate, d.start_at_candidate, d.end_at_candidate, "
            "d.confidence, d.parser_notes, d.error_message "
            "FROM parse_drafts d JOIN raw_posts r ON r.id = d.raw_post_id "
            "WHERE r.source = ? ORDER BY d.raw_post_id, d.section_index, d.id",
            (JOYBOMB_SOURCE,),
        ).fetchall()
        draft_ids = [int(row[0]) for row in draft_rows]
        suits_by_draft: dict[int, list[dict[str, object]]] = defaultdict(list)
        if draft_ids:
            placeholders = ",".join("?" for _ in draft_ids)
            for row in connection.execute(
                "SELECT parse_draft_id, suit_name_candidate, confidence, notes "
                f"FROM parse_draft_suits WHERE parse_draft_id IN ({placeholders}) "
                "ORDER BY parse_draft_id, position",
                draft_ids,
            ).fetchall():
                suits_by_draft[int(row[0])].append(
                    {"name": str(row[1]), "confidence": row[2], "notes": row[3]}
                )
    finally:
        connection.close()

    drafts_by_raw: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in draft_rows:
        draft = {
            "id": int(row[0]), "raw_post_id": int(row[1]), "section_index": int(row[2]),
            "section_heading": row[3], "section_start_line": int(row[4]),
            "section_end_line": int(row[5]), "section_hash": str(row[6]),
            "splitter_version": str(row[7]), "status": str(row[8]), "title": row[9],
            "content_type_candidate": str(row[10] or "other"), "event_name_candidate": row[11],
            "start_at_candidate": row[12], "end_at_candidate": row[13], "confidence": row[14],
            "parser_notes": row[15], "error_message": row[16], "suits": suits_by_draft[int(row[0])],
        }
        drafts_by_raw[draft["raw_post_id"]].append(draft)

    posts: list[dict[str, object]] = []
    content_types: Counter[str] = Counter()
    event_name_present = event_name_missing = suit_present = suit_missing = story_match_count = 0
    high_confidence = needs_review = skip = failed = sections = 0
    for raw_id, source_post_id, url, content, published_at, metadata_json in raw_rows:
        metadata = _metadata(metadata_json)
        raw_content = str(content)
        split_reasons = {
            section.section_hash: section.split_reason
            for section in split_notice_sections(
                raw_content,
                source=JOYBOMB_SOURCE,
                source_post_id=str(source_post_id),
                raw_post_id=int(raw_id),
                title=str(metadata.get("title")) if metadata.get("title") else None,
            ).sections
        }
        drafts = drafts_by_raw[int(raw_id)]
        rendered_sections: list[dict[str, object]] = []
        for draft in drafts:
            text = _section_text(raw_content, int(draft["section_start_line"]), int(draft["section_end_line"]))
            story_matches = [match.canonical_name for match in match_story_events(text)]
            recommendation = recommendation_for(draft, story_matches)
            draft["text"] = text
            draft["split_reason"] = split_reasons.get(str(draft["section_hash"]), "unknown")
            draft["story_matches"] = story_matches
            draft["recommendation"] = recommendation
            rendered_sections.append(draft)
            sections += 1
            content_types[str(draft["content_type_candidate"])] += 1
            event_name_present += int(bool(draft["event_name_candidate"]))
            event_name_missing += int(not draft["event_name_candidate"])
            suit_present += int(bool(draft["suits"]))
            suit_missing += int(not draft["suits"])
            story_match_count += len(story_matches)
            failed += int(draft["status"] == "failed")
            high_confidence += int(recommendation == "high_confidence")
            needs_review += int(recommendation == "needs_review")
            skip += int(recommendation == "skip")
        posts.append(
            {
                "raw_post_id": int(raw_id), "source_post_id": str(source_post_id), "url": str(url),
                "published_at": published_at, "title": metadata.get("title") or None,
                "notice_id": metadata.get("notice_id") or str(source_post_id).split(":")[-1],
                "section": metadata.get("section") or str(source_post_id).split(":")[0],
                "wayback_url": metadata.get("archive_url") or None,
                "sections": rendered_sections,
            }
        )

    summary = ReportSummary(
        raw_posts=len(posts), sections=sections, drafts=sections,
        multi_section_raw_posts=sum(len(post["sections"]) > 1 for post in posts), failed=failed,
        content_types=dict(sorted(content_types.items())), event_name_present=event_name_present,
        event_name_missing=event_name_missing, suit_present=suit_present, suit_missing=suit_missing,
        story_matches=story_match_count, high_confidence=high_confidence,
        needs_review=needs_review, skip=skip,
    )
    return posts, summary


def _escape(value: object | None) -> str:
    return html.escape(str(value or ""), quote=True)


def _label_for_recommendation(value: str) -> str:
    return {"high_confidence": "高信心候選", "needs_review": "Needs Review", "skip": "Skip"}[value]


def _render_section(section: dict[str, object]) -> str:
    suits = section["suits"]
    suit_text = "、".join(_escape(suit["name"]) for suit in suits) if suits else "無"
    story_text = "、".join(_escape(name) for name in section["story_matches"]) or "無"
    warnings = "；".join(
        part for part in (_escape(section["parser_notes"]), _escape(section["error_message"])) if part
    ) or "無"
    period = " ～ ".join(
        item for item in (_escape(section["start_at_candidate"]), _escape(section["end_at_candidate"])) if item
    ) or "未辨識"
    section_text = _escape(section["text"])
    return f'''<section class="section-card" data-type="{_escape(section["content_type_candidate"])}" data-rec="{section["recommendation"]}" data-suits="{str(bool(suits)).lower()}" data-story="{str(bool(section["story_matches"])).lower()}">
      <h3>段落 {section["section_index"]}：{_escape(section["section_heading"]) or "未命名"}</h3>
      <p class="meta">切分原因：{_escape(section["split_reason"])} · Splitter：{_escape(section["splitter_version"])} · Hash：{ _escape(section["section_hash"][:12]) }…</p>
      <dl>
        <dt>活動名稱候選</dt><dd>{_escape(section["event_name_candidate"]) or "未辨識"}</dd>
        <dt>內容類型</dt><dd>{_escape(section["content_type_candidate"])}</dd>
        <dt>活動期間</dt><dd>{period}</dd>
        <dt>套裝候選</dt><dd>{suit_text}</dd>
        <dt>故事套裝命中</dt><dd>{story_text}</dd>
        <dt>解析狀態</dt><dd>{_escape(section["status"])}</dd>
        <dt>建議分類</dt><dd><span class="tag {section["recommendation"]}">{_label_for_recommendation(str(section["recommendation"]))}</span></dd>
        <dt>警告</dt><dd>{warnings}</dd>
      </dl>
      <details><summary>顯示段落原文</summary><pre>{section_text}</pre></details>
    </section>'''


def render_html(posts: list[dict[str, object]], summary: ReportSummary) -> str:
    """Render a standalone report using only escaped source values and native browser APIs."""
    content_type_options = "".join(
        f'<option value="{_escape(name)}">{_escape(name)}（{count}）</option>'
        for name, count in summary.content_types.items()
    )
    summary_items = [
        ("Raw Post 總數", summary.raw_posts), ("Section 總數", summary.sections),
        ("Parse Draft 總數", summary.drafts), ("多 Section 公告數", summary.multi_section_raw_posts),
        ("解析失敗數", summary.failed), ("有活動名稱／無活動名稱", f"{summary.event_name_present} / {summary.event_name_missing}"),
        ("有套裝候選／無套裝候選", f"{summary.suit_present} / {summary.suit_missing}"),
        ("Story Event 命中數", summary.story_matches), ("高信心候選", summary.high_confidence),
        ("Needs Review", summary.needs_review), ("Skip", summary.skip),
    ]
    stats = "".join(f"<li><strong>{name}</strong><span>{value}</span></li>" for name, value in summary_items)
    type_stats = "".join(f"<span class=\"type-count\">{_escape(name)}：{count}</span>" for name, count in summary.content_types.items())
    cards: list[str] = []
    for post in posts:
        title = _escape(post["title"]) or "未提供標題"
        raw_url = _escape(post["url"])
        wayback = post["wayback_url"]
        links = f'<a href="{raw_url}">原始公告</a>'
        if wayback:
            links += f' · <a href="{_escape(wayback)}">Wayback</a>'
        search_text = " ".join(
            [str(post["title"] or ""), str(post["notice_id"]), str(post["section"])]
            + [str(section["event_name_candidate"] or "") + " " + " ".join(suit["name"] for suit in section["suits"]) for section in post["sections"]]
        )
        cards.append(f'''<article class="post-card" data-year="{_escape(str(post["published_at"] or "")[:4])}" data-multi="{str(len(post["sections"]) > 1).lower()}" data-search="{_escape(search_text).lower()}">
          <header><h2>{title}</h2><p class="meta">Raw #{post["raw_post_id"]} · Notice ID：{_escape(post["notice_id"])} · Section：{_escape(post["section"])} · 發布日期：{_escape(post["published_at"]) or "未提供"} · {links}</p><p>段落數：{len(post["sections"])}</p></header>
          {''.join(_render_section(section) for section in post["sections"]) or '<p class="empty">沒有可顯示的 Parse Draft。</p>'}
        </article>''')
    return f'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>JoyBomb Draft-only 解析報告</title>
<style>
body{{margin:0;background:#f7f8fb;color:#202636;font:15px/1.55 system-ui,"Microsoft JhengHei",sans-serif}} main{{max-width:1200px;margin:auto;padding:28px}} h1,h2,h3{{margin:.2em 0}} .intro,.filters,.post-card{{background:#fff;border:1px solid #dfe4ec;border-radius:8px;padding:18px;margin:16px 0}} .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;padding:0;list-style:none}} .stats li{{border:1px solid #e7eaf0;padding:10px;border-radius:6px}} .stats span{{display:block;font-size:22px;font-weight:700}} .filters{{position:sticky;top:0;z-index:2}} input,select,label{{margin:4px 8px 4px 0}} input,select{{padding:7px;border:1px solid #bcc6d6;border-radius:4px}} .type-count{{display:inline-block;margin:3px 8px 3px 0;padding:3px 7px;background:#edf1f7;border-radius:4px}} .post-card{{box-shadow:0 1px 2px #0000000b}} .section-card{{border-left:4px solid #7a9cc6;background:#fafcff;margin:14px 0;padding:14px}} dl{{display:grid;grid-template-columns:150px 1fr;gap:4px 12px}} dt{{font-weight:700}} dd{{margin:0}} .meta{{color:#596579;font-size:13px}} pre{{white-space:pre-wrap;word-break:break-word;background:#202636;color:#f5f7fa;padding:12px;border-radius:4px}} .tag{{padding:2px 7px;border-radius:999px;font-size:13px;font-weight:700}} .high_confidence{{background:#d9f3e5;color:#15603a}} .needs_review{{background:#fff0c8;color:#825600}} .skip{{background:#e6e9ef;color:#4a5362}} .hidden{{display:none}} a{{color:#1d5fa7}} .empty{{color:#596579}}
</style></head><body><main>
<h1>JoyBomb 歷史公告 Draft-only 解析報告</h1><p>本報告只讀取 <code>joybomb_archive</code> 的 raw posts 與 section-level parse drafts；不會建立 Knowledge 資料、公告工作或 Discord 訊息。建議分類僅供人工檢視，不會回寫資料庫。</p>
<section class="intro"><ul class="stats">{stats}</ul><p><strong>內容類型：</strong>{type_stats}</p></section>
<section class="filters"><label>關鍵字 <input id="search" placeholder="標題、Notice ID、活動、套裝"></label><label>年份 <select id="year"><option value="">全部</option></select></label><label>內容類型 <select id="type"><option value="">全部</option>{content_type_options}</select></label><label>建議 <select id="rec"><option value="">全部</option><option value="high_confidence">高信心候選</option><option value="needs_review">Needs Review</option><option value="skip">Skip</option></select></label><label><input id="multi" type="checkbox">只看多 Section</label><label><input id="suits" type="checkbox">只看有套裝候選</label><label><input id="story" type="checkbox">只看 Story Event 命中</label><span id="visible"></span></section>
<section id="posts">{''.join(cards)}</section>
</main><script>
const posts=[...document.querySelectorAll('.post-card')], year=document.querySelector('#year'), type=document.querySelector('#type'), rec=document.querySelector('#rec');
for(const value of [...new Set(posts.map(p=>p.dataset.year).filter(Boolean))].sort().reverse()) year.insertAdjacentHTML('beforeend',`<option value="${{value}}">${{value}}</option>`);
function applyFilters(){{const q=document.querySelector('#search').value.trim().toLowerCase(), multi=document.querySelector('#multi').checked, suits=document.querySelector('#suits').checked, story=document.querySelector('#story').checked, hasSectionFilters=Boolean(type.value||rec.value||suits||story);let visible=0;for(const post of posts){{let ok=(!q||post.dataset.search.includes(q))&&(!year.value||post.dataset.year===year.value)&&(!multi||post.dataset.multi==='true'), sectionMatch=false;for(const section of post.querySelectorAll('.section-card')){{const sectionOk=(!type.value||section.dataset.type===type.value)&&(!rec.value||section.dataset.rec===rec.value)&&(!suits||section.dataset.suits==='true')&&(!story||section.dataset.story==='true');section.classList.toggle('hidden',!sectionOk);sectionMatch||=sectionOk}}if(hasSectionFilters)ok&&=sectionMatch;post.classList.toggle('hidden',!ok);if(ok)visible++}}document.querySelector('#visible').textContent=`顯示 ${{visible}} / ${{posts.length}} 篇公告`;}}
for(const element of document.querySelectorAll('input,select')) element.addEventListener('input',applyFilters);applyFilters();
</script></body></html>'''


def export_report(output_path: Path = DEFAULT_OUTPUT, database_path: Path = DATABASE_PATH) -> ReportSummary:
    """Write the offline HTML file and return its read-only summary."""
    posts, summary = load_report_data(database_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(posts, summary), encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a read-only JoyBomb draft-only HTML report.")
    parser.add_argument("--database-path", type=Path, default=DATABASE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = export_report(args.output, args.database_path)
    print(f"Report written: {args.output}")
    print(f"Raw posts: {summary.raw_posts}; sections/drafts: {summary.sections}/{summary.drafts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
