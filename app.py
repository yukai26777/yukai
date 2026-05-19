import os
import time
from datetime import datetime, timedelta
from functools import wraps

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from FinMind.data import DataLoader

load_dotenv()

app = Flask(__name__)

# ── FinMind client ──────────────────────────────────────────────────────────

_dl: DataLoader | None = None

def get_dl() -> DataLoader:
    global _dl
    if _dl is None:
        _dl = DataLoader()
        token = os.getenv("FINMIND_TOKEN", "")
        if token:
            _dl.login_by_token(api_token=token)
    return _dl


# ── Simple TTL cache ─────────────────────────────────────────────────────────

_cache: dict = {}

def cached(ttl: int = 300):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = fn.__name__ + str(args) + str(kwargs)
            if key in _cache:
                ts, val = _cache[key]
                if time.time() - ts < ttl:
                    return val
            val = fn(*args, **kwargs)
            _cache[key] = (time.time(), val)
            return val
        return wrapper
    return decorator


# ── Helpers ──────────────────────────────────────────────────────────────────

def _start(days: int) -> str:
    return (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")


@cached(ttl=300)
def _fetch_yf(symbol: str) -> dict | None:
    try:
        df = yf.download(symbol, period="7d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if len(df) < 1:
            return None
        today = float(df["Close"].iloc[-1])
        prev  = float(df["Close"].iloc[-2]) if len(df) > 1 else today
        chg   = today - prev
        return {"price": round(today, 4), "change": round(chg, 4),
                "change_pct": round(chg / prev * 100, 2) if prev else 0}
    except Exception as e:
        print(f"[yf quote {symbol}] {e}")
        return None


@cached(ttl=300)
def _fetch_finmind_total_return(index_id: str) -> dict | None:
    """加權/櫃買報酬指數 — used only as fallback when yfinance has no data."""
    try:
        dl = get_dl()
        df = dl.taiwan_stock_total_return_index(index_id=index_id, start_date=_start(20))
        if df.empty:
            return None
        df = df.sort_values("date")
        latest = float(df["price"].iloc[-1])
        prev   = float(df["price"].iloc[-2]) if len(df) > 1 else latest
        chg    = latest - prev
        return {"price": round(latest, 2), "change": round(chg, 2),
                "change_pct": round(chg / prev * 100, 2) if prev else 0,
                "note": "報酬指數"}
    except Exception as e:
        print(f"[finmind total return {index_id}] {e}")
        return None


@cached(ttl=600)
def _fetch_yf_kline(symbol: str, days: int) -> list:
    try:
        df = yf.download(symbol, period="2y", progress=False, auto_adjust=True)
        if df.empty:
            return []
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        df = df[df["Close"] > 0]
        df = df.tail(days)
        df["MA5"]  = df["Close"].rolling(5).mean()
        df["MA10"] = df["Close"].rolling(10).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA60"] = df["Close"].rolling(60).mean()
        result = []
        for date, row in df.iterrows():
            result.append({
                "date": date.strftime("%Y-%m-%d"),
                "o": round(float(row["Open"]),  2),
                "h": round(float(row["High"]),  2),
                "l": round(float(row["Low"]),   2),
                "c": round(float(row["Close"]), 2),
                "ma5":  round(float(row["MA5"]),  2) if pd.notna(row["MA5"])  else None,
                "ma10": round(float(row["MA10"]), 2) if pd.notna(row["MA10"]) else None,
                "ma20": round(float(row["MA20"]), 2) if pd.notna(row["MA20"]) else None,
                "ma60": round(float(row["MA60"]), 2) if pd.notna(row["MA60"]) else None,
            })
        return result
    except Exception as e:
        print(f"[yf kline {symbol}] {e}")
        return []


@cached(ttl=600)
def _fetch_finmind_kline(index_id: str, days: int) -> list:
    """Line chart data (close only) from FinMind total return index."""
    try:
        dl = get_dl()
        df = dl.taiwan_stock_total_return_index(index_id=index_id, start_date=_start(days + 30))
        if df.empty:
            return []
        df = df.sort_values("date").tail(days)
        df["MA5"]  = df["price"].rolling(5).mean()
        df["MA10"] = df["price"].rolling(10).mean()
        df["MA20"] = df["price"].rolling(20).mean()
        df["MA60"] = df["price"].rolling(60).mean()
        result = []
        for _, row in df.iterrows():
            p = round(float(row["price"]), 2)
            result.append({
                "date": str(row["date"])[:10],
                "o": p, "h": p, "l": p, "c": p,
                "ma5":  round(float(row["MA5"]),  2) if pd.notna(row["MA5"])  else None,
                "ma10": round(float(row["MA10"]), 2) if pd.notna(row["MA10"]) else None,
                "ma20": round(float(row["MA20"]), 2) if pd.notna(row["MA20"]) else None,
                "ma60": round(float(row["MA60"]), 2) if pd.notna(row["MA60"]) else None,
            })
        return result
    except Exception as e:
        print(f"[finmind kline {index_id}] {e}")
        return []


# Stock info cache
_stock_info_cache: dict | None = None
_stock_info_ts: float = 0

def get_stock_info() -> pd.DataFrame:
    global _stock_info_cache, _stock_info_ts
    if _stock_info_cache is None or time.time() - _stock_info_ts > 3600:
        try:
            df = get_dl().taiwan_stock_info()
            _stock_info_cache = df
            _stock_info_ts = time.time()
        except Exception as e:
            print(f"[stock info] {e}")
            return pd.DataFrame()
    return _stock_info_cache


# ── Market config ─────────────────────────────────────────────────────────────

MARKETS = {
    "taiex":  {"name": "加權指數",       "src": "yf",      "yf_sym": "^TWII",    "fm_id": None},
    "tpex":   {"name": "櫃買指數",       "src": "finmind", "yf_sym": None,        "fm_id": "TPEx"},
    "dji":    {"name": "道瓊指數",       "src": "yf",      "yf_sym": "^DJI",     "fm_id": None},
    "spx":    {"name": "S&P 500",        "src": "yf",      "yf_sym": "^GSPC",    "fm_id": None},
    "ixic":   {"name": "那斯達克",       "src": "yf",      "yf_sym": "^IXIC",    "fm_id": None},
    "vix":    {"name": "VIX 恐慌指數",   "src": "yf",      "yf_sym": "^VIX",     "fm_id": None},
    "usdtwd": {"name": "美元／台幣",     "src": "yf",      "yf_sym": "TWD=X",    "fm_id": None},
    "jpytwd": {"name": "日圓／台幣",     "src": "cross",   "yf_sym": None,       "fm_id": None},
    "gold":   {"name": "黃金",           "src": "yf",      "yf_sym": "GC=F",     "fm_id": None},
    "brent":  {"name": "布蘭特原油",     "src": "yf",      "yf_sym": "BZ=F",     "fm_id": None},
}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/dashboard")
def dashboard():
    result = {}
    for key, m in MARKETS.items():
        if m["src"] == "yf":
            result[key] = _fetch_yf(m["yf_sym"])
        elif m["src"] == "finmind":
            result[key] = _fetch_finmind_total_return(m["fm_id"])
        elif m["src"] == "cross" and key == "jpytwd":
            # Compute JPY/TWD from USD cross rates
            try:
                twd = _fetch_yf("TWD=X")
                jpy = _fetch_yf("USDJPY=X")
                if twd and jpy and jpy["price"] > 0:
                    price = round(twd["price"] / jpy["price"], 5)
                    prev_price = round((twd["price"] - twd["change"]) / (jpy["price"] - jpy["change"]), 5) if jpy["price"] != jpy["change"] else price
                    chg = round(price - prev_price, 5)
                    result[key] = {"price": price, "change": chg, "change_pct": round(chg/prev_price*100, 2) if prev_price else 0}
                else:
                    result[key] = None
            except Exception as e:
                print(f"[jpytwd dashboard] {e}")
                result[key] = None
    return jsonify({"success": True, "data": result})


@cached(ttl=600)
def _compute_jpytwd_kline(days: int) -> list:
    """Compute JPY/TWD daily OHLC from USD cross rates."""
    try:
        twd_klines = _fetch_yf_kline("TWD=X", days + 30)
        jpy_klines = _fetch_yf_kline("USDJPY=X", days + 30)
        if not twd_klines or not jpy_klines:
            return []
        twd_d = {d["date"]: d for d in twd_klines}
        jpy_d = {d["date"]: d for d in jpy_klines}
        common = sorted(set(twd_d.keys()) & set(jpy_d.keys()))
        result = []
        for date in common:
            t, j = twd_d[date], jpy_d[date]
            jc = j["c"]
            if jc <= 0:
                continue
            entry = {
                "date": date,
                "o": round(t["o"] / jc, 5),
                "h": round(t["h"] / jc, 5),
                "l": round(t["l"] / jc, 5),
                "c": round(t["c"] / jc, 5),
            }
            result.append(entry)
        result = result[-days:]
        # Compute MAs
        closes = [d["c"] for d in result]
        for i, d in enumerate(result):
            for w, key in [(5, "ma5"), (10, "ma10"), (20, "ma20"), (60, "ma60")]:
                if i >= w - 1:
                    d[key] = round(sum(closes[i - w + 1:i + 1]) / w, 5)
                else:
                    d[key] = None
        return result
    except Exception as e:
        print(f"[jpytwd kline] {e}")
        return []


@app.route("/api/market_detail")
def market_detail():
    market_id = request.args.get("id", "taiex")
    try:
        days = int(request.args.get("days", 60))
    except Exception:
        days = 60

    m = MARKETS.get(market_id)
    if not m:
        return jsonify({"success": False, "error": "unknown market"})

    if m["src"] == "yf" and m["yf_sym"]:
        k_data = _fetch_yf_kline(m["yf_sym"], days)
    elif m["src"] == "finmind" and m["fm_id"]:
        k_data = _fetch_finmind_kline(m["fm_id"], days)
    elif m["src"] == "cross" and market_id == "jpytwd":
        k_data = _compute_jpytwd_kline(days)
    else:
        k_data = []

    if not k_data:
        return jsonify({"success": False, "error": "no data"})
    return jsonify({"success": True, "name": m["name"], "k_data": k_data})


@app.route("/api/vix_history")
@cached(ttl=3600)
def vix_history():
    try:
        df = yf.download("^VIX", period="1y", progress=False, auto_adjust=True)
        if df.empty:
            return jsonify({"success": False})
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        data = [{"date": d.strftime("%Y-%m-%d"), "vix": round(float(v), 2)}
                for d, v in zip(df.index, df["Close"])]
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stock_search")
def stock_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"success": True, "results": []})
    df = get_stock_info()
    if df.empty:
        return jsonify({"success": False, "error": "無法載入股票清單"})
    mask = df["stock_id"].str.contains(q, case=False) | df["stock_name"].str.contains(q, case=False, na=False)
    hits = df[mask][["stock_id", "stock_name", "industry_category", "type"]].drop_duplicates("stock_id").head(20)
    return jsonify({"success": True, "results": hits.to_dict(orient="records")})


