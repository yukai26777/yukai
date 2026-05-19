#!/usr/bin/env python3
"""
analyze.py — 每日技術面選股分析（專業技術分析引擎）
用法: python3 analyze.py
"""

import json
import os
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from FinMind.data import DataLoader

load_dotenv()

BASE = os.path.dirname(__file__)
WATCHLIST_PATH = os.path.join(BASE, "watchlist.txt")
OUTPUT_PATH    = os.path.join(BASE, "ai_recommend.json")

# ── 工具函式 ──────────────────────────────────────────────────────────

def _start(days: int) -> str:
    return (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")

def get_dl() -> DataLoader:
    dl = DataLoader()
    token = os.getenv("FINMIND_TOKEN", "")
    if token:
        dl.login_by_token(api_token=token)
    return dl

def load_watchlist() -> list[tuple[str, str]]:
    result = []
    current_theme = "自選股"
    if os.path.exists(WATCHLIST_PATH):
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if s.startswith("#"):
                    t = s.lstrip("#").strip()
                    if t:
                        current_theme = t
                else:
                    result.append((s, current_theme))
    else:
        for sid in ["2330", "2317", "2454"]:
            result.append((sid, "自選股"))
    return result

def get_stock_names(dl: DataLoader) -> dict:
    try:
        df = dl.taiwan_stock_info()
        return {r["stock_id"]: r["stock_name"] for _, r in df.iterrows()}
    except Exception:
        return {}

# ── 指標計算 ──────────────────────────────────────────────────────────

def fetch_kline(dl: DataLoader, sid: str, days: int = 120) -> "pd.DataFrame | None":
    try:
        today = datetime.today().strftime("%Y-%m-%d")
        df = dl.taiwan_stock_daily(
            stock_id=sid, start_date=_start(days + 220), end_date=today
        )
        if df.empty or len(df) < 30:
            return None
        df = df.sort_values("date").copy()

        # ── 均線 ──
        df["ma5"]   = df["close"].rolling(5).mean()
        df["ma10"]  = df["close"].rolling(10).mean()
        df["ma20"]  = df["close"].rolling(20).mean()
        df["ma60"]  = df["close"].rolling(60).mean()
        df["ma120"] = df["close"].rolling(120).mean()
        df["ma20_slope"] = (df["ma20"] - df["ma20"].shift(5)) / df["ma20"].shift(5) * 100

        # ── MACD (12, 26, 9) ──
        ema12      = df["close"].ewm(span=12, adjust=False).mean()
        ema26      = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26
        df["dea"]  = df["macd"].ewm(span=9, adjust=False).mean()
        df["hist"] = df["macd"] - df["dea"]

        # ── KD (9) ──
        low9  = df["min"].rolling(9).min()
        high9 = df["max"].rolling(9).max()
        denom = high9 - low9
        rsv = ((df["close"] - low9) / denom * 100).where(denom > 0, 50).fillna(50)
        kp, dp = 50.0, 50.0
        K_vals, D_vals = [], []
        for rv in rsv:
            kp = 2/3 * kp + 1/3 * float(rv)
            dp = 2/3 * dp + 1/3 * kp
            K_vals.append(kp)
            D_vals.append(dp)
        df["K"] = K_vals
        df["D"] = D_vals

        # ── RSI-14 ──
        delta = df["close"].diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, 1e-9))

        # ── ROC-10 ──
        df["roc10"] = df["close"].pct_change(10) * 100

        # ── ATR-14 ──
        prev_c = df["close"].shift(1)
        tr = pd.concat([
            df["max"] - df["min"],
            (df["max"] - prev_c).abs(),
            (df["min"] - prev_c).abs(),
        ], axis=1).max(axis=1)
        df["atr14"] = tr.rolling(14).mean()

        # ── Bollinger Bands (20, 2) ──
        df["bb_mid"]   = df["close"].rolling(20).mean()
        df["bb_std"]   = df["close"].rolling(20).std()
        df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
        df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"] * 100
        df["bb_pct"]   = (
            (df["close"] - df["bb_lower"]) /
            (df["bb_upper"] - df["bb_lower"] + 1e-9) * 100
        )

        # ── Historical Volatility 20d annualized (%) ──
        log_ret   = np.log(df["close"] / df["close"].shift(1).replace(0, np.nan))
        df["hv20"] = log_ret.rolling(20).std() * np.sqrt(252) * 100

        # ── OBV ──
        direction   = np.sign(df["close"].diff().fillna(0))
        df["obv"]   = (df["Trading_Volume"] * direction).cumsum()
        df["obv_ma20"] = df["obv"].rolling(20).mean()

        # ── Volume ratio vs 20d avg ──
        df["vol_ma20"]  = df["Trading_Volume"].rolling(20).mean()
        df["vol_ratio"] = df["Trading_Volume"] / df["vol_ma20"].replace(0, np.nan)

        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        print(f"    [{sid}] 取資料失敗: {e}")
        return None

