# -*- coding: utf-8 -*-
"""
Clean Technical Pullback Engine

هدف این نسخه:
- سیگنال کمتر، اما تمیزتر
- حذف ورودهای هیجانی 5M
- ورود فقط وقتی جهت، ساختار، قدرت روند، پولبک و فاصله از EMA20 منطقی باشند
- بدون Setup / Watchlist / Pending
"""

import ccxt
import pandas as pd
import ta

from config import MIN_DIRECT_SCORE, MIN_MANUAL_CONFIRMATIONS, MIN_ADX_FOR_TREND


exchange = ccxt.okx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"},
})


# Core architecture constants
CLEAN_ADX_MIN = max(float(MIN_ADX_FOR_TREND), 25.0)

SL_ATR_MULTIPLIER = 1.30
TP1_ATR_MULTIPLIER = 0.80
TP2_ATR_MULTIPLIER = 1.50

# Entry quality
PULLBACK_LOOKBACK = 6
PULLBACK_TOUCH_TOLERANCE_ATR = 0.25
MAX_DISTANCE_FROM_EMA20_ATR = 0.85
MAX_EXTENSION_FROM_EMA20_ATR = 1.15
MAX_CONSECUTIVE_TREND_CANDLES = 5

# Market structure
SWING_LOOKBACK = 80
SWING_WINDOW = 3


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

    df["atr"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14
    )

    adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
    df["adx"] = adx.adx()

    typical = (df["high"] + df["low"] + df["close"]) / 3
    volume_sum = df["volume"].cumsum().replace(0, pd.NA)
    df["vwap"] = (typical * df["volume"]).cumsum() / volume_sum
    df["volume_ma20"] = df["volume"].rolling(20).mean()

    df = df.dropna()
    if len(df) < 60:
        raise Exception("اندیکاتورها کامل محاسبه نشدند")

    return df


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


def find_swings(df, lookback=SWING_LOOKBACK, window=SWING_WINDOW):
    recent = df.tail(lookback).copy()
    lows = []
    highs = []

    for i in range(window, len(recent) - window):
        row = recent.iloc[i]
        left = recent.iloc[i - window:i]
        right = recent.iloc[i + 1:i + 1 + window]

        if row["low"] <= left["low"].min() and row["low"] <= right["low"].min():
            lows.append((recent.index[i], float(row["low"])))

        if row["high"] >= left["high"].max() and row["high"] >= right["high"].max():
            highs.append((recent.index[i], float(row["high"])))

    return lows, highs


def market_structure(df):
    lows, highs = find_swings(df)

    if len(lows) < 2 or len(highs) < 2:
        return "range_structure"

    last_low = lows[-1][1]
    prev_low = lows[-2][1]
    last_high = highs[-1][1]
    prev_high = highs[-2][1]

    if last_high > prev_high and last_low > prev_low:
        return "bullish_structure"

    if last_high < prev_high and last_low < prev_low:
        return "bearish_structure"

    return "range_structure"


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


def vwap_status(df):
    last = df.iloc[-1]
    if last["close"] > last["vwap"]:
        return "above_vwap"
    if last["close"] < last["vwap"]:
        return "below_vwap"
    return "near_vwap"


def volume_spike(df):
    last = df.iloc[-1]
    try:
        return float(last["volume"]) > float(last["volume_ma20"]) * 1.35
    except Exception:
        return False


def distance_from_ema20_atr(df):
    last = df.iloc[-1]
    price = float(last["close"])
    ema20 = float(last["ema20"])
    atr = max(float(last["atr"]), price * 0.0015)
    return abs(price - ema20) / atr


def consecutive_direction_candles(df, direction, candles=8):
    recent = df.tail(candles)
    count = 0

    for _, row in reversed(list(recent.iterrows())):
        if direction == "LONG" and row["close"] > row["open"]:
            count += 1
        elif direction == "SHORT" and row["close"] < row["open"]:
            count += 1
        else:
            break

    return count


def is_overextended(df_15m, direction):
    distance = distance_from_ema20_atr(df_15m)
    consecutive = consecutive_direction_candles(df_15m, direction)

    if distance > MAX_EXTENSION_FROM_EMA20_ATR:
        return True, f"فاصله قیمت از EMA20 زیاد است: {round(distance, 2)} ATR"

    if consecutive >= MAX_CONSECUTIVE_TREND_CANDLES:
        return True, f"حرکت {consecutive} کندل پشت‌سرهم رفته و احتمال ورود دیر وجود دارد"

    return False, None


