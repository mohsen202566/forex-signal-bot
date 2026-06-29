from __future__ import annotations

from dataclasses import dataclass

from config import AI_MIN_SAMPLES_MEDIUM, AI_MIN_SAMPLES_VALID, WEIGHTS
from indicators import IndicatorSnapshot
from scorer import Direction


@dataclass(frozen=True)
class RangeMemoryResult:
    profile: str
    score: int
    confidence: int
    experience: int
    adjustment: int
    expected_move_pct: float | None
    expected_mae_pct: float | None
    verdict: str
    reasons: tuple[str, ...]


class AIRangeMemory:
    def analyze(self, storage, *, symbol_name: str, direction: Direction, snapshot_5m: IndicatorSnapshot, snapshot_15m: IndicatorSnapshot, entry_quality: str, candle_pattern: str) -> RangeMemoryResult:
        profile = self.profile_key(direction, snapshot_5m, snapshot_15m, entry_quality, candle_pattern)
        stats = storage.indicator_range_stats(symbol_name=symbol_name, direction=direction, entry_quality=entry_quality, rsi_5m=snapshot_5m.rsi, rsi_15m=snapshot_15m.rsi, adx_15m=snapshot_15m.adx, volume_ratio_5m=snapshot_5m.volume_ratio, volume_ratio_15m=snapshot_15m.volume_ratio)
        samples = int(stats.get("samples", 0))
        wr = float(stats.get("win_rate", 0.0))
        avg_mfe = float(stats.get("avg_mfe", 0.0))
        avg_mae = float(stats.get("avg_mae", 0.0))
        base = self._seed_score(direction, snapshot_5m, snapshot_15m, entry_quality, candle_pattern)
        adjustment = 0
        verdict = "NEUTRAL"
        confidence = 45
        if samples >= AI_MIN_SAMPLES_VALID:
            adjustment = max(-8, min(8, int((wr - 50.0) / 5.0)))
            confidence = int(max(25, min(99, wr + min(18, samples // 7))))
            verdict = "POSITIVE" if wr >= 60 else "NEGATIVE" if wr <= 40 else "NEUTRAL"
        elif samples >= AI_MIN_SAMPLES_MEDIUM:
            adjustment = max(-4, min(4, int((wr - 50.0) / 8.0)))
            confidence = int(max(35, min(88, wr + samples // 2)))
            verdict = "POSITIVE" if wr >= 64 else "NEGATIVE" if wr <= 36 else "NEUTRAL"
        score = max(0, min(WEIGHTS.ai_memory, base + adjustment))
        reasons = [f"Range Memory: {samples} نمونه در بازه اندیکاتوری، WR={wr:.1f}%، verdict={verdict}"]
        return RangeMemoryResult(profile, score, confidence, samples, adjustment, avg_mfe or None, avg_mae or None, verdict, tuple(reasons))

    def profile_key(self, direction: Direction, s5: IndicatorSnapshot, s15: IndicatorSnapshot, entry_quality: str, candle_pattern: str) -> str:
        return "|".join([
            direction, entry_quality, candle_pattern,
            f"rsi5:{self._bin(s5.rsi, 5)}", f"rsi15:{self._bin(s15.rsi, 5)}",
            f"macd5:{self._slope_bin(s5.macd_hist_slope)}", f"adx15:{self._bin(s15.adx, 4)}",
            f"vol5:{self._vol_bin(s5.volume_ratio)}", f"vol15:{self._vol_bin(s15.volume_ratio)}",
            f"atr15:{self._atr_bin(s15.atr_pct)}",
        ])

    @staticmethod
    def _seed_score(direction: Direction, s5: IndicatorSnapshot, s15: IndicatorSnapshot, entry_quality: str, candle_pattern: str) -> int:
        points = 8
        if direction == "LONG":
            if s5.rsi_delta > 0:
                points += 3
            if s5.macd_hist_slope > 0 and s15.macd_hist_slope >= 0:
                points += 3
            if s15.plus_di >= s15.minus_di:
                points += 2
        else:
            if s5.rsi_delta < 0:
                points += 3
            if s5.macd_hist_slope < 0 and s15.macd_hist_slope <= 0:
                points += 3
            if s15.minus_di >= s15.plus_di:
                points += 2
        if entry_quality in {"EARLY_IGNITION", "GOOD_ENTRY", "POWER_BUILDING", "REVERSAL_BUILDING"}:
            points += 2
        if candle_pattern == "REVERSAL_BUILDING":
            points += 2
        return max(0, min(WEIGHTS.ai_memory, points))

    @staticmethod
    def _bin(value: float, size: int) -> str:
        low = int(value // size) * size
        return f"{low}-{low + size}"

    @staticmethod
    def _slope_bin(value: float) -> str:
        if value > 0:
            return "up"
        if value < 0:
            return "down"
        return "flat"

    @staticmethod
    def _vol_bin(value: float) -> str:
        if value < 0.6:
            return "low"
        if value <= 1.4:
            return "normal"
        if value <= 2.6:
            return "pressure"
        if value <= 3.6:
            return "hot"
        return "climax"

    @staticmethod
    def _atr_bin(value: float) -> str:
        pct = value * 100
        if pct < 0.20:
            return "quiet"
        if pct < 0.60:
            return "start"
        if pct < 1.20:
            return "active"
        return "expanded"
