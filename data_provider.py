# -*- coding: utf-8 -*-
import time
from typing import Dict, Tuple

import pandas as pd
import requests

from config import TWELVE_DATA_API_KEY

BASE_URL = "https://api.twelvedata.com"
_CACHE: Dict[Tuple[str, str, int], Tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 45

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

def get_latest_price(symbol: str):
    if not TWELVE_DATA_API_KEY:
        return {"success": False, "error": "TWELVE_DATA_API_KEY تنظیم نشده است."}

    key = ("price", symbol, 1)
    cached = _cached(key)
    if cached:
        return cached

    try:
        response = requests.get(
            f"{BASE_URL}/price",
            params={"symbol": symbol, "apikey": TWELVE_DATA_API_KEY},
            timeout=15,
        )
        data = response.json()

        if "price" not in data:
            return {"success": False, "error": data.get("message", "خطا در دریافت قیمت"), "raw": data}

        result = {"success": True, "symbol": symbol, "price": float(data["price"])}
        return _set_cache(key, result)

    except Exception as e:
        return {"success": False, "error": str(e)}

def get_candles(symbol: str, interval: str = "5min", outputsize: int = 250):
    if not TWELVE_DATA_API_KEY:
        return {"success": False, "error": "TWELVE_DATA_API_KEY تنظیم نشده است."}

    key = ("candles", f"{symbol}:{interval}", outputsize)
    cached = _cached(key)
    if cached:
        return cached

    try:
        response = requests.get(
            f"{BASE_URL}/time_series",
            params={
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": TWELVE_DATA_API_KEY,
            },
            timeout=25,
        )
        data = response.json()

        if "values" not in data:
            return {"success": False, "error": data.get("message", "خطا در دریافت کندل‌ها"), "raw": data}

        df = pd.DataFrame(data["values"])
        required = ["datetime", "open", "high", "low", "close"]
        for col in required:
            if col not in df.columns:
                return {"success": False, "error": f"ستون {col} در دیتای دریافتی وجود ندارد."}

        df["datetime"] = pd.to_datetime(df["datetime"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values("datetime").reset_index(drop=True)

        if len(df) < 60:
            return {"success": False, "error": "کندل کافی برای تحلیل دریافت نشد."}

        result = {"success": True, "symbol": symbol, "interval": interval, "data": df}
        return _set_cache(key, result)

    except Exception as e:
        return {"success": False, "error": str(e)}