def ema20_pullback(df_15m, direction):
    last = df_15m.iloc[-1]
    atr = max(float(last["atr"]), float(last["close"]) * 0.0015)
    price = float(last["close"])
    ema20 = float(last["ema20"])
    distance = abs(price - ema20) / atr

    recent = df_15m.tail(PULLBACK_LOOKBACK)
    tolerance = atr * PULLBACK_TOUCH_TOLERANCE_ATR

    if direction == "LONG":
        touched = bool((recent["low"] <= recent["ema20"] + tolerance).any())
        reclaimed = price > ema20 and last["close"] > last["open"]
        not_far = distance <= MAX_DISTANCE_FROM_EMA20_ATR
        return touched and reclaimed and not_far, round(distance, 2)

    if direction == "SHORT":
        touched = bool((recent["high"] >= recent["ema20"] - tolerance).any())
        reclaimed = price < ema20 and last["close"] < last["open"]
        not_far = distance <= MAX_DISTANCE_FROM_EMA20_ATR
        return touched and reclaimed and not_far, round(distance, 2)

    return False, round(distance, 2)


def technical_direction_score(df_4h, df_1h, df_15m, df_5m):
    long_score = 0
    short_score = 0
    long_reasons = []
    short_reasons = []
    confirmations_long = 0
    confirmations_short = 0

    trends = {
        "4H": trend_direction(df_4h),
        "1H": trend_direction(df_1h),
        "15M": trend_direction(df_15m),
        "5M": trend_direction(df_5m),  # فقط خروجی نمایشی/اطلاعاتی
    }

    structure = market_structure(df_15m)

    last_4h = df_4h.iloc[-1]
    last_1h = df_1h.iloc[-1]
    last_15 = df_15m.iloc[-1]
    prev_15 = df_15m.iloc[-2]
    last_5 = df_5m.iloc[-1]

    buy2, sell2 = buy_sell_power(df_5m, 2)
    buy3, sell3 = buy_sell_power(df_5m, 3)
    buy6, sell6 = buy_sell_power(df_5m, 6)
    buy20, sell20 = buy_sell_power(df_5m, 20)

    # 4H + 1H main direction
    if trends["4H"] in ["bullish", "weak_bullish"]:
        long_score += 18
        confirmations_long += 1
        long_reasons.append("4H: جهت کلی لانگ را تایید می‌کند")
    if trends["4H"] in ["bearish", "weak_bearish"]:
        short_score += 18
        confirmations_short += 1
        short_reasons.append("4H: جهت کلی شورت را تایید می‌کند")

    if trends["1H"] in ["bullish", "weak_bullish"]:
        long_score += 26
        confirmations_long += 1
        long_reasons.append("1H: جهت اصلی لانگ است")
    if trends["1H"] in ["bearish", "weak_bearish"]:
        short_score += 26
        confirmations_short += 1
        short_reasons.append("1H: جهت اصلی شورت است")

    # Strong EMA/MACD alignment on higher TFs
    if last_1h["close"] > last_1h["ema20"] > last_1h["ema50"] and last_1h["macd"] > last_1h["macd_signal"]:
        long_score += 20
        confirmations_long += 1
        long_reasons.append("1H: EMA20/EMA50 و MACD لانگ را تایید می‌کنند")

    if last_1h["close"] < last_1h["ema20"] < last_1h["ema50"] and last_1h["macd"] < last_1h["macd_signal"]:
        short_score += 20
        confirmations_short += 1
        short_reasons.append("1H: EMA20/EMA50 و MACD شورت را تایید می‌کنند")

    # 15M clean movement quality
    if last_15["close"] > last_15["ema20"] > last_15["ema50"] and last_15["macd"] > last_15["macd_signal"]:
        long_score += 24
        confirmations_long += 2
        long_reasons.append("15M: حرکت لانگ تمیز است؛ قیمت بالای EMA20/EMA50 و MACD مثبت")

    if last_15["close"] < last_15["ema20"] < last_15["ema50"] and last_15["macd"] < last_15["macd_signal"]:
        short_score += 24
        confirmations_short += 2
        short_reasons.append("15M: حرکت شورت تمیز است؛ قیمت پایین EMA20/EMA50 و MACD منفی")

    # ADX trend strength on 15M
    adx_15 = float(last_15["adx"])
    if adx_15 >= CLEAN_ADX_MIN:
        long_score += 12
        short_score += 12
        long_reasons.append("ADX 15M بالای 25 است؛ قدرت روند کافی است")
        short_reasons.append("ADX 15M بالای 25 است؛ قدرت روند کافی است")

    # Structure filter
    if structure == "bullish_structure":
        long_score += 16
        confirmations_long += 1
        long_reasons.append("ساختار 15M صعودی است: HH/HL")
    elif structure == "bearish_structure":
        short_score += 16
        confirmations_short += 1
        short_reasons.append("ساختار 15M نزولی است: LH/LL")
    else:
        long_reasons.append("ساختار 15M رنج/نامشخص است")
        short_reasons.append("ساختار 15M رنج/نامشخص است")

    # Pullback entry on EMA20 15M
    long_pullback, long_distance = ema20_pullback(df_15m, "LONG")
    short_pullback, short_distance = ema20_pullback(df_15m, "SHORT")

    if long_pullback:
        long_score += 24
        confirmations_long += 2
        long_reasons.append("ورود لانگ روی پولبک EMA20 در 15M است")
    else:
        long_reasons.append(f"لانگ: پولبک EMA20 مناسب نیست؛ فاصله {long_distance} ATR")

    if short_pullback:
        short_score += 24
        confirmations_short += 2
        short_reasons.append("ورود شورت روی پولبک EMA20 در 15M است")
    else:
        short_reasons.append(f"شورت: پولبک EMA20 مناسب نیست؛ فاصله {short_distance} ATR")

    # End-of-move / late-entry protection
    long_overextended, long_ext_reason = is_overextended(df_15m, "LONG")
    short_overextended, short_ext_reason = is_overextended(df_15m, "SHORT")

    if long_overextended:
        long_score = min(long_score, 69)
        long_reasons.append(f"رد لانگ: {long_ext_reason}")

    if short_overextended:
        short_score = min(short_score, 69)
        short_reasons.append(f"رد شورت: {short_ext_reason}")

    # 15M RSI slope as soft confirmation
    if last_15["rsi"] > prev_15["rsi"] and 45 <= last_15["rsi"] <= 66:
        long_score += 7
        confirmations_long += 1
        long_reasons.append("RSI 15M در محدوده مناسب رو به بالا است")

    if last_15["rsi"] < prev_15["rsi"] and 34 <= last_15["rsi"] <= 55:
        short_score += 7
        confirmations_short += 1
        short_reasons.append("RSI 15M در محدوده مناسب رو به پایین است")

    # VWAP / 5M only safety, not entry creator
    if last_5["close"] > last_5["vwap"]:
        long_score += 3
        long_reasons.append("5M: قیمت بالای VWAP است")
    elif last_5["close"] < last_5["vwap"]:
        short_score += 3
        short_reasons.append("5M: قیمت پایین VWAP است")

    # Reject clear instant opposite pressure, but do not let Power create entries
    if sell2 > buy2 + 8:
        long_score = min(long_score, 69)
        long_reasons.append("رد لانگ: فشار لحظه‌ای فروش در 5M خلاف ورود است")
    elif buy2 > sell2:
        long_score += 2
        long_reasons.append("فشار لحظه‌ای خرید خلاف لانگ نیست")

    if buy2 > sell2 + 8:
        short_score = min(short_score, 69)
        short_reasons.append("رد شورت: فشار لحظه‌ای خرید در 5M خلاف ورود است")
    elif sell2 > buy2:
        short_score += 2
        short_reasons.append("فشار لحظه‌ای فروش خلاف شورت نیست")

    pattern = candle_pattern(df_15m)
    if pattern.startswith("bullish"):
        long_score += 5
        confirmations_long += 1
        long_reasons.append(f"کندل 15M تاییدی لانگ: {pattern}")
    elif pattern.startswith("bearish"):
        short_score += 5
        confirmations_short += 1
        short_reasons.append(f"کندل 15M تاییدی شورت: {pattern}")

    if volume_spike(df_15m):
        long_score += 4
        short_score += 4
        long_reasons.append("افزایش حجم در 15M دیده شد")
        short_reasons.append("افزایش حجم در 15M دیده شد")

    long_valid = (
        trends["4H"] in ["bullish", "weak_bullish"]
        and trends["1H"] in ["bullish", "weak_bullish"]
        and trends["15M"] in ["bullish", "weak_bullish"]
        and last_1h["close"] > last_1h["ema20"] > last_1h["ema50"]
        and last_1h["macd"] > last_1h["macd_signal"]
        and last_15["close"] > last_15["ema20"] > last_15["ema50"]
        and last_15["macd"] > last_15["macd_signal"]
        and adx_15 >= CLEAN_ADX_MIN
        and structure == "bullish_structure"
        and long_pullback
        and not long_overextended
        and not (sell2 > buy2 + 8)
    )

    short_valid = (
        trends["4H"] in ["bearish", "weak_bearish"]
        and trends["1H"] in ["bearish", "weak_bearish"]
        and trends["15M"] in ["bearish", "weak_bearish"]
        and last_1h["close"] < last_1h["ema20"] < last_1h["ema50"]
        and last_1h["macd"] < last_1h["macd_signal"]
        and last_15["close"] < last_15["ema20"] < last_15["ema50"]
        and last_15["macd"] < last_15["macd_signal"]
        and adx_15 >= CLEAN_ADX_MIN
        and structure == "bearish_structure"
        and short_pullback
        and not short_overextended
        and not (buy2 > sell2 + 8)
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
        "market_structure": structure,
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
        "pullback_distance_atr_long": long_distance,
        "pullback_distance_atr_short": short_distance,
        "adx_15": adx_15,
    }


