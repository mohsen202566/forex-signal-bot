"""ساخت پروفایل رفتاری غلتان هفت‌روزه برای هر ارز."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median
from typing import Any, Iterable
import logging
import time

import config
from okx_client import OKXClient
from storage import Storage

logger = logging.getLogger("adaptive_bot.profiles")


@dataclass(frozen=True)
class SymbolSpec:
    base: str
    okx: str
    toobit: str

    @property
    def id(self) -> str:
        return self.base.upper()


def quantile(values: Iterable[float], q: float, default: float = 0.0) -> float:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return default
    if len(clean) == 1:
        return clean[0]
    q = max(0.0, min(1.0, float(q)))
    pos = (len(clean) - 1) * q
    low = int(pos)
    high = min(low + 1, len(clean) - 1)
    frac = pos - low
    return clean[low] * (1.0 - frac) + clean[high] * frac


def _pct(a: float, b: float) -> float:
    return abs(b - a) / a * 100.0 if a > 0 else 0.0


def _quote_volume(candle: dict[str, Any]) -> float:
    quote = float(candle.get("vol_quote") or 0.0)
    if quote > 0:
        return quote
    return float(candle.get("volume") or 0.0) * float(candle.get("close") or 0.0)


def build_behavior_profile(symbol: SymbolSpec, candles: list[dict[str, Any]]) -> dict[str, Any]:
    if len(candles) < config.PROFILE_MIN_CANDLES:
        raise ValueError(f"نمونه پروفایل کم است: {len(candles)}")
    candles = sorted(candles, key=lambda row: int(row["ts"]))
    bodies: list[float] = []
    ranges: list[float] = []
    volumes: list[float] = []
    directions: list[float] = []
    signed_bodies: list[float] = []

    for candle in candles:
        open_price = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        body = _pct(open_price, close)
        range_pct = (high - low) / open_price * 100.0 if open_price > 0 else 0.0
        directionality = body / range_pct if range_pct > 0 else 0.0
        bodies.append(body)
        ranges.append(range_pct)
        volumes.append(_quote_volume(candle))
        directions.append(directionality)
        signed_bodies.append((close - open_price) / open_price * 100.0 if open_price > 0 else 0.0)

    move_q = quantile(bodies, config.TRIGGER_MOVE_QUANTILE)
    range_q = quantile(ranges, config.TRIGGER_SUPPORT_QUANTILE)
    volume_q = quantile(volumes, config.TRIGGER_SUPPORT_QUANTILE)
    noise_q75 = quantile(bodies, 0.75)
    event_indices: dict[str, list[int]] = {"LONG": [], "SHORT": []}
    for index, candle in enumerate(candles[:-max(config.HORIZONS_MINUTES)]):
        if bodies[index] < move_q or directions[index] < config.PROFILE_EVENT_MIN_DIRECTIONALITY:
            continue
        if ranges[index] < range_q and volumes[index] < volume_q:
            continue
        side = "LONG" if signed_bodies[index] > 0 else "SHORT"
        if signed_bodies[index] != 0:
            event_indices[side].append(index)

    horizons: dict[str, dict[str, dict[str, float | int]]] = {"LONG": {}, "SHORT": {}}
    for side in ("LONG", "SHORT"):
        indices = event_indices[side]
        fallback_indices = event_indices["LONG"] + event_indices["SHORT"]
        use_indices = indices if len(indices) >= config.PROFILE_MIN_EVENTS_PER_SIDE else fallback_indices
        for horizon in config.HORIZONS_MINUTES:
            mfe_values: list[float] = []
            mae_values: list[float] = []
            time_values: list[float] = []
            for index in use_indices:
                if index + horizon >= len(candles):
                    continue
                entry = float(candles[index]["close"])
                future = candles[index + 1 : index + horizon + 1]
                if entry <= 0 or not future:
                    continue
                if side == "LONG":
                    favorable = [(float(row["high"]) - entry) / entry * 100.0 for row in future]
                    adverse = [(entry - float(row["low"])) / entry * 100.0 for row in future]
                else:
                    favorable = [(entry - float(row["low"])) / entry * 100.0 for row in future]
                    adverse = [(float(row["high"]) - entry) / entry * 100.0 for row in future]
                mfe = max(0.0, max(favorable))
                mae = max(0.0, max(adverse))
                best_index = favorable.index(max(favorable)) + 1
                mfe_values.append(mfe)
                mae_values.append(mae)
                time_values.append(float(best_index))
            horizons[side][str(horizon)] = {
                "samples": len(mfe_values),
                "mfe_q50": quantile(mfe_values, 0.50),
                "mfe_q60": quantile(mfe_values, 0.60),
                "mfe_q70": quantile(mfe_values, 0.70),
                "mae_q70": quantile(mae_values, 0.70),
                "mae_q75": quantile(mae_values, 0.75),
                "time_to_mfe_median": median(time_values) if time_values else float(horizon),
            }

    windows: dict[str, dict[str, float]] = {}
    for window in config.TRIGGER_WINDOWS_SECONDS:
        time_scale = sqrt(window / 60.0)
        volume_scale = window / 60.0
        windows[str(window)] = {
            "move_threshold_pct": max(config.MIN_WINDOW_MOVE_PCT[window], move_q * time_scale),
            "range_threshold_pct": max(config.MIN_WINDOW_RANGE_PCT[window], range_q * time_scale),
            "volume_threshold_quote": max(0.0, volume_q * volume_scale),
        }

    return {
        "version": 1,
        "symbol_id": symbol.id,
        "okx_symbol": symbol.okx,
        "toobit_symbol": symbol.toobit,
        "created_at": int(time.time()),
        "candle_count": len(candles),
        "first_ts": int(candles[0]["ts"]),
        "last_ts": int(candles[-1]["ts"]),
        "base": {
            "move_q72_pct": move_q,
            "range_q60_pct": range_q,
            "volume_q60_quote": volume_q,
            "noise_q75_pct": noise_q75,
            "directionality_median": quantile(directions, 0.50),
        },
        "windows": windows,
        "events": {"long": len(event_indices["LONG"]), "short": len(event_indices["SHORT"])},
        "horizons": horizons,
    }


class ProfileManager:
    def __init__(self, okx: OKXClient, storage: Storage) -> None:
        self.okx = okx
        self.storage = storage
        self.profiles: dict[str, dict[str, Any]] = {}

    def load_or_build(self, symbols: list[SymbolSpec], force: bool = False) -> dict[str, dict[str, Any]]:
        ready: dict[str, dict[str, Any]] = {}
        logger.info("[PROFILE_START] symbols=%d days=%d force=%s", len(symbols), config.PROFILE_DAYS, force)
        for index, symbol in enumerate(symbols, start=1):
            try:
                cached = self.storage.load_profile(symbol.id)
                if not force and cached and self.storage.is_profile_fresh(symbol.id):
                    ready[symbol.id] = cached
                    logger.info(
                        "[PROFILE_READY] %s source=cache candles=%s progress=%d/%d",
                        symbol.id, cached.get("candle_count"), index, len(symbols),
                    )
                    continue
                candles = self.okx.get_history_candles(symbol.okx)
                profile = build_behavior_profile(symbol, candles)
                self.storage.save_profile(symbol.id, symbol.okx, symbol.toobit, profile)
                ready[symbol.id] = profile
                logger.info(
                    "[PROFILE_READY] %s source=okx candles=%d events_long=%d events_short=%d progress=%d/%d",
                    symbol.id, len(candles), profile["events"]["long"], profile["events"]["short"], index, len(symbols),
                )
            except Exception as exc:
                cached = self.storage.load_profile(symbol.id)
                if cached:
                    ready[symbol.id] = cached
                    logger.warning("[PROFILE_FALLBACK] %s reason=%s", symbol.id, exc)
                else:
                    logger.warning("[PROFILE_FAILED] %s reason=%s", symbol.id, exc)
                    self.storage.add_health_event("profile", "warning", str(exc), symbol.id)
        self.profiles = ready
        self.storage.set("profiles_ready", len(ready))
        self.storage.set("profiles_updated_at", int(time.time()))
        logger.info("[PROFILE_DONE] ready=%d total=%d", len(ready), len(symbols))
        return ready

    def get(self, symbol_id: str) -> dict[str, Any] | None:
        return self.profiles.get(symbol_id)
