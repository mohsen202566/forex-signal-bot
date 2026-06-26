"""کلاینت‌های OKX و Toobit.

OKX منبع تحلیل، کندل، قیمت و سیگنال عادی است.
Toobit فقط برای باز کردن REAL، تایید باز شدن و نتیجه REAL استفاده می‌شود.

برای Toobit پیشنهاد پروژه: فایل سالم ربات قبلی را به نام `tobit_client.py` کنار این فایل بگذار.
این Adapter فقط یک لایه نازک است تا معماری جدید به آن وصل شود.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests


class OKXClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("OKX_BASE_URL", "https://www.okx.com")

    def get_candles(self, symbol: str, bar: str = "15m", limit: int = 120) -> list[dict[str, float]]:
        inst_id = symbol.replace("USDT", "-USDT-SWAP")
        url = f"{self.base_url}/api/v5/market/candles"
        r = requests.get(url, params={"instId": inst_id, "bar": bar, "limit": str(limit)}, timeout=10)
        r.raise_for_status()
        data = r.json().get("data", [])
        candles = []
        for row in reversed(data):
            # OKX: ts,o,h,l,c,vol,...
            candles.append({
                "ts": int(row[0]), "open": float(row[1]), "high": float(row[2]),
                "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
            })
        return candles

    def get_last_price(self, symbol: str) -> float:
        inst_id = symbol.replace("USDT", "-USDT-SWAP")
        url = f"{self.base_url}/api/v5/market/ticker"
        r = requests.get(url, params={"instId": inst_id}, timeout=10)
        r.raise_for_status()
        return float(r.json()["data"][0]["last"])

    def get_open_interest_series(self, symbol: str) -> list[float]:
        # OKX public OI history endpoint coverage may vary؛ اگر نشد خالی برمی‌گردانیم.
        return []


class ToobitAdapter:
    def __init__(self):
        self.connected = False
        self.legacy = None
        try:
            import tobit_client  # فایل سالم ربات قبلی
            # اگر کلاس/تابع متفاوت بود، همین Adapter را با نام‌های واقعی هماهنگ کن.
            if hasattr(tobit_client, "ToobitClient"):
                self.legacy = tobit_client.ToobitClient()
            else:
                self.legacy = tobit_client
            self.connected = True
        except Exception:
            self.connected = False

    def account_panel(self) -> dict[str, Any]:
        if not self.connected or not self.legacy:
            return {"connected": False}
        for name in ("account_panel", "get_account_panel", "get_balance_panel"):
            fn = getattr(self.legacy, name, None)
            if callable(fn):
                out = fn()
                out["connected"] = True
                return out
        return {"connected": True, "balance": "نامشخص", "margin": "نامشخص", "free_margin": "نامشخص"}

    def open_position_with_tp_sl(self, *, symbol: str, side: str, margin_usdt: float, leverage: int, entry: float, tp: float, sl: float) -> dict[str, Any]:
        """پوزیشن + TP + SL باید در یک فرآیند ثبت شوند، نه جدا جدا."""
        if not self.connected or not self.legacy:
            return {"ok": False, "error": "TOBIT_CLIENT_NOT_CONNECTED"}
        for name in ("open_position_with_tp_sl", "place_order_with_tp_sl", "open_futures_position"):
            fn = getattr(self.legacy, name, None)
            if callable(fn):
                return fn(symbol=symbol, side=side, margin_usdt=margin_usdt, leverage=leverage, entry=entry, tp=tp, sl=sl)
        return {"ok": False, "error": "LEGACY_METHOD_NOT_FOUND"}

    def position_exists(self, symbol: str, side: str | None = None) -> dict[str, Any]:
        if not self.connected or not self.legacy:
            return {"exists": False, "error": "TOBIT_CLIENT_NOT_CONNECTED"}
        for name in ("position_exists", "get_open_position", "get_position"):
            fn = getattr(self.legacy, name, None)
            if callable(fn):
                out = fn(symbol=symbol) if side is None else fn(symbol=symbol, side=side)
                if isinstance(out, dict):
                    return out
                return {"exists": bool(out), "raw": out}
        return {"exists": False, "error": "LEGACY_METHOD_NOT_FOUND"}

    def closed_result(self, symbol: str, side: str, position_id: str | None = None) -> dict[str, Any]:
        if not self.connected or not self.legacy:
            return {"closed": False}
        for name in ("closed_result", "get_closed_result", "check_position_result"):
            fn = getattr(self.legacy, name, None)
            if callable(fn):
                return fn(symbol=symbol, side=side, position_id=position_id)
        return {"closed": False}


def sleep_until_open_confirmation():
    time.sleep(int(os.getenv("TOBIT_OPEN_CONFIRM_SECONDS", "70")))