@app.route("/api/stock_kline")
def stock_kline():
    sid = request.args.get("id", "")
    try:
        days = int(request.args.get("days", 60))
    except Exception:
        days = 60
    if not sid:
        return jsonify({"success": False, "error": "missing id"})
    data = _get_stock_kline(sid, days)
    if not data:
        return jsonify({"success": False, "error": "no data"})
    return jsonify({"success": True, "k_data": data})


@cached(ttl=600)
def _get_stock_kline(sid: str, days: int) -> list:
    try:
        dl = get_dl()
        today = datetime.today().strftime("%Y-%m-%d")
        df = dl.taiwan_stock_daily(stock_id=sid, start_date=_start(days + 150), end_date=today)
        if df.empty:
            return []
        df = df.sort_values("date")

        # MA
        df["MA5"]  = df["close"].rolling(5).mean()
        df["MA10"] = df["close"].rolling(10).mean()
        df["MA20"] = df["close"].rolling(20).mean()
        df["MA60"] = df["close"].rolling(60).mean()

        # MACD (12, 26, 9)
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        df["MACD"]   = ema12 - ema26
        df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["Hist"]   = df["MACD"] - df["Signal"]

        # KD Stochastic (period=9, init=50)
        low_min  = df["min"].rolling(9).min()
        high_max = df["max"].rolling(9).max()
        denom = high_max - low_min
        rsv = ((df["close"] - low_min) / denom * 100).where(denom > 0, 50).fillna(50)
        K_vals, D_vals, kp, dp = [], [], 50.0, 50.0
        for rv in rsv:
            kp = 2/3 * kp + 1/3 * float(rv)
            dp = 2/3 * dp + 1/3 * kp
            K_vals.append(round(kp, 1))
            D_vals.append(round(dp, 1))
        df["K_val"] = K_vals
        df["D_val"] = D_vals

        df = df.tail(days)
        result = []
        for _, row in df.iterrows():
            result.append({
                "date": str(row["date"])[:10],
                "o":  round(float(row["open"]),  2),
                "h":  round(float(row["max"]),   2),
                "l":  round(float(row["min"]),   2),
                "c":  round(float(row["close"]), 2),
                "v":  int(row.get("Trading_Volume", 0)),
                "ma5":    round(float(row["MA5"]),  2) if pd.notna(row["MA5"])  else None,
                "ma10":   round(float(row["MA10"]), 2) if pd.notna(row["MA10"]) else None,
                "ma20":   round(float(row["MA20"]), 2) if pd.notna(row["MA20"]) else None,
                "ma60":   round(float(row["MA60"]), 2) if pd.notna(row["MA60"]) else None,
                "macd":   round(float(row["MACD"]),   2) if pd.notna(row["MACD"])   else None,
                "signal": round(float(row["Signal"]), 2) if pd.notna(row["Signal"]) else None,
                "hist":   round(float(row["Hist"]),   2) if pd.notna(row["Hist"])   else None,
                "k":      round(float(row["K_val"]), 1),
                "d":      round(float(row["D_val"]), 1),
            })
        return result
    except Exception as e:
        print(f"[stock kline {sid}] {e}")
        return []


