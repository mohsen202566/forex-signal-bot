import requests
import pandas as pd
from config import TWELVE_DATA_API_KEY

BASE_URL = "https://api.twelvedata.com"


def _api_error(data, default="خطا در دریافت دیتا"):
    if isinstance(data, dict):
        return data.get("message") or data.get("error") or data.get("status") or default
    return default


def get_latest_price(symbol: str):
    if not TWELVE_DATA_API_KEY:
        return {"success": False, "error": "TWELVE_DATA_API_KEY روی VPS تنظیم نشده است."}
    try:
        response = requests.get(
            f"{BASE_URL}/price",
            params={"symbol": symbol, "apikey": TWELVE_DATA_API_KEY},
            timeout=15,
        )
        data = response.json()
        if "price" not in data:
            return {"success": False, "error": _api_error(data, "خطا در دریافت قیمت"), "raw": data}
        return {"success": True, "symbol": symbol, "price": float(data["price"])}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_candles(symbol: str, interval: str = "5min", outputsize: int = 250):
    if not TWELVE_DATA_API_KEY:
        return {"success": False, "error": "TWELVE_DATA_API_KEY روی VPS تنظیم نشده است."}
    try:
        response = requests.get(
            f"{BASE_URL}/time_series",
            params={
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": TWELVE_DATA_API_KEY,
            },
            timeout=20,
        )
        data = response.json()
        if "values" not in data:
            return {"success": False, "error": _api_error(data, "خطا در دریافت کندل‌ها"), "raw": data}
        df = pd.DataFrame(data["values"])
        required = ["datetime", "open", "high", "low", "close"]
        for col in required:
            if col not in df.columns:
                return {"success": False, "error": f"ستون {col} در دیتای دریافتی وجود ندارد."}
        df["datetime"] = pd.to_datetime(df["datetime"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values("datetime").reset_index(drop=True)
        if len(df) < 60:
            return {"success": False, "error": f"کندل کافی برای {symbol} در تایم‌فریم {interval} دریافت نشد."}
        return {"success": True, "symbol": symbol, "interval": interval, "data": df}
    except Exception as e:
        return {"success": False, "error": str(e)}
