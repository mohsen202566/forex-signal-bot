"""اندیکاتورهای بدون وابستگی سنگین برای DIFT-5M."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from utils import safe_float


@dataclass(slots=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirm: bool = True

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return max(0.0, self.high - self.low)

    @property
    def body_ratio(self) -> float:
        r = self.range
        return self.body / r if r > 0 else 0.0

    @property
    def close_position(self) -> float:
        r = self.range
        return (self.close - self.low) / r if r > 0 else 0.5


def parse_okx_candles(rows: list[list[str]]) -> list[Candle]:
    candles: list[Candle] = []
    # OKX معمولاً جدیدترین کندل را اول می‌دهد؛ ما قدیمی به جدید می‌خواهیم.
    for row in reversed(rows or []):
        if len(row) < 6:
            continue
        candles.append(
            Candle(
                ts=int(float(row[0])),
                open=safe_float(row[1]),
                high=safe_float(row[2]),
                low=safe_float(row[3]),
                close=safe_float(row[4]),
                volume=safe_float(row[5]),
                confirm=str(row[-1]) == "1" if len(row) >= 9 else True,
            )
        )
    return candles


def closes(candles: Iterable[Candle]) -> list[float]:
    return [c.close for c in candles]


def highs(candles: Iterable[Candle]) -> list[float]:
    return [c.high for c in candles]


def lows(candles: Iterable[Candle]) -> list[float]:
    return [c.low for c in candles]


def volumes(candles: Iterable[Candle]) -> list[float]:
    return [c.volume for c in candles]


def sma(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = []
    if length <= 0:
        return [None for _ in values]
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= length:
            s -= values[i - length]
        out.append(s / length if i >= length - 1 else None)
    return out


def ema(values: list[float], length: int) -> list[float | None]:
    if not values or length <= 0:
        return []
    out: list[float | None] = []
    k = 2 / (length + 1)
    prev: float | None = None
    for i, v in enumerate(values):
        if i < length - 1:
            out.append(None)
            continue
        if prev is None:
            prev = sum(values[i - length + 1:i + 1]) / length
        else:
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def atr(candles: list[Candle], length: int) -> list[float | None]:
    trs: list[float] = []
    prev_close: float | None = None
    for c in candles:
        if prev_close is None:
            tr = c.high - c.low
        else:
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(max(0.0, tr))
        prev_close = c.close
    return sma(trs, length)


def rolling_vwap(candles: list[Candle], length: int) -> list[float | None]:
    out: list[float | None] = []
    pv: list[float] = []
    vv: list[float] = []
    for c in candles:
        typical = (c.high + c.low + c.close) / 3
        pv.append(typical * c.volume)
        vv.append(c.volume)
    for i in range(len(candles)):
        start = max(0, i - length + 1)
        vol = sum(vv[start:i + 1])
        out.append(sum(pv[start:i + 1]) / vol if vol > 0 and i >= length - 1 else None)
    return out


def adx(candles: list[Candle], length: int = 14) -> list[float | None]:
    if len(candles) < length + 2:
        return [None for _ in candles]
    trs = [0.0]
    plus_dm = [0.0]
    minus_dm = [0.0]
    for i in range(1, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        up = cur.high - prev.high
        down = prev.low - cur.low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))

    tr_s = sma(trs, length)
    p_s = sma(plus_dm, length)
    m_s = sma(minus_dm, length)
    dx: list[float | None] = []
    for tr, p, m in zip(tr_s, p_s, m_s):
        if tr in (None, 0) or p is None or m is None:
            dx.append(None)
            continue
        pdi = 100 * p / tr
        mdi = 100 * m / tr
        denom = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / denom if denom > 0 else None)
    dx_vals = [0.0 if x is None else x for x in dx]
    raw = sma(dx_vals, length)
    out: list[float | None] = []
    for i, v in enumerate(raw):
        out.append(v if i >= (2 * length - 2) else None)
    return out


def last_valid(values: list[float | None], fallback: float = 0.0) -> float:
    for v in reversed(values):
        if v is not None:
            return float(v)
    return fallback
