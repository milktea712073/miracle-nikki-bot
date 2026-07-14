# miracle-nikki-bot

Python 專案骨架，用於開發《奇蹟暖暖》相關的資料爬取、資料庫與機器人功能。

## 環境設定（Conda）

```powershell
conda env create -f environment.yml
conda activate miracle-nikki-bot
```

如要安裝之後新增的套件：

```powershell
pip install -r requirements.txt
```

## 啟動 Bot

以 `.env.example` 建立本機 `.env`，填入 Discord Bot Token 與頻道設定後，可在 VS Code 選取目前的 Conda interpreter，按 `F5` 執行 **Run Miracle Nikki Bot**。此設定會啟動 `${workspaceFolder}/bot/main.py`，不會寫死 Python 路徑。

`.env` 至少需要設定：`DISCORD_TOKEN`、`ANNOUNCEMENT_CHANNEL_IDS`、`QUERY_CHANNEL_IDS`、`ADMIN_CHANNEL_IDS`。管理員白名單可選擇設定 `DISCORD_ADMIN_USER_IDS` 與 `DISCORD_ADMIN_ROLE_IDS`；多個 ID 使用半形逗號分隔。

## 管理資料

使用 `/活動` 與 `/套裝` 查詢資料；管理員可在管理頻道的資料卡上使用編輯按鈕校正內容。`parse_drafts` 與 `parse_draft_suits` 是 Parser 的內部中間與稽核資料，日常不再提供 Discord 草稿審核指令。

## 開發與維運工具

所有工具會依檔案位置解析專案根目錄；從其他工作目錄呼叫時，請使用該 script 的實際路徑。先使用 `--help` 查看參數；下列範例不含任何真實帳號、網址或頻道資料。

**日常資料流程**

- `scripts/data/fetch_raw_posts.py`：抓取 Facebook 原始貼文並寫入本機資料庫；會修改資料庫，不發送 Discord。
  `python scripts/data/fetch_raw_posts.py --limit 10`
- `scripts/data/parse_raw_posts.py`：解析待處理原始貼文並更新知識庫；會修改資料庫。
  `python scripts/data/parse_raw_posts.py --limit 10`

**資料庫維護**

- `scripts/data/rebuild_database.py`：開發用重建資料；會清除可再生資料並要求精確輸入 `YES`。預設保留公告 Queue。
  `python scripts/data/rebuild_database.py --limit 50`
- `scripts/data/reset_database.py`：危險工具，清空業務資料、重設 AUTOINCREMENT 並要求精確輸入 `YES`。
  `python scripts/data/reset_database.py`
- `scripts/data/cleanup_auto_suits.py`：預設只列出不合法的自動建立套裝；使用 `--apply` 後仍須輸入 `YES` 才會刪除。
  `python scripts/data/cleanup_auto_suits.py --apply`

**公告 Queue**

- `scripts/announcement/initialize_announcement_queue.py`：首次部署設定公告起點，既有 raw posts 會標記為 skipped，不發送 Discord，須輸入 `YES`。
  `python scripts/announcement/initialize_announcement_queue.py`
- `scripts/announcement/baseline_announcements.py`：人工維運時將明確指定的歷史貼文標記為 skipped jobs；不建立假 announcements，須輸入 `YES`。
  `python scripts/announcement/baseline_announcements.py --post-url "https://example.invalid/posts/old" --exclude-post-url "https://example.invalid/posts/current"`
- `scripts/announcement/requeue_announcement.py`：以指定貼文 URL 明確重送一篇公告。
  `python scripts/announcement/requeue_announcement.py --post-url "https://www.facebook.com/TwNikkiNikki/posts/example"`
- `scripts/announcement/requeue_latest.py`：重新排入最近一筆已成功送達的公告。
  `python scripts/announcement/requeue_latest.py`

**一次性／舊版 migration**

- `scripts/announcement/migrations/migrate_announcement_baseline.py`：僅供舊 baseline 資料庫遷移至 announcement jobs；會顯示 `DEPRECATED` 並要求 `YES`。
  `python scripts/announcement/migrations/migrate_announcement_baseline.py`
- `scripts/legacy/review_drafts.py`：保留給舊版人工復原用途；日常管理請使用活動與套裝資料卡。
  `python scripts/legacy/review_drafts.py --help`

**診斷**

- `scripts/diagnostic/facebook_feed_diagnostic.py`：比較 storage state 與專用 persistent profile 的 Facebook Feed。
  `python scripts/diagnostic/facebook_feed_diagnostic.py --rounds 1`
- `scripts/diagnostic/facebook_feed_network_diagnostic.py`：記錄 Feed GraphQL response 的 permalink 覆蓋率。
  `python scripts/diagnostic/facebook_feed_network_diagnostic.py --rounds 1`
- `scripts/diagnostic/debug_facebook_mobile.py` 與 `scripts/diagnostic/debug_facebook_post_sources.py`：保留的唯讀 Facebook DOM／入口診斷工具；不修改資料庫。
  `python scripts/diagnostic/debug_facebook_mobile.py --help`
  `python scripts/diagnostic/debug_facebook_post_sources.py --help`

## 本機敏感資料

`database/database.db`、其 `-wal`／`-shm` 執行期檔案、Facebook storage state/profile，以及登入後產生的 Facebook debug HTML 都只應保留在本機，不應公開分享或提交到 Git。

## 專案結構

```text
crawler/   資料爬取程式
database/  資料庫模型與存取層
bot/       機器人應用程式
docs/      專案文件
```
