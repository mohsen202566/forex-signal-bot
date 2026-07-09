"""کلاینت دیتای عمومی OKX با کش نماد، تبدیل درست instId و کنترل rate-limit.

ورودی داخلی ربات مثل BTCUSDT است، اما OKX برای فیوچرز/سواپ instId را به شکل BTC-USDT-SWAP می‌خواهد.
این فایل جلوی خطاهای تکراری 51001 و 429 را می‌گیرد و نماد نامعتبر را از اسکن بعدی حذف می‌کند.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time

import requests

import config
from indicators import Candle, parse_okx_candles
from utils import logger, normalize_symbol, safe_float, to_okx_inst_id


@dataclass(slots=True)
class OrderFlow:
    bid_qty: float
    ask_qty: float
    bid_ratio: float
    taker_buy_qty: float
    taker_sell_qty: float
    taker_ratio: float
    spread_pct: float
    funding_rate: float | None
    open_interest: float | None


@dataclass(slots=True)
class MarketData:
    symbol: str
    inst_id: str
    candles_5m: list[Candle]
    candles_15m: list[Candle]
    candles_1h: list[Candle]
    flow: OrderFlow
    last_price: float


class OKXClient:
    def __init__(self, base_url: str = config.OKX_BASE_URL, timeout: int = config.REQUEST_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self._last_request_ts = 0.0
        self._inst_map: dict[str, str] | None = None   # BTCUSDT -> BTC-USDT-SWAP
        self._bad_symbols: dict[str, float] = {}       # symbol -> retry_after_ts

    # -----------------------------
    # Rate limit / request
    # -----------------------------
    def _pace(self) -> None:
        delay = max(0.0, float(getattr(config, "OKX_REQUEST_DELAY_SECONDS", 0.18)))
        if delay <= 0:
            return
        now = time.monotonic()
        wait = delay - (now - self._last_request_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        max_retries = max(1, int(getattr(config, "OKX_MAX_RETRIES", 2)))
        for attempt in range(max_retries):
            try:
                self._pace()
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429:
                    retry_after = safe_float(r.headers.get("Retry-After"), 1.5)
                    logger.warning("OKX 429؛ مکث %.1f ثانیه | %s %s", retry_after, path, params)
                    time.sleep(max(1.0, retry_after))
                    continue
                r.raise_for_status()
                payload = r.json()
            except Exception as exc:
                last_error = exc
                if attempt + 1 < max_retries:
                    time.sleep(0.7 * (attempt + 1))
                    continue
                raise RuntimeError(f"خطا در دریافت OKX {path}: {exc}") from exc

            code = str(payload.get("code", "0"))
            if code == "0":
                return payload
            if code == "51001":
                # Instrument ID نامعتبر است؛ retry فایده ندارد.
                raise RuntimeError(f"OKX instrument نامعتبر است: {params.get('instId')} | {payload.get('msg')}")
            raise RuntimeError(f"پاسخ ناموفق OKX: {payload}")
        raise RuntimeError(f"OKX ناموفق بعد از retry: {last_error}")

    # -----------------------------
    # Instruments / symbol resolver
    # -----------------------------
    @staticmethod
    def _internal_from_inst_id(inst_id: str) -> str:
        parts = str(inst_id or "").upper().split("-")
        if len(parts) >= 3 and parts[1] == "USDT":
            return f"{parts[0]}USDT"
        return normalize_symbol(inst_id)

    def get_instruments(self, force: bool = False) -> list[dict[str, Any]]:
        """لیست خام Instrumentهای OKX."""
        payload = self._get("/api/v5/public/instruments", {"instType": config.OKX_INST_TYPE})
        return [x for x in (payload.get("data") or []) if isinstance(x, dict)]

    def refresh_instruments(self, force: bool = False) -> dict[str, str]:
        if self._inst_map is not None and not force:
            return self._inst_map
        instruments = self.get_instruments(force=force)
        out: dict[str, str] = {}
        suffix = f"-USDT-{config.OKX_INST_TYPE}".upper()
        for item in instruments:
            inst_id = str(item.get("instId") or "").upper()
            state = str(item.get("state") or "").lower()
            if state and state not in {"live", "trading"}:
                continue
            if not inst_id.endswith(suffix):
                continue
            out[self._internal_from_inst_id(inst_id)] = inst_id
        self._inst_map = out
        return out

    def available_symbols(self) -> set[str]:
        return set(self.refresh_instruments().keys())

    def resolve_inst_id(self, symbol: str) -> str:
        internal = normalize_symbol(symbol)
        now = time.time()
        retry_after = self._bad_symbols.get(internal, 0)
        if retry_after and retry_after > now:
            raise RuntimeError(f"نماد OKX موقتاً حذف شده است: {internal}")

        inst_map = self.refresh_instruments()
        inst_id = inst_map.get(internal)
        if inst_id:
            return inst_id

        # اگر نماد در کش نبود، یک بار کش را تازه کن. بعد از آن دیگر اسپم نمی‌کنیم.
        inst_map = self.refresh_instruments(force=True)
        inst_id = inst_map.get(internal)
        if inst_id:
            return inst_id

        self._bad_symbols[internal] = now + int(getattr(config, "OKX_BAD_SYMBOL_COOLDOWN_SECONDS", 3600))
        guessed = to_okx_inst_id(internal)
        raise RuntimeError(f"نماد در OKX SWAP پیدا نشد: {internal} / {guessed}")

    # -----------------------------
    # Market endpoints
    # -----------------------------
    def get_candles(self, symbol: str, bar: str, limit: int) -> list[Candle]:
        inst_id = self.resolve_inst_id(symbol)
        payload = self._get("/api/v5/market/candles", {"instId": inst_id, "bar": bar, "limit": str(limit)})
        return parse_okx_candles(payload.get("data") or [])

    def get_ticker(self, symbol: str) -> dict[str, Any]:
        inst_id = self.resolve_inst_id(symbol)
        payload = self._get("/api/v5/market/ticker", {"instId": inst_id})
        data = payload.get("data") or []
        return data[0] if data else {}

    def get_orderbook(self, symbol: str, depth: int = config.OKX_ORDERBOOK_DEPTH) -> dict[str, Any]:
        inst_id = self.resolve_inst_id(symbol)
        payload = self._get("/api/v5/market/books", {"instId": inst_id, "sz": str(depth)})
        data = payload.get("data") or []
        return data[0] if data else {}

    def get_trades(self, symbol: str, limit: int = config.OKX_TRADE_LIMIT) -> list[dict[str, Any]]:
        inst_id = self.resolve_inst_id(symbol)
        payload = self._get("/api/v5/market/trades", {"instId": inst_id, "limit": str(limit)})
        return [x for x in (payload.get("data") or []) if isinstance(x, dict)]

    def get_funding_rate(self, symbol: str) -> float | None:
        if not getattr(config, "OKX_FETCH_FUNDING_EVERY_SCAN", False):
            return None
        try:
            inst_id = self.resolve_inst_id(symbol)
            payload = self._get("/api/v5/public/funding-rate", {"instId": inst_id})
            data = payload.get("data") or []
            if data:
                return safe_float(data[0].get("fundingRate"), None)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("funding OKX ناموفق بود %s: %s", symbol, exc)
        return None

    def get_open_interest(self, symbol: str) -> float | None:
        if not getattr(config, "OKX_FETCH_FUNDING_EVERY_SCAN", False):
            return None
        try:
            inst_id = self.resolve_inst_id(symbol)
            payload = self._get("/api/v5/public/open-interest", {"instType": config.OKX_INST_TYPE, "instId": inst_id})
            data = payload.get("data") or []
            if data:
                return safe_float(data[0].get("oi") or data[0].get("oiCcy"), None)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("open interest OKX ناموفق بود %s: %s", symbol, exc)
        return None

    @staticmethod
    def _sum_book_qty(rows: list[list[str]]) -> float:
        total = 0.0
        for row in rows or []:
            if len(row) >= 2:
                total += safe_float(row[1])
        return total

    def build_order_flow(self, symbol: str, ticker: dict[str, Any] | None = None) -> OrderFlow:
        ticker = ticker or self.get_ticker(symbol)
        book = self.get_orderbook(symbol)
        trades = self.get_trades(symbol)

        bids = book.get("bids") or []
        asks = book.get("asks") or []
        bid_qty = self._sum_book_qty(bids)
        ask_qty = self._sum_book_qty(asks)
        total_book = bid_qty + ask_qty
        bid_ratio = bid_qty / total_book if total_book > 0 else 0.5

        buy_qty = 0.0
        sell_qty = 0.0
        for t in trades:
            size = safe_float(t.get("sz"))
            side = str(t.get("side") or "").lower()
            if side == "buy":
                buy_qty += size
            elif side == "sell":
                sell_qty += size
        taker_ratio = buy_qty / max(sell_qty, 1e-12)

        bid_px = safe_float(ticker.get("bidPx"))
        ask_px = safe_float(ticker.get("askPx"))
        last_px = safe_float(ticker.get("last"))
        mid = (bid_px + ask_px) / 2 if bid_px > 0 and ask_px > 0 else last_px
        spread_pct = ((ask_px - bid_px) / mid * 100) if mid > 0 and ask_px >= bid_px > 0 else 0.0

        return OrderFlow(
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            bid_ratio=bid_ratio,
            taker_buy_qty=buy_qty,
            taker_sell_qty=sell_qty,
            taker_ratio=taker_ratio,
            spread_pct=spread_pct,
            funding_rate=self.get_funding_rate(symbol),
            open_interest=self.get_open_interest(symbol),
        )

    def get_market_data(self, symbol: str) -> MarketData:
        symbol = normalize_symbol(symbol)
        inst_id = self.resolve_inst_id(symbol)
        candles_5m = self.get_candles(symbol, "5m", config.OKX_CANDLE_LIMIT_5M)
        candles_15m = self.get_candles(symbol, "15m", config.OKX_CANDLE_LIMIT_15M)
        candles_1h = self.get_candles(symbol, "1H", config.OKX_CANDLE_LIMIT_1H)
        ticker = self.get_ticker(symbol)
        last_price = safe_float(ticker.get("last") or ticker.get("lastPx") or (candles_5m[-1].close if candles_5m else 0))
        flow = self.build_order_flow(symbol, ticker=ticker)
        return MarketData(symbol=symbol, inst_id=inst_id, candles_5m=candles_5m, candles_15m=candles_15m, candles_1h=candles_1h, flow=flow, last_price=last_price)