# ── 市場狀態分類 ──────────────────────────────────────────────────────

def classify_market_state(df: pd.DataFrame) -> str:
    if len(df) < 20:
        return "盤整"
    r = df.iloc[-1]

    if pd.notna(r.get("hv20")) and r["hv20"] > 55:
        return "高波動"
    if pd.notna(r.get("bb_width")) and r["bb_width"] < 4:
        return "低波動"

    if len(df) >= 21:
        high20 = df["max"].iloc[-21:-1].max()
        low20  = df["min"].iloc[-21:-1].min()
        vol_ok = pd.notna(r.get("vol_ratio")) and r["vol_ratio"] > 1.4
        if r["close"] >= high20 * 0.995:
            return "突破"
        if r["close"] <= low20 * 1.005 and vol_ok:
            return "跌破"

    if len(df) >= 3:
        p = df.iloc[-2]
        if r["K"] > r["D"] and p["K"] < p["D"] and r["K"] < 35:
            return "反轉"
        if r["K"] < r["D"] and p["K"] > p["D"] and r["K"] > 65:
            return "反轉"

    has60 = pd.notna(r.get("ma60"))
    if has60:
        if r["ma5"] > r["ma10"] > r["ma20"] > r["ma60"]:
            return "上升趨勢"
        if r["ma5"] < r["ma10"] < r["ma20"] < r["ma60"]:
            return "下降趨勢"
    else:
        if pd.notna(r.get("ma20")):
            if r["ma5"] > r["ma20"]: return "上升趨勢"
            if r["ma5"] < r["ma20"]: return "下降趨勢"
    return "盤整"

# ── 支撐壓力 ──────────────────────────────────────────────────────────

def find_support_resistance(df: pd.DataFrame) -> tuple[float, float]:
    close = float(df.iloc[-1]["close"])
    if len(df) < 20:
        return close * 0.95, close * 1.05
    recent = df.tail(30)
    lows   = sorted([v for v in recent["min"].values if v < close], reverse=True)
    highs  = sorted([v for v in recent["max"].values if v > close])
    sup = lows[0]  if lows  else close * 0.95
    res = highs[0] if highs else close * 1.05
    return sup, res

# ── 走前回測（Walk-Forward）──────────────────────────────────────────

