# Legacy Runtime Inventory（封存執行期盤點）

> **文件用途：** 說明仍保留在倉庫、但不屬於目前正式公告同步主線的程式與入口。
> 正式架構請見 [README](../README.md)、[系統架構](ARCHITECTURE.md) 與[部署手冊](DEPLOY.md)。
> 下方既有英文盤點內容保留作技術追溯；不得將列出的 Facebook、Knowledge 或 Parser 元件視為正式 VM 的啟動流程。

## Active At Normal Bot Startup

`bot/main.py` initializes the standalone v2 announcement-state SQLite file,
starts Discord presence rotation, polls the Taiwan and China **official website**
sources, and delivers their persisted announcements. It does **not** register
Knowledge commands or start Facebook, a parser, or Knowledge auto-import task.

The application-command callbacks for `/活動` and `/套裝` remain as retained
code, but are explicitly removed from the command tree before `tree.sync()`.
They are not available to Discord users.

## Retained, Disabled Facebook Archive Components

- `crawler/facebook_crawler.py` and `crawler/facebook_session.py`
- `scripts/data/fetch_raw_posts.py`
- `bot.main.poll_tw_announcements`
- `bot.main.poll_facebook_posts`
- `bot.main.process_v2_announcement_deliveries`
- `bot.main.process_announcement_queue`

These are legacy archive and recovery tools. They are intentionally not called
by `on_ready()` and must not be treated as a live source. Existing Facebook raw
posts, announcement records, image records, and crawler tests are preserved.

## Retained, Disabled Knowledge Components

- `database/knowledge_query_repository.py`, `database/knowledge_repository.py`
- `database/parse_draft_repository.py`, `database/review_repository.py`
- `database/auto_import_service.py`, `database/import_service.py`
- `parser/`, `content/section_splitter.py`, and `knowledge/`
- `bot/admin/knowledge_event_views.py` and `bot/admin/knowledge_suit_views.py`
- `scripts/data/parse_raw_posts.py`, `scripts/data/seed_fixed_series.py`, and
  other explicit Knowledge repair utilities

They retain historical Knowledge data and recovery capability, but no normal Bot
startup path invokes them. Do not run their scripts as part of the active
announcement-only product without an explicit maintenance decision.

## One-Off and Diagnostic Scripts

`scripts/legacy/review_drafts.py` is already archived and has no Bot entry
point. Facebook, JoyBomb, draft, repair, and migration scripts under
`scripts/data/`, `scripts/announcement/`, and `scripts/diagnostic/` remain in
place because tests, recovery procedures, or documented investigations import
them directly. They are manual tools, not runtime services.

Before moving any additional script, update every direct import and its tests;
the current Phase intentionally avoids path churn while preserving recoverability.
