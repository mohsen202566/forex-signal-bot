# -*- coding: utf-8 -*-
"""Prediction-focused Forex analysis engine.

Architecture:
- 4H/1H = soft higher-timeframe market direction context
- 30M/15M = setup quality and readiness
- 5M = fast activation trigger
- Buy/Sell Power 2C/3C = activation confirmation only, not prediction scoring
- Fresh Momentum = activation confirmation only, not prediction scoring
- News is warning-only and never blocks signals

This file is UTF-8/Persian safe and VPS-safe.
"""

import math
from typing import Dict, Optional, Tuple

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

# Balanced prediction/activation thresholds.
SETUP_MIN_SCORE = 62
ACTIVATION_MIN_SCORE = 70
MIN_DIRECTION_GAP = 8

# Helps avoid score inflation when one side is too dominant by pure percentage math.
NEUTRAL_SCORE_BASE = 10

# Buy/Sell Power thresholds. These confirm entry activation only; they do not add prediction points.
POWER_2_CANDLE_MIN = 60
POWER_3_CANDLE_MIN = 55

# Soft higher-timeframe bias. It is intentionally small to keep scalp entries fast.
HTF_CONTEXT_BIAS_POINTS = 5


SCALP_SYMBOLS_2_DIGITS = {
    "XAU/USD", "XAG/USD", "WTI/USD", "BRENT/USD", "US30", "NAS100",
    "SPX500", "DAX40", "DXY", "BTC/USD", "ETH/USD", "SOL/USD",
}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
    except Exception:
        return default