def run_backtest(df: pd.DataFrame, state: str) -> dict:
    if len(df) < 40:
        return {"valid": False, "note": "樣本不足（<40交易日），回測不具可信度"}

    test_start = int(len(df) * 0.6)
    tdf = df.iloc[test_start:].copy().reset_index(drop=True)
    if len(tdf) < 10:
        return {"valid": False, "note": "測試期樣本不足"}

    trades, in_trade, entry_price, entry_idx = [], False, 0.0, 0

    for i in range(1, len(tdf) - 1):
        r, p = tdf.iloc[i], tdf.iloc[i-1]
        atr = float(r.get("atr14") or r["close"] * 0.02)

        if not in_trade:
            sig = False
            if state in ("上升趨勢", "突破"):
                if r["macd"] > r["dea"] and p["macd"] < p["dea"] and pd.notna(r.get("ma20")) and r["close"] > r["ma20"]:
                    sig = True
                elif r["K"] > r["D"] and p["K"] < p["D"] and 30 < r["K"] < 65:
                    sig = True
            elif state == "反轉":
                if r["K"] > r["D"] and p["K"] < p["D"] and r["K"] < 40:
                    sig = True
            elif state == "盤整":
                if r["K"] > r["D"] and p["K"] < p["D"] and r["K"] < 30 and r.get("vol_ratio", 1) > 1.2:
                    sig = True
            elif state == "下降趨勢":
                if r["rsi"] < 25 and r["K"] > r["D"] and p["K"] < p["D"]:
                    sig = True
            if sig:
                in_trade, entry_price, entry_idx = True, float(r["close"]), i

        else:
            hold = i - entry_idx
            exit_sig = (
                r["close"] < entry_price - 2 * atr or
                r["close"] > entry_price + 3 * atr or
                (pd.notna(r.get("ma20")) and r["close"] < r["ma20"] * 0.985 and hold > 2) or
                hold >= 20
            )
            if exit_sig:
                ret = (float(r["close"]) - entry_price) / entry_price * 100
                trades.append({"ret": ret, "days": hold, "win": ret > 0})
                in_trade = False

    if not trades:
        return {"valid": True, "trade_count": 0, "note": f"測試期({len(tdf)}日)無觸發交易，無法評估"}

    rets   = np.array([t["ret"] for t in trades])
    wins   = rets[rets > 0]
    losses = rets[rets <= 0]
    wr     = len(wins) / len(trades) * 100
    avg_w  = float(np.mean(wins))   if len(wins)   else 0.0
    avg_l  = float(np.mean(losses)) if len(losses) else 0.0
    rr     = abs(avg_w / avg_l) if avg_l != 0 else 0.0
    pf     = abs(float(wins.sum()) / losses.sum()) if losses.sum() != 0 else 99.0
    exp    = wr / 100 * avg_w + (1 - wr / 100) * avg_l
    equity = np.cumprod(1 + rets / 100) * 100
    peak   = np.maximum.accumulate(equity)
    max_dd = float(((equity - peak) / peak * 100).min())
    avg_d  = float(np.mean([t["days"] for t in trades]))
    sharpe = float(np.mean(rets) / (np.std(rets) + 1e-9) * np.sqrt(252 / max(avg_d, 1))) if len(rets) > 1 else 0.0
    conf   = "低" if len(trades) < 5 else "中" if len(trades) < 10 else "高"

    return {
        "valid": True, "trade_count": len(trades),
        "win_rate": round(wr, 1), "avg_ret": round(float(np.mean(rets)), 2),
        "avg_win": round(avg_w, 2), "avg_loss": round(avg_l, 2),
        "risk_reward": round(rr, 2), "profit_factor": round(min(pf, 99.0), 2),
        "max_drawdown": round(max_dd, 2), "sharpe": round(sharpe, 2),
        "expectancy": round(exp, 2), "avg_hold_days": round(avg_d, 1),
        "test_days": len(tdf), "confidence": conf,
        "note": f"走前驗證，測試期 {len(tdf)} 日，{conf}可信度（{len(trades)} 筆）",
    }

# ── 操作建議決策（6選1）─────────────────────────────────────────────

def determine_operation(state: str, r_sc: int, t_sc: int, s_sc: int,
                         bt: dict, df: pd.DataFrame) -> str:
    r      = df.iloc[-1]
    bt_ok  = bt.get("valid") and bt.get("trade_count", 0) >= 3 and bt.get("win_rate", 0) >= 45
    rr_ok  = bt.get("risk_reward", 0) >= 1.5
    vol_ok = pd.notna(r.get("vol_ratio")) and r["vol_ratio"] >= 1.3

    if state == "高波動":   return "停止交易"
    if state == "跌破":     return "分批出場"
    if state == "下降趨勢":
        return "停止交易" if bt.get("win_rate", 50) < 40 else "觀察"

    if state in ("突破", "上升趨勢"):
        if s_sc >= 8 and bt_ok and rr_ok and vol_ok: return "分批進場"
        if s_sc >= 5 or t_sc >= 7:                   return "等待確認"
        return "觀察"

    if state == "反轉":
        if r_sc >= 7 and bt_ok and vol_ok: return "分批進場"
        if r_sc >= 5:                      return "等待確認"
        return "觀察"

    if state == "盤整":
        return "等待確認" if r_sc >= 6 and bt_ok else "觀察"

    if state == "低波動":
        return "等待確認"

    return "觀察"

# ── 評分函式 ──────────────────────────────────────────────────────────

