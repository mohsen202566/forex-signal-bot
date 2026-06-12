# -*- coding: utf-8 -*-
"""
Balanced Classic Technical Engine

معماری این نسخه:
- بدون Setup / Watchlist / Pending
- ورود مستقیم فقط با تحلیل تکنیکال بالانس
- تمرکز ورود روی 15M و 30M؛ وزن 15M بیشتر است
- ADX زیر 20 رد کامل
- Auto Signal عملاً زیر 85 رد می‌شود
- Order Block فقط جریمه نرم 2 تا 3 امتیازی دارد؛ هم‌جهت امتیاز اضافه نمی‌گیرد
- Fear & Greed، Altseason و وضعیت کلی بازار فقط اثر نرم دارند
- SL/TP با حمایت و مقاومت 5M تنظیم می‌شود؛ TP قبل از سطح و SL پشت سطح با buffer هوشمند
"""

import time
from urllib.request import urlopen, Request

import ccxt
import pandas as pd
import ta

from config import MIN_DIRECT_SCORE, MIN_MANUAL_CONFIRMATIONS, MIN_ADX_FOR_TREND


exchange = ccxt.okx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"},
})

# Main thresholds
AUTO_DIRECT_SCORE_MIN = 85
ADX_HARD_MIN = max(float(MIN_ADX_FOR_TREND), 20.0)

# Trade levels
SL_ATR_MULTIPLIER = 1.25
TP1_ATR_MULTIPLIER = 0.75
TP2_ATR_MULTIPLIER = 1.40
POWER2_SIGNAL_MIN = 80.0
MIN_SL_ATR_MULTIPLIER = 1.25
MAX_SL_ATR_MULTIPLIER = 1.90

# Soft context cache
_CONTEXT_CACHE = {"ts": 0, "data": None}
_CONTEXT_CACHE_SECONDS = 900


# ---------- Basic helpers ----------
def to_okx_symbol(symbol):
    coin = str(symbol).upper().replace("USDT", "")
    return f"{coin}/USDT:USDT"


def safe_round(value, digits=8):
    try:
        if value is None:
            return None
        return round(float(value), digits)
    except Exception:
        return None


def cap_score(value):
    try:
        return max(0, min(100, int(round(float(value)))))
    except Exception:
        return 0


def get_klines(symbol, interval="15m", limit=260, include_current=False):
    data = exchange.fetch_ohlcv(to_okx_symbol(symbol), timeframe=interval, limit=limit)
    if not data or len(data) < 220:
        raise Exception(f"داده کافی برای {symbol} در تایم {interval} دریافت نشد")

    df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna()
    if not include_current:
        df = df.iloc[:-1]

    if len(df) < 210:
        raise Exception(f"داده کندل کافی برای {symbol} در تایم {interval} کامل نیست")

    return df


