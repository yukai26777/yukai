# 股票分析與回測 POC

以 Flask + Bootstrap 5 + jQuery + Plotly 建置的單頁股票技術分析與策略回測示範專案。

---

## 功能

| 功能 | 說明 |
|------|------|
| 技術指標 | 現價、MA20、MA50、RSI(14)、成交量 |
| K 線圖 | Plotly 互動式 K 線 + 均線疊加 |
| 策略回測 | 移動平均交叉策略（MA Crossover） |
| 績效指標 | 總收益率、年化收益率、夏普比率、最大回撤、勝率 |
| 權益曲線 | 每日淨值走勢圖 |

---

## 快速開始

### 1. 建立虛擬環境（建議）

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 2. 安裝依賴

```bash
pip install -r requirements.txt
```

### 3. 啟動伺服器

```bash
python app.py
```

### 4. 開啟瀏覽器

```
http://127.0.0.1:5000
```

---

## 使用說明

1. **股票代碼**
   - 台股加 `.TW`，例如：`2330.TW`（台積電）、`2317.TW`（鴻海）
   - 美股直接輸入：`AAPL`、`TSLA`、`MSFT`
2. **設定日期範圍**，點擊「取得資料」
3. 查看技術指標與 K 線圖
4. 調整均線視窗參數，點擊「執行回測」查看績效

---

## 專案結構

```
stock_poc/
├── app.py                  # Flask 後端 + API
├── requirements.txt
├── README.md
├── templates/
│   └── index.html          # 單頁前端（Bootstrap 5）
└── static/
    ├── css/style.css       # 自訂樣式
    └── js/main.js          # jQuery 事件流程
```

---

## API 說明

### `GET /api/strategies`
回傳支援的策略清單。

### `POST /api/fetch_data`
```json
{ "symbol": "2330.TW", "start_date": "2024-01-01", "end_date": "2025-01-01" }
```

### `POST /api/backtest`
```json
{
  "symbol": "2330.TW",
  "start_date": "2024-01-01",
  "end_date": "2025-01-01",
  "strategy": "ma",
  "params": { "short_window": 10, "long_window": 30 }
}
```

---

## 注意事項

- 本專案為 POC 示範，回測不含滑點與手續費
- 資料來源為 Yahoo Finance（`yfinance`），需要網路連線
- **本專案不構成任何投資建議**

---

## 環境需求

- Python 3.10+
- 網路連線（下載股票資料）
