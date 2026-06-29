from __future__ import annotations

from dataclasses import dataclass

from config import WEIGHTS
from indicators import IndicatorSnapshot


@dataclass(frozen=True)
class MarketModeResult:
    mode: str
    score: int
    risk: int
    reasons: tuple[str, ...]


class MarketModeBrain:
    def analyze(self, snapshot_5m: IndicatorSnapshot, snapshot_15m: IndicatorSnapshot) -> MarketModeResult:
        reasons: list[str] = []
        atr_ratio = snapshot_15m.atr / max(snapshot_15m.prev_atr, snapshot_15m.close * 0.0001)
        volume = max(snapshot_5m.volume_ratio, snapshot_15m.volume_ratio)
        if volume > 4.2 or atr_ratio > 2.45:
            return MarketModeResult("CLIMAX_RISK", max(2, WEIGHTS.market_mode - 6), 70, ("بازار حالت کلایمکس/ریسک مصرف حرکت دارد.",))
        if 0.75 <= atr_ratio <= 2.05 and 0.65 <= volume <= 3.4:
            if abs(snapshot_5m.macd_hist_slope) > 0 and abs(snapshot_5m.rsi_delta) > 0.20:
                return MarketModeResult("MOMENTUM_BUILDING", WEIGHTS.market_mode, 25, ("بازار برای شکار شروع حرکت فعال است.",))
            return MarketModeResult("NORMAL", max(5, WEIGHTS.market_mode - 2), 35, ("بازار عادی و قابل بررسی است.",))
        if volume < 0.55 or atr_ratio < 0.70:
            reasons.append("بازار کم‌جان است؛ AI باید صبورتر باشد.")
            return MarketModeResult("QUIET", 3, 45, tuple(reasons))
        return MarketModeResult("NOISY", 4, 55, ("بازار نویزی است؛ TP/SL و Real باید محتاط‌تر باشد.",))