@app.route("/api/stock_fundamentals")
def stock_fundamentals():
    sid = request.args.get("id", "")
    if not sid:
        return jsonify({"success": False, "error": "missing id"})

    dl = get_dl()
    result = {"stock_id": sid}

    # Basic info
    info_df = get_stock_info()
    if not info_df.empty:
        row = info_df[info_df["stock_id"] == sid]
        if not row.empty:
            result["name"]     = row.iloc[0]["stock_name"]
            result["industry"] = row.iloc[0]["industry_category"]
            result["market"]   = "上市" if row.iloc[0]["type"] == "twse" else "上櫃"

    # PE / PBR / 殖利率 (last 90 days)
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        per_df = dl.taiwan_stock_per_pbr(stock_id=sid, start_date=_start(90), end_date=today)
        if not per_df.empty:
            per_df = per_df.sort_values("date")
            latest = per_df.iloc[-1]
            result["per"]            = round(float(latest["PER"]), 2) if pd.notna(latest["PER"]) else None
            result["pbr"]            = round(float(latest["PBR"]), 2) if pd.notna(latest["PBR"]) else None
            result["dividend_yield"] = round(float(latest["dividend_yield"]), 2) if pd.notna(latest["dividend_yield"]) else None
            # Latest price from daily
            price_df = dl.taiwan_stock_daily(stock_id=sid, start_date=_start(7), end_date=today)
            if not price_df.empty:
                result["price"] = round(float(price_df.sort_values("date").iloc[-1]["close"]), 2)
            result["per_history"] = [
                {"date": str(r["date"])[:10],
                 "per": round(float(r["PER"]), 2) if pd.notna(r["PER"]) else None,
                 "pbr": round(float(r["PBR"]), 2) if pd.notna(r["PBR"]) else None}
                for _, r in per_df.tail(60).iterrows()
            ]
    except Exception as e:
        print(f"[per_pbr {sid}] {e}")

    # 月營收 (last 13 months)
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        rev_df = dl.taiwan_stock_month_revenue(stock_id=sid, start_date=_start(420), end_date=today)
        if not rev_df.empty:
            rev_df = rev_df.sort_values("date").tail(13)
            result["revenue"] = [
                {"date": f"{int(r['revenue_year'])}/{int(r['revenue_month']):02d}",
                 "revenue": int(r["revenue"])}
                for _, r in rev_df.iterrows()
            ]
    except Exception as e:
        print(f"[revenue {sid}] {e}")

    # 三大法人 (last 20 trading days) — aggregate to 外資/投信/自營商
    NAME_MAP = {
        "Foreign_Investor":    "外資",
        "Foreign_Dealer_Self": "外資",
        "Investment_Trust":    "投信",
        "Dealer_self":         "自營商",
        "Dealer_Hedging":      "自營商",
    }
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        inv_df = dl.taiwan_stock_institutional_investors(stock_id=sid, start_date=_start(45), end_date=today)
        if not inv_df.empty:
            inv_df = inv_df.sort_values("date")
            inv_df["net"]  = inv_df["buy"] - inv_df["sell"]
            inv_df["name"] = inv_df["name"].map(NAME_MAP).fillna("其他")
            pivot = inv_df.pivot_table(index="date", columns="name", values="net", aggfunc="sum").fillna(0)
            pivot = pivot.tail(20)
            cols_order = [c for c in ["外資", "投信", "自營商"] if c in pivot.columns]
            result["institutional"] = {
                "dates": [str(d)[:10] for d in pivot.index],
                "data":  {col: [int(v) for v in pivot[col]] for col in cols_order}
            }
    except Exception as e:
        print(f"[institutional {sid}] {e}")

    return jsonify({"success": True, "data": result})


