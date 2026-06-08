import pandas as pd
import ta

from data_provider import get_latest_price, get_candles


def calculate_indicators(df: pd.DataFrame):
    df = df.copy()

    df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
    df["ema200"] = ta.trend.EMAIndicator(df["close"], window=200).ema_indicator()

    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    return df


def analyze_pair(symbol: str):
    price_data = get_latest_price(symbol)
    if not price_data["success"]:
        return {
            "success": False,
            "error": price_data["error"]
        }

    candles_1h = get_candles(symbol, interval="1h", outputsize=250)
    if not candles_1h["success"]:
        return {
            "success": False,
            "error": candles_1h["error"]
        }

    df = calculate_indicators(candles_1h["data"])
    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 50
    reasons = []

    if last["ema50"] > last["ema200"]:
        score += 15
        direction = "BUY"
        reasons.append("EMA50 بالای EMA200 است؛ روند کلی صعودی است.")
    elif last["ema50"] < last["ema200"]:
        score += 15
        direction = "SELL"
        reasons.append("EMA50 پایین EMA200 است؛ روند کلی نزولی است.")
    else:
        direction = "NEUTRAL"
        reasons.append("EMA50 و EMA200 وضعیت واضحی ندارند.")

    if last["macd"] > last["macd_signal"]:
        if direction == "BUY":
            score += 10
        reasons.append("MACD حالت صعودی دارد.")
    elif last["macd"] < last["macd_signal"]:
        if direction == "SELL":
            score += 10
        reasons.append("MACD حالت نزولی دارد.")

    if last["rsi"] > prev["rsi"]:
        if direction == "BUY":
            score += 8
        reasons.append("RSI در حال افزایش است.")
    elif last["rsi"] < prev["rsi"]:
        if direction == "SELL":
            score += 8
        reasons.append("RSI در حال کاهش است.")

    if 45 <= last["rsi"] <= 65 and direction == "BUY":
        score += 5
        reasons.append("RSI برای خرید در محدوده مناسب است.")
    elif 35 <= last["rsi"] <= 55 and direction == "SELL":
        score += 5
        reasons.append("RSI برای فروش در محدوده مناسب است.")

    score = min(score, 100)

    return {
        "success": True,
        "symbol": symbol,
        "price": price_data["price"],
        "direction": direction,
        "score": round(score, 1),
        "rsi": round(last["rsi"], 2),
        "ema50": round(last["ema50"], 5),
        "ema200": round(last["ema200"], 5),
        "macd": round(last["macd"], 5),
        "macd_signal": round(last["macd_signal"], 5),
        "reasons": reasons
    }
