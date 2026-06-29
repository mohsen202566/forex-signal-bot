from __future__ import annotations

from dataclasses import dataclass

from config import WEIGHTS
from indicators import IndicatorSnapshot
from scorer import Direction


@dataclass(frozen=True)
class EntryPrecisionResult:
    state: str
    precision_pct: float
    score: int
    confidence: int
    reasons: tuple[str, ...]


class EntryPrecisionEngine:
    def analyze(self, snapshot: IndicatorSnapshot, direction: Direction) -> EntryPrecisionResult:
        atr = max(snapshot.atr, snapshot.close * 0.0001)
        if direction == "LONG":
            base = min(snapshot.ema20, snapshot.vwap, snapshot.recent_low)
            distance = max(0.0, snapshot.close - base)
            flow_ok = snapshot.rsi_delta > 0 and snapshot.macd_hist_slope > 0
        else:
            base = max(snapshot.ema20, snapshot.vwap, snapshot.recent_high)
            distance = max(0.0, base - snapshot.close)
            flow_ok = snapshot.rsi_delta < 0 and snapshot.macd_hist_slope < 0
        precision = max(0.0, 100.0 - min(100.0, (distance / max(atr * 3.2, snapshot.close * 0.0008)) * 100.0))
        reasons: list[str] = [f"Entry Precision={precision:.1f}%"]
        if precision >= 82:
            return EntryPrecisionResult("READY", precision, WEIGHTS.entry_precision, 92, tuple(reasons + ["AI محدوده ورود دقیق را تایید کرد."]))
        if precision >= 65:
            return EntryPrecisionResult("READY", precision, max(8, WEIGHTS.entry_precision - 2), 78, tuple(reasons + ["AI محدوده ورود را قابل اجرا می‌داند." ]))
        if precision >= 42 and flow_ok:
            return EntryPrecisionResult("WATCH", precision, max(4, WEIGHTS.entry_precision - 6), 58, tuple(reasons + ["AI هنوز دنبال تایید دقیق‌تر است." ]))
        return EntryPrecisionResult("WAIT", precision, 1, 35, tuple(reasons + ["AI ورود دقیق را هنوز تایید نکرده است." ]))
