import requests

from config import TWELVE_DATA_API_KEY


BASE_URL = "https://api.twelvedata.com"


def get_latest_price(symbol: str):
    """
    دریافت آخرین قیمت از Twelve Data
    مثال symbol:
    EUR/USD
    XAU/USD
    """

    if not TWELVE_DATA_API_KEY:
        return {
            "success": False,
            "error": "TWELVE_DATA_API_KEY تنظیم نشده است."
        }

    try:
        url = f"{BASE_URL}/price"
        params = {
            "symbol": symbol,
            "apikey": TWELVE_DATA_API_KEY
        }

        response = requests.get(url, params=params, timeout=15)
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
