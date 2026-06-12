# -*- coding: utf-8 -*-
import ccxt
import pandas as pd
import ta

from config import MIN_DIRECT_SCORE, MIN_MANUAL_CONFIRMATIONS, MIN_ADX_FOR_TREND

exchange = ccxt.okx({
    "enableRateLimit": True,
    "timeout": 20000,
    "options": {"defaultType": "swap"},
})


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
        left = recent.iloc[i-window:i]
        right = recent.iloc[i+1:i+1+window]
        if row["low"] <= left["low"].min() and row["low"] <= right["low"].min():
            lows.append(float(row["low"]))
        if row["high"] >= left["high"].max() and row["high"] >= right["high"].max():
            highs.append(float(row["high"]))
    below = [x for x in lows if x < price]
    above = [x for x in highs if x > price]
    support = max(below) if below else float(recent["low"].min())
    resistance = min(above) if above else float(recent["high"].max())
    return support, resistance


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


def score_direction(symbol, df_4h, df_1h, df_15m, df_5m):
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
        "5M": trend_direction(df_5m),
    }

    trend_weights = {"4H": 8, "1H": 14, "15M": 18, "5M": 20}
    for tf, trend in trends.items():
        w = trend_weights[tf]
        if trend == "bullish":
            long_score += w
            confirmations_long += 1
            long_reasons.append(f"{tf}: روند صعودی")
        elif trend == "weak_bullish":
            long_score += int(w * 0.55)
            long_reasons.append(f"{tf}: تمایل صعودی")
        elif trend == "bearish":
            short_score += w
            confirmations_short += 1
            short_reasons.append(f"{tf}: روند نزولی")
        elif trend == "weak_bearish":
            short_score += int(w * 0.55)
            short_reasons.append(f"{tf}: تمایل نزولی")

    last5 = df_5m.iloc[-1]
    prev5 = df_5m.iloc[-2]
    last15 = df_15m.iloc[-1]

    # EMA + MACD direct entry core
    if last5["close"] > last5["ema20"] and last5["macd"] > last5["macd_signal"]:
        long_score += 18; confirmations_long += 1; long_reasons.append("5M: EMA20 و MACD لانگ را تایید می‌کنند")
    if last5["close"] < last5["ema20"] and last5["macd"] < last5["macd_signal"]:
        short_score += 18; confirmations_short += 1; short_reasons.append("5M: EMA20 و MACD شورت را تایید می‌کنند")

    # MACD histogram slope + RSI slope
    if last5["macd_hist"] > prev5["macd_hist"]:
        long_score += 8; confirmations_long += 1; long_reasons.append("شیب MACD Histogram صعودی است")
    if last5["macd_hist"] < prev5["macd_hist"]:
        short_score += 8; confirmations_short += 1; short_reasons.append("شیب MACD Histogram نزولی است")
    if last5["rsi"] > prev5["rsi"] and 40 <= last5["rsi"] <= 70:
        long_score += 7; confirmations_long += 1; long_reasons.append("RSI در محدوده مناسب رو به بالا است")
    if last5["rsi"] < prev5["rsi"] and 30 <= last5["rsi"] <= 60:
        short_score += 7; confirmations_short += 1; short_reasons.append("RSI در محدوده مناسب رو به پایین است")

    buy2, sell2 = buy_sell_power(df_5m, 2)
    buy3, sell3 = buy_sell_power(df_5m, 3)
    buy6, sell6 = buy_sell_power(df_5m, 6)
    buy20, sell20 = buy_sell_power(df_5m, 20)

    if buy2 >= 60:
        long_score += 11; confirmations_long += 1; long_reasons.append("قدرت خرید 2 کندلی مناسب است")
    if buy3 >= 58:
        long_score += 8; long_reasons.append("قدرت خرید 3 کندلی تایید دارد")
    if buy6 >= 56:
        long_score += 5; long_reasons.append("قدرت خرید کوتاه‌مدت مثبت است")
    if sell2 >= 60:
        short_score += 11; confirmations_short += 1; short_reasons.append("قدرت فروش 2 کندلی مناسب است")
    if sell3 >= 58:
        short_score += 8; short_reasons.append("قدرت فروش 3 کندلی تایید دارد")
    if sell6 >= 56:
        short_score += 5; short_reasons.append("قدرت فروش کوتاه‌مدت مثبت است")

    if last5["close"] > last5["vwap"]:
        long_score += 7; confirmations_long += 1; long_reasons.append("قیمت بالای VWAP است")
        short_score -= 4
    elif last5["close"] < last5["vwap"]:
        short_score += 7; confirmations_short += 1; short_reasons.append("قیمت پایین VWAP است")
        long_score -= 4

    pattern = candle_pattern(df_5m)
    if pattern.startswith("bullish"):
        long_score += 6; confirmations_long += 1; long_reasons.append(f"کندل تاییدی لانگ: {pattern}")
    elif pattern.startswith("bearish"):
        short_score += 6; confirmations_short += 1; short_reasons.append(f"کندل تاییدی شورت: {pattern}")

    if float(last15["adx"]) >= MIN_ADX_FOR_TREND:
        long_score += 4; short_score += 4
        long_reasons.append("ADX 15M قدرت روند قابل قبول نشان می‌دهد")
        short_reasons.append("ADX 15M قدرت روند قابل قبول نشان می‌دهد")
    if volume_spike(df_5m):
        long_score += 4; short_score += 4
        long_reasons.append("افزایش حجم دیده شد")
        short_reasons.append("افزایش حجم دیده شد")

    return {
        "long_score": cap_score(long_score),
        "short_score": cap_score(short_score),
        "long_reasons": long_reasons,
        "short_reasons": short_reasons,
        "confirmations_long": confirmations_long,
        "confirmations_short": confirmations_short,
        "trends": trends,
        "power2_buy": buy2, "power2_sell": sell2,
        "power3_buy": buy3, "power3_sell": sell3,
        "power6_buy": buy6, "power6_sell": sell6,
        "buy_power": buy20, "sell_power": sell20,
        "candle_pattern": pattern,
    }