def score_rebound(df: pd.DataFrame) -> tuple[int, list[str]]:
    if len(df) < 5: return 0, []
    r, p, p2 = df.iloc[-1], df.iloc[-2], df.iloc[-3]
    sc, sg = 0, []

    if r["K"] < 30 and r["K"] > p["K"]:
        sc += 3; sg.append(f"KD低位翻揚 {r['K']:.0f}")
    if r["K"] < 25 and r["D"] < 25:
        sc += 1; sg.append("KD極度超賣")
    if r["K"] > r["D"] and p["K"] < p["D"]:
        sc += 3; sg.append("KD黃金交叉")
    if pd.notna(r["rsi"]) and r["rsi"] < 30:
        sc += 2; sg.append(f"RSI超賣 {r['rsi']:.0f}")
    elif pd.notna(r["rsi"]) and r["rsi"] < 35 and r["rsi"] > p["rsi"]:
        sc += 1; sg.append(f"RSI低位回升 {r['rsi']:.0f}")
    if r["hist"] < 0 and p["hist"] < 0 and r["hist"] > p["hist"] > p2["hist"]:
        sc += 3; sg.append("MACD底背離縮空")
    if pd.notna(r.get("ma60")) and 0.95 * r["ma60"] < r["close"] < 1.03 * r["ma60"]:
        sc += 2; sg.append("測MA60支撐")
    if pd.notna(r.get("vol_ratio")) and r["vol_ratio"] > 1.3:
        sc += 1; sg.append("量能回溫")
    if pd.notna(r.get("obv")) and pd.notna(p.get("obv")) and r["obv"] > p["obv"] and r["close"] < p["close"]:
        sc += 1; sg.append("OBV底背離")
    # ATR 品質門檻：日波動超 5% 降分
    if pd.notna(r.get("atr14")) and r["atr14"] / r["close"] > 0.05:
        sc -= 1
    return sc, sg


def score_turning(df: pd.DataFrame) -> tuple[int, list[str]]:
    if len(df) < 5: return 0, []
    r, p, p2 = df.iloc[-1], df.iloc[-2], df.iloc[-3]
    sc, sg = 0, []

    if r["macd"] > r["dea"] and p["macd"] < p["dea"]:
        sc += 4; sg.append("MACD黃金交叉")
    if r["hist"] > 0 and r["hist"] > p["hist"] > p2["hist"]:
        sc += 2; sg.append("MACD柱持續放大")
    elif r["hist"] > 0 and r["hist"] > p["hist"]:
        sc += 1; sg.append("MACD柱擴張")
    if pd.notna(r.get("ma20")) and r["close"] > r["ma20"] and p["close"] < p["ma20"]:
        sc += 3; sg.append("突破MA20壓力")
    elif pd.notna(r.get("ma20")) and r["close"] > r["ma20"]:
        sc += 1; sg.append("站穩MA20")
    if 40 < r["K"] < 80 and r["K"] > r["D"] and r["K"] > p["K"]:
        sc += 2; sg.append(f"KD強勢向上 {r['K']:.0f}")
    if pd.notna(r.get("vol_ratio")) and r["vol_ratio"] > 1.5:
        sc += 2; sg.append("放量攻擊")
    if pd.notna(r["rsi"]) and 50 < r["rsi"] < 70:
        sc += 1; sg.append(f"RSI多頭 {r['rsi']:.0f}")
    if pd.notna(r.get("obv_ma20")) and r["obv"] > r["obv_ma20"]:
        sc += 1; sg.append("OBV均線上方")
    if pd.notna(r.get("atr14")) and r["atr14"] / r["close"] > 0.05:
        sc -= 1
    return sc, sg


