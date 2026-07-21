# Miracle Nikki Bot

Miracle Nikki Bot 是一個將《奇蹟暖暖》台服與陸服**官方網站公告**同步至 Discord 的 Python Bot。

## 目前產品方向

現役功能只聚焦於官方公告同步：

- 台服官方網站公告
- 陸服官方網站公告
- Discord Embed、原文連結與依序圖片
- 每來源、每頻道的公告去重與送達重試

Facebook crawler、JoyBomb Wayback、Knowledge DB、Parser、活動／套裝／Series 與舊 Discord 管理功能均保留作歷史資料、研究或維護用途，但**不是正式部署主流程**。

## 現役資料流

```text
台服官方網站             陸服官方網站
      │                       │
      └─────── Crawler ───────┘
                    │
                    ▼
              Announcement
                    │
                    ▼
         AnnouncementStateStore
                    │
                    ▼
      Pending Delivery（每個頻道）
                    │
                    ▼
               Dispatcher
                    │
                    ▼
                 Discord
```

- 台服：`crawler/tw_official_crawler.py`
- 陸服：`crawler/cn_official_crawler.py`
- 狀態資料庫：`database/announcement_state.db`
- Bot runtime：`bot/main.py`

Poller 每 5 分鐘檢查兩個官方來源；delivery worker 每分鐘處理 pending 或可重試的 delivery。

## 快速開始

### 本機開發

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

將 `.env.example` 複製為本機 `.env`，填入**測試** Discord Bot token 與測試頻道 ID。不要提交 `.env`。

第一次建立新的公告 state 前，先初始化 baseline：

```powershell
python scripts/announcement/initialize_official_baseline.py --dry-run
python scripts/announcement/initialize_official_baseline.py
```

這只記錄目前最新公告，不會補送歷史公告或直接發送 Discord。之後可啟動 Bot：

```powershell
python bot/main.py
```

完整本機開發流程請見 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

### 測試

```powershell
python -m pytest -q --basetemp=.pytest-runtime
```

### 正式部署

Google Cloud Compute Engine 的部署、systemd、日常更新、日誌與備份請見 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 官方公告工具

### Baseline

```powershell
python scripts/announcement/initialize_official_baseline.py --dry-run
python scripts/announcement/initialize_official_baseline.py
```

只在全新的 `announcement_state.db` 第一次部署時執行正式初始化。日常更新或重啟時不要重跑。

### Replay

Replay 用於驗證指定公告在測試頻道的 Discord 呈現。它只建立或重設明確指定頻道的 pending delivery；Dispatcher 仍是唯一送達路徑。

```powershell
python scripts/announcement/replay_latest_official.py --source tw --dry-run
python scripts/announcement/replay_latest_official.py --source cn --external-id 988639 --dry-run

python scripts/announcement/replay_latest_official.py --source tw --channel-id 123456789012345678 --replay
python scripts/announcement/replay_latest_official.py --source cn --external-id 988639 --channel-id 123456789012345678 --replay
```

## 設定

現役 pipeline 至少使用下列 `.env` 變數：

```dotenv
DISCORD_TOKEN=
TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=
CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=
```

- `DISCORD_TOKEN`：Discord Bot token。
- `TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS`：台服公告目標頻道，可用逗號分隔多個 ID。
- `CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS`：陸服公告目標頻道，可用逗號分隔多個 ID。

不要將 token、channel ID、外部 IP、deploy key、`.env`、SQLite database 或 backup 提交至 Git。

## 文件索引

| 文件 | 用途 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 現役系統架構、責任分層、資料流與 legacy 邊界 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 本機開發、測試 Bot、測試、提交與雲端更新流程 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | 正式 VM 日常維運、systemd、日誌與故障排除 |
| [docs/deployment_google_cloud.md](docs/deployment_google_cloud.md) | Google Cloud VM 建立與完整部署細節 |
| [docs/official_announcement_pipeline.md](docs/official_announcement_pipeline.md) | AnnouncementStateStore、baseline、delivery 與 replay 設計 |
| [docs/legacy_runtime_inventory.md](docs/legacy_runtime_inventory.md) | 已停用但保留的 Facebook／Knowledge／Parser runtime 元件 |
| [docs/archive/README_legacy.md](docs/archive/README_legacy.md) | v2 前的 README 歷史內容 |

## Legacy／Archived 功能

以下程式與資料仍保留，但不得視為正式公告同步部署流程：

- `crawler/facebook_crawler.py` 與 Facebook session／Playwright 工具
- `crawler/joybomb_archive_crawler.py` 與 Wayback 研究資料
- `parser/`、`content/section_splitter.py`、`knowledge/`
- `database/database.db`、`raw_posts`、`parse_drafts`、`events`、`suits` 等舊 Knowledge 資料
- `scripts/data/rebuild_database.py`、`scripts/data/reset_database.py` 與各種舊 Queue repair／requeue 工具
- 舊 Discord `/活動`、`/套裝`、草稿與管理 UI 的保留程式碼

若需研究或維護這些功能，先閱讀 [docs/legacy_runtime_inventory.md](docs/legacy_runtime_inventory.md) 與對應歷史文件；不要在正式公告 VM 上直接執行 legacy rebuild、reset、crawler 或 repair script。
