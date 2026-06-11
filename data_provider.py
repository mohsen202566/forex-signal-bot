# -*- coding: utf-8 -*-
"""
Multi-source data provider for Forex Signal Bot.

Order of sources:
1) Yahoo Finance direct chart endpoint (no API key)
2) yfinance, if installed (no API key)
3) Stooq, limited fallback (no API key)
4) TwelveData, only as last fallback if API key exists

Public free data can still be rate-limited by providers. This file reduces dependency
on TwelveData credits and prevents the whole bot from failing when one source fails.
"""

import time
from typing import Dict, Optional, Tuple

import pandas as pd
import requests

try:
    import yfinance as yf
except Exception:
    yf = None

from config import TWELVE_DATA_API_KEY

TWELVE_BASE_URL = "https://api.twelvedata.com"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
STOOQ_CSV_URL = "https://stooq.com/q/d/l/"

_CACHE: Dict[Tuple[str, str, int], Tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 180

YAHOO_SYMBOLS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "USD/CHF": "CHF=X",
    "AUD/USD": "AUDUSD=X",
    "NZD/USD": "NZDUSD=X",
    "USD/CAD": "CAD=X",
    "EUR/JPY": "EURJPY=X",
    "EUR/GBP": "EURGBP=X",
    "EUR/CHF": "EURCHF=X",
    "EUR/AUD": "EURAUD=X",
    "EUR/CAD": "EURCAD=X",
    "GBP/JPY": "GBPJPY=X",
    "GBP/CHF": "GBPCHF=X",
    "AUD/JPY": "AUDJPY=X",
    "CAD/JPY": "CADJPY=X",
    "CHF/JPY": "CHFJPY=X",
    "NZD/JPY": "NZDJPY=X",
    "XAU/USD": "XAUUSD=X",
    "XAG/USD": "XAGUSD=X",
    "WTI/USD": "CL=F",
    "BRENT/USD": "BZ=F",
    "DXY": "DX-Y.NYB",
    "US30": "YM=F",
    "NAS100": "NQ=F",
    "SPX500": "ES=F",
    "DAX40": "^GDAXI",
    "BTC/USD": "BTC-USD",
    "ETH/USD": "ETH-USD",
    "SOL/USD": "SOL-USD",
}


# Alternative Yahoo tickers used only if the main ticker returns Not Found / no data.
# This is especially useful for metals on some VPS/IP regions where XAUUSD=X or XAGUSD=X may fail.
YAHOO_FALLBACK_SYMBOLS = {
    "XAU/USD": ["GC=F", "MGC=F"],
    "XAG/USD": ["SI=F", "SIL=F"],
}


def _get_yahoo_tickers(symbol: str):
    main = YAHOO_SYMBOLS.get(symbol)
    tickers = []
    if main:
        tickers.append(main)
    for alt in YAHOO_FALLBACK_SYMBOLS.get(symbol, []):
        if alt and alt not in tickers:
            tickers.append(alt)
    return tickers

STOOQ_SYMBOLS = {
    "EUR/USD": "eurusd",
    "GBP/USD": "gbpusd",
    "USD/JPY": "usdjpy",
    "USD/CHF": "usdchf",
    "AUD/USD": "audusd",
    "NZD/USD": "nzdusd",
    "USD/CAD": "usdcad",
    "EUR/JPY": "eurjpy",
    "EUR/GBP": "eurgbp",
    "EUR/CHF": "eurchf",
    "GBP/JPY": "gbpjpy",
    "XAU/USD": "xauusd",
    "XAG/USD": "xagusd",
    "BTC/USD": "btcusd",
    "ETH/USD": "ethusd",
}

INTERVAL_MAP_YAHOO = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "1h": "60m",
    "4h": "60m",
    "1day": "1d",
    "1d": "1d",
}

RANGE_BY_INTERVAL = {
    "1m": "7d",
    "5m": "30d",
    "15m": "60d",
    "30m": "60d",
    "60m": "730d",
    "1d": "5y",
}


def _cached(key):
    item = _CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if time.time() - ts <= CACHE_TTL_SECONDS:
        return value
    return None


def _set_cache(key, value):
    _CACHE[key] = (time.time(), value)
    return value


