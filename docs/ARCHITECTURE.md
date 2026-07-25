# 現役系統架構

## 範圍

Miracle Nikki Bot 目前的正式產品是官方公告同步服務。正式主線不包含 Knowledge DB、公告內容語意解析、活動／套裝資料或 Facebook live crawler。

## 資料流

```text
台服官網                           陸服官網
  │                                  │
  ▼                                  ▼
tw_official_crawler            cn_official_crawler
  │                                  │
  └───────────── Announcement ───────┘
                         │
                         ▼
              AnnouncementStateStore
              database/announcement_state.db
                         │
                         ▼
       announcements + announcement_deliveries
                         │
                         ▼
                 Dispatcher worker
                         │
                         ▼
                       Discord
```

## 官方來源與 crawler

| 來源 | 模組 | 擷取方式 | 輸出 |
|---|---|---|---|
| 台服官網 | `crawler/tw_official_crawler.py` | 既有官網 JSON API 與 Next.js detail data | 統一 `Announcement` |
| 陸服官網 | `crawler/cn_official_crawler.py` | `requests` + BeautifulSoup | 統一 `Announcement` |

Crawler 的責任僅限於取得官方公告、正文、發布時間、分類與依 DOM 順序排列的圖片。Crawler 不操作 Discord、不建立 delivery、不寫 SQLite state。

`Announcement` 定義於 `announcement/models.py`，至少包含 source、external ID、canonical URL、標題、分類、發布時間、原始 HTML、正文與圖片 URL。

## 公告快照與狀態

`announcement/state_store.py` 的 `AnnouncementStateStore` 是現役狀態唯一權威來源。

資料庫路徑：

```text
database/announcement_state.db
```

它保存：

- 公告快照：標題、正文、HTML、圖片 URL、發布時間、來源與 URL。
- 去重身分：優先 `source + external_id`，其次 `source + canonical_url`。
- 每個目標 Discord channel 的 delivery 狀態、重試資訊與 message IDs。
- 每個官方來源的 baseline external ID。

它不使用也不需要舊 `database/database.db` 作為現役公告狀態。

## Poller、baseline 與 delivery

`bot/main.py` 在 Discord ready 後啟動兩個現役背景工作：

1. 官方 poller：每 5 分鐘抓取台服與陸服最近公告。
2. delivery worker：每分鐘 claim pending／failed delivery，經 Dispatcher 發送。

首次部署前需執行：

```bash
python scripts/announcement/initialize_official_baseline.py
```

Baseline 記錄當下兩來源官方列表第一篇的 external ID，避免第一次部署補送歷史公告。之後 poller 只處理本輪列表中位於 baseline 前方的公告；external ID 僅是身分，不以數字大小判斷新舊。baseline 不在抓取窗口時會安全略過該來源並保留 baseline。日常 restart 或更新不可重新初始化 baseline。

Dispatcher（`announcement/dispatcher.py`）是唯一 Discord 送達路徑。只有成功送達後才標記該 channel delivery 為 sent；失敗會保留為可重試狀態。

## Replay 與備份

`scripts/announcement/replay_latest_official.py` 用於在指定 channel 重新建立或重設某一官方公告的 pending delivery，供測試 Embed、正文與圖片。它不直接傳送 Discord，也不會自行啟動 Bot。

Replay 支援最新公告與指定 external ID：

```bash
python scripts/announcement/replay_latest_official.py --source tw --dry-run
python scripts/announcement/replay_latest_official.py --source cn --external-id 988639 --channel-id YOUR_TEST_CHANNEL_ID --replay
```

SQLite 備份應針對 `announcement_state.db` 使用 SQLite online backup；正式操作流程見 [DEPLOY.md](DEPLOY.md)。

## 正式部署

正式環境為 Google Cloud Compute Engine VM：

```text
systemd: miracle-nikki-bot.service
  │
  ▼
/opt/miracle-nikki-bot/.venv/bin/python bot/main.py
  │
  ▼
/opt/miracle-nikki-bot/database/announcement_state.db
```

部署方式、`.env`、日誌、更新與故障排除見 [DEPLOY.md](DEPLOY.md)；VM 建立與成本注意事項見 [deployment_google_cloud.md](deployment_google_cloud.md)。

## Legacy 邊界

下列項目不屬於正式公告同步主線：

- Facebook crawler 與 Playwright session。
- JoyBomb Wayback crawler、section splitter 與研究／稽核工具。
- Parser、Story Dictionary、Knowledge DB、Event、Suit、Series 與舊 Discord 管理 UI。
- 舊 `database/database.db`、`raw_posts`、`announcement_jobs`、`parse_drafts` 與相關 repair／rebuild scripts。

它們保留供歷史資料、研究或日後維護；正常 `bot/main.py` 啟動不會排程 Facebook、Parser、Knowledge 或舊 Queue worker。詳見 [legacy_runtime_inventory.md](legacy_runtime_inventory.md)。