def build_trade_levels(direction, price, atr):
    price = float(price)
    atr = max(float(atr or 0), price * 0.0015)
    if direction == "LONG":
        sl = price - atr * 1.10
        tp1 = price + atr * 0.90
        tp2 = price + atr * 1.60
    else:
        sl = price + atr * 1.10
        tp1 = price - atr * 0.90
        tp2 = price - atr * 1.60
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

        score = score_direction(symbol, df_4h, df_1h, df_15m, df_5m)
        price = float(df_5m.iloc[-1]["close"])
        atr = float(df_5m.iloc[-1]["atr"])
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
        else:
            direction = "SHORT"
            final_score = short_score
            confirmations = score["confirmations_short"]
            reasons = score["short_reasons"]

        if final_score < MIN_DIRECT_SCORE or confirmations < MIN_MANUAL_CONFIRMATIONS or edge < 6:
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
            if final_score >= 88 and confirmations >= 6:
                risk_level = "LOW"
            elif final_score >= 78 and confirmations >= 4:
                risk_level = "MEDIUM"
            else:
                risk_level = "HIGH"
            freshness = "HIGH" if confirmations >= 6 else "MEDIUM" if confirmations >= 4 else "LOW"

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
            "rsi": safe_round(df_5m.iloc[-1]["rsi"], 2),
            "macd": safe_round(df_5m.iloc[-1]["macd"], 6),
            "macd_signal": safe_round(df_5m.iloc[-1]["macd_signal"], 6),
            "macd_hist": safe_round(df_5m.iloc[-1]["macd_hist"], 6),
            "adx": safe_round(df_15m.iloc[-1]["adx"], 2),
            "vwap_status": vwap,
            "support": safe_round(support),
            "resistance": safe_round(resistance),
            "trends": score["trends"],
            "power2_buy": score["power2_buy"],
            "power2_sell": score["power2_sell"],
            "power3_buy": score["power3_buy"],
            "power3_sell": score["power3_sell"],
            "buy_power": score["buy_power"],
            "sell_power": score["sell_power"],
            "candle_pattern": score["candle_pattern"],
            "reasons": reasons[:12],
            "signal_timeframe": "5M تا 15M",
            "validity": "5 تا 15 دقیقه" if entry_confirmed else "سیگنال معتبر نیست",
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