def build_trade_levels(direction, price, atr):
    price = float(price)
    atr = max(float(atr or 0), price * 0.0015)

    if direction == "LONG":
        sl = price - atr * SL_ATR_MULTIPLIER
        tp1 = price + atr * TP1_ATR_MULTIPLIER
        tp2 = price + atr * TP2_ATR_MULTIPLIER
    else:
        sl = price + atr * SL_ATR_MULTIPLIER
        tp1 = price - atr * TP1_ATR_MULTIPLIER
        tp2 = price - atr * TP2_ATR_MULTIPLIER

    risk = abs(price - sl)
    reward = abs(tp1 - price)
    rr = round(reward / risk, 2) if risk > 0 else 0

    return safe_round(sl), safe_round(tp1), safe_round(tp2), rr


def analyze_symbol(symbol):
    symbol = str(symbol).upper().strip()

    try:
        df_4h = add_indicators(get_klines(symbol, "4h"))
        df_1h = add_indicators(get_klines(symbol, "1h"))
        df_15m = add_indicators(get_klines(symbol, "15m"))
        df_5m = add_indicators(get_klines(symbol, "5m"))

        score = technical_direction_score(df_4h, df_1h, df_15m, df_5m)

        price = float(df_15m.iloc[-1]["close"])
        atr = float(df_15m.iloc[-1]["atr"])
        support, resistance = support_resistance(df_15m)
        vwap = vwap_status(df_5m)

        long_score = score["long_score"]
        short_score = score["short_score"]
        edge = abs(long_score - short_score)

        if long_score >= short_score:
            direction = "LONG"
            final_score = long_score
            confirmations = score["confirmations_long"]
            reasons = score["long_reasons"]
            valid_direction = score.get("long_valid", False)
            pullback_distance_atr = score.get("pullback_distance_atr_long")
        else:
            direction = "SHORT"
            final_score = short_score
            confirmations = score["confirmations_short"]
            reasons = score["short_reasons"]
            valid_direction = score.get("short_valid", False)
            pullback_distance_atr = score.get("pullback_distance_atr_short")

        if (
            not valid_direction
            or final_score < MIN_DIRECT_SCORE
            or confirmations < MIN_MANUAL_CONFIRMATIONS
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
            stop_loss, tp1, tp2, rr = build_trade_levels(direction, price, atr)

            if final_score >= 90 and confirmations >= 7:
                risk_level = "LOW"
            elif final_score >= 82 and confirmations >= 5:
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
            "trends": score["trends"],
            "market_structure": score["market_structure"],
            "power2_buy": score["power2_buy"],
            "power2_sell": score["power2_sell"],
            "power3_buy": score["power3_buy"],
            "power3_sell": score["power3_sell"],
            "buy_power": score["buy_power"],
            "sell_power": score["sell_power"],
            "candle_pattern": score["candle_pattern"],
            "pullback_distance_atr": pullback_distance_atr,
            "reasons": reasons[:12],
            "signal_timeframe": "15M Pullback با جهت 1H/4H",
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
            "adx": None,
            "support": None,
            "resistance": None,
            "reasons": [f"خطا در تحلیل: {str(e)[:160]}"],
            "signal_timeframe": "بدون تایم‌فریم ورود",
            "validity": "سیگنال معتبر نیست",
        }
