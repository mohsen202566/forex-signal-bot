# -*- coding: utf-8 -*-
"""Prediction-focused Forex analysis engine.

Architecture:
- 4H/1H = market direction context
- 30M/15M = setup quality and readiness
- 5M = fast activation trigger
- News is warning-only and never blocks signals
"""

import math
from typing import Dict, Optional

import pandas as pd
import ta

from data_provider import get_latest_price, get_candles
from news_engine import get_news_risk

TIMEFRAMES = {
    "4H": "4h",
    "1H": "1h",
    "30M": "30min",
    "15M": "15min",
    "5M": "5min",
}

SETUP_MIN_SCORE = 62
ACTIVATION_MIN_SCORE = 58
MIN_DIRECTION_GAP = 6

# Soft higher-timeframe context bias.
# If 4H and 1H agree, the aligned side gets +5 and the opposite side gets -5.
# This is intentionally soft so the forex scalp engine stays fast and does not become over-filtered.
HTF_CONTEXT_BIAS_POINTS = 5


def _round_price(value, symbol=""):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None

    if symbol in (
        "XAU/USD", "XAG/USD", "WTI/USD", "BRENT/USD", "US30", "NAS100",
        "SPX500", "DAX40", "DXY", "BTC/USD", "ETH/USD", "SOL/USD"
    ):
        digits = 2
    elif "JPY" in symbol:
        digits = 3
    else:
        digits = 5

    return round(float(value), digits)


def calculate_indicators(df: pd.DataFrame):
    df = df.copy()
    df["ema20"] = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
    df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
    df["ema200"] = ta.trend.EMAIndicator(df["close"], window=200).ema_indicator()
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()
    df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()
    try:
        df["adx"] = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14).adx()
    except Exception:
        df["adx"] = 0
    return df


def _tf_analysis(symbol: str, label: str, interval: str):
    raw = get_candles(symbol, interval=interval, outputsize=250)
    if not raw.get("success"):
        return {"success": False, "error": raw.get("error", "خطا در دریافت دیتا")}

    df = calculate_indicators(raw["data"]).dropna().reset_index(drop=True)
    if len(df) < 8:
        return {"success": False, "error": "داده کافی برای اندیکاتورها وجود ندارد."}

    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    buy = 0
    sell = 0
    reasons_buy = []
    reasons_sell = []

    if last["ema50"] > last["ema200"]:
        buy += 16
        reasons_buy.append(f"{label}: EMA50 بالای EMA200 است.")
    elif last["ema50"] < last["ema200"]:
        sell += 16
        reasons_sell.append(f"{label}: EMA50 پایین EMA200 است.")

    if last["close"] > last["ema20"]:
        buy += 8
        reasons_buy.append(f"{label}: قیمت بالای EMA20 است.")
    elif last["close"] < last["ema20"]:
        sell += 8
        reasons_sell.append(f"{label}: قیمت پایین EMA20 است.")

    if last["macd"] > last["macd_signal"]:
        buy += 9
        reasons_buy.append(f"{label}: MACD صعودی است.")
    elif last["macd"] < last["macd_signal"]:
        sell += 9
        reasons_sell.append(f"{label}: MACD نزولی است.")

    if last["macd_hist"] > prev["macd_hist"] > prev2["macd_hist"]:
        buy += 8
        reasons_buy.append(f"{label}: هیستوگرام MACD دو کندل پشت‌سرهم صعودی تقویت شده است.")
    elif last["macd_hist"] < prev["macd_hist"] < prev2["macd_hist"]:
        sell += 8
        reasons_sell.append(f"{label}: هیستوگرام MACD دو کندل پشت‌سرهم نزولی تقویت شده است.")
    elif last["macd_hist"] > prev["macd_hist"]:
        buy += 4
    elif last["macd_hist"] < prev["macd_hist"]:
        sell += 4

    if last["rsi"] > prev["rsi"] > prev2["rsi"]:
        buy += 7
        reasons_buy.append(f"{label}: شیب RSI دو کندل صعودی است.")
    elif last["rsi"] < prev["rsi"] < prev2["rsi"]:
        sell += 7
        reasons_sell.append(f"{label}: شیب RSI دو کندل نزولی است.")
    elif last["rsi"] > prev["rsi"]:
        buy += 3
    elif last["rsi"] < prev["rsi"]:
        sell += 3

    if 44 <= last["rsi"] <= 68:
        buy += 4
    if 32 <= last["rsi"] <= 56:
        sell += 4

    if last.get("adx", 0) >= 16:
        if buy > sell:
            buy += 4
        elif sell > buy:
            sell += 4

    return {
        "success": True,
        "label": label,
        "df": df,
        "buy": buy,
        "sell": sell,
        "reasons_buy": reasons_buy,
        "reasons_sell": reasons_sell,
        "last": {
            "close": _round_price(last["close"], symbol),
            "ema20": _round_price(last["ema20"], symbol),
            "ema50": _round_price(last["ema50"], symbol),
            "ema200": _round_price(last["ema200"], symbol),
            "rsi": round(float(last["rsi"]), 2),
            "macd": round(float(last["macd"]), 5),
            "macd_signal": round(float(last["macd_signal"]), 5),
            "macd_hist": round(float(last["macd_hist"]), 5),
            "prev_macd_hist": round(float(prev["macd_hist"]), 5),
            "atr": _round_price(last["atr"], symbol),
            "adx": round(float(last.get("adx", 0)), 2),
        },
    }


