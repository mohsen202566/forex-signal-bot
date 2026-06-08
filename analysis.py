import math
from datetime import datetime
from typing import Dict, Any, List

import pandas as pd
import ta

from config import MIN_SIGNAL_SCORE
from data_provider import get_latest_price, get_candles
from news_engine import get_news_risk_for_symbol


def _round_price(symbol: str, value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    digits = 2 if symbol == "XAU/USD" else (3 if "JPY" in symbol else 5)
    return round(float(value), digits)


def _safe_round(value, ndigits=5):
    try:
        if value is None or math.isnan(float(value)):
            return None
        return round(float(value), ndigits)
    except Exception:
        return None


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
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
    df["body"] = (df["close"] - df["open"]).abs()
    df["range"] = (df["high"] - df["low"]).replace(0, pd.NA)
    df["body_ratio"] = (df["body"] / df["range"]).fillna(0)
    return df


def load_tf(symbol: str, interval: str, outputsize: int = 250):
    data = get_candles(symbol, interval=interval, outputsize=outputsize)
    if not data["success"]:
        return data
    try:
        df = calculate_indicators(data["data"])
        df = df.dropna().reset_index(drop=True)
        if len(df) < 5:
            return {"success": False, "error": f"دیتای کافی بعد از محاسبه اندیکاتورها برای {interval} وجود ندارد."}
        return {"success": True, "data": df}
    except Exception as e:
        return {"success": False, "error": f"خطا در محاسبه اندیکاتورها برای {interval}: {e}"}


def tf_bias(df: pd.DataFrame, weight: int, label: str) -> Dict[str, Any]:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    buy = sell = 0
    reasons = []

    if last["ema50"] > last["ema200"]:
        buy += weight
        reasons.append(f"{label}: EMA50 بالای EMA200 است؛ بایاس صعودی.")
    elif last["ema50"] < last["ema200"]:
        sell += weight
        reasons.append(f"{label}: EMA50 پایین EMA200 است؛ بایاس نزولی.")

    if last["close"] > last["ema20"]:
        buy += max(1, weight // 3)
    elif last["close"] < last["ema20"]:
        sell += max(1, weight // 3)

    if last["macd_hist"] > prev["macd_hist"]:
        buy += max(1, weight // 3)
        reasons.append(f"{label}: مومنتوم MACD رو به رشد است.")
    elif last["macd_hist"] < prev["macd_hist"]:
        sell += max(1, weight // 3)
        reasons.append(f"{label}: مومنتوم MACD رو به ضعف/نزول است.")

    if last["rsi"] > prev["rsi"]:
        buy += max(1, weight // 4)
    elif last["rsi"] < prev["rsi"]:
        sell += max(1, weight // 4)

    if last.get("adx", 0) >= 20:
        if buy > sell:
            buy += 2
        elif sell > buy:
            sell += 2

    return {"buy": buy, "sell": sell, "reasons": reasons, "last": last, "prev": prev}


def detect_entry(symbol: str, direction: str, df5: pd.DataFrame, price: float):
    last = df5.iloc[-1]
    prev = df5.iloc[-2]
    prev2 = df5.iloc[-3]
    score = 0
    reasons = []

    if direction == "BUY":
        if last["close"] > last["ema20"]:
            score += 18
            reasons.append("5M: قیمت بالای EMA20 است؛ ورود خرید سریع‌تر تایید می‌شود.")
        if last["macd_hist"] > prev["macd_hist"] > prev2["macd_hist"]:
            score += 18
            reasons.append("5M: MACD Histogram دو کندل پشت‌سرهم قوی‌تر شده.")
        if last["rsi"] > prev["rsi"]:
            score += 14
            reasons.append("5M: RSI Slope صعودی است.")
        if last["close"] > last["open"] and last["body_ratio"] >= 0.45:
            score += 12
            reasons.append("5M: کندل صعودی نسبتاً قوی دیده می‌شود.")
    elif direction == "SELL":
        if last["close"] < last["ema20"]:
            score += 18
            reasons.append("5M: قیمت پایین EMA20 است؛ ورود فروش سریع‌تر تایید می‌شود.")
        if last["macd_hist"] < prev["macd_hist"] < prev2["macd_hist"]:
            score += 18
            reasons.append("5M: MACD Histogram دو کندل پشت‌سرهم ضعیف‌تر شده.")
        if last["rsi"] < prev["rsi"]:
            score += 14
            reasons.append("5M: RSI Slope نزولی است.")
        if last["close"] < last["open"] and last["body_ratio"] >= 0.45:
            score += 12
            reasons.append("5M: کندل نزولی نسبتاً قوی دیده می‌شود.")

    atr = float(last["atr"])
    if not atr or math.isnan(atr) or atr <= 0:
        atr = abs(float(last["close"]) - float(prev["close"])) or price * 0.001

    # Scalp-oriented TP/SL for 5M/15M entry
    if direction == "BUY":
        entry = price
        sl = entry - atr * 1.05
        tp1 = entry + atr * 0.90
        tp2 = entry + atr * 1.60
    elif direction == "SELL":
        entry = price
        sl = entry + atr * 1.05
        tp1 = entry - atr * 0.90
        tp2 = entry - atr * 1.60
    else:
        entry = sl = tp1 = tp2 = None

    active = score >= 42
    return {
        "entry_active": active,
        "entry_score": min(score, 100),
        "entry": _round_price(symbol, entry),
        "stop_loss": _round_price(symbol, sl),
        "tp1": _round_price(symbol, tp1),
        "tp2": _round_price(symbol, tp2),
        "atr": _round_price(symbol, atr),
        "reasons": reasons,
    }


def analyze_pair(symbol: str) -> Dict[str, Any]:
    price_data = get_latest_price(symbol)
    if not price_data["success"]:
        return {"success": False, "error": price_data["error"]}
    price = float(price_data["price"])

    loaded = {}
    for tf, interval in [("4H", "4h"), ("1H", "1h"), ("15M", "15min"), ("5M", "5min")]:
        out = load_tf(symbol, interval, 250)
        if not out["success"]:
            return {"success": False, "error": f"{tf}: {out['error']}"}
        loaded[tf] = out["data"]

    # Higher TF predicts direction. 5M is mostly entry trigger.
    weights = {"4H": 18, "1H": 24, "15M": 18, "5M": 10}
    buy_score = sell_score = 0
    reasons: List[str] = []
    tf_summary = {}

    for tf in ["4H", "1H", "15M", "5M"]:
        b = tf_bias(loaded[tf], weights[tf], tf)
        buy_score += b["buy"]
        sell_score += b["sell"]
        reasons.extend(b["reasons"][:2])
        last = b["last"]
        tf_summary[tf] = {
            "close": _safe_round(last["close"], 5),
            "ema20": _safe_round(last["ema20"], 5),
            "ema50": _safe_round(last["ema50"], 5),
            "ema200": _safe_round(last["ema200"], 5),
            "rsi": _safe_round(last["rsi"], 2),
            "macd_hist": _safe_round(last["macd_hist"], 6),
            "adx": _safe_round(last.get("adx", 0), 2),
        }

    gap = abs(buy_score - sell_score)
    if buy_score > sell_score and gap >= 8:
        direction = "BUY"
    elif sell_score > buy_score and gap >= 8:
        direction = "SELL"
    else:
        direction = "NEUTRAL"

    base_score = 50 + min(gap, 35)
    if direction != "NEUTRAL":
        # Add alignment bonus when 4H and 1H agree with chosen direction.
        h4_bias = "BUY" if tf_summary["4H"]["ema50"] > tf_summary["4H"]["ema200"] else "SELL"
        h1_bias = "BUY" if tf_summary["1H"]["ema50"] > tf_summary["1H"]["ema200"] else "SELL"
        if h4_bias == direction:
            base_score += 5
        if h1_bias == direction:
            base_score += 7
    else:
        reasons.append("اختلاف امتیاز خرید و فروش کم است؛ بازار برای پیش‌بینی قطعی مناسب نیست.")

    news = get_news_risk_for_symbol(symbol)
    if news.get("blocked"):
        base_score -= 12
        reasons.append("فیلتر اخبار: نزدیک خبر مهم هستیم؛ ریسک سیگنال کاهش پیدا کرد.")
    elif news.get("risk_level") == "MEDIUM":
        base_score -= 5

    prediction_score = max(0, min(100, round(base_score, 1)))
    entry_data = detect_entry(symbol, direction, loaded["5M"], price) if direction != "NEUTRAL" else {
        "entry_active": False, "entry_score": 0, "entry": None, "stop_loss": None, "tp1": None, "tp2": None, "atr": None, "reasons": []
    }

    final_status = "SIGNAL" if direction != "NEUTRAL" and prediction_score >= MIN_SIGNAL_SCORE and entry_data["entry_active"] and not news.get("blocked") else "PREDICTION_ONLY"
    if direction == "NEUTRAL":
        final_status = "NO_TRADE"
    if news.get("blocked"):
        final_status = "NEWS_BLOCKED"

    return {
        "success": True,
        "symbol": symbol,
        "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "price": _round_price(symbol, price),
        "direction": direction,
        "prediction_score": prediction_score,
        "score": prediction_score,
        "buy_score": round(buy_score, 1),
        "sell_score": round(sell_score, 1),
        "status": final_status,
        "entry_active": entry_data["entry_active"],
        "entry_score": entry_data["entry_score"],
        "entry": entry_data["entry"],
        "stop_loss": entry_data["stop_loss"],
        "tp1": entry_data["tp1"],
        "tp2": entry_data["tp2"],
        "atr": entry_data["atr"],
        "tf_summary": tf_summary,
        "news": news,
        "reasons": reasons[:8],
        "entry_reasons": entry_data["reasons"][:6],
    }