@app.route("/api/ai_recommend")
def ai_recommend():
    import json
    path = os.path.join(os.path.dirname(__file__), "ai_recommend.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"success": True, "data": data})
    except FileNotFoundError:
        return jsonify({"success": False, "error": "推薦檔案不存在，請聯繫管理員更新。"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stock_margin")
def stock_margin():
    sid = request.args.get("id", "")
    try:
        days = int(request.args.get("days", 60))
    except Exception:
        days = 60
    if not sid:
        return jsonify({"success": False, "error": "missing id"})
    data = _get_stock_margin(sid, days)
    if not data:
        return jsonify({"success": False, "error": "no data"})
    return jsonify({"success": True, "data": data})


@cached(ttl=600)
def _get_stock_margin(sid: str, days: int) -> dict:
    try:
        dl = get_dl()
        today = datetime.today().strftime("%Y-%m-%d")
        df = dl.taiwan_stock_margin_purchase_short_sale(
            stock_id=sid, start_date=_start(days + 30), end_date=today
        )
        if df.empty:
            return {}
        df = df.sort_values("date").tail(days)
        cols = df.columns.tolist()
        margin_col = next((c for c in cols if "Today" in c and "Margin" in c), None)
        short_col  = next((c for c in cols if "Today" in c and "Short" in c), None)
        result: dict = {"dates": [str(d)[:10] for d in df["date"]]}
        if margin_col:
            result["margin_balance"] = [int(v) for v in df[margin_col]]
        if short_col:
            result["short_balance"]  = [int(v) for v in df[short_col]]
        return result if len(result) > 1 else {}
    except Exception as e:
        print(f"[margin {sid}] {e}")
        return {}


@app.route("/api/fx_sparklines")
@cached(ttl=600)
def fx_sparklines():
    direct = {"usdtwd": "TWD=X", "gold": "GC=F", "brent": "BZ=F"}
    result: dict = {}
    for key, sym in direct.items():
        klines = _fetch_yf_kline(sym, 65)
        if klines:
            result[key] = [k["c"] for k in klines[-60:]]

    # JPY/TWD: compute from USD cross rates (JPYTWD=X often unreliable)
    try:
        usd_twd = _fetch_yf_kline("TWD=X", 65)
        usd_jpy = _fetch_yf_kline("USDJPY=X", 65)
        if usd_twd and usd_jpy:
            twd_d = {d["date"]: d["c"] for d in usd_twd}
            jpy_d = {d["date"]: d["c"] for d in usd_jpy}
            common = sorted(set(twd_d) & set(jpy_d))
            cross = [round(twd_d[d] / jpy_d[d], 5) for d in common if jpy_d[d] > 0]
            if cross:
                result["jpytwd"] = cross[-60:]
    except Exception as e:
        print(f"[jpytwd cross] {e}")

    return jsonify({"success": True, "data": result})


@app.route("/api/run_analyze")
def run_analyze():
    import subprocess, json as _json
    from flask import Response, stream_with_context

    def generate():
        try:
            proc = subprocess.Popen(
                ["python3", "analyze.py"],
                cwd=os.path.dirname(__file__),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue
                payload: dict = {"line": line}
                if line.startswith("PROGRESS:"):
                    parts = line.split(":", 3)
                    if len(parts) >= 4:
                        cur, tot = parts[1].split("/")
                        payload.update({"type": "progress", "current": int(cur),
                                        "total": int(tot), "stock_id": parts[2], "name": parts[3]})
                elif "✅" in line or "完成" in line:
                    payload["type"] = "done"
                else:
                    payload["type"] = "log"
                yield f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"
            proc.wait()
            yield f"data: {_json.dumps({'type':'done','code':proc.returncode})}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'type':'error','message':str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/stock_prices")
def stock_prices():
    """Batch fetch latest closing price for a list of stock IDs."""
    ids_str = request.args.get("ids", "")
    if not ids_str:
        return jsonify({"success": True, "data": {}})
    ids = [s.strip() for s in ids_str.split(",") if s.strip()][:20]
    result: dict = {}
    today = datetime.today().strftime("%Y-%m-%d")
    dl = get_dl()
    for sid in ids:
        try:
            df = dl.taiwan_stock_daily(stock_id=sid, start_date=_start(7), end_date=today)
            if not df.empty:
                df = df.sort_values("date")
                result[sid] = {
                    "price": round(float(df.iloc[-1]["close"]), 2),
                    "date":  str(df.iloc[-1]["date"])[:10],
                }
        except Exception as e:
            print(f"[stock_prices {sid}] {e}")
    return jsonify({"success": True, "data": result})


@app.route("/api/ticker_sparklines")
def ticker_sparklines():
    import json as _json
    path = os.path.join(os.path.dirname(__file__), "ai_recommend.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            rec = _json.load(f)
    except Exception:
        return jsonify({"success": False})

    seen: set = set()
    result: dict = {}
    for cat in rec.get("categories", []):
        for s in cat.get("stocks", []):
            sid = s["stock_id"]
            if sid in seen:
                continue
            seen.add(sid)
            klines = _get_stock_kline(sid, 30)
            if klines:
                result[sid] = [k["c"] for k in klines[-20:]]

    return jsonify({"success": True, "data": result})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