def _make_levels(symbol: str, direction: str, price: float, atr: float):
    if not atr or atr <= 0:
        return None, None, None, None

    # Scalp-oriented levels: smaller TP1, moderate SL, TP2 separate.
    if direction == "BUY":
        entry = price
        sl = price - (atr * 1.10)
        tp1 = price + (atr * 0.95)
        tp2 = price + (atr * 1.65)
    elif direction == "SELL":
        entry = price
        sl = price + (atr * 1.10)
        tp1 = price - (atr * 0.95)
        tp2 = price - (atr * 1.65)
    else:
        return None, None, None, None

    return (
        _round_price(entry, symbol),
        _round_price(sl, symbol),
        _round_price(tp1, symbol),
        _round_price(tp2, symbol),
    )


def _fast_entry_score(direction: str, entry_tf: Dict, confirm_tf: Optional[Dict] = None):
    score = 0
    reasons = []
    last = entry_tf["last"]

    if direction == "BUY":
        if last["close"] > last["ema20"]:
            score += 24
            reasons.append("5M: قیمت بالای EMA20 است.")
        if last["macd_hist"] > last.get("prev_macd_hist", 0):
            score += 22
            reasons.append("5M: هیستوگرام MACD در حال تقویت صعودی است.")
        if last["macd_hist"] > 0:
            score += 12
            reasons.append("5M: هیستوگرام MACD مثبت است.")
        if last["rsi"] >= 50:
            score += 16
            reasons.append("5M: RSI بالای 50 است.")
    elif direction == "SELL":
        if last["close"] < last["ema20"]:
            score += 24
            reasons.append("5M: قیمت پایین EMA20 است.")
        if last["macd_hist"] < last.get("prev_macd_hist", 0):
            score += 22
            reasons.append("5M: هیستوگرام MACD در حال تقویت نزولی است.")
        if last["macd_hist"] < 0:
            score += 12
            reasons.append("5M: هیستوگرام MACD منفی است.")
        if last["rsi"] <= 50:
            score += 16
            reasons.append("5M: RSI پایین 50 است.")

    if last.get("adx", 0) >= 16:
        score += 10
        reasons.append("5M: ADX برای اسکالپ قابل قبول است.")

    if confirm_tf:
        c = confirm_tf["last"]
        if direction == "BUY" and c["close"] > c["ema20"]:
            score += 10
            reasons.append("15M: قیمت با جهت خرید هم‌راستا است.")
        elif direction == "SELL" and c["close"] < c["ema20"]:
            score += 10
            reasons.append("15M: قیمت با جهت فروش هم‌راستا است.")

    return min(100, score), reasons


def _simple_tf_direction(item: Optional[Dict]) -> Optional[str]:
    """Return BUY/SELL/None using the already-calculated TF score."""
    if not item or not item.get("success"):
        return None

    buy = float(item.get("buy") or 0)
    sell = float(item.get("sell") or 0)

    if buy > sell:
        return "BUY"
    if sell > buy:
        return "SELL"
    return None


def _apply_higher_tf_context_bias(buy_score: float, sell_score: float, analyses: Dict):
    """Apply a soft 4H/1H context bias without hard-blocking counter-trend scalps."""
    trend_4h = _simple_tf_direction(analyses.get("4H"))
    trend_1h = _simple_tf_direction(analyses.get("1H"))

    if not trend_4h or not trend_1h or trend_4h != trend_1h:
        return buy_score, sell_score, None, None

    if trend_4h == "BUY":
        buy_score += HTF_CONTEXT_BIAS_POINTS
        sell_score = max(0, sell_score - HTF_CONTEXT_BIAS_POINTS)
        return (
            buy_score,
            sell_score,
            "BUY",
            f"4H و 1H هم‌جهت خرید هستند؛ {HTF_CONTEXT_BIAS_POINTS} امتیاز به خرید اضافه و از فروش کم شد.",
        )

    if trend_4h == "SELL":
        sell_score += HTF_CONTEXT_BIAS_POINTS
        buy_score = max(0, buy_score - HTF_CONTEXT_BIAS_POINTS)
        return (
            buy_score,
            sell_score,
            "SELL",
            f"4H و 1H هم‌جهت فروش هستند؛ {HTF_CONTEXT_BIAS_POINTS} امتیاز به فروش اضافه و از خرید کم شد.",
        )

    return buy_score, sell_score, None, None


