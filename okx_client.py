"""کلاینت OKX برای دیتای عمومی و مانیتورینگ سیگنال‌های عادی.
تمام تحلیل‌ها فقط از OKX تغذیه می‌شوند.
"""
from __future__ import annotations

import time
from typing import Any

import requests

import config

class OKXError(RuntimeError):
    pass

class OKXClient:
    def __init__(self, base_url: str = config.OKX_BASE_URL, timeout: int = config.OKX_REQUEST_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            r = self.session.get(url, params=params or {}, timeout=self.timeout)
            if r.status_code >= 400:
                raise OKXError(f"HTTP {r.status_code}: {r.text[:300]}")
            payload = r.json()
        except Exception as exc:
            if isinstance(exc, OKXError):
                raise
            raise OKXError(f"OKX connection error: {exc}") from exc
        if isinstance(payload, dict) and str(payload.get("code", "0")) not in ("0", "200", ""):
            raise OKXError(f"OKX error: {payload.get('msg') or payload}")
        return payload

    def get_ticker(self, inst_id: str) -> dict[str, Any]:
        payload = self._get("/api/v5/market/ticker", {"instId": inst_id})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            raise OKXError(f"ticker empty: {inst_id}")
        return data[0]

    def get_last_price(self, inst_id: str) -> float:
        item = self.get_ticker(inst_id)
        return float(item.get("last") or item.get("lastPx") or 0.0)

    def get_candles(self, inst_id: str, bar: str = config.OKX_BAR, limit: int = config.OKX_CANDLE_LIMIT) -> list[dict[str, float]]:
        payload = self._get("/api/v5/market/candles", {"instId": inst_id, "bar": bar, "limit": str(limit)})
        rows = payload.get("data") if isinstance(payload, dict) else []
        out: list[dict[str, float]] = []
        # OKX: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
        for r in reversed(rows or []):
            try:
                out.append({
                    "ts": int(r[0]),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5]),
                    "vol_ccy": float(r[6]) if len(r) > 6 else 0.0,
                    "vol_quote": float(r[7]) if len(r) > 7 else 0.0,
                    "confirm": int(r[8]) if len(r) > 8 else 1,
                })
            except Exception:
                continue
        if len(out) < 20:
            raise OKXError(f"candles too few: {inst_id}")
        return out

    @staticmethod
    def reached_tp_or_sl(candles: list[dict[str, float]], side: str, tp: float, sl: float, after_ts_ms: int) -> tuple[str | None, float | None, int | None]:
        side = side.upper()
        for c in candles:
            if int(c["ts"]) <= int(after_ts_ms):
                continue
            h, l = float(c["high"]), float(c["low"])
            if side == "LONG":
                if l <= sl:
                    return "SL", sl, int(c["ts"])
                if h >= tp:
                    return "TP", tp, int(c["ts"])
            else:
                if h >= sl:
                    return "SL", sl, int(c["ts"])
                if l <= tp:
                    return "TP", tp, int(c["ts"])
        return None, None, None

    @staticmethod
    def max_favorable_adverse(candles: list[dict[str, float]], side: str, entry: float, after_ts_ms: int) -> tuple[float, float]:
        mfe = 0.0
        mae = 0.0
        side = side.upper()
        for c in candles:
            if int(c["ts"]) <= int(after_ts_ms):
                continue
            if side == "LONG":
                mfe = max(mfe, (float(c["high"]) - entry) / entry * 100.0)
                mae = min(mae, (float(c["low"]) - entry) / entry * 100.0)
            else:
                mfe = max(mfe, (entry - float(c["low"])) / entry * 100.0)
                mae = min(mae, (entry - float(c["high"])) / entry * 100.0)
        return mfe, mae
