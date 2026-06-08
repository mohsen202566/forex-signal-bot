import requests
import pandas as pd

from config import TWELVE_DATA_API_KEY

BASE_URL = "https://api.twelvedata.com"


def get_latest_price(symbol: str):
    if not TWELVE_DATA_API_KEY:
        return {
            "success": False,
            "error": "TWELVE_DATA_API_KEY تنظیم نشده است."
        }

    try:
        response = requests.get(
            f"{BASE_URL}/price",
            params={
                "symbol": symbol,
                "apikey": TWELVE_DATA_API_KEY
            },
            timeout=15
        )

        data = response.json()

        if "price" not in data:
            return {
                "success": False,
                "error": data.get("message", "خطا در دریافت قیمت"),
                "raw": data
            }

        return {
            "success": True,
            "symbol": symbol,
            "price": float(data["price"])
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def get_candles(symbol: str, interval: str = "5min", outputsize: int = 200):
    """
    دریافت کندل‌های واقعی از Twelve Data
    خروجی به صورت DataFrame مرتب‌شده از قدیمی به جدید
    """

    if not TWELVE_DATA_API_KEY:
        return {
            "success": False,
            "error": "TWELVE_DATA_API_KEY تنظیم نشده است."
        }

    try:
        response = requests.get(
            f"{BASE_URL}/time_series",
            params={
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": TWELVE_DATA_API_KEY
            },
            timeout=20
        )

        data = response.json()

        if "values" not in data:
            return {
                "success": False,
                "error": data.get("message", "خطا در دریافت کندل‌ها"),
                "raw": data
            }

        df = pd.DataFrame(data["values"])

        df["datetime"] = pd.to_datetime(df["datetime"])
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)

        df = df.sort_values("datetime").reset_index(drop=True)

        return {
            "success": True,
            "symbol": symbol,
            "interval": interval,
            "data": df
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
