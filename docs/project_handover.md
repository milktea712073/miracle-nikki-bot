# Archived：舊 Knowledge／Facebook 架構交接文件

> **此文件已過時，保留作歷史追溯。** 它描述的是 Query-as-Review、Facebook live crawler、Knowledge DB、Parser、活動／套裝與舊 announcement queue 的設計，不是目前正式公告同步架構。
>
> 請優先閱讀：
> - [專案首頁](../README.md)
> - [現役系統架構](ARCHITECTURE.md)
> - [正式部署與日常維運](DEPLOY.md)
> - [Legacy Runtime Inventory](legacy_runtime_inventory.md)

# Miracle Nikki Bot 專案交接說明

## 1. 專案目的

Miracle Nikki Bot 用於收集《奇蹟暖暖》官方公告、保存原始資料、解析活動與套裝資訊，並提供 Discord 查詢與管理介面。

系統採用「Query-as-Review」模式：Parser 產生知識資料後，管理員平時透過 Discord 的 `/活動`、`/套裝` 卡片檢查結果，發現錯誤時直接使用卡片上的編輯功能校正。`parse_drafts` 是內部解析與追溯資料，不是日常人工審核入口。

## 2. 主要功能

### 官方資料來源

| 來源 | 用途 | 是否建立 Discord 公告 |
|---|---|---|
| Facebook | 官方社群公告、月刊、得獎名單與社群內容 | 是，唯一公告來源 |
| Fearless Website | 新官網正式活動資料 | 否，只進知識資料流程 |
| JoyBomb Wayback Archive | 2017 至 2024 的歷史公告 | 否，只進原始資料與歷史知識整理流程 |

Facebook crawler 同時使用首頁 DOM 與 Feed GraphQL permalink 作為 URL 收集來源。每個 URL 仍須由 Detail Parser 驗證官方主貼文後才會保存。Facebook 同一主文可能有多個 pfbid；系統使用 alias 合併，避免重複 raw post、公告工作與 Discord 重送。

### 公告 Queue

```text
Facebook crawler
  -> raw_posts / raw_post_images
  -> announcement_jobs
  -> Discord delivery worker
  -> announcements
```

- `raw_posts` 保存可信官方貼文；`published_at` 可為空，不會因缺少 Facebook 絕對發布時間而略過貼文。
- `announcement_jobs` 是耐久 Queue，狀態為 `pending`、`sending`、`sent`、`skipped`、`failed`。
- Discord Worker 每輪最多處理 3 筆 pending / failed job；不依 Facebook Feed 順序判斷新舊。
- `announcements` 只記錄實際成功送達 Discord 的紀錄，不存 baseline 假紀錄。
- Bot 啟動後會先輪詢 Facebook，再由 Queue Worker 發送新 job；Facebook 抓取和 Queue 發送是兩個獨立背景工作。

### 知識資料流程

```text
raw_posts
  -> Parser / Section Splitter
  -> parse_drafts / parse_draft_suits
  -> Auto Import 或明確 repair 工具
  -> events / event_periods / event_suits / suits / cost_records
  -> Discord /活動、/套裝
```

- Facebook、Fearless 與 JoyBomb 最終都可使用 Shared Semantic Parser。
- JoyBomb 一篇公告可先切成多個 section；draft identity 使用 raw post、section hash、splitter version、parser version，避免同一 section 重跑時重複建立 draft。
- JoyBomb 現階段不建立公告 job；歷史資料可先 draft-only，再依明確工具處理可安全匯入的候選。

## 3. Discord 使用方式

### 頻道限制

- `ANNOUNCEMENT_CHANNEL_IDS`：只接收自動公告。
- `QUERY_CHANNEL_IDS`：可使用 `/活動`、`/套裝`，不顯示管理按鈕。
- `ADMIN_CHANNEL_IDS`：可查詢，並顯示管理按鈕。
- 管理 callback 會再次驗證管理頻道及管理員權限，舊卡片不能繞過限制。

### `/活動`

- 一般活動：顯示分類、期間、套裝、花費、備註與來源公告第一張圖片（若 `source_raw_post_id` 有圖片）。
- 固定 Series：透過綁定 Event 顯示名稱、分類、主套、小套、Live2D、檔期、花費與備註。
- 一般活動管理入口只有 `✏️ 編輯`。
- 固定 Series 管理入口為 `✏️ 編輯資訊`、`👗 編輯套裝`、`📅 編輯檔期`。
- 活動卡沒有手動圖片編輯功能。

### `/套裝`

- 顯示套裝所屬活動、分類、取得方式、花費與套裝圖片。
- 若套裝透過 EventSuit 關聯到固定 Series，顯示 `🏛️ 所屬系列`；若同時也屬於一般活動，兩種關聯都會保留，不會互相遮蔽。
- 管理入口為 `✏️ 編輯套裝` 與 `🖼️ 編輯圖片`。
- 套裝圖片採翻頁預覽；管理員按 `📝 編輯圖片` 後直接在同頻道上傳 Discord attachment，等待 5 分鐘，輸入「取消」可結束。