def score_strong(df: pd.DataFrame) -> tuple[int, list[str]]:
    if len(df) < 10: return 0, []
    r = df.iloc[-1]
    sc, sg = 0, []

    if pd.notna(r.get("ma60")) and r["ma5"] > r["ma10"] > r["ma20"] > r["ma60"]:
        sc += 4; sg.append("均線多頭排列")
    elif pd.notna(r.get("ma20")) and r["ma5"] > r["ma10"] > r["ma20"]:
        sc += 2; sg.append("短中線多頭")
    if r["macd"] > 0 and r["dea"] > 0 and r["hist"] > 0:
        sc += 3; sg.append("MACD完全多頭")
    elif r["hist"] > 0 and r["macd"] > 0:
        sc += 1; sg.append("MACD正值")
    if r["K"] > 70 and r["D"] > 70 and r["K"] > r["D"]:
        sc += 2; sg.append(f"KD高位強勢 {r['K']:.0f}")
    elif r["K"] > 55 and r["K"] > r["D"]:
        sc += 1; sg.append(f"KD偏多 {r['K']:.0f}")
    if len(df) >= 10:
        ret5 = (r["close"] - df.iloc[-6]["close"]) / df.iloc[-6]["close"] * 100
        if   ret5 >  8: sc += 3; sg.append(f"5日強漲 +{ret5:.1f}%")
        elif ret5 >  4: sc += 2; sg.append(f"5日漲 +{ret5:.1f}%")
        elif ret5 > 1.5: sc += 1; sg.append(f"5日漲 +{ret5:.1f}%")
    if pd.notna(r.get("atr14")) and r["atr14"] / r["close"] > 0.05:
        sc -= 1
    return sc, sg

# ── 8節結構化報告生成 ─────────────────────────────────────────────────

