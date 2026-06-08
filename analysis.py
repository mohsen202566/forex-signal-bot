# -*- coding: utf-8 -*-
import math
from typing import Dict

import pandas as pd
import ta

from data_provider import get_latest_price, get_candles
from news_engine import get_news_risk

TIMEFRAMES = {
    "4H": "4h",
    "1H": "1h",
    "15M": "15min",
    "5M": "5min",
}

def _round_price(value, symbol=""):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None

    if symbol in ("XAU/USD", "XAG/USD", "WTI/USD", "BRENT/USD", "US30", "NAS100", "SPX500", "DAX40", "DXY", "BTC/USD", "ETH/USD", "SOL/USD"):
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
    if len(df) < 5:
        return {"success": False, "error": "داده کافی برای اندیکاتورها وجود ندارد."}

    last = df.iloc[-1]
    prev = df.iloc[-2]

    buy = 0
    sell = 0
    reasons_buy = []
    reasons_sell = []

    if last["ema50"] > last["ema200"]:
        buy += 18
        reasons_buy.append(f"{label}: EMA50 بالای EMA200 است.")
    elif last["ema50"] < last["ema200"]:
        sell += 18
        reasons_sell.append(f"{label}: EMA50 پایین EMA200 است.")

    if last["close"] > last["ema20"]:
        buy += 7
        reasons_buy.append(f"{label}: قیمت بالای EMA20 است.")
    elif last["close"] < last["ema20"]:
        sell += 7
        reasons_sell.append(f"{label}: قیمت پایین EMA20 است.")

    if last["macd"] > last["macd_signal"]:
        buy += 9
        reasons_buy.append(f"{label}: MACD صعودی است.")
    elif last["macd"] < last["macd_signal"]:
        sell += 9
        reasons_sell.append(f"{label}: MACD نزولی است.")

    if last["macd_hist"] > prev["macd_hist"]:
        buy += 5
        reasons_buy.append(f"{label}: هیستوگرام MACD در حال تقویت صعودی است.")
    elif last["macd_hist"] < prev["macd_hist"]:
        sell += 5
        reasons_sell.append(f"{label}: هیستوگرام MACD در حال تقویت نزولی است.")

    if last["rsi"] > prev["rsi"]:
        buy += 6
        reasons_buy.append(f"{label}: RSI رو به افزایش است.")
    elif last["rsi"] < prev["rsi"]:
        sell += 6
        reasons_sell.append(f"{label}: RSI رو به کاهش است.")

    if 45 <= last["rsi"] <= 68:
        buy += 4
    if 32 <= last["rsi"] <= 55:
        sell += 4

    if last.get("adx", 0) >= 18:
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
            "atr": _round_price(last["atr"], symbol),
            "adx": round(float(last.get("adx", 0)), 2),
        },
    }

def _make_levels(symbol: str, direction: str, price: float, atr: float):
    if not atr or atr <= 0:
        return None, None, None, None
    if direction == "BUY":
        entry = price
        sl = price - (atr * 1.2)
        tp1 = price + (atr * 1.2)
        tp2 = price + (atr * 2.2)
    elif direction == "SELL":
        entry = price
        sl = price + (atr * 1.2)
        tp1 = price - (atr * 1.2)
        tp2 = price - (atr * 2.2)
    else:
        return None, None, None, None
    return (
        _round_price(entry, symbol),
        _round_price(sl, symbol),
        _round_price(tp1, symbol),
        _round_price(tp2, symbol),
    )

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

    weights = {"4H": 1.2, "1H": 1.3, "15M": 1.1, "5M": 1.0}
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

    total = max(buy_score + sell_score, 1)
    buy_percent = round((buy_score / total) * 100, 1)
    sell_percent = round((sell_score / total) * 100, 1)

    if buy_percent - sell_percent >= 8:
        direction = "BUY"
        prediction_score = min(100, round(buy_percent, 1))
        reasons = buy_reasons[:12]
    elif sell_percent - buy_percent >= 8:
        direction = "SELL"
        prediction_score = min(100, round(sell_percent, 1))
        reasons = sell_reasons[:12]
    else:
        direction = "NEUTRAL"
        prediction_score = round(max(buy_percent, sell_percent), 1)
        reasons = ["اختلاف امتیاز خرید و فروش کافی نیست؛ بازار خنثی یا نامشخص است."]

    entry_score = 0
    entry_reasons = []
    status = "PREDICTION_ONLY"
    entry = stop_loss = tp1 = tp2 = None

    entry_tf = analyses.get("5M")
    if direction in ("BUY", "SELL") and entry_tf:
        last = entry_tf["last"]
        if direction == "BUY":
            if last["close"] > last["ema20"]:
                entry_score += 30
                entry_reasons.append("5M: قیمت بالای EMA20 است.")
            if last["macd_hist"] > 0:
                entry_score += 25
                entry_reasons.append("5M: هیستوگرام MACD مثبت است.")
            if last["rsi"] >= 50:
                entry_score += 20
                entry_reasons.append("5M: RSI بالای 50 است.")
        else:
            if last["close"] < last["ema20"]:
                entry_score += 30
                entry_reasons.append("5M: قیمت پایین EMA20 است.")
            if last["macd_hist"] < 0:
                entry_score += 25
                entry_reasons.append("5M: هیستوگرام MACD منفی است.")
            if last["rsi"] <= 50:
                entry_score += 20
                entry_reasons.append("5M: RSI پایین 50 است.")

        if last["adx"] >= 18:
            entry_score += 10
            entry_reasons.append("5M: ADX قابل قبول است.")

        if prediction_score >= 65:
            entry_score += 15

        entry_score = min(100, entry_score)

        if prediction_score >= 65 and entry_score >= 55:
            entry, stop_loss, tp1, tp2 = _make_levels(symbol, direction, float(price_data["price"]), float(last["atr"] or 0))
            status = "SIGNAL"
        elif prediction_score < 60:
            status = "NO_TRADE"
        else:
            status = "PREDICTION_ONLY"

    # خبر فقط به عنوان هشدار نمایش داده می‌شود و هیچ سیگنالی را بلاک نمی‌کند.
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
    }