def _normalize_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None

    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

    if "datetime" not in df.columns:
        if df.index is not None:
            df = df.reset_index()
            df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
            for candidate in ("datetime", "date", "index"):
                if candidate in df.columns:
                    df = df.rename(columns={candidate: "datetime"})
                    break

    if "adj_close" in df.columns and "close" not in df.columns:
        df = df.rename(columns={"adj_close": "close"})

    required = ["datetime", "open", "high", "low", "close"]
    for col in required:
        if col not in df.columns:
            return None

    df = df[required]
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", utc=True).dt.tz_localize(None)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required)
    df = df.sort_values("datetime").drop_duplicates(subset=["datetime"]).reset_index(drop=True)

    if df.empty:
        return None
    return df


def _resample_4h(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    temp = df.copy()
    temp["datetime"] = pd.to_datetime(temp["datetime"], errors="coerce")
    temp = temp.dropna(subset=["datetime"]).set_index("datetime").sort_index()
    resampled = temp.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }).dropna().reset_index()
    return _normalize_df(resampled)


def _yahoo_direct_candles(symbol: str, interval: str, outputsize: int):
    tickers = _get_yahoo_tickers(symbol)
    if not tickers:
        return {"success": False, "error": f"Yahoo ticker برای {symbol} تعریف نشده است."}

    yahoo_interval = INTERVAL_MAP_YAHOO.get(interval, interval)
    yahoo_range = RANGE_BY_INTERVAL.get(yahoo_interval, "60d")
    errors = []

    for ticker in tickers:
        try:
            response = requests.get(
                YAHOO_CHART_URL.format(ticker=ticker),
                params={"interval": yahoo_interval, "range": yahoo_range, "includePrePost": "false"},
                timeout=25,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = response.json()

            chart = data.get("chart", {})
            if chart.get("error"):
                errors.append(f"{ticker}: {chart.get('error')}")
                continue

            result = (chart.get("result") or [None])[0]
            if not result:
                errors.append(f"{ticker}: Yahoo داده‌ای برنگرداند.")
                continue

            timestamps = result.get("timestamp") or []
            quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]

            if not timestamps or not quote:
                errors.append(f"{ticker}: Yahoo کندل معتبر نداد.")
                continue

            df = pd.DataFrame({
                "datetime": pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(None),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
            })

            df = _normalize_df(df)
            if df is None:
                errors.append(f"{ticker}: ساختار دیتای Yahoo قابل استفاده نبود.")
                continue

            if interval == "4h":
                df = _resample_4h(df)

            if df is None or len(df) < 60:
                errors.append(f"{ticker}: Yahoo کندل کافی برای تحلیل نداد.")
                continue

            df = df.tail(outputsize).reset_index(drop=True)
            source = "yahoo_direct" if ticker == tickers[0] else f"yahoo_direct_fallback:{ticker}"
            return {"success": True, "symbol": symbol, "interval": interval, "data": df, "source": source}

        except Exception as e:
            errors.append(f"{ticker}: Yahoo direct error: {e}")

    return {"success": False, "error": " | ".join(errors) if errors else "Yahoo داده‌ای برنگرداند."}


def _yfinance_candles(symbol: str, interval: str, outputsize: int):
    if yf is None:
        return {"success": False, "error": "پکیج yfinance نصب نیست."}

    tickers = _get_yahoo_tickers(symbol)
    if not tickers:
        return {"success": False, "error": f"yfinance ticker برای {symbol} تعریف نشده است."}

    yahoo_interval = INTERVAL_MAP_YAHOO.get(interval, interval)
    period = RANGE_BY_INTERVAL.get(yahoo_interval, "60d")
    errors = []

    for ticker in tickers:
        try:
            df = yf.download(
                tickers=ticker,
                period=period,
                interval=yahoo_interval,
                progress=False,
                auto_adjust=False,
                threads=False,
            )
            df = _normalize_df(df)

            if interval == "4h":
                df = _resample_4h(df)

            if df is None or len(df) < 60:
                errors.append(f"{ticker}: yfinance کندل کافی برای تحلیل نداد.")
                continue

            df = df.tail(outputsize).reset_index(drop=True)
            source = "yfinance" if ticker == tickers[0] else f"yfinance_fallback:{ticker}"
            return {"success": True, "symbol": symbol, "interval": interval, "data": df, "source": source}

        except Exception as e:
            errors.append(f"{ticker}: yfinance error: {e}")

    return {"success": False, "error": " | ".join(errors) if errors else "yfinance داده‌ای برنگرداند."}


