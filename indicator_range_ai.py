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
    """Learns real scalping start ranges per symbol + direction + indicator zone.

    This is intentionally not a display-only AI. It returns a decision bias used by entry_gate.
    """

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
        base_score, base_reasons = self._heuristic_score(direction, snapshot_5m, snapshot_15m)
        verdict = "NEUTRAL"
        adjustment = 0
        score = base_score
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
            else:
                verdict = "NEUTRAL"
        elif samples >= 12:
            adjustment = max(-5, min(5, int((wr - 50.0) / 8.0)))
            confidence = int(max(35, min(88, wr + samples // 2)))
            verdict = "POSITIVE" if wr >= 64 else "NEGATIVE" if wr <= 36 else "NEUTRAL"
            reasons.append("AI نمونه متوسط دارد؛ اثر کنترل‌شده اعمال شد.")
        else:
            reasons.append("AI هنوز نمونه کافی ندارد؛ از منطق شروع حرکت استفاده شد.")
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
            f"adx15:{self._bin(s15.adx, 4)}",
            f"vol5:{self._vol_bin(s5.volume_ratio)}",
            f"vol15:{self._vol_bin(s15.volume_ratio)}",
            f"atr15:{self._atr_bin(s15.atr / max(s15.close, 1e-9))}",
        ])

    def _heuristic_score(self, direction: Direction, s5: IndicatorSnapshot, s15: IndicatorSnapshot) -> tuple[int, list[str]]:
        points = 8
        reasons: list[str] = []
        if direction == "LONG":
            if 50 <= s5.rsi <= 58 and 47 <= s15.rsi <= 60:
                points += 4; reasons.append("AI Range Seed: RSI لانگ در شروع حرکت است.")
            elif s5.rsi > 62 or s15.rsi > 64:
                points -= 5; reasons.append("AI Range Seed: RSI لانگ دیر/خسته است.")
            if s5.macd_hist >= s5.prev_macd_hist and s15.macd_hist >= s15.prev_macd_hist:
                points += 3
            if 14 <= s15.adx <= 28 and s15.plus_di >= s15.minus_di:
                points += 3
        else:
            if 42 <= s5.rsi <= 52 and 40 <= s15.rsi <= 54:
                points += 4; reasons.append("AI Range Seed: RSI شورت در شروع حرکت است.")
            elif s5.rsi < 38 or s15.rsi < 36:
                points -= 5; reasons.append("AI Range Seed: RSI شورت دیر/خسته است.")
            if s5.macd_hist <= s5.prev_macd_hist and s15.macd_hist <= s15.prev_macd_hist:
                points += 3
            if 14 <= s15.adx <= 28 and s15.minus_di >= s15.plus_di:
                points += 3
        if 0.85 <= s5.volume_ratio <= 2.6 and 0.80 <= s15.volume_ratio <= 2.4:
            points += 2
        elif s5.volume_ratio > 3.2 or s15.volume_ratio > 3.0:
            points -= 4
        atr_ratio = s15.atr / max(s15.prev_atr, s15.close * 0.0001)
        if 0.9 <= atr_ratio <= 1.55:
            points += 1
        elif atr_ratio > 1.85:
            points -= 3
        return max(0, min(WEIGHTS.ai_memory, points)), reasons

    def _bin(self, value: float, size: int) -> str:
        low = int(value // size) * size
        return f"{low}-{low + size}"

    def _vol_bin(self, value: float) -> str:
        if value < 0.8:
            return "low"
        if value <= 1.4:
            return "normal-rising"
        if value <= 2.4:
            return "strong-start"
        if value <= 3.2:
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