def analyze_pair(symbol: str) -> Dict:
    price_data = get_latest_price(symbol)
    if not price_data.get("success"):
        return {"success": False, "error": price_data.get("error", "خطا در دریافت قیمت")}

    analyses = {}
    errors = []
    for label, interval in TIMEFRAMES.items():
        item = _tf_analysis(symbol, label, interval)
        if item.get("success"):
            analyses[label] = item
        else:
            errors.append(f"{label}: {item.get('error')}")

    if not analyses:
        return {"success": False, "error": "تحلیل هیچ تایم‌فریمی موفق نبود. " + " | ".join(errors)}

    # Futures-like hierarchy for scalp: 5M > 15M > 30M > 1H > 4H.
    # Higher timeframes still guide direction, but fast TFs decide setup freshness/activation.
    weights = {"4H": 0.80, "1H": 1.00, "30M": 1.15, "15M": 1.35, "5M": 1.55}
    buy_score = 0
    sell_score = 0
    buy_reasons = []
    sell_reasons = []
    tf_summary = {}

    for label, item in analyses.items():
        w = weights.get(label, 1)
        buy_score += item["buy"] * w
        sell_score += item["sell"] * w
        buy_reasons.extend(item["reasons_buy"])
        sell_reasons.extend(item["reasons_sell"])
        tf_summary[label] = item["last"]

    buy_score, sell_score, htf_bias_direction, htf_bias_reason = _apply_higher_tf_context_bias(
        buy_score,
        sell_score,
        analyses,
    )

    if htf_bias_reason:
        if htf_bias_direction == "BUY":
            buy_reasons.insert(0, htf_bias_reason)
        elif htf_bias_direction == "SELL":
            sell_reasons.insert(0, htf_bias_reason)

    total = max(buy_score + sell_score, 1)
    buy_percent = round((buy_score / total) * 100, 1)
    sell_percent = round((sell_score / total) * 100, 1)

    if buy_percent - sell_percent >= MIN_DIRECTION_GAP:
        direction = "BUY"
        prediction_score = min(100, round(buy_percent, 1))
        reasons = buy_reasons[:12]
    elif sell_percent - buy_percent >= MIN_DIRECTION_GAP:
        direction = "SELL"
        prediction_score = min(100, round(sell_percent, 1))
        reasons = sell_reasons[:12]
    else:
        direction = "NEUTRAL"
        prediction_score = round(max(buy_percent, sell_percent), 1)
        reasons = ["اختلاف امتیاز خرید و فروش کافی نیست؛ بازار خنثی یا نامشخص است."]

    entry_score = 0
    entry_reasons = []
    status = "NO_TRADE"
    entry = stop_loss = tp1 = tp2 = None

    if direction in ("BUY", "SELL") and prediction_score >= SETUP_MIN_SCORE:
        entry_tf = analyses.get("5M") or analyses.get("15M")
        confirm_tf = analyses.get("15M")
        if entry_tf:
            entry_score, entry_reasons = _fast_entry_score(direction, entry_tf, confirm_tf)
            atr = float((entry_tf.get("last") or {}).get("atr") or 0)
            entry, stop_loss, tp1, tp2 = _make_levels(symbol, direction, float(price_data["price"]), atr)

            if entry and stop_loss and tp1:
                if entry_score >= ACTIVATION_MIN_SCORE:
                    status = "SIGNAL"
                else:
                    status = "SETUP"
        else:
            status = "PREDICTION_ONLY"
    elif direction in ("BUY", "SELL"):
        status = "PREDICTION_ONLY"

    news = get_news_risk(symbol)

    return {
        "success": True,
        "symbol": symbol,
        "price": _round_price(price_data["price"], symbol),
        "direction": direction,
        "prediction_score": prediction_score,
        "buy_score": buy_percent,
        "sell_score": sell_percent,
        "status": status,
        "entry_score": entry_score,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "reasons": reasons or ["دلیل مشخصی ثبت نشد."],
        "entry_reasons": entry_reasons or ["تریگر ورود سریع هنوز کامل نیست."],
        "tf_summary": tf_summary,
        "news": news,
        "errors": errors,
    }