def _stooq_candles(symbol: str, interval: str, outputsize: int):
    stooq_symbol = STOOQ_SYMBOLS.get(symbol)
    if not stooq_symbol:
        return {"success": False, "error": f"Stooq symbol برای {symbol} تعریف نشده است."}

    try:
        response = requests.get(
            STOOQ_CSV_URL,
            params={"s": stooq_symbol, "i": "d"},
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code != 200 or not response.text.strip():
            return {"success": False, "error": "Stooq داده‌ای برنگرداند."}

        from io import StringIO
        df = pd.read_csv(StringIO(response.text))

        if df.empty or "Date" not in df.columns:
            return {"success": False, "error": "ساختار دیتای Stooq معتبر نیست."}

        df = df.rename(columns={
            "Date": "datetime",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
        })
        df = _normalize_df(df)

        if df is None or len(df) < 60:
            return {"success": False, "error": "Stooq کندل کافی نداد."}

        df = df.tail(outputsize).reset_index(drop=True)
        return {"success": True, "symbol": symbol, "interval": interval, "data": df, "source": "stooq_daily"}

    except Exception as e:
        return {"success": False, "error": f"Stooq error: {e}"}


def _twelvedata_price(symbol: str):
    if not TWELVE_DATA_API_KEY:
        return {"success": False, "error": "TWELVE_DATA_API_KEY تنظیم نشده است."}

    try:
        response = requests.get(
            f"{TWELVE_BASE_URL}/price",
            params={"symbol": symbol, "apikey": TWELVE_DATA_API_KEY},
            timeout=15,
        )
        data = response.json()

        if "price" not in data:
            return {"success": False, "error": data.get("message", "خطا در دریافت قیمت TwelveData"), "raw": data}

        return {"success": True, "symbol": symbol, "price": float(data["price"]), "source": "twelvedata"}

    except Exception as e:
        return {"success": False, "error": f"TwelveData price error: {e}"}


def _twelvedata_candles(symbol: str, interval: str, outputsize: int):
    if not TWELVE_DATA_API_KEY:
        return {"success": False, "error": "TWELVE_DATA_API_KEY تنظیم نشده است."}

    try:
        response = requests.get(
            f"{TWELVE_BASE_URL}/time_series",
            params={"symbol": symbol, "interval": interval, "outputsize": outputsize, "apikey": TWELVE_DATA_API_KEY},
            timeout=25,
        )
        data = response.json()

        if "values" not in data:
            return {"success": False, "error": data.get("message", "خطا در دریافت کندل‌های TwelveData"), "raw": data}

        df = pd.DataFrame(data["values"])
        df = _normalize_df(df)

        if df is None or len(df) < 60:
            return {"success": False, "error": "TwelveData کندل کافی برای تحلیل نداد."}

        df = df.tail(outputsize).reset_index(drop=True)
        return {"success": True, "symbol": symbol, "interval": interval, "data": df, "source": "twelvedata"}

    except Exception as e:
        return {"success": False, "error": f"TwelveData candles error: {e}"}


def get_candles(symbol: str, interval: str = "5min", outputsize: int = 250):
    key = ("candles", f"{symbol}:{interval}", outputsize)
    cached = _cached(key)
    if cached:
        return cached

    errors = []

    result = _yahoo_direct_candles(symbol, interval, outputsize)
    if result.get("success"):
        return _set_cache(key, result)
    errors.append(f"YahooDirect: {result.get('error')}")

    result = _yfinance_candles(symbol, interval, outputsize)
    if result.get("success"):
        return _set_cache(key, result)
    errors.append(f"yfinance: {result.get('error')}")

    result = _stooq_candles(symbol, interval, outputsize)
    if result.get("success"):
        return _set_cache(key, result)
    errors.append(f"Stooq: {result.get('error')}")

    result = _twelvedata_candles(symbol, interval, outputsize)
    if result.get("success"):
        return _set_cache(key, result)
    errors.append(f"TwelveData: {result.get('error')}")

    return {"success": False, "error": " | ".join(errors[:4])}


def get_latest_price(symbol: str):
    key = ("price", symbol, 1)
    cached = _cached(key)
    if cached:
        return cached

    candles = get_candles(symbol, interval="5min", outputsize=80)
    if candles.get("success"):
        df = candles.get("data")
        if df is not None and not df.empty:
            price = float(df.iloc[-1]["close"])
            result = {"success": True, "symbol": symbol, "price": price, "source": candles.get("source", "candles")}
            return _set_cache(key, result)

    result = _twelvedata_price(symbol)
    if result.get("success"):
        return _set_cache(key, result)

    return {
        "success": False,
        "error": f"قیمت دریافت نشد. candles_error=({candles.get('error')}) | price_error=({result.get('error')})",
    }