## 4. 主要資料表責任

| 資料表 | 責任 |
|---|---|
| `raw_posts` | 各來源的原始公告本文與來源 metadata |
| `raw_post_images` | 原始公告圖片，依 `raw_post_id` 與 position 排序 |
| `raw_post_aliases` | Facebook 同文不同 pfbid 的別名識別 |
| `announcement_jobs` | Facebook 公告的耐久發送 Queue |
| `announcements` | Discord 成功送達 ledger |
| `parse_drafts` / `parse_draft_suits` | Parser 中間結果、診斷與追溯資料 |
| `events` | Discord 查詢與知識資料的活動核心 |
| `event_periods` | 活動期間或固定 Series 顯示型檔期的同步結果 |
| `suits` | 全域唯一套裝名稱與基本資料 |
| `event_suits` | Event 與 Suit 的關聯、排序、取得方式、花費脈絡 |
| `cost_records` | 活動或單套花費 |
| `suit_images` | 套裝唯一可手動管理的圖片來源 |
| `series` | 固定系列的管理 metadata，透過 `event_id` 綁定 Event |
| `series_contents` / `series_periods` | 固定 Series 管理輸入，會同步至 Event 關聯資料 |

## 5. 圖片責任

```text
活動卡圖片
events.source_raw_post_id
  -> raw_post_images 第一張
  -> 唯讀展示

套裝卡圖片
suits
  -> suit_images
  -> raw_post_images.raw_post_image_id 或手動 image_url
  -> 唯一可手動編輯的圖片入口
```

不要以 `raw_posts.content LIKE 活動名稱` 搜尋圖片；同名活動、復刻和公告內文提及都會造成錯誤關聯。系統已退役舊 Event Image Manager，活動圖片不應改用 SuitImages，套裝圖片也不應直接推測使用活動公告首圖。

## 6. 日常維運

### 啟動

1. 以 `.env.example` 建立本機 `.env`。
2. 設定 Discord Token、公告／查詢／管理頻道與管理員設定。
3. 在 VS Code 選擇 `miracle-nikki-bot` Conda interpreter 後按 F5，或執行：

```powershell
conda activate miracle-nikki-bot
python bot/main.py
```

### 常用指令

```powershell
# 手動抓取 Facebook 原始貼文；預設可建立新公告 job。
python scripts/data/fetch_raw_posts.py --limit 10

# 解析待處理原始貼文。
python scripts/data/parse_raw_posts.py --limit 10

# 匯入或更新 JoyBomb raw layer，不送公告。
python scripts/data/import_joybomb_archive.py --from-year 2017 --to-year 2024

# JoyBomb section-level draft-only 解析，不進 Knowledge DB。
python scripts/data/parse_raw_posts.py --source joybomb_archive --limit 575 --draft-only

# 重新排入明確指定的公告。
python scripts/announcement/requeue_announcement.py --post-url "https://www.facebook.com/TwNikkiNikki/posts/..."

# 重新排入最近一筆成功送達的公告。
python scripts/announcement/requeue_latest.py
```

詳細工具與危險操作請見 [README](../README.md)。所有 `--apply`、reset、rebuild、baseline 與 repair 類工具都應先 dry-run、確認影響範圍、建立資料庫備份後再執行。

## 7. 重要安全規則

- 不要提交 `.env`、Facebook storage state/profile、`database.db`、WAL/SHM 檔案或登入後 HTML。
- 不要在未確認公告 Queue 狀態時執行 `rebuild_database.py`、`reset_database.py` 或公告 repair。
- 一般 rebuild 預設應保留 announcement queue 與 sent ledger；只有 `--reset-announcements` 並完成第二次 `YES` 確認時才允許清除。
- Facebook 新公告的永久去重身分是 canonical URL；不得只用會在 rebuild 中變動的 `raw_post_id`。
- JoyBomb、Fearless 不建立 Discord announcement job。
- 不要以活動名稱作為 Event 自動合併鍵；來源 section / raw post identity 才是自動匯入的主要依據。

## 8. 目前技術債與交接注意事項

1. 固定 Series 目前保存管理資料並同步到綁定 Event。正式查詢已以 Event 為中心，但 `series_contents`、`series_periods`、`diamond_cost` 仍存在，未來改動要避免兩條寫入路徑互相覆蓋。
2. `parse_drafts` 仍保留歷史與診斷用途；不要因為 Discord 沒有草稿審核 UI 就刪除。
3. JoyBomb 歷史資料跨年代版型差異大。先以 draft-only 與診斷報告驗證，再小批量處理 Knowledge import。
4. Facebook Feed 不是可靠時間排序；公告系統不得以本輪 Feed 第一篇或 `published_at` 排序判定新舊。
5. 正式修改前請執行完整測試：

```powershell
conda run -n miracle-nikki-bot python -m pytest -q --basetemp=.pytest-runtime
```

目前最近一次完整測試結果為 `404 passed`。
