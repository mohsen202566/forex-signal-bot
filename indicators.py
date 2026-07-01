from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Sequence

try:
    from okx_client import Candle
except Exception:  # pragma: no cover
    Candle = object  # type: ignore


@dataclass(frozen=True)
class Level:
    price: float
    kind: str  # support/resistance
    touches: int
    strength: float


def closes(candles: Sequence[Candle]) -> list[float]:
    return [float(c.close) for c in candles]


def highs(candles: Sequence[Candle]) -> list[float]:
    return [float(c.high) for c in candles]


def lows(candles: Sequence[Candle]) -> list[float]:
    return [float(c.low) for c in candles]


def volumes(candles: Sequence[Candle]) -> list[float]:
    return [float(c.volume) for c in candles]


def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    if period <= 1:
        return [float(v) for v in values]
    k = 2.0 / (period + 1.0)
    out: list[float] = []
    prev = float(values[0])
    for value in values:
        prev = float(value) * k + prev * (1.0 - k)
        out.append(prev)
    return out


def rsi(values: Sequence[float], period: int = 14) -> list[float]:
    if len(values) < 2:
        return [50.0] * len(values)
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for i in range(1, len(values)):
        change = float(values[i]) - float(values[i - 1])
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    out = [50.0] * len(values)
    avg_gain = mean(gains[1 : period + 1]) if len(gains) > period else mean(gains)
    avg_loss = mean(losses[1 : period + 1]) if len(losses) > period else mean(losses)
    for i in range(1, len(values)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i] = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float], list[float], list[float]]:
    if not values:
        return [], [], []
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def atr(candles: Sequence[Candle], period: int = 14) -> list[float]:
    if not candles:
        return []
    trs: list[float] = []
    prev_close = float(candles[0].close)
    for c in candles:
        tr = max(float(c.high) - float(c.low), abs(float(c.high) - prev_close), abs(float(c.low) - prev_close))
        trs.append(tr)
        prev_close = float(c.close)
    out: list[float] = []
    current = trs[0]
    for i, tr in enumerate(trs):
        if i < period:
            current = mean(trs[: i + 1])
        else:
            current = (current * (period - 1) + tr) / period
        out.append(current)
    return out


def candle_body_strength(candle: Candle) -> float:
    rng = float(candle.high) - float(candle.low)
    if rng <= 0:
        return 0.0
    return abs(float(candle.close) - float(candle.open)) / rng


def candle_direction(candle: Candle) -> str:
    if candle.close > candle.open:
        return "LONG"
    if candle.close < candle.open:
        return "SHORT"
    return "NEUTRAL"


def average_volume(candles: Sequence[Candle], period: int = 20) -> float:
    if not candles:
        return 0.0
    window = volumes(candles)[-period:]
    return mean(window) if window else 0.0


def detect_levels(candles: Sequence[Candle], *, min_touches: int = 3, tolerance_pct: float = 0.45) -> list[Level]:
    """Groups repeated daily swing reactions into simple support/resistance levels."""
    if len(candles) < 20:
        return []
    pivots: list[tuple[float, str]] = []
    data = list(candles)
    for i in range(2, len(data) - 2):
        c = data[i]
        if c.high >= max(data[i - 2].high, data[i - 1].high, data[i + 1].high, data[i + 2].high):
            pivots.append((float(c.high), "resistance"))
        if c.low <= min(data[i - 2].low, data[i - 1].low, data[i + 1].low, data[i + 2].low):
            pivots.append((float(c.low), "support"))
    levels: list[Level] = []
    for kind in ("support", "resistance"):
        prices = sorted([p for p, k in pivots if k == kind])
        groups: list[list[float]] = []
        for price in prices:
            placed = False
            for group in groups:
                base = mean(group)
                if base > 0 and abs(price - base) / base * 100.0 <= tolerance_pct:
                    group.append(price)
                    placed = True
                    break
            if not placed:
                groups.append([price])
        for group in groups:
            if len(group) >= min_touches:
                price = mean(group)
                strength = len(group) * 10.0
                levels.append(Level(price=price, kind=kind, touches=len(group), strength=strength))
    return sorted(levels, key=lambda x: x.price)


def nearest_level_above(levels: Sequence[Level], price: float, kind: str | None = None) -> Level | None:
    candidates = [l for l in levels if l.price > price and (kind is None or l.kind == kind)]
    return min(candidates, key=lambda l: l.price - price) if candidates else None


def nearest_level_below(levels: Sequence[Level], price: float, kind: str | None = None) -> Level | None:
    candidates = [l for l in levels if l.price < price and (kind is None or l.kind == kind)]
    return max(candidates, key=lambda l: l.price) if candidates else None
