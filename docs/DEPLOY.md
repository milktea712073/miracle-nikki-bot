# 正式部署與日常維運

本文件適用於已部署在 Google Cloud Compute Engine 的 Miracle Nikki Bot 現役 Official Announcement Pipeline。

正式部署路徑：

```text
/opt/miracle-nikki-bot
```

Python 虛擬環境：

```text
/opt/miracle-nikki-bot/.venv
```

systemd 服務名稱：

```text
miracle-nikki-bot.service
```

## 現役資料與安全界線

正式執行狀態資料庫是：

```text
/opt/miracle-nikki-bot/database/announcement_state.db
```

這個 SQLite 資料庫保存官方公告的去重、baseline 與各 Discord 頻道 delivery 狀態。正式部署只應操作這個 state database。

不要在正式機器的日常維運中執行以下 legacy Knowledge／舊資料庫工具：

```text
scripts/data/rebuild_database.py
scripts/data/reset_database.py
```

它們不屬於現役 Official Announcement Pipeline，可能影響封存的舊資料或造成不必要風險。

不要將 Discord Token、Discord channel ID、外部 IP、private deploy key、`.env` 或 SQLite 備份提交到 Git。

## 連線至 VM

可使用 VS Code Remote - SSH 開啟主機，或從終端連線：

```bash
ssh miracle-nikki-bot
```

此命令假設本機 `~/.ssh/config` 已設定 `Host miracle-nikki-bot`。若尚未設定，請使用 Google Cloud Console SSH、IAP 或組織核准的 SSH 方式連線，不要將私鑰提交到 repository。

連線後確認目錄與服務：

```bash
cd /opt/miracle-nikki-bot
pwd
sudo systemctl status miracle-nikki-bot --no-pager
```

## `.env` 設定

正式 `.env` 必須位於：

```text
/opt/miracle-nikki-bot/.env
```

以 repository 的 `.env.example` 為欄位參考。現役公告同步至少需要：

```dotenv
APP_ENV=production
DISCORD_TOKEN=
GUILD_ID=
TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=
CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=
ENABLE_ANNOUNCEMENT_PIPELINE=true
```

- `APP_ENV`：正式 VM 請填 `production`，僅作環境標記與日誌辨識。
- `DISCORD_TOKEN`：Discord Bot token。
- `GUILD_ID`：Production 可留空，保留既有全域 Slash Command 同步；若填寫，僅同步到該 Guild。
- `ENABLE_ANNOUNCEMENT_PIPELINE`：正式 VM 必須為 `true`，以啟用官方公告輪詢與 Discord delivery。
- `TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS`：台服官方公告頻道，可使用逗號分隔多個 ID。
- `CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS`：陸服官方公告頻道，可使用逗號分隔多個 ID。

`.env` 應由服務帳號擁有，且只有擁有者可讀：

```bash
sudo chown miraclebot:miraclebot /opt/miracle-nikki-bot/.env
sudo chmod 600 /opt/miracle-nikki-bot/.env
```

不要在 shell history、systemd unit、README、issue、聊天記錄或 Git 中貼上真實 token。

## 第一次部署

1. 使用唯讀 GitHub deploy key clone private repository 至 `/opt/miracle-nikki-bot`。
2. 建立 venv 並安裝相依套件：

   ```bash
   cd /opt/miracle-nikki-bot
   /opt/miracle-nikki-bot/.venv/bin/python -m pip install -r requirements.txt
   ```

3. 管理者手動建立 `.env`，不要將它放入 Git。
4. 在**第一次啟動服務前**初始化 Official Baseline：

   ```bash
   cd /opt/miracle-nikki-bot
   /opt/miracle-nikki-bot/.venv/bin/python \
     scripts/announcement/initialize_official_baseline.py --dry-run

   /opt/miracle-nikki-bot/.venv/bin/python \
     scripts/announcement/initialize_official_baseline.py
   ```

   此 script 只將目前台服與陸服最新公告記錄為 baseline，不建立 delivery、不發送 Discord、不補送歷史公告。

5. 啟用並啟動服務：

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now miracle-nikki-bot
   sudo systemctl status miracle-nikki-bot --no-pager
   ```

首次初始化後，**不要在每次更新或重啟時重跑 baseline**。重跑可能將停機期間的新公告視為既知資料。

## 日常更新流程

先停止服務，更新程式與相依套件，再重新啟動：

```bash
sudo systemctl stop miracle-nikki-bot

cd /opt/miracle-nikki-bot
git pull --ff-only

