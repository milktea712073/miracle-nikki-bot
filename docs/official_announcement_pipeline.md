# Official Announcement Pipeline v2.0

本文件是現役公告同步流程的交接文件。Facebook crawler、Knowledge DB、Parser、Event、Suit 與舊 announcement queue 都保留為歷史封存程式與資料，但不屬於正常 Bot 啟動流程。

## 現役資料流

```text
Official Website
        │
        ▼
Crawler
        │  Announcement
        ▼
AnnouncementStateStore
        │  announcement + per-channel delivery
        ▼
Pending Delivery
        │
        ▼
Dispatcher
        │
        ▼
Discord
```

`AnnouncementStateStore` 的資料位於獨立的 `database/announcement_state.db`。它是現役流程唯一的持久化狀態來源，不讀寫舊 `database/database.db`。

## 模組責任

| 模組 | 責任 | 不負責 |
|---|---|---|
| `crawler/tw_official_crawler.py` | 取得台服官網公告，轉為統一 `Announcement` | Discord、SQLite、頻道設定 |
| `crawler/cn_official_crawler.py` | 取得陸服官網公告，轉為統一 `Announcement`；清理 HTML 正文與固定 QR footer 圖 | Discord、SQLite、頻道設定 |
| `announcement/models.py` | 定義來源無關的 `Announcement` 與 URL 正規化 | 網路存取、送達狀態 |
| `announcement/state_store.py` | 以 `source + external_id` 優先、canonical URL 次要身分保存公告；建立每頻道 delivery；保存 baseline | Discord API、爬取 |
| `announcement/dispatcher.py` | 將單筆已 claim 的 delivery payload 交給既有發送函式 | claim 其他 delivery、改寫公告內容 |
| `bot/main.py` | 啟動官方 poller 與 delivery worker，解析環境頻道設定，透過 Discord 發送 | 網站 HTML 解析、歷史補送 |
| `scripts/announcement/initialize_official_baseline.py` | 初始化或更新各官方來源 baseline | 建立 delivery、發送 Discord |
| `scripts/announcement/replay_latest_official.py` | 以指定 channel 重設最新公告的單一 delivery 供測試 | 啟動 Bot、直接送 Discord、使用預設頻道 |

## Baseline

首次部署前執行：

```powershell
python scripts/announcement/initialize_official_baseline.py
```

工具各抓取台服與陸服第一篇公告，將其 `external_id` 持久化為 baseline。它不建立 Announcement、不建立 Pending Delivery，也不發送 Discord。

正常 poller 的規則：

1. 沒有 baseline 時，安全略過該來源並要求先初始化。
2. 最新公告等於 baseline 時，不建立 delivery。
3. external ID 比 baseline 新時，依序 register 公告、建立目標頻道的 pending delivery，並推進 baseline。

因此 poller 不會在第一次部署時補送官網現有歷史公告。

Dry-run：

```powershell
python scripts/announcement/initialize_official_baseline.py --dry-run
```

Dry-run 只顯示兩來源最新公告的 external ID 與標題，不改變 state。

## Delivery 與 Discord

每一個公告與每一個目標 channel 都有獨立 delivery 狀態。只有 Dispatcher 的正式送達路徑可以呼叫 Discord 發送函式：

1. worker claim pending 或可重試的 delivery。
2. Dispatcher 依公告 payload 呼叫既有 Discord sender。
3. 全部該 delivery 的 Discord 發送成功後，state store 才標記成功與 `sent_at`。
4. 發送失敗不會先標記 sent，該 channel 可在後續 worker 週期重試。

此設計避免一個頻道成功後，另一個失敗頻道永久漏送。

## Replay

Replay 用於反覆檢查 Discord Embed、正文與圖片排列。必須指定目標頻道：

```powershell
python scripts/announcement/replay_latest_official.py --source tw --channel-id 123456789012345678 --replay
python scripts/announcement/replay_latest_official.py --source cn --channel-id 123456789012345678 --replay
```

```text
Crawler
  ↓
AnnouncementStateStore (reset specified channel only)
  ↓
Pending Delivery
  ↓
Dispatcher
```

Replay 不依賴 scheduler，不會啟動完整 Bot，也不會使用未指定的正式頻道。它僅建立或重設該次 `--channel-id` 的 delivery；實際發送仍必須經由既有 authenticated Dispatcher 路徑。

唯讀預覽：

```powershell
python scripts/announcement/replay_latest_official.py --source tw --dry-run
python scripts/announcement/replay_latest_official.py --source cn --dry-run
```

## 設定

```dotenv
TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=111111111111111111,222222222222222222
CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=333333333333333333
```

- `TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS`：台服官網公告目標頻道，可設定多個。
- `CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS`：陸服官網公告目標頻道，可設定多個，必須明確提供。
- 不要將真實 channel ID 或 Discord token 提交至 Git。

## 維運原則

- Crawler 只取資料，不直接操作 SQLite 或 Discord。
- `AnnouncementStateStore` 是去重、baseline 與 delivery 狀態的唯一權威來源。
- Dispatcher 是唯一 Discord 送達路徑；不要在 crawler、replay 或 scheduler 內重新實作 Embed 或直接發送。
- Poller 只處理 baseline 之後的新官方公告，不補送歷史公告。
- Facebook 仍保留為 legacy archive source，絕不屬於 live pipeline。