def add_indicators(df):
    df = df.copy()

    df["ema20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)

    adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
    df["adx"] = adx.adx()

    typical = (df["high"] + df["low"] + df["close"]) / 3
    volume_sum = df["volume"].cumsum().replace(0, pd.NA)
    df["vwap"] = (typical * df["volume"]).cumsum() / volume_sum
    df["volume_ma20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma20"].replace(0, pd.NA)

    df = df.dropna()
    if len(df) < 60:
        raise Exception("اندیکاتورها کامل محاسبه نشدند")
    return df


# ---------- Technical components ----------
def trend_direction(df):
    last = df.iloc[-1]
    close = float(last["close"])

    if close > last["ema20"] > last["ema50"] > last["ema200"]:
        return "bullish"
    if close < last["ema20"] < last["ema50"] < last["ema200"]:
        return "bearish"
    if close > last["ema50"] and close > last["ema200"]:
        return "weak_bullish"
    if close < last["ema50"] and close < last["ema200"]:
        return "weak_bearish"
    return "range"


def buy_sell_power(df, candles=20):
    recent = df.tail(candles)
    green = recent[recent["close"] > recent["open"]]["volume"].sum()
    red = recent[recent["close"] < recent["open"]]["volume"].sum()
    total = green + red
    if total <= 0:
        return 50.0, 50.0
    return round((green / total) * 100, 1), round((red / total) * 100, 1)


def support_resistance(df, lookback=100):
    recent = df.tail(lookback)
    price = float(recent.iloc[-1]["close"])
    lows = []
    highs = []
    window = 3

    for i in range(window, len(recent) - window):
        row = recent.iloc[i]
        left = recent.iloc[i - window:i]
        right = recent.iloc[i + 1:i + 1 + window]

        if row["low"] <= left["low"].min() and row["low"] <= right["low"].min():
            lows.append(float(row["low"]))
        if row["high"] >= left["high"].max() and row["high"] >= right["high"].max():
            highs.append(float(row["high"]))

    below = [x for x in lows if x < price]
    above = [x for x in highs if x > price]

    support = max(below) if below else float(recent["low"].min())
    resistance = min(above) if above else float(recent["high"].max())
    return support, resistance




def support_resistance_levels(df, lookback=140, swing_window=3, atr=None):
    """
    استخراج چند سطح حمایت/مقاومت از کندل‌های 5M.
    سطوح نزدیک به هم با ATR ادغام می‌شوند تا TP/SL روی نویز کندلی تنظیم نشود.
    """
    recent = df.tail(lookback).copy()
    price = float(recent.iloc[-1]["close"])
    lows = []
    highs = []

    for i in range(swing_window, len(recent) - swing_window):
        row = recent.iloc[i]
        left = recent.iloc[i - swing_window:i]
        right = recent.iloc[i + 1:i + 1 + swing_window]

        if row["low"] <= left["low"].min() and row["low"] <= right["low"].min():
            lows.append(float(row["low"]))
        if row["high"] >= left["high"].max() and row["high"] >= right["high"].max():
            highs.append(float(row["high"]))

    # fallback if swing levels are not enough
    if not lows:
        lows = [float(recent["low"].min())]
    if not highs:
        highs = [float(recent["high"].max())]

    merge_distance = max(float(atr or 0) * 0.20, price * 0.0008)

    def merge_levels(levels):
        merged = []
        for level in sorted(levels):
            if not merged or abs(level - merged[-1]) > merge_distance:
                merged.append(level)
            else:
                merged[-1] = (merged[-1] + level) / 2
        return merged

    support_levels = [x for x in merge_levels(lows) if x < price]
    resistance_levels = [x for x in merge_levels(highs) if x > price]

    return {
        "supports": sorted(support_levels, reverse=True),  # closest first
        "resistances": sorted(resistance_levels),           # closest first
        "nearest_support": support_levels[-1] if support_levels else float(recent["low"].min()),
        "nearest_resistance": resistance_levels[0] if resistance_levels else float(recent["high"].max()),
    }


def pick_safe_target(direction, price, atr, levels, fallback_multiplier, level_buffer):
    """
    TP را دقیقاً روی حمایت/مقاومت نمی‌گذارد.
    LONG: کمی قبل از مقاومت. SHORT: کمی قبل از حمایت.
    اگر سطح خیلی نزدیک یا غیرمنطقی باشد، fallback ATR استفاده می‌شود.
    """
    min_tp_distance = max(atr * 0.35, price * 0.0010)
    fallback = price + atr * fallback_multiplier if direction == "LONG" else price - atr * fallback_multiplier

    if direction == "LONG":
        for resistance in levels:
            target = resistance - level_buffer
            if target > price and abs(target - price) >= min_tp_distance:
                return target
    else:
        for support in levels:
            target = support + level_buffer
            if target < price and abs(target - price) >= min_tp_distance:
                return target

    return fallback

def vwap_status(df):
    last = df.iloc[-1]
    if last["close"] > last["vwap"]:
        return "above_vwap"
    if last["close"] < last["vwap"]:
        return "below_vwap"
    return "near_vwap"


def candle_pattern(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    body = abs(float(last["close"]) - float(last["open"]))
    rng = max(float(last["high"]) - float(last["low"]), 1e-12)
    upper = float(last["high"]) - max(float(last["close"]), float(last["open"]))
    lower = min(float(last["close"]), float(last["open"])) - float(last["low"])

    if last["close"] > last["open"] and prev["close"] < prev["open"] and last["close"] > prev["open"]:
        return "bullish_engulfing"
    if last["close"] < last["open"] and prev["close"] > prev["open"] and last["close"] < prev["open"]:
        return "bearish_engulfing"
    if lower > body * 2 and upper < body * 1.2:
        return "bullish_pinbar"
    if upper > body * 2 and lower < body * 1.2:
        return "bearish_pinbar"
    if body / rng >= 0.6:
        return "bullish_strong" if last["close"] > last["open"] else "bearish_strong"
    return "neutral"


def volume_quality(df):
    last = df.iloc[-1]
    try:
        ratio = float(last["volume_ratio"])
    except Exception:
        ratio = 1.0

    if ratio >= 1.40:
        return "high_volume", ratio
    if ratio >= 1.05:
        return "normal_volume", ratio
    if ratio <= 0.70:
        return "weak_volume", ratio
    return "neutral_volume", ratio


def simple_order_block(df):
    """تشخیص سبک و نرم OB. فقط برای جریمه خلاف جهت استفاده می‌شود؛ امتیاز مثبت نمی‌دهد."""
    recent = df.tail(30)
    avg_body = (recent["close"] - recent["open"]).abs().rolling(10).mean().iloc[-1]
    avg_body = float(avg_body) if pd.notna(avg_body) and avg_body > 0 else 0
    if avg_body <= 0:
        return "neutral_order_block"

    for i in range(len(recent) - 4, 1, -1):
        prev = recent.iloc[i - 1]
        cur = recent.iloc[i]
        cur_body = abs(float(cur["close"] - cur["open"]))
        if cur_body < avg_body * 1.25:
            continue
        # bullish displacement after a red candle
        if prev["close"] < prev["open"] and cur["close"] > cur["open"] and cur["close"] > prev["high"]:
            return "bullish_order_block"
        # bearish displacement after a green candle
        if prev["close"] > prev["open"] and cur["close"] < cur["open"] and cur["close"] < prev["low"]:
            return "bearish_order_block"
    return "neutral_order_block"


# ---------- Soft market context ----------
def fetch_fear_greed_value():
    try:
        req = Request("https://api.alternative.me/fng/?limit=1", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=4) as r:
            import json
            data = json.loads(r.read().decode("utf-8"))
        value = int(data["data"][0]["value"])
        return value
    except Exception:
        return None


def return_pct(df, candles=20):
    try:
        recent = df.tail(candles)
        first = float(recent.iloc[0]["close"])
        last = float(recent.iloc[-1]["close"])
        if first <= 0:
            return 0.0
        return ((last - first) / first) * 100
    except Exception:
        return 0.0


def get_soft_context():
    now = int(time.time())
    if _CONTEXT_CACHE["data"] is not None and now - _CONTEXT_CACHE["ts"] < _CONTEXT_CACHE_SECONDS:
        return _CONTEXT_CACHE["data"]

    context = {
        "market_regime": "neutral_market",
        "altseason_status": "neutral_altseason",
        "fear_greed_value": None,
        "fear_greed_status": "neutral_fear_greed",
    }

    try:
        btc_1h = add_indicators(get_klines("BTCUSDT", "1h"))
        btc_4h = add_indicators(get_klines("BTCUSDT", "4h"))
        btc_trend_1h = trend_direction(btc_1h)
        btc_trend_4h = trend_direction(btc_4h)
        if btc_trend_1h in ["bullish", "weak_bullish"] and btc_trend_4h in ["bullish", "weak_bullish"]:
            context["market_regime"] = "bullish_market"
        elif btc_trend_1h in ["bearish", "weak_bearish"] and btc_trend_4h in ["bearish", "weak_bearish"]:
            context["market_regime"] = "bearish_market"
        else:
            context["market_regime"] = "range_market"

        eth_1d = add_indicators(get_klines("ETHUSDT", "1d"))
        btc_1d = add_indicators(get_klines("BTCUSDT", "1d"))
        eth_ret = return_pct(eth_1d, 20)
        btc_ret = return_pct(btc_1d, 20)
        if eth_ret > btc_ret + 3:
            context["altseason_status"] = "altseason_positive"
        elif btc_ret > eth_ret + 3:
            context["altseason_status"] = "altseason_negative"
        else:
            context["altseason_status"] = "neutral_altseason"
    except Exception:
        pass

    fg = fetch_fear_greed_value()
    context["fear_greed_value"] = fg
    if fg is not None:
        if fg >= 70:
            context["fear_greed_status"] = "greed_high"
        elif fg >= 55:
            context["fear_greed_status"] = "greed_moderate"
        elif fg <= 25:
            context["fear_greed_status"] = "fear_extreme"
        elif fg <= 40:
            context["fear_greed_status"] = "fear_moderate"
        else:
            context["fear_greed_status"] = "neutral_fear_greed"

    _CONTEXT_CACHE["ts"] = now
    _CONTEXT_CACHE["data"] = context
    return context


def apply_soft_context(symbol, long_score, short_score, long_reasons, short_reasons, context):
    symbol = str(symbol).upper()
    is_btc = symbol.startswith("BTC")

    # Overall market regime: very soft influence
    if context.get("market_regime") == "bullish_market":
        long_score += 3
        short_score -= 2
        long_reasons.append("وضعیت کلی بازار صعودی است؛ اثر نرم مثبت برای لانگ")
    elif context.get("market_regime") == "bearish_market":
        short_score += 3
        long_score -= 2
        short_reasons.append("وضعیت کلی بازار نزولی است؛ اثر نرم مثبت برای شورت")
    elif context.get("market_regime") == "range_market":
        long_score -= 1
        short_score -= 1
        long_reasons.append("بازار کلی رنج است؛ امتیاز کمی محافظه‌کار شد")
        short_reasons.append("بازار کلی رنج است؛ امتیاز کمی محافظه‌کار شد")

    # Altseason: soft effect mostly for non-BTC alts
    if not is_btc:
        if context.get("altseason_status") == "altseason_positive":
            long_score += 2
            short_score -= 1
            long_reasons.append("وضعیت Altseason مثبت است؛ اثر نرم برای لانگ آلت‌ها")
        elif context.get("altseason_status") == "altseason_negative":
            short_score += 2
            long_score -= 1
            short_reasons.append("وضعیت Altseason ضعیف است؛ اثر نرم برای شورت آلت‌ها")

    # Fear & Greed: soft, not a blocker
    fg_status = context.get("fear_greed_status")
    if fg_status == "greed_high":
        long_score -= 2
        short_score += 1
        short_reasons.append("ترس و طمع در ناحیه طمع بالا است؛ لانگ کمی محافظه‌کار شد")
    elif fg_status == "greed_moderate":
        long_score += 1
        long_reasons.append("ترس و طمع تمایل مثبت دارد؛ اثر نرم برای لانگ")
    elif fg_status == "fear_extreme":
        short_score -= 2
        long_score += 1
        long_reasons.append("ترس شدید بازار؛ شورت کمی محافظه‌کار شد")
    elif fg_status == "fear_moderate":
        short_score += 1
        short_reasons.append("ترس بازار متوسط است؛ اثر نرم برای شورت")

    return long_score, short_score


# ---------- Main scoring ----------
def technical_direction_score(symbol, df_4h, df_1h, df_30m, df_15m, df_5m):
    long_score = 0
    short_score = 0
    long_reasons = []
    short_reasons = []
    confirmations_long = 0
    confirmations_short = 0

    trends = {
        "4H": trend_direction(df_4h),
        "1H": trend_direction(df_1h),
        "30M": trend_direction(df_30m),
        "15M": trend_direction(df_15m),
        "5M": trend_direction(df_5m),
    }

    last_4h = df_4h.iloc[-1]
    last_1h = df_1h.iloc[-1]
    last_30 = df_30m.iloc[-1]
    last_15 = df_15m.iloc[-1]
    prev_15 = df_15m.iloc[-2]
    last_5 = df_5m.iloc[-1]

    buy2, sell2 = buy_sell_power(df_5m, 2)
    buy3, sell3 = buy_sell_power(df_5m, 3)
    buy6, sell6 = buy_sell_power(df_5m, 6)
    buy20, sell20 = buy_sell_power(df_5m, 20)

    adx_15 = float(last_15["adx"])
    ob = simple_order_block(df_15m)
    vol_status, vol_ratio = volume_quality(df_15m)
    pattern = candle_pattern(df_15m)
    context = get_soft_context()

    # 1) Higher timeframe direction: soft background
    if trends["4H"] in ["bullish", "weak_bullish"]:
        long_score += 8
        long_reasons.append("4H: زمینه کلی صعودی است")
    elif trends["4H"] in ["bearish", "weak_bearish"]:
        short_score += 8
        short_reasons.append("4H: زمینه کلی نزولی است")

    if trends["1H"] in ["bullish", "weak_bullish"]:
        long_score += 12
        confirmations_long += 1
        long_reasons.append("1H: جهت اصلی لانگ است")
    elif trends["1H"] in ["bearish", "weak_bearish"]:
        short_score += 12
        confirmations_short += 1
        short_reasons.append("1H: جهت اصلی شورت است")

    # 2) 30M entry context: important, but below 15M
    if trends["30M"] in ["bullish", "weak_bullish"]:
        long_score += 14
        confirmations_long += 1
        long_reasons.append("30M: جهت ورود لانگ را تایید می‌کند")
    elif trends["30M"] in ["bearish", "weak_bearish"]:
        short_score += 14
        confirmations_short += 1
        short_reasons.append("30M: جهت ورود شورت را تایید می‌کند")

    if last_30["close"] > last_30["ema20"] and last_30["macd"] > last_30["macd_signal"]:
        long_score += 10
        confirmations_long += 1
        long_reasons.append("30M: EMA20 و MACD لانگ را تایید می‌کنند")
    if last_30["close"] < last_30["ema20"] and last_30["macd"] < last_30["macd_signal"]:
        short_score += 10
        confirmations_short += 1
        short_reasons.append("30M: EMA20 و MACD شورت را تایید می‌کنند")

    # 3) 15M main entry engine: highest weight
    if trends["15M"] in ["bullish", "weak_bullish"]:
        long_score += 20
        confirmations_long += 1
        long_reasons.append("15M: تایم اصلی ورود لانگ را تایید می‌کند")
    elif trends["15M"] in ["bearish", "weak_bearish"]:
        short_score += 20
        confirmations_short += 1
        short_reasons.append("15M: تایم اصلی ورود شورت را تایید می‌کند")

    if last_15["close"] > last_15["ema20"] > last_15["ema50"]:
        long_score += 14
        confirmations_long += 1
        long_reasons.append("15M: قیمت بالای EMA20 و EMA50 است")
    if last_15["close"] < last_15["ema20"] < last_15["ema50"]:
        short_score += 14
        confirmations_short += 1
        short_reasons.append("15M: قیمت پایین EMA20 و EMA50 است")

    if last_15["macd"] > last_15["macd_signal"]:
        long_score += 10
        confirmations_long += 1
        long_reasons.append("15M: MACD مثبت است")
    if last_15["macd"] < last_15["macd_signal"]:
        short_score += 10
        confirmations_short += 1
        short_reasons.append("15M: MACD منفی است")

    if last_15["macd_hist"] > prev_15["macd_hist"]:
        long_score += 6
        confirmations_long += 1
        long_reasons.append("15M: هیستوگرام MACD رو به تقویت صعودی است")
    if last_15["macd_hist"] < prev_15["macd_hist"]:
        short_score += 6
        confirmations_short += 1
        short_reasons.append("15M: هیستوگرام MACD رو به تقویت نزولی است")

    # RSI balanced, not hard
    if last_15["rsi"] > prev_15["rsi"] and 45 <= last_15["rsi"] <= 68:
        long_score += 6
        confirmations_long += 1
        long_reasons.append("15M: RSI در محدوده مناسب رو به بالا است")
    if last_15["rsi"] < prev_15["rsi"] and 32 <= last_15["rsi"] <= 55:
        short_score += 6
        confirmations_short += 1
        short_reasons.append("15M: RSI در محدوده مناسب رو به پایین است")

    # ADX hard reject under 20, bonus above 20
    if adx_15 >= ADX_HARD_MIN:
        long_score += 8
        short_score += 8
        long_reasons.append("ADX 15M بالای 20 است؛ قدرت روند قابل قبول است")
        short_reasons.append("ADX 15M بالای 20 است؛ قدرت روند قابل قبول است")
    else:
        long_score = min(long_score, 69)
        short_score = min(short_score, 69)
        long_reasons.append("رد: ADX 15M زیر 20 است")
        short_reasons.append("رد: ADX 15M زیر 20 است")

    # Volume: soft technical component
    if vol_status == "high_volume":
        long_score += 5
        short_score += 5
        long_reasons.append(f"Vol 15M قوی است؛ نسبت حجم {round(vol_ratio, 2)}")
        short_reasons.append(f"Vol 15M قوی است؛ نسبت حجم {round(vol_ratio, 2)}")
    elif vol_status == "normal_volume":
        long_score += 2
        short_score += 2
        long_reasons.append("Vol 15M قابل قبول است")
        short_reasons.append("Vol 15M قابل قبول است")
    elif vol_status == "weak_volume":
        long_score -= 4
        short_score -= 4
        long_reasons.append("Vol 15M ضعیف است؛ امتیاز محافظه‌کار شد")
        short_reasons.append("Vol 15M ضعیف است؛ امتیاز محافظه‌کار شد")

    # VWAP from 15M/5M: soft confirmation
    if last_15["close"] > last_15["vwap"]:
        long_score += 4
        long_reasons.append("15M: قیمت بالای VWAP است")
    elif last_15["close"] < last_15["vwap"]:
        short_score += 4
        short_reasons.append("15M: قیمت پایین VWAP است")

    if last_5["close"] > last_5["vwap"]:
        long_score += 2
        long_reasons.append("5M: VWAP با لانگ تضاد ندارد")
    elif last_5["close"] < last_5["vwap"]:
        short_score += 2
        short_reasons.append("5M: VWAP با شورت تضاد ندارد")

    # Power is secondary, not a signal maker
    if buy20 > sell20 + 8:
        long_score += 5
        long_reasons.append("قدرت 20 کندلی خرید برتری دارد")
    elif sell20 > buy20 + 8:
        short_score += 5
        short_reasons.append("قدرت 20 کندلی فروش برتری دارد")

    if buy6 > sell6 + 6:
        long_score += 3
        long_reasons.append("قدرت 6 کندلی خرید هم‌جهت است")
    elif sell6 > buy6 + 6:
        short_score += 3
        short_reasons.append("قدرت 6 کندلی فروش هم‌جهت است")

    # 2-candle power is a hard quality gate for automatic/direct signals.
    # LONG requires buy power >= 80%. SHORT requires sell power >= 80%.
    if buy2 >= POWER2_SIGNAL_MIN:
        long_score += 3
        long_reasons.append("قدرت خرید 2 کندلی بالای 80٪ و هم‌جهت لانگ است")
    else:
        long_score = min(long_score, 69)
        long_reasons.append("رد لانگ: قدرت خرید 2 کندلی زیر 80٪ است")

    if sell2 >= POWER2_SIGNAL_MIN:
        short_score += 3
        short_reasons.append("قدرت فروش 2 کندلی بالای 80٪ و هم‌جهت شورت است")
    else:
        short_score = min(short_score, 69)
        short_reasons.append("رد شورت: قدرت فروش 2 کندلی زیر 80٪ است")

    # Order block soft penalty only. Same-direction gives no bonus.
    if ob == "bearish_order_block":
        long_score -= 3
        long_reasons.append("Order Block مخالف لانگ است؛ جریمه نرم 3 امتیازی")
    elif ob == "bullish_order_block":
        short_score -= 3
        short_reasons.append("Order Block مخالف شورت است؛ جریمه نرم 3 امتیازی")

    # Candle pattern small technical effect
    if pattern.startswith("bullish"):
        long_score += 3
        long_reasons.append(f"کندل 15M تاییدی لانگ: {pattern}")
    elif pattern.startswith("bearish"):
        short_score += 3
        short_reasons.append(f"کندل 15M تاییدی شورت: {pattern}")

    # Soft market context: market regime, altseason, fear & greed
    long_score, short_score = apply_soft_context(
        symbol, long_score, short_score, long_reasons, short_reasons, context
    )

    # Hard validity: 15M + 30M entry must agree enough, ADX >= 20, and final score high.
    long_valid = (
        adx_15 >= ADX_HARD_MIN
        and trends["15M"] in ["bullish", "weak_bullish"]
        and trends["30M"] in ["bullish", "weak_bullish"]
        and last_15["close"] > last_15["ema20"]
        and last_15["macd"] > last_15["macd_signal"]
        and buy2 >= POWER2_SIGNAL_MIN
    )

    short_valid = (
        adx_15 >= ADX_HARD_MIN
        and trends["15M"] in ["bearish", "weak_bearish"]
        and trends["30M"] in ["bearish", "weak_bearish"]
        and last_15["close"] < last_15["ema20"]
        and last_15["macd"] < last_15["macd_signal"]
        and sell2 >= POWER2_SIGNAL_MIN
    )

    if not long_valid:
        long_score = min(long_score, 69)
    if not short_valid:
        short_score = min(short_score, 69)

    return {
        "long_score": cap_score(long_score),
        "short_score": cap_score(short_score),
        "long_reasons": long_reasons,
        "short_reasons": short_reasons,
        "confirmations_long": confirmations_long,
        "confirmations_short": confirmations_short,
        "trends": trends,
        "order_block": ob,
        "market_regime": context.get("market_regime"),
        "altseason_status": context.get("altseason_status"),
        "fear_greed_value": context.get("fear_greed_value"),
        "fear_greed_status": context.get("fear_greed_status"),
        "volume_status": vol_status,
        "volume_ratio": round(vol_ratio, 2),
        "power2_buy": buy2,
        "power2_sell": sell2,
        "power3_buy": buy3,
        "power3_sell": sell3,
        "power6_buy": buy6,
        "power6_sell": sell6,
        "buy_power": buy20,
        "sell_power": sell20,
        "candle_pattern": pattern,
        "long_valid": long_valid,
        "short_valid": short_valid,
        "adx_15": adx_15,
        "power2_signal_min": POWER2_SIGNAL_MIN,
    }


def build_trade_levels(direction, price, atr, df_5m=None):
    """
    ساخت SL/TP هوشمند بر اساس حمایت/مقاومت 5M.
    TP روی خود سطح قرار نمی‌گیرد؛ قبل از سطح گذاشته می‌شود.
    SL پشت سطح قرار می‌گیرد. اگر سطح مناسب پیدا نشود، ATR fallback استفاده می‌شود.
    """
    price = float(price)
    atr = max(float(atr or 0), price * 0.0015)

    level_buffer = max(atr * 0.12, price * 0.0008)
    sl_buffer = max(atr * 0.22, price * 0.0010)

    if df_5m is not None and len(df_5m) >= 80:
        levels = support_resistance_levels(df_5m, lookback=140, swing_window=3, atr=atr)
        supports = levels.get("supports", [])
        resistances = levels.get("resistances", [])

        if direction == "LONG":
            nearest_support = supports[0] if supports else price - atr * SL_ATR_MULTIPLIER
            sl = nearest_support - sl_buffer
            # SL باید پشت حمایت باشد اما نه خیلی نزدیک و نه خیلی دور.
            # اگر حمایت خیلی نزدیک/دور بود، از ATR کلاسیک استفاده می‌شود.
            sl_distance = abs(price - sl)
            if sl_distance < atr * MIN_SL_ATR_MULTIPLIER or sl_distance > atr * MAX_SL_ATR_MULTIPLIER:
                sl = price - atr * SL_ATR_MULTIPLIER
            tp1 = pick_safe_target("LONG", price, atr, resistances, TP1_ATR_MULTIPLIER, level_buffer)
            tp2 = pick_safe_target("LONG", price, atr, resistances[1:] if len(resistances) > 1 else [], TP2_ATR_MULTIPLIER, level_buffer)
        else:
            nearest_resistance = resistances[0] if resistances else price + atr * SL_ATR_MULTIPLIER
            sl = nearest_resistance + sl_buffer
            sl_distance = abs(price - sl)
            if sl_distance < atr * MIN_SL_ATR_MULTIPLIER or sl_distance > atr * MAX_SL_ATR_MULTIPLIER:
                sl = price + atr * SL_ATR_MULTIPLIER
            tp1 = pick_safe_target("SHORT", price, atr, supports, TP1_ATR_MULTIPLIER, level_buffer)
            tp2 = pick_safe_target("SHORT", price, atr, supports[1:] if len(supports) > 1 else [], TP2_ATR_MULTIPLIER, level_buffer)
    else:
        if direction == "LONG":
            sl = price - atr * SL_ATR_MULTIPLIER
            tp1 = price + atr * TP1_ATR_MULTIPLIER
            tp2 = price + atr * TP2_ATR_MULTIPLIER
        else:
            sl = price + atr * SL_ATR_MULTIPLIER
            tp1 = price - atr * TP1_ATR_MULTIPLIER
            tp2 = price - atr * TP2_ATR_MULTIPLIER

    # حداقل فاصله SL همیشه باید ATR * 1.25 باشد.
    # اگر SL هوشمند با حمایت/مقاومت نزدیک‌تر از این شد، به حداقل استاندارد برمی‌گردد.
    min_sl_distance = atr * SL_ATR_MULTIPLIER
    if direction == "LONG" and (price - sl) < min_sl_distance:
        sl = price - min_sl_distance
    if direction == "SHORT" and (sl - price) < min_sl_distance:
        sl = price + min_sl_distance

    # ترتیب TPها را منطقی نگه می‌دارد
    if direction == "LONG" and tp2 <= tp1:
        tp2 = price + atr * TP2_ATR_MULTIPLIER
    if direction == "SHORT" and tp2 >= tp1:
        tp2 = price - atr * TP2_ATR_MULTIPLIER

    # حداقل فاصله TP1 را حفظ می‌کند تا TP خیلی نزدیک سطح/نویز نباشد.
    min_tp1_distance = max(atr * 0.35, price * 0.0010)
    if direction == "LONG" and tp1 - price < min_tp1_distance:
        tp1 = price + atr * TP1_ATR_MULTIPLIER
    if direction == "SHORT" and price - tp1 < min_tp1_distance:
        tp1 = price - atr * TP1_ATR_MULTIPLIER

    risk = abs(price - sl)
    reward = abs(tp1 - price)
    rr = round(reward / risk, 2) if risk > 0 else 0
    return safe_round(sl), safe_round(tp1), safe_round(tp2), rr


def analyze_symbol(symbol):
    symbol = str(symbol).upper().strip()

    try:
        df_4h = add_indicators(get_klines(symbol, "4h"))
        df_1h = add_indicators(get_klines(symbol, "1h"))
        df_30m = add_indicators(get_klines(symbol, "30m"))
        df_15m = add_indicators(get_klines(symbol, "15m"))
        df_5m = add_indicators(get_klines(symbol, "5m"))

        score = technical_direction_score(symbol, df_4h, df_1h, df_30m, df_15m, df_5m)

        price = float(df_15m.iloc[-1]["close"])
        atr = float(df_5m.iloc[-1]["atr"])
        sr_5m = support_resistance_levels(df_5m, lookback=140, swing_window=3, atr=atr)
        support = sr_5m["nearest_support"]
        resistance = sr_5m["nearest_resistance"]
        vwap = vwap_status(df_15m)

        long_score = score["long_score"]
        short_score = score["short_score"]
        edge = abs(long_score - short_score)

        if long_score >= short_score:
            direction = "LONG"
            final_score = long_score
            confirmations = score["confirmations_long"]
            reasons = score["long_reasons"]
            valid_direction = score.get("long_valid", False)
        else:
            direction = "SHORT"
            final_score = short_score
            confirmations = score["confirmations_short"]
            reasons = score["short_reasons"]
            valid_direction = score.get("short_valid", False)

        # Auto signal score below 85 is rejected here too, so scanner stays safe.
        min_required_score = max(int(MIN_DIRECT_SCORE), AUTO_DIRECT_SCORE_MIN)

        if (
            not valid_direction
            or final_score < min_required_score
            or confirmations < int(MIN_MANUAL_CONFIRMATIONS)
            or edge < 8
        ):
            direction = "NO TRADE"
            entry_confirmed = False
            entry_mode = "NO_ENTRY"
            stop_loss = tp1 = tp2 = None
            rr = 0
            risk_level = "نامشخص"
            freshness = "LOW"
        else:
            entry_confirmed = True
            entry_mode = "CLASSIC_TECHNICAL"
            stop_loss, tp1, tp2, rr = build_trade_levels(direction, price, atr, df_5m=df_5m)

            if final_score >= 92 and confirmations >= 7:
                risk_level = "LOW"
            elif final_score >= 85 and confirmations >= 5:
                risk_level = "MEDIUM"
            else:
                risk_level = "HIGH"

            freshness = "HIGH" if confirmations >= 7 else "MEDIUM" if confirmations >= 5 else "LOW"

        return {
            "symbol": symbol,
            "direction": direction,
            "score": cap_score(final_score),
            "long_score": long_score,
            "short_score": short_score,
            "entry_mode": entry_mode,
            "entry_confirmed": entry_confirmed,
            "status": "ACTIVE" if entry_confirmed else "NO_TRADE",
            "price": safe_round(price),
            "entry": safe_round(price),
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "atr": safe_round(atr),
            "risk_reward": rr,
            "risk_level": risk_level,
            "freshness": freshness,
            "confirmations": confirmations,
            "rsi": safe_round(df_15m.iloc[-1]["rsi"], 2),
            "macd": safe_round(df_15m.iloc[-1]["macd"], 6),
            "macd_signal": safe_round(df_15m.iloc[-1]["macd_signal"], 6),
            "macd_hist": safe_round(df_15m.iloc[-1]["macd_hist"], 6),
            "adx": safe_round(df_15m.iloc[-1]["adx"], 2),
            "vwap_status": vwap,
            "support": safe_round(support),
            "resistance": safe_round(resistance),
            "sr_timeframe": "5M",
            "trends": score["trends"],
            "order_block": score["order_block"],
            "market_regime": score["market_regime"],
            "altseason_status": score["altseason_status"],
            "fear_greed_value": score["fear_greed_value"],
            "fear_greed_status": score["fear_greed_status"],
            "volume_status": score["volume_status"],
            "volume_ratio": score["volume_ratio"],
            "power2_buy": score["power2_buy"],
            "power2_sell": score["power2_sell"],
            "power2_signal_min": score.get("power2_signal_min"),
            "power3_buy": score["power3_buy"],
            "power3_sell": score["power3_sell"],
            "buy_power": score["buy_power"],
            "sell_power": score["sell_power"],
            "candle_pattern": score["candle_pattern"],
            "reasons": reasons[:12],
            "signal_timeframe": "15M/30M Technical Entry",
            "validity": "15 تا 45 دقیقه" if entry_confirmed else "سیگنال معتبر نیست",
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "direction": "NO TRADE",
            "score": 0,
            "entry_mode": "ERROR",
            "entry_confirmed": False,
            "price": None,
            "stop_loss": None,
            "tp1": None,
            "tp2": None,
            "risk_level": "نامشخص",
            "risk_reward": 0,
            "freshness": "LOW",
            "confirmations": 0,
            "rsi": None,
            "macd": None,
            "macd_hist": None,
            "adx": None,
            "support": None,
            "resistance": None,
            "reasons": [f"خطا در تحلیل: {str(e)[:160]}"],
            "signal_timeframe": "بدون تایم‌فریم ورود",
            "validity": "سیگنال معتبر نیست",
        }
