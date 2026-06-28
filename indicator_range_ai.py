from __future__ import annotations

from dataclasses import dataclass

from config import WEIGHTS
from indicators import IndicatorSnapshot
from scorer import Direction


@dataclass(frozen=True)
class IndicatorRangeAIResult:
    score: int
    confidence: int
    experience: int
    adjustment: int
    expected_move_pct: float | None
    verdict: str
    profile: str
    reasons: tuple[str, ...]


class IndicatorRangeAI:
    """Learns real scalping start/reversal ranges per symbol + direction + indicator zone."""

    def analyze(self, storage, *, symbol_name: str, direction: Direction, snapshot_5m: IndicatorSnapshot, snapshot_15m: IndicatorSnapshot, entry_quality: str, candle_pattern: str) -> IndicatorRangeAIResult:
        profile = self.profile_key(direction, snapshot_5m, snapshot_15m, entry_quality, candle_pattern)
        stats = storage.indicator_range_stats(
            symbol_name=symbol_name,
            direction=direction,
            entry_quality=entry_quality,
            rsi_5m=snapshot_5m.rsi,
            rsi_15m=snapshot_15m.rsi,
            adx_15m=snapshot_15m.adx,
            volume_ratio_5m=snapshot_5m.volume_ratio,
            volume_ratio_15m=snapshot_15m.volume_ratio,
        )
        samples = int(stats.get("samples", 0))
        wr = float(stats.get("win_rate", 0.0))
        avg_mfe = float(stats.get("avg_mfe", 0.0))
        base_score, base_reasons = self._heuristic_score(direction, snapshot_5m, snapshot_15m, entry_quality, candle_pattern)
        verdict = "NEUTRAL"
        adjustment = 0
        confidence = 45
        reasons = base_reasons + [f"AI Range: {samples} نمونه مشابه، WR={wr:.1f}%"]
        if samples >= 35:
            adjustment = max(-10, min(10, int((wr - 50.0) / 4.0)))
            confidence = int(max(25, min(99, wr + min(18, samples // 7))))
            if wr >= 60:
                verdict = "POSITIVE"
                reasons.append("AI بازه اندیکاتوری این ارز/جهت را مثبت می‌داند.")
            elif wr <= 40:
                verdict = "NEGATIVE"
                reasons.append("AI بازه اندیکاتوری این ارز/جهت را منفی می‌داند؛ Real نباید زده شود.")
        elif samples >= 12:
            adjustment = max(-5, min(5, int((wr - 50.0) / 8.0)))
            confidence = int(max(35, min(88, wr + samples // 2)))
            verdict = "POSITIVE" if wr >= 64 else "NEGATIVE" if wr <= 36 else "NEUTRAL"
            reasons.append("AI نمونه متوسط دارد؛ اثر کنترل‌شده اعمال شد.")
        else:
            reasons.append("AI هنوز نمونه کافی ندارد؛ منطق شروع قدرت/برگشت اعمال شد.")
        score = max(0, min(WEIGHTS.ai_memory, base_score + adjustment))
        expected = avg_mfe if samples >= 12 and avg_mfe > 0 else None
        return IndicatorRangeAIResult(score, confidence, samples, adjustment, expected, verdict, profile, tuple(reasons))

    def profile_key(self, direction: Direction, s5: IndicatorSnapshot, s15: IndicatorSnapshot, entry_quality: str, candle_pattern: str) -> str:
        return "|".join([
            direction,
            entry_quality,
            candle_pattern,
            f"rsi5:{self._bin(s5.rsi, 5)}",
            f"rsi15:{self._bin(s15.rsi, 5)}",
            f"rsi_delta5:{self._slope_bin(s5.rsi_delta)}",
            f"macd_slope5:{self._slope_bin(s5.macd_hist_slope)}",
            f"adx15:{self._bin(s15.adx, 4)}",
            f"vol5:{self._vol_bin(s5.volume_ratio)}",
            f"vol15:{self._vol_bin(s15.volume_ratio)}",
            f"atr15:{self._atr_bin(s15.atr / max(s15.close, 1e-9))}",
        ])

    def _heuristic_score(self, direction: Direction, s5: IndicatorSnapshot, s15: IndicatorSnapshot, entry_quality: str, candle_pattern: str) -> tuple[int, list[str]]:
        points = 8
        reasons: list[str] = []
        if direction == "LONG":
            if (s5.rsi > 50 and s5.rsi_delta >= -0.10) or (s5.rsi >= 47 and s5.rsi_delta > 0.35):
                points += 4; reasons.append("AI Seed: RSI لانگ از تعادل به سمت قدرت حرکت کرده است.")
            if s5.macd_hist_slope > 0 and s15.macd_hist_slope >= 0:
                points += 3
            if s15.plus_di >= s15.minus_di or s5.rsi_delta > 0.65:
                points += 3
            if candle_pattern == "REVERSAL_BUILDING":
                points += 3; reasons.append("AI Seed: الگوی برگشت لانگ بعد از دامپ قابل یادگیری است.")
        else:
            if (s5.rsi < 50 and s5.rsi_delta <= 0.10) or (s5.rsi <= 53 and s5.rsi_delta < -0.35):
                points += 4; reasons.append("AI Seed: RSI شورت از تعادل به سمت ضعف حرکت کرده است.")
            if s5.macd_hist_slope < 0 and s15.macd_hist_slope <= 0:
                points += 3
            if s15.minus_di >= s15.plus_di or s5.rsi_delta < -0.65:
                points += 3
            if candle_pattern == "REVERSAL_BUILDING":
                points += 3; reasons.append("AI Seed: الگوی برگشت شورت بعد از پامپ قابل یادگیری است.")
        if entry_quality in {"EARLY_IGNITION", "GOOD_ENTRY", "POWER_BUILDING", "REVERSAL_BUILDING"}:
            points += 2
        if 0.60 <= s5.volume_ratio <= 3.4 and 0.60 <= s15.volume_ratio <= 3.0:
            points += 2
        elif s5.volume_ratio > 4.2 or s15.volume_ratio > 4.0:
            points -= 3
        atr_ratio = s15.atr / max(s15.prev_atr, s15.close * 0.0001)
        if 0.70 <= atr_ratio <= 2.05:
            points += 1
        elif atr_ratio > 2.35:
            points -= 2
        return max(0, min(WEIGHTS.ai_memory, points)), reasons

    def _bin(self, value: float, size: int) -> str:
        low = int(value // size) * size
        return f"{low}-{low + size}"

    def _slope_bin(self, value: float) -> str:
        if value > 0:
            return "up"
        if value < 0:
            return "down"
        return "flat"

    def _vol_bin(self, value: float) -> str:
        if value < 0.6:
            return "low"
        if value <= 1.4:
            return "normal"
        if value <= 2.6:
            return "pressure"
        if value <= 3.6:
            return "hot"
        return "climax"

    def _atr_bin(self, value: float) -> str:
        pct = value * 100
        if pct < 0.20:
            return "quiet"
        if pct < 0.60:
            return "start"
        if pct < 1.20:
            return "active"
        return "expanded"
