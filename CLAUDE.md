# 股票儀表板專案交接文件

## 專案概述
Flask + Bootstrap 5 + Plotly 的台股技術分析儀表板。
- **後端**：`app.py`（Flask API）
- **前端**：`templates/index.html`（所有 JS 內嵌）
- **選股引擎**：`analyze.py`（每日手動執行）
- **伺服器**：`python3 app.py`，預設 `http://localhost:5000`
- **資料來源**：FinMind（台股）+ yfinance（美股/指數）

---

## 目錄結構
```
stock/
├── app.py                  # Flask 後端，所有 API
├── analyze.py              # 每日技術選股引擎（手動跑）
├── watchlist.txt           # 自選股清單（# 開頭為題材分類）
├── ai_recommend.json       # analyze.py 輸出結果（前端讀取）
├── templates/index.html    # 單頁前端（Bootstrap+Plotly，JS全內嵌）
├── static/css/style.css    # Liquid Glass 深色主題
├── requirements.txt
└── .env                    # FINMIND_TOKEN=xxx（選填）
```

---

## 已完成功能

### 儀表板首頁
- 市場指數卡片：加權、櫃買、道瓊、S&P500、那斯達克、VIX、美元/台幣、日圓/台幣
- VIX 恐慌河流圖（1年歷史）
- 點擊指數卡片 → K線 Modal（7日/1月/3月/半年/1年）

### 個股搜尋（FinMind 全市場）
- Navbar 搜尋框輸入代號或名稱
- 點選結果 → 個股 Modal，包含三個 Tab：
  1. **K線＋技術指標**：4格 Plotly 圖（K線+MA → 三大法人 → MACD → KD），高度 720px
  2. **籌碼面**：融資融券餘額 + 三大法人累積淨買超
  3. **月營收**：柱狀圖
- 若該股在 `ai_recommend.json` 有訊號，Modal 標題旁顯示閃爍徽章（即將反彈🟢/轉強訊號🔵/強勢持續🟡）

### 本日技術選股（Navbar 按鈕）
- 讀取 `ai_recommend.json`，顯示三類：即將反彈 / 轉強訊號 / 強勢持續
- 每張股票卡顯示：股票代號、名稱、題材標籤、訊號標籤、漲跌幅
- **詳細報告按鈕**：展開 8 節結構化分析（市場狀態/趨勢/動能/量價/支撐壓力/風險/回測/操作建議）
- 點擊股票卡 → 跳入個股 Modal

---

## API 端點（app.py）

| 端點 | 說明 |
|------|------|
| `GET /` | 首頁 |
| `GET /api/dashboard` | 所有指數即時報價 |
| `GET /api/market_detail?id=taiex&days=60` | 指數 K 線資料 |
| `GET /api/vix_history` | VIX 1年歷史 |
| `GET /api/stock_search?q=台積電` | 個股搜尋 |
| `GET /api/stock_kline?id=2330&days=60` | 個股 K線+MA+MACD+KD |
| `GET /api/stock_fundamentals?id=2330` | PER/PBR/殖利率/月營收/三大法人 |
| `GET /api/stock_margin?id=2330&days=60` | 融資融券餘額 |
| `GET /api/ai_recommend` | 讀取 ai_recommend.json |

---

## analyze.py 技術選股邏輯

### 執行方式
```bash
cd ~/Desktop/stock && python3 analyze.py
```
掃 `watchlist.txt` 所有股票（目前 35 支），約 40 秒完成。

### 技術指標
MA5/10/20/60/120、MACD(12,26,9)、KD(9)、RSI(14)、ATR(14)、  
布林通道(20,2)、HV20（歷史波動率）、OBV、ROC(10)、Vol Ratio

### 市場狀態分類（8種）
`classify_market_state(df)` 依序判斷：
高波動 → 低波動 → 突破 → 跌破 → 反轉 → 上升/下降趨勢 → 盤整

### 評分門檻
- `score_rebound` / `score_turning` / `score_strong` 各自回傳 (score, signals)
- **THRESHOLD = 5**，達標才進入對應類別
- ATR > 5% 自動扣 1 分（高波動品質門檻）

### 操作建議邏輯（6選1）
`determine_operation()` 決策樹：
- 高波動 → 停止交易
- 跌破 → 分批出場
- 下降趨勢 → 觀察/停止交易
- 上升/突破 + score≥8 + 回測OK + 量比≥1.3 → 分批進場
- 其他有訊號 → 等待確認
- 預設 → 觀察

### 走前回測（Walk-Forward）
- 前 60% 為 context 期，後 40% 為 test 期
- 進場：依市場狀態選擇 MACD/KD 交叉訊號
- 出場：止損 2ATR / 止盈 3ATR / MA20跌破 / 最長持有 20 日
- 輸出：勝率、平均報酬、RR、PF、最大回撤、Sharpe、Expectancy、交易次數、平均持有日

---

## 前端 JS 關鍵變數（index.html）

```javascript
_signalMap     // {stock_id: {name,color,icon,id}} 頁面載入時從 /api/ai_recommend 預取
_instDataCache // 個股三大法人資料快取
_chipLoaded    // 籌碼面 tab 是否已載入
curStock       // 目前開啟的個股代號
curSdays       // 目前個股 K 線天數
```

### 主要函式
- `loadDashboard()` — 載入首頁指數
- `renderKline(cid, kd, accent)` — 指數 K 線（2格：K線+MA）
- `renderStockCombined(cid, kd, instData, accent)` — 個股 4 格圖（K線/三大法人/MACD/KD）
- `openStockModal(sid)` — 開啟個股 Modal，自動顯示訊號徽章
- `loadChipData(sid)` — 籌碼面資料（融資券 + 三大法人累積）
- `toggleReport(uid, btn)` — 展開/收起詳細報告面板

---

## watchlist.txt 格式
```
# 題材名稱（自動成為 theme 欄位）
2330
2317
# 另一個題材
6285
```

---

## 常見操作

### 新增自選股
編輯 `watchlist.txt`，加入代號，再跑 `python3 analyze.py`

### 調整選股門檻
`analyze.py` 第 `THRESHOLD = 5` 那行，數字越高越嚴格

### 手機存取
Mac 與手機同一 WiFi，手機瀏覽器輸入 `http://192.168.0.202:5000`

### 重啟伺服器
```bash
pkill -f "python3 app.py"
cd ~/Desktop/stock && python3 app.py
```

---

## 已知問題 / 待辦

- `3273 神準`：FinMind 代碼可能有誤，回傳無資料，需確認正確代碼
- `3587`：FinMind 顯示為「閎康」（半導體測試），原本想放光通訊的「光環」，代碼待查正
- `analyze.py` THRESHOLD 目前設 5，可依市場情況調整（牛市可降至 4，震盪市可升至 6）
- 回測樣本量偏少（只有 40-50 日測試期），Sharpe / Expectancy 僅供方向參考，不宜過度依賴
