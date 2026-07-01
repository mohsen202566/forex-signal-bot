from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

import config


@dataclass(frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class OKXClient:
    """OKX public-data client. It is used only for analysis, never execution."""

    def __init__(self, base_url: str | None = None, session: requests.Session | None = None) -> None:
        self.base_url = (base_url or config.OKX_BASE_URL).rstrip("/")
        self.session = session or requests.Session()

    def get_swap_symbols(self) -> set[str]:
        payload = self._get("/api/v5/public/instruments", {"instType": "SWAP"})
        result: set[str] = set()
        for item in payload.get("data", []):
            inst_id = str(item.get("instId") or "").upper()
            if inst_id.endswith("-USDT-SWAP"):
                result.add(inst_id)
        return result

    def get_candles(self, inst_id: str, bar: str, limit: int = 200) -> list[Candle]:
        payload = self._get("/api/v5/market/candles", {"instId": inst_id, "bar": bar, "limit": str(limit)})
        candles: list[Candle] = []
        for row in payload.get("data", []):
            try:
                candles.append(
                    Candle(
                        ts=int(row[0]),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                )
            except (TypeError, ValueError, IndexError):
                continue
        candles.sort(key=lambda c: c.ts)
        return candles

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=config.OKX_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("code", "0")) != "0":
            raise RuntimeError(f"خطای OKX: {payload}")
        return payload
