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

## 本機敏感資料

`database/database.db`、其 `-wal`／`-shm` 執行期檔案、Facebook storage state/profile，以及登入後產生的 Facebook debug HTML 都只應保留在本機，不應公開分享或提交到 Git。

## 專案結構

```text
crawler/   資料爬取程式
database/  資料庫模型與存取層
bot/       機器人應用程式
docs/      專案文件
```
