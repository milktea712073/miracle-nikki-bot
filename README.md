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

## 專案結構

```text
crawler/   資料爬取程式
database/  資料庫模型與存取層
bot/       機器人應用程式
docs/      專案文件
```
