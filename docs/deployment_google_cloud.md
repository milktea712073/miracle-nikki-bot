# Google Cloud Compute Engine 部署指南

本文件說明如何將 Miracle Nikki Bot 的**現役 Official Announcement Pipeline**部署至 Google Cloud Compute Engine。目標是 Ubuntu 24.04 LTS、`e2-micro`、Python venv、systemd 與本機 SQLite。

本文件不會建立 Google Cloud 資源、帳務設定、Discord Token、`.env` 或 GitHub deploy key；這些操作必須由專案擁有者自行完成。

## 成本與責任

Google Cloud Free Tier 不等於保證帳單為零。建立 VM 前請先閱讀並定期確認 Google 的最新資格與價格：

- [Google Cloud Free Program](https://cloud.google.com/free/docs/free-cloud-features)
- [Compute Engine pricing](https://cloud.google.com/compute/pricing)

重要事項：

- Free Tier 目前提供的 `e2-micro`、30 GB-month `pd-standard` 與流量額度都有地區、用量及帳務帳戶條件。
- 即使 VM 規格符合 Free Tier，超出磁碟、流量、快照、IP、區域或其他服務使用量仍可能產生費用。
- 外部 IPv4，包括 ephemeral external IPv4，可能依目前 Google Cloud 計價方式產生費用；建立後應在 Billing reports 與 pricing 頁面確認。
- 不要保留 static external IP。若停止或刪除 VM，請確認沒有未使用的 reserved static IP。
- 建立 Budget Alert，但 Budget Alert **只會通知，不會自動停止資源或費用**。
- Bot 只需要對外連線至 Discord 與官網，不需要開放 HTTP/HTTPS ingress。

## 目標規格

| 項目 | 值 |
|---|---|
| OS | Ubuntu 24.04 LTS |
| Machine type | `e2-micro` |
| Provisioning model | Standard，非 Spot |
| Region | Free Tier eligible US region，例如 `us-west1`、`us-central1` 或 `us-east1` 中當下可用的 zone |
| Boot disk | 20 GB `pd-standard` |
| Application user | `miraclebot` |
| Application path | `/opt/miracle-nikki-bot` |
| Python environment | `/opt/miracle-nikki-bot/.venv` |
| State database | `/opt/miracle-nikki-bot/database/announcement_state.db` |

Free Tier eligible region、quota 與可用 zone 會變動；請以建立 VM 畫面與 [Free Program 文件](https://cloud.google.com/free/docs/free-cloud-features) 顯示內容為準。

## 1. Google Cloud Console：建立專案、帳務與警示

1. 在 Google Cloud Console 建立或選擇專案。
2. 將帳務帳戶連結至該專案；Free Tier 仍通常需要有效帳務帳戶。
3. 啟用 **Compute Engine API**。
4. 前往 **Billing → Budgets & alerts**，建立月度 Budget Alert。
   - 建議設定低於預期上限的通知門檻，例如 50%、90%、100%。
   - 確認通知 email 能收到信件。
   - Budget Alert 不會自動停機、刪除磁碟或封鎖費用。
5. 在 **IAM & Admin** 確認只有必要管理者可建立 VM 或變更帳務。

## 2. Google Cloud Console：建立 VM

Google 官方 Console 步驟參考：[Create a Linux VM instance](https://cloud.google.com/compute/docs/create-linux-vm-instance)。

1. 開啟 **Compute Engine → VM instances → Create instance**。
2. 設定名稱，例如 `miracle-nikki-bot`。
3. 選擇符合 Free Tier 的 US region 與可用 zone。
4. 在 **Machine configuration** 選擇：
   - Series：E2
   - Machine type：`e2-micro`
   - Provisioning model：**Standard**；不要選 Spot。
5. 在 **OS and storage → Change** 選擇：
   - Operating system：Ubuntu
   - Version：Ubuntu 24.04 LTS
   - Boot disk type：`pd-standard`
   - Size：20 GB
6. Networking 保持預設 network 即可；不要勾選 Allow HTTP traffic 或 Allow HTTPS traffic。
7. 不建立或保留 static external IP。若 Console 自動配置 ephemeral external IPv4，請在費用頁面確認其計價影響。
8. 建立 VM，並使用 Console 的 **SSH** 按鈕連線。

## 3. 可選：使用 gcloud 建立 VM

以下命令須在已登入、已選定專案的 Cloud Shell 或本機 Google Cloud CLI 中執行。請自行替換變數，並先確認 zone 屬於當前 Free Tier eligible region。

```bash
export PROJECT_ID="your-project-id"
export ZONE="us-west1-b"
export VM_NAME="miracle-nikki-bot"

gcloud config set project "$PROJECT_ID"

gcloud compute instances create "$VM_NAME" \
  --zone="$ZONE" \
  --machine-type=e2-micro \
  --provisioning-model=STANDARD \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-type=pd-standard \
  --boot-disk-size=20GB \
  --no-address
```

`--no-address` 會避免建立外部 IP。若使用它，必須改用 IAP、VPN、bastion 或其他已核准的管理方式連線；請依自身 SSH 存取策略選擇。若省略 `--no-address`，Compute Engine 可能配置 ephemeral external IPv4，應確認成本與安全風險。

## 4. VM 初始系統設定

連入 VM 後，以具 sudo 權限的管理帳號執行：

```bash
sudo apt update
sudo apt install -y git python3-venv sqlite3

sudo useradd --system --create-home --home-dir /home/miraclebot --shell /bin/bash miraclebot
sudo install -d -o miraclebot -g miraclebot /opt/miracle-nikki-bot
```

不要以 root 執行 Bot。`miraclebot` 僅應擁有其應用程式目錄與 SQLite state 檔案。

## 5. Private GitHub Repository：唯讀 deploy key

在 VM 上以 `miraclebot` 建立專用 key：

```bash
sudo -u miraclebot ssh-keygen -t ed25519 -C "miracle-nikki-bot-gce" \
  -f /home/miraclebot/.ssh/id_ed25519 -N ""
sudo -u miraclebot cat /home/miraclebot/.ssh/id_ed25519.pub
```

將輸出的**公開金鑰**加入 GitHub private repository：

1. Repository → **Settings → Deploy keys → Add deploy key**。
2. 貼上 public key。
3. 保持 read-only；不要勾選 write access。

接著以 `miraclebot` clone repository：

```bash
sudo -u miraclebot git clone git@github.com:OWNER/REPOSITORY.git /opt/miracle-nikki-bot
```

第一次 SSH 連線若要求確認 GitHub host key，應先依 GitHub 官方文件驗證 fingerprint。不要把個人 access token 寫入 remote URL、shell history、`.env` 或 systemd service。

## 6. Python venv 與相依套件

```bash
sudo -u miraclebot bash -lc '
  cd /opt/miracle-nikki-bot
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
'
```

`requirements.txt` 目前保留 Playwright Python package，原因是 legacy Facebook archive 模組仍可被 import。現役 Official Announcement Pipeline 不會啟動 Facebook crawler，因此不需要執行 `playwright install`，也不需要安裝瀏覽器。

可在不啟動 Bot 的前提下驗證：

```bash
sudo -u miraclebot bash -lc '
  cd /opt/miracle-nikki-bot
  .venv/bin/python -m pytest -q --basetemp=.pytest-runtime
'
```

## 7. `.env` 位置與必要設定

應由管理者手動建立：

```text
/opt/miracle-nikki-bot/.env
```

可參考 `.env.example`，但不要提交或分享實際 `.env`。設定完成後限制權限：

```bash
sudo chown miraclebot:miraclebot /opt/miracle-nikki-bot/.env
sudo chmod 600 /opt/miracle-nikki-bot/.env
```

現役 pipeline 至少需要：

```dotenv
DISCORD_TOKEN=replace-with-the-real-token-locally
TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=111111111111111111
CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=222222222222222222
```

- `DISCORD_TOKEN`：Discord Bot token。
- `TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS`：台服官網公告頻道，可填逗號分隔的多個 ID。
- `CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS`：陸服官網公告頻道，可填逗號分隔的多個 ID。

不要使用示例 ID，也不要將真實 token 或 channel ID 寫入 Git。

## 8. 第一次部署：初始化 Official Baseline

在啟動 service 前，以 `miraclebot` 執行：

```bash
sudo -u miraclebot bash -lc '
  cd /opt/miracle-nikki-bot
  .venv/bin/python scripts/announcement/initialize_official_baseline.py --dry-run
  .venv/bin/python scripts/announcement/initialize_official_baseline.py
'
```

Dry-run 應列出台服與陸服最新公告。正式指令只將兩個 external ID 寫入 `database/announcement_state.db`：

- 不建立 Announcement。
- 不建立 Pending Delivery。
- 不發送 Discord。
- 不讀寫 legacy `database/database.db`。

完成後不要重複執行 baseline 初始化；它代表「目前已知最新公告」，重跑可能跳過停機期間尚未送出的新公告。

## 9. systemd service

由管理者建立 `/etc/systemd/system/miracle-nikki-bot.service`：

```ini
[Unit]
Description=Miracle Nikki Official Announcement Bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=miraclebot
Group=miraclebot
WorkingDirectory=/opt/miracle-nikki-bot
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONUTF8=1
Environment=PYTHONIOENCODING=utf-8
ExecStart=/opt/miracle-nikki-bot/.venv/bin/python bot/main.py
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

啟用並啟動：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now miracle-nikki-bot
sudo systemctl status miracle-nikki-bot --no-pager
```

service 只由 Bot 自己從專案根目錄讀取 `.env`；不需要將 token 寫入 systemd unit。

## 10. 狀態、日誌與重啟

```bash
# service 狀態
sudo systemctl status miracle-nikki-bot --no-pager

# 即時日誌
sudo journalctl -u miracle-nikki-bot -f

# 最近 200 行
sudo journalctl -u miracle-nikki-bot -n 200 --no-pager

# 本次開機後的日誌
sudo journalctl -u miracle-nikki-bot -b --no-pager

# 重啟
sudo systemctl restart miracle-nikki-bot

# 停止
sudo systemctl stop miracle-nikki-bot
```

故障排查順序：

1. `systemctl status` 確認 process 是否存活。
2. `journalctl` 檢查 Discord token、網路、官方網站抓取或 SQLite 錯誤。
3. 確認 `/opt/miracle-nikki-bot/.env` 的 owner 為 `miraclebot`、權限為 `600`。
4. 確認 `database/` 可由 `miraclebot` 寫入。
5. 不要為了解決啟動問題而執行 legacy rebuild、reset、Facebook crawler 或 Knowledge scripts。

## 11. Replay 驗證

Replay 只建立或重設**明確指定頻道**的 pending delivery；它不直接送 Discord，實際送達仍由已啟動的 Dispatcher worker 處理。

```bash
sudo -u miraclebot bash -lc '
  cd /opt/miracle-nikki-bot
  .venv/bin/python scripts/announcement/replay_latest_official.py \
    --source cn \
    --external-id 988639 \
    --channel-id YOUR_TEST_CHANNEL_ID \
    --replay
'
```

先以 dry-run 驗證資料，不變更 state：

```bash
sudo -u miraclebot bash -lc '
  cd /opt/miracle-nikki-bot
  .venv/bin/python scripts/announcement/replay_latest_official.py \
    --source tw --dry-run
'
```

## 12. 更新流程

更新前先停止 service，避免 SQLite 與程式碼同時變更：

```bash
sudo systemctl stop miracle-nikki-bot

sudo -u miraclebot bash -lc '
  cd /opt/miracle-nikki-bot
  git pull --ff-only
  .venv/bin/python -m pip install -r requirements.txt
'

sudo systemctl start miracle-nikki-bot
sudo systemctl status miracle-nikki-bot --no-pager
```

更新不需要重新初始化 official baseline。Bot 停機期間出現的新公告應由既有 baseline 與 poller 在恢復後正常處理。

## 13. SQLite 備份

現役資料庫是：

```text
/opt/miracle-nikki-bot/database/announcement_state.db
```

使用 SQLite 的 online backup 指令建立一致備份，不要只在 WAL 模式下直接複製單一 `.db` 檔：

```bash
sudo install -d -o miraclebot -g miraclebot /var/backups/miracle-nikki-bot
sudo -u miraclebot sqlite3 /opt/miracle-nikki-bot/database/announcement_state.db \
  ".backup '/var/backups/miracle-nikki-bot/announcement_state-$(date +%F-%H%M%S).db'"
```

本文件不建立 timer、自動備份或 CI/CD。備份保留週期與異地保存策略需由管理者另行決定。

## 14. Fresh Deployment 驗收清單

在全新的 Ubuntu 24.04 VM 上，確認：

1. `git clone` 可透過唯讀 deploy key 完成。
2. `.venv/bin/python -m pip install -r requirements.txt` 成功。
3. 不需要 Windows 路徑、Conda、Facebook storage state 或 Playwright browser。
4. `.env` 僅存在 VM 本機，權限為 `600`。
5. Baseline dry-run 與正式初始化成功，沒有建立 delivery 或 Discord 訊息。
6. `systemctl enable --now miracle-nikki-bot` 成功。
7. `journalctl` 顯示台服與陸服 poller 正常運作。
8. 沒有 legacy Facebook、Knowledge、Parser 或舊 Queue 背景工作被啟動。
9. State 僅寫入 `database/announcement_state.db`，未修改舊 `database/database.db`。