def generate_report(category_id: str, signals: list[str], base: dict,
                    state: str, bt: dict, df: pd.DataFrame,
                    support: float, resistance: float, operation: str) -> dict:
    name  = base.get("name", "")
    price = base.get("price", 0)
    r     = df.iloc[-1]

    atr   = float(r.get("atr14") or price * 0.02)
    hv    = float(r.get("hv20") or 0)
    bb_w  = float(r.get("bb_width") or 0)
    rsi   = float(r.get("rsi") or 50)
    kv    = float(r["K"])
    dv    = float(r["D"])
    vol_r = float(r.get("vol_ratio") or 1.0)

    sup_pct = round((price - support)  / price * 100, 1)
    res_pct = round((resistance - price) / price * 100, 1)
    sl_price = round(price - 2 * atr, 2)
    sl_pct   = round(atr * 2 / price * 100, 1)
    mae      = round(atr * 2.5, 2)

    # ── 1. 市場狀態 ──
    s1 = (
        f"市場狀態：{state}。"
        f"近期日波動率（HV20）{hv:.1f}%，布林通道寬度 {bb_w:.1f}%。"
        f"{'波動明顯偏高，操作風險加大，建議降低部位。' if hv > 45 else '波動處於正常範圍。'}"
    )

    # ── 2. 主要趨勢 ──
    has60 = pd.notna(r.get("ma60"))
    ma_txt = (
        f"MA5={r['ma5']:.1f} / MA10={r['ma10']:.1f} / MA20={r['ma20']:.1f}"
        + (f" / MA60={r['ma60']:.1f}" if has60 else "")
    )
    slope_txt = ""
    if pd.notna(r.get("ma20_slope")):
        slope_txt = f"，MA20斜率 {r['ma20_slope']:.2f}%（{'向上' if r['ma20_slope'] > 0 else '向下'}）"
    roc_txt = f"，10日ROC {r['roc10']:.1f}%" if pd.notna(r.get("roc10")) else ""
    bb_pos  = f"布林帶位置 {r.get('bb_pct', 50):.0f}%（{'上軌附近' if r.get('bb_pct',50)>80 else '下軌附近' if r.get('bb_pct',50)<20 else '中性區間'}）"
    s2 = f"主要趨勢：{ma_txt}{slope_txt}{roc_txt}。{bb_pos}。"

    # ── 3. 動能判定 ──
    rsi_lbl  = "超買" if rsi > 70 else ("超賣" if rsi < 30 else "中性")
    kd_lbl   = "黃金交叉" if kv > dv else "死亡交叉"
    hist_lbl = "正" if r["hist"] > 0 else "負"
    s3 = (
        f"動能判定：RSI={rsi:.1f}（{rsi_lbl}），KD=K{kv:.0f}/D{dv:.0f}（{kd_lbl}），"
        f"MACD直方柱 {r['hist']:.2f}（{hist_lbl}值）。"
        f"觸發訊號：{'、'.join(signals) if signals else '無明顯訊號'}。"
        f"{'多項訊號同步確認，可信度較高。' if len(signals) >= 3 else '訊號數量偏少，需等待更多確認。' if len(signals) < 2 else ''}"
    )

    # ── 4. 量價確認 ──
    vol_lbl = "放量" if vol_r > 1.3 else ("縮量" if vol_r < 0.7 else "均量")
    obv_txt = ""
    if pd.notna(r.get("obv")) and pd.notna(r.get("obv_ma20")):
        obv_txt = f"OBV位於20日均線{'上方（資金流入）' if r['obv'] > r['obv_ma20'] else '下方（資金流出）'}。"
    vol_qual = "訊號有量能支撐，可信度較高。" if vol_r > 1.3 else "訊號缺乏量能確認，可信度偏低，建議等待量能配合再行動。"
    s4 = (
        f"量價確認：今日成交量為20日均量的 {vol_r:.2f} 倍（{vol_lbl}）。"
        f"{obv_txt}{vol_qual}"
    )

    # ── 5. 關鍵支撐壓力 ──
    sr_warn = ""
    if sup_pct < 2:   sr_warn += "支撐距離偏近，停損空間有限。"
    if res_pct < 3:   sr_warn += "壓力距離偏近，上漲空間受限，風險報酬比較差。"
    s5 = (
        f"關鍵支撐壓力：近期支撐 {support:.2f}（距現價 -{sup_pct}%），"
        f"近期壓力 {resistance:.2f}（距現價 +{res_pct}%）。{sr_warn}"
    )

    # ── 6. 波動與風險摘要 ──
    trend_risk  = "高" if state in ("下降趨勢", "跌破") else ("中" if state in ("盤整", "高波動") else "低")
    vol_risk    = "高" if hv > 50 else ("中" if hv > 30 else "低")
    struct_risk = "高" if res_pct < 3 or sup_pct < 2 else ("中" if res_pct < 6 else "低")
    trade_risk  = "高" if vol_r < 0.7 else ("中" if vol_r < 1.2 else "低")
    s6 = (
        f"波動風險：{vol_risk}（HV20={hv:.1f}%，ATR14={atr:.2f}）。"
        f"趨勢風險：{trend_risk}。結構風險：{struct_risk}（壓力距 {res_pct}%）。"
        f"交易風險：{trade_risk}（量比 {vol_r:.2f}）。"
        f"建議停損：{sl_price}（現價下方 {sl_pct}%，2×ATR）。"
        f"預估最大不利波動（MAE）：±{mae:.2f}（2.5×ATR）。"
    )

    # ── 7. 回測摘要 ──
    if not bt.get("valid"):
        s7 = f"回測摘要：{bt.get('note', '無法回測')}，本次回測結果不具參考性。"
    elif bt.get("trade_count", 0) == 0:
        s7 = f"回測摘要：{bt.get('note', '')}，無法評估歷史表現。"
    else:
        bt_warn = " ⚠️ 樣本量偏少（<5筆），結果僅供參考。" if bt["trade_count"] < 5 else ""
        s7 = (
            f"回測摘要（走前驗證 · {bt['test_days']}日 · {bt['confidence']}可信度）："
            f"交易 {bt['trade_count']} 筆 | 勝率 {bt['win_rate']}% | "
            f"平均報酬 {bt['avg_ret']:+.2f}% | 風險報酬比 {bt['risk_reward']:.2f} | "
            f"Profit Factor {bt['profit_factor']:.2f} | 最大回撤 {bt['max_drawdown']:.2f}% | "
            f"Sharpe {bt['sharpe']:.2f} | Expectancy {bt['expectancy']:.2f}% | "
            f"平均持有 {bt['avg_hold_days']:.1f} 日。{bt_warn}"
        )

    # ── 8. 操作建議 ──
    op_guide = {
        "觀察":     "目前訊號不足或趨勢未明，建議持續追蹤但不進場，等待更清晰的確認訊號。",
        "等待確認": f"方向初步明確但尚未完全確認。建議等待量能放大（量比>1.5）或收盤站穩 {resistance:.1f} 壓力後再行動。",
        "分批進場": f"多項指標同步確認，可考慮分批布局。首批不超過總部位 30%，停損設 {sl_price}（-{sl_pct}%）。",
        "分批出場": "技術面轉弱或跌破關鍵支撐，建議分批減碼出場，降低持倉風險。",
        "降低部位": "目前波動偏高或趨勢偏弱，建議主動降低部位至正常倉位 50% 以下。",
        "停止交易": "市場狀態不利，趨勢或回測指標過差，建議暫停交易，等待市場結構改善。",
    }
    s8 = f"操作建議：【{operation}】。{op_guide.get(operation, '')}"

    return {
        "market_state":       s1,
        "trend":              s2,
        "momentum":           s3,
        "volume_price":       s4,
        "support_resistance": s5,
        "risk":               s6,
        "backtest":           s7,
        "operation":          s8,
        "full_report":        True,
    }