def _round_price(value, symbol: str = ""):
    value = _safe_float(value, default=float("nan"))
    if math.isnan(value):
        return None

    if symbol in SCALP_SYMBOLS_2_DIGITS:
        digits = 2
    elif "JPY" in symbol:
        digits = 3
    else:
        digits = 5

    return round(value, digits)


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add indicators required by prediction and entry engines."""
    df = df.copy()
    df["ema20"] = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
    df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
    df["ema200"] = ta.trend.EMAIndicator(df["close"], window=200).ema_indicator()
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()
    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range()

    try:
        df["adx"] = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14).adx()
    except Exception:
        df["adx"] = 0

    return df


def _tf_analysis(symbol: str, label: str, interval: str) -> Dict:
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

    # Trend context / direction.
    if last["ema50"] > last["ema200"]:
        buy += 16
        reasons_buy.append(f"{label}: EMA50 بالای EMA200 است.")
    elif last["ema50"] < last["ema200"]:
        sell += 16
        reasons_sell.append(f"{label}: EMA50 پایین EMA200 است.")

    # Local positioning.
    if last["close"] > last["ema20"]:
        buy += 8
        reasons_buy.append(f"{label}: قیمت بالای EMA20 است.")
    elif last["close"] < last["ema20"]:
        sell += 8
        reasons_sell.append(f"{label}: قیمت پایین EMA20 است.")

    # MACD direction.
    if last["macd"] > last["macd_signal"]:
        buy += 9
        reasons_buy.append(f"{label}: MACD صعودی است.")
    elif last["macd"] < last["macd_signal"]:
        sell += 9
        reasons_sell.append(f"{label}: MACD نزولی است.")

    # Momentum acceleration.
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

    # RSI slope, not overbought/oversold entry trigger.
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

    # Soft RSI zone support.
    if 44 <= last["rsi"] <= 68:
        buy += 4
    if 32 <= last["rsi"] <= 56:
        sell += 4

    # ADX only strengthens the side already winning inside that TF.
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
            "rsi": round(_safe_float(last["rsi"]), 2),
            "macd": round(_safe_float(last["macd"]), 5),
            "macd_signal": round(_safe_float(last["macd_signal"]), 5),
            "macd_hist": round(_safe_float(last["macd_hist"]), 5),
            "prev_macd_hist": round(_safe_float(prev["macd_hist"]), 5),
            "prev2_macd_hist": round(_safe_float(prev2["macd_hist"]), 5),
            "prev_rsi": round(_safe_float(prev["rsi"]), 2),
            "prev2_rsi": round(_safe_float(prev2["rsi"]), 2),
            "atr": _round_price(last["atr"], symbol),
            "adx": round(_safe_float(last.get("adx", 0)), 2),
        },
    }


def _make_levels(symbol: str, direction: str, price: float, atr: float):
    atr = _safe_float(atr)
    price = _safe_float(price)
    if atr <= 0 or price <= 0:
        return None, None, None, None

    # Scalp-oriented levels: TP1 fast, TP2 separate, SL moderate.
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


def _calculate_buy_sell_power(df: pd.DataFrame, candles: int) -> Tuple[float, float]:
    """Calculate short-term Buy/Sell Power from candle bodies.

    This is intentionally used as an entry confirmation, not as a prediction-score source.
    """
    try:
        if df is None or len(df) < candles:
            return 50.0, 50.0

        recent = df.tail(candles)
        buy_body = 0.0
        sell_body = 0.0

        for _, row in recent.iterrows():
            body = _safe_float(row.get("close")) - _safe_float(row.get("open"))
            if body > 0:
                buy_body += abs(body)
            elif body < 0:
                sell_body += abs(body)

        total = buy_body + sell_body
        if total <= 0:
            return 50.0, 50.0

        return round((buy_body / total) * 100, 1), round((sell_body / total) * 100, 1)
    except Exception:
        return 50.0, 50.0


def _power_entry_confirmation(direction: str, entry_tf: Dict) -> Tuple[bool, str, Dict]:
    """Buy/Sell Power confirmation layer for activation."""
    df = entry_tf.get("df")
    buy2, sell2 = _calculate_buy_sell_power(df, 2)
    buy3, sell3 = _calculate_buy_sell_power(df, 3)

    power_info = {
        "buy2": buy2,
        "sell2": sell2,
        "buy3": buy3,
        "sell3": sell3,
    }

    if direction == "BUY":
        ok = buy2 >= POWER_2_CANDLE_MIN and buy3 >= POWER_3_CANDLE_MIN
        if ok:
            reason = f"تایید قدرت خرید: Buy Power 2C={buy2}% و 3C={buy3}% است."
        else:
            reason = f"قدرت خرید هنوز کافی نیست: Buy Power 2C={buy2}% و 3C={buy3}%."
        return ok, reason, power_info

    if direction == "SELL":
        ok = sell2 >= POWER_2_CANDLE_MIN and sell3 >= POWER_3_CANDLE_MIN
        if ok:
            reason = f"تایید قدرت فروش: Sell Power 2C={sell2}% و 3C={sell3}% است."
        else:
            reason = f"قدرت فروش هنوز کافی نیست: Sell Power 2C={sell2}% و 3C={sell3}%."
        return ok, reason, power_info

    return False, "قدرت خرید/فروش: جهت نامعتبر است.", power_info


def _fresh_momentum_confirmation(direction: str, entry_tf: Dict, power_info: Dict) -> Tuple[bool, str]:
    """Detect fresh 5M momentum for activation confirmation."""
    df = entry_tf.get("df")
    if df is None or len(df) < 4:
        return False, "Fresh Momentum: داده کافی برای بررسی مومنتوم تازه وجود ندارد."

    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]

        macd_last = _safe_float(last.get("macd_hist"))
        macd_prev = _safe_float(prev.get("macd_hist"))
        macd_prev2 = _safe_float(prev2.get("macd_hist"))
        rsi_last = _safe_float(last.get("rsi"))
        rsi_prev = _safe_float(prev.get("rsi"))
        rsi_prev2 = _safe_float(prev2.get("rsi"))

        macd_accel_up = macd_last > macd_prev > macd_prev2
        macd_accel_down = macd_last < macd_prev < macd_prev2
        rsi_up = rsi_last > rsi_prev > rsi_prev2
        rsi_down = rsi_last < rsi_prev < rsi_prev2

        buy2 = _safe_float(power_info.get("buy2"), 50.0)
        buy3 = _safe_float(power_info.get("buy3"), 50.0)
        sell2 = _safe_float(power_info.get("sell2"), 50.0)
        sell3 = _safe_float(power_info.get("sell3"), 50.0)

        if direction == "BUY":
            power_support = buy2 >= POWER_2_CANDLE_MIN or buy3 >= POWER_3_CANDLE_MIN
            ok = macd_accel_up and rsi_up and power_support
            if ok:
                return True, f"Fresh Momentum خرید تایید شد: MACD/RSI تازه صعودی شده و Buy Power 2C={buy2}% | 3C={buy3}% است."
            return False, f"Fresh Momentum خرید هنوز کامل نیست: Buy Power 2C={buy2}% | 3C={buy3}%."

        if direction == "SELL":
            power_support = sell2 >= POWER_2_CANDLE_MIN or sell3 >= POWER_3_CANDLE_MIN
            ok = macd_accel_down and rsi_down and power_support
            if ok:
                return True, f"Fresh Momentum فروش تایید شد: MACD/RSI تازه نزولی شده و Sell Power 2C={sell2}% | 3C={sell3}% است."
            return False, f"Fresh Momentum فروش هنوز کامل نیست: Sell Power 2C={sell2}% | 3C={sell3}%."

    except Exception:
        return False, "Fresh Momentum: خطا در محاسبه مومنتوم تازه."

    return False, "Fresh Momentum: جهت نامعتبر است."


def _fast_entry_score(direction: str, entry_tf: Dict, confirm_tf: Optional[Dict] = None) -> Tuple[int, list, bool, Dict]:
    """Fast entry trigger score plus mandatory activation confirmations."""
    score = 0
    reasons = []
    last = entry_tf["last"]

    if direction == "BUY":
        if last["close"] > last["ema20"]:
            score += 20
            reasons.append("5M: قیمت بالای EMA20 است.")
        if last["macd_hist"] > last.get("prev_macd_hist", 0):
            score += 18
            reasons.append("5M: هیستوگرام MACD در حال تقویت صعودی است.")
        if last["macd_hist"] > 0:
            score += 10
            reasons.append("5M: هیستوگرام MACD مثبت است.")
        if last["rsi"] >= 50:
            score += 14
            reasons.append("5M: RSI بالای 50 است.")
    elif direction == "SELL":
        if last["close"] < last["ema20"]:
            score += 20
            reasons.append("5M: قیمت پایین EMA20 است.")
        if last["macd_hist"] < last.get("prev_macd_hist", 0):
            score += 18
            reasons.append("5M: هیستوگرام MACD در حال تقویت نزولی است.")
        if last["macd_hist"] < 0:
            score += 10
            reasons.append("5M: هیستوگرام MACD منفی است.")
        if last["rsi"] <= 50:
            score += 14
            reasons.append("5M: RSI پایین 50 است.")

    if last.get("adx", 0) >= 16:
        score += 8
        reasons.append("5M: ADX برای اسکالپ قابل قبول است.")

    if confirm_tf:
        c = confirm_tf["last"]
        if direction == "BUY" and c["close"] > c["ema20"]:
            score += 10
            reasons.append("15M: قیمت با جهت خرید هم‌راستا است.")
        elif direction == "SELL" and c["close"] < c["ema20"]:
            score += 10
            reasons.append("15M: قیمت با جهت فروش هم‌راستا است.")

    power_ok, power_reason, power_info = _power_entry_confirmation(direction, entry_tf)
    fresh_ok, fresh_reason = _fresh_momentum_confirmation(direction, entry_tf, power_info)

    reasons.append(power_reason)
    reasons.append(fresh_reason)

    # Entry activation needs score + at least one real-time confirmation.
    activation_confirmed = power_ok or fresh_ok
    return min(100, int(score)), reasons, activation_confirmed, {
        "power_ok": power_ok,
        "fresh_momentum_ok": fresh_ok,
        **power_info,
    }


def _simple_tf_direction(item: Optional[Dict]) -> Optional[str]:
    if not item or not item.get("success"):
        return None
    buy = _safe_float(item.get("buy"))
    sell = _safe_float(item.get("sell"))
    if buy > sell:
        return "BUY"
    if sell > buy:
        return "SELL"
    return None


def _apply_higher_tf_context_bias(buy_score: float, sell_score: float, analyses: Dict) -> Tuple[float, float, Optional[str], Optional[str]]:
    """Apply soft 4H/1H context bias without hard-blocking counter-trend scalps."""
    trend_4h = _simple_tf_direction(analyses.get("4H"))
    trend_1h = _simple_tf_direction(analyses.get("1H"))

    if not trend_4h or not trend_1h or trend_4h != trend_1h:
        return buy_score, sell_score, None, None

    if trend_4h == "BUY":
        buy_score += HTF_CONTEXT_BIAS_POINTS
        sell_score = max(0, sell_score - HTF_CONTEXT_BIAS_POINTS)
        return buy_score, sell_score, "BUY", f"4H و 1H هم‌جهت خرید هستند؛ {HTF_CONTEXT_BIAS_POINTS} امتیاز به خرید اضافه و از فروش کم شد."

    if trend_4h == "SELL":
        sell_score += HTF_CONTEXT_BIAS_POINTS
        buy_score = max(0, buy_score - HTF_CONTEXT_BIAS_POINTS)
        return buy_score, sell_score, "SELL", f"4H و 1H هم‌جهت فروش هستند؛ {HTF_CONTEXT_BIAS_POINTS} امتیاز به فروش اضافه و از خرید کم شد."

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

    # Scalp hierarchy: fast TFs have more influence, HTFs provide direction context.
    weights = {"4H": 0.80, "1H": 1.00, "30M": 1.15, "15M": 1.35, "5M": 1.55}
    buy_score = 0.0
    sell_score = 0.0
    buy_reasons = []
    sell_reasons = []
    tf_summary = {}

    for label, item in analyses.items():
        w = weights.get(label, 1.0)
        buy_score += item["buy"] * w
        sell_score += item["sell"] * w
        buy_reasons.extend(item["reasons_buy"])
        sell_reasons.extend(item["reasons_sell"])
        tf_summary[label] = item["last"]

    buy_score, sell_score, htf_bias_direction, htf_bias_reason = _apply_higher_tf_context_bias(
        buy_score, sell_score, analyses
    )

    if htf_bias_reason:
        if htf_bias_direction == "BUY":
            buy_reasons.insert(0, htf_bias_reason)
        elif htf_bias_direction == "SELL":
            sell_reasons.insert(0, htf_bias_reason)

    # Neutral base keeps scores from constantly inflating into 95-99 range.
    total = max(buy_score + sell_score + (NEUTRAL_SCORE_BASE * 2), 1)
    buy_percent = round(((buy_score + NEUTRAL_SCORE_BASE) / total) * 100, 1)
    sell_percent = round(((sell_score + NEUTRAL_SCORE_BASE) / total) * 100, 1)

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
    entry_confirmations = {}
    status = "NO_TRADE"
    entry = stop_loss = tp1 = tp2 = None

    if direction in ("BUY", "SELL") and prediction_score >= SETUP_MIN_SCORE:
        entry_tf = analyses.get("5M") or analyses.get("15M")
        confirm_tf = analyses.get("15M")
        if entry_tf:
            entry_score, entry_reasons, activation_confirmed, entry_confirmations = _fast_entry_score(
                direction, entry_tf, confirm_tf
            )
            atr = _safe_float((entry_tf.get("last") or {}).get("atr"))
            entry, stop_loss, tp1, tp2 = _make_levels(symbol, direction, _safe_float(price_data.get("price")), atr)

            if entry is not None and stop_loss is not None and tp1 is not None:
                if entry_score >= ACTIVATION_MIN_SCORE and activation_confirmed:
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
        "price": _round_price(price_data.get("price"), symbol),
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
        "entry_confirmations": entry_confirmations,
        "tf_summary": tf_summary,
        "news": news,
        "errors": errors,
    }