# 只有 requirements.txt 有變更時才需要執行；重複執行也是安全的。
/opt/miracle-nikki-bot/.venv/bin/python -m pip install -r requirements.txt

sudo systemctl start miracle-nikki-bot
sudo systemctl status miracle-nikki-bot --no-pager
```

更新不需要重新執行 `initialize_official_baseline.py`。

若更新失敗，保持服務停止，先查看 Git 狀態與 journal，再決定是否回復至已知版本；不要用 `reset_database.py` 或 `rebuild_database.py` 嘗試修復部署問題。

## systemd 操作

```bash
# 啟動
sudo systemctl start miracle-nikki-bot

# 停止
sudo systemctl stop miracle-nikki-bot

# 重新啟動
sudo systemctl restart miracle-nikki-bot

# 查看狀態
sudo systemctl status miracle-nikki-bot --no-pager

# 設為開機自動啟動
sudo systemctl enable miracle-nikki-bot
```

服務 unit 檔應為：

```text
/etc/systemd/system/miracle-nikki-bot.service
```

完整 systemd 範本與 Google Cloud VM 建立步驟請參閱 [deployment_google_cloud.md](deployment_google_cloud.md)。

## 查看 Log

```bash
# 即時追蹤
sudo journalctl -u miracle-nikki-bot -f

# 最近 200 行
sudo journalctl -u miracle-nikki-bot -n 200 --no-pager

# 本次開機後的全部服務日誌
sudo journalctl -u miracle-nikki-bot -b --no-pager
```

正常運作時，日誌應可看到官方 poller 與 delivery worker。官方網站輪詢間隔目前是 5 分鐘；pending delivery worker 每分鐘處理一次。

## 常見故障排除

### 服務無法啟動

```bash
sudo systemctl status miracle-nikki-bot --no-pager
sudo journalctl -u miracle-nikki-bot -n 200 --no-pager
```

檢查：

1. `ExecStart` 是否指向 `/opt/miracle-nikki-bot/.venv/bin/python`。
2. `WorkingDirectory` 是否為 `/opt/miracle-nikki-bot`。
3. `.env` 是否存在、owner 是否為 `miraclebot`、權限是否為 `600`。
4. `DISCORD_TOKEN`、台服與陸服頻道設定是否已填寫。
5. `miraclebot` 是否可寫入 `/opt/miracle-nikki-bot/database/`。

### Bot 啟動但沒有補送現有公告

這通常是正確行為。首次部署的 baseline 會避免補送歷史公告。只有比 baseline 更新的官方公告才會建立 pending delivery。

### 日誌要求先初始化 baseline

先以 dry-run 確認最新公告，再執行一次正式初始化：

```bash
cd /opt/miracle-nikki-bot
/opt/miracle-nikki-bot/.venv/bin/python \
  scripts/announcement/initialize_official_baseline.py --dry-run
/opt/miracle-nikki-bot/.venv/bin/python \
  scripts/announcement/initialize_official_baseline.py
```

只有尚未初始化的全新 state database 才應執行此流程。

### 需要驗證公告排版

先使用 dry-run，不寫入 state：

```bash
cd /opt/miracle-nikki-bot
/opt/miracle-nikki-bot/.venv/bin/python \
  scripts/announcement/replay_latest_official.py --source tw --dry-run
```

若要建立指定測試頻道的 pending delivery，可使用：

```bash
/opt/miracle-nikki-bot/.venv/bin/python \
  scripts/announcement/replay_latest_official.py \
  --source cn \
  --external-id 988639 \
  --channel-id YOUR_TEST_CHANNEL_ID \
  --replay
```

Replay 不直接傳送 Discord；既有 Dispatcher worker 仍是唯一送達路徑。

### SQLite 備份

使用 SQLite online backup，避免在 WAL 模式下只複製單一 `.db` 檔：

```bash
sudo install -d -o miraclebot -g miraclebot /var/backups/miracle-nikki-bot
sudo -u miraclebot sqlite3 \
  /opt/miracle-nikki-bot/database/announcement_state.db \
  ".backup '/var/backups/miracle-nikki-bot/announcement_state-$(date +%F-%H%M%S).db'"
```

本文件不建立自動備份、systemd timer 或 CI/CD。

## 參考文件

- [Google Cloud 部署細節](deployment_google_cloud.md)
- [Official Announcement Pipeline](official_announcement_pipeline.md)
- [Legacy Runtime Inventory](legacy_runtime_inventory.md)