# ── 主程式 ────────────────────────────────────────────────────────────

def analyze():
    print("=" * 55)
    print("  台股技術面選股分析（專業技術分析引擎）")
    print(f"  {datetime.today().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    dl        = get_dl()
    name_map  = get_stock_names(dl)
    watchlist = load_watchlist()
    print(f"\n分析 {len(watchlist)} 支股票...\n")

    rebound_list: list[dict] = []
    turning_list: list[dict] = []
    strong_list:  list[dict] = []

    total = len(watchlist)
    for idx, (sid, theme) in enumerate(watchlist, 1):
        name = name_map.get(sid, sid)
        print(f"PROGRESS:{idx}/{total}:{sid}:{name}", flush=True)
        print(f"  {sid} {name}...", end="", flush=True)
        df = fetch_kline(dl, sid)
        if df is None:
            print(" 無資料"); continue

        state           = classify_market_state(df)
        support, resist = find_support_resistance(df)
        bt              = run_backtest(df, state)
        r_sc, r_sg      = score_rebound(df)
        t_sc, t_sg      = score_turning(df)
        s_sc, s_sg      = score_strong(df)
        operation       = determine_operation(state, r_sc, t_sc, s_sc, bt, df)

        close = float(df.iloc[-1]["close"])
        prev  = float(df.iloc[-2]["close"]) if len(df) > 1 else close
        chg   = round((close - prev) / prev * 100, 2) if prev else 0

        base = {
            "stock_id": sid, "name": name,
            "theme": theme, "price": round(close, 2),
            "change_pct": chg, "state": state,
        }

        THRESHOLD = 5
        def make_entry(sc, sg, cid):
            e = {**base, "score": sc, "signals": sg}
            e["report"] = generate_report(cid, sg, base, state, bt, df, support, resist, operation)
            return e

        if r_sc >= THRESHOLD: rebound_list.append(make_entry(r_sc, r_sg, "rebound"))
        if t_sc >= THRESHOLD: turning_list.append(make_entry(t_sc, t_sg, "turning"))
        if s_sc >= THRESHOLD: strong_list.append(make_entry(s_sc, s_sg, "strong"))

        print(f"  [{state}] 反彈:{r_sc} 轉強:{t_sc} 強勢:{s_sc} → {operation}")
        time.sleep(0.4)

    for lst in (rebound_list, turning_list, strong_list):
        lst.sort(key=lambda x: x["score"], reverse=True)

    rebound_list = rebound_list[:6]
    turning_list = turning_list[:6]
    strong_list  = strong_list[:6]

    today_str = datetime.today().strftime("%Y年%m月%d日")
    comment = (
        f"今日技術掃描完成（走前回測驗證）："
        f"反彈候選 {len(rebound_list)} 支、"
        f"轉強訊號 {len(turning_list)} 支、"
        f"強勢持續 {len(strong_list)} 支。"
    )

    output = {
        "date": today_str,
        "generated_by": "專業技術分析引擎（多指標 + 走前回測）",
        "market_comment": comment,
        "categories": [
            {"id": "rebound", "name": "即將反彈",
             "desc": "超賣反彈訊號（含走前回測）",
             "color": "#5cd98a", "icon": "arrow-up-circle", "stocks": rebound_list},
            {"id": "turning", "name": "轉強訊號",
             "desc": "由弱轉強關鍵訊號（含走前回測）",
             "color": "#5ab4ff", "icon": "lightning-charge", "stocks": turning_list},
            {"id": "strong",  "name": "強勢持續",
             "desc": "趨勢確立多頭格局（含走前回測）",
             "color": "#ffc947", "icon": "fire", "stocks": strong_list},
        ],
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成！結果寫入 {OUTPUT_PATH}")
    print(f"  即將反彈: {[s['stock_id'] for s in rebound_list]}")
    print(f"  轉強訊號: {[s['stock_id'] for s in turning_list]}")
    print(f"  強勢持續: {[s['stock_id'] for s in strong_list]}")


if __name__ == "__main__":
    analyze()
