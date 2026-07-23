# 本機開發指南

## 本機與雲端的分工

| 環境 | 用途 |
|---|---|
| 本機開發環境 | 修改程式、執行 pytest、使用測試 Discord Bot 與測試頻道驗證公告呈現 |
| Google Cloud VM | 使用正式 Discord Bot token 常駐執行官方公告 poller 與 delivery worker |

不要在本機與正式 VM 同時以**同一個正式 Discord Bot Token**啟動 Bot。這會造成重複連線、難以判讀日誌與公告送達風險。

本機測試應使用另一個 Discord application / Bot token 與獨立測試頻道。Token 只保存在本機 `.env`，不得提交。

## Python 虛擬環境

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

`requirements.txt` 是目前相依套件的唯一來源。雖然它仍包含 Playwright Python package，現役官方公告 crawler 不需要 browser；不要為現役公告流程自行執行 Facebook login 或 `playwright install`。

## 本機 `.env`

以 `.env.example` 為範本建立未追蹤的 `.env`：

```dotenv
APP_ENV=development
DISCORD_TOKEN=TEST_BOT_TOKEN_ONLY
GUILD_ID=TEST_GUILD_ID
TW_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=TEST_TW_CHANNEL_ID
CN_OFFICIAL_ANNOUNCEMENT_CHANNEL_IDS=TEST_CN_CHANNEL_ID
ENABLE_ANNOUNCEMENT_PIPELINE=false
```

`GUILD_ID` 設定後，Slash Commands 僅同步到該測試 Guild，不會修改全域指令。Production VM 可留空，維持既有全域同步行為。

本機只測試 Discord UI、Slash Commands、查詢或管理功能時，設定 `ENABLE_ANNOUNCEMENT_PIPELINE=false`。Bot 仍會登入 Discord 並同步指令，但不會初始化公告 state、輪詢官網、建立 delivery 或發送公告。需要驗證公告同步時才改為 `true`。

只填入測試 token、Guild 與測試頻道。不得提交 `.env`、token、Guild／channel ID、外部 IP、deploy key、SQLite database 或 backup。

## 測試

執行完整測試：

```powershell
python -m pytest -q --basetemp=.pytest-runtime
```

Windows 終端若遇到 Unicode 輸出問題，可設定：

```powershell
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
python -m pytest -q --basetemp=.pytest-runtime
```

執行前不要啟動正式 Bot；測試不應發送真實 Discord 公告。

## 本機測試官方公告功能

### Baseline

使用新的本機 `announcement_state.db` 前，先確認與初始化 baseline：

```powershell
python scripts/announcement/initialize_official_baseline.py --dry-run
python scripts/announcement/initialize_official_baseline.py
```

不要在已有有效 baseline 的測試 state 上反覆執行正式初始化，否則會更新 baseline。

### Replay

先使用 dry-run 檢查抓取結果：

```powershell
python scripts/announcement/replay_latest_official.py --source tw --dry-run
python scripts/announcement/replay_latest_official.py --source cn --external-id 988639 --dry-run
```

以明確測試頻道建立 replay delivery：

```powershell
python scripts/announcement/replay_latest_official.py `
  --source cn `
  --external-id 988639 `
  --channel-id YOUR_TEST_CHANNEL_ID `
  --replay
```

Replay 不直接發送 Discord。要驗證 Dispatcher，使用測試 token 啟動本機 Bot，並確認 delivery 僅建立在測試 channel。

### 啟動測試 Bot

```powershell
python bot/main.py
```

確認 `.env` 僅使用測試 token、測試頻道後再執行。停止時使用 `Ctrl+C`。

## Git 提交流程

提交前至少執行測試與檢查工作目錄：

```powershell
python -m pytest -q --basetemp=.pytest-runtime
git status --short
git diff --check
```

確認不包含 `.env`、SQLite database、backup、Token、IP 或 deploy key 後：

```powershell
git add <intended-files>
git commit -m "Describe the change"
git push
```

不要以 `git add .` 取代檢查；先確認 staged 檔案只包含預期修改。

## 雲端更新

雲端只負責使用正式 token 長期運行。更新前在本機完成測試並 push，之後連線 VM：

```bash
ssh miracle-nikki-bot
sudo systemctl stop miracle-nikki-bot
cd /opt/miracle-nikki-bot
git pull --ff-only

# requirements.txt 有變更時才需要；重複執行也安全。
/opt/miracle-nikki-bot/.venv/bin/python -m pip install -r requirements.txt

sudo systemctl start miracle-nikki-bot
sudo systemctl status miracle-nikki-bot --no-pager
```

不要因為更新而重跑 `initialize_official_baseline.py`，也不要在正式 VM 執行 legacy rebuild、reset、Facebook crawler、Parser 或 Knowledge scripts。

部署與日常維運細節見 [DEPLOY.md](DEPLOY.md)。
