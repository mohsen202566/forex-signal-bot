from __future__ import annotations

from dataclasses import dataclass

from config import WEIGHTS
from indicators import IndicatorSnapshot
from scorer import Direction, DirectionState


@dataclass(frozen=True)
class PreIgnitionResult:
    state: DirectionState
    score: int
    confidence: int
    reasons: tuple[str, ...]


class PreIgnitionEngine:
    def analyze(self, snapshot_15m: IndicatorSnapshot, snapshot_5m: IndicatorSnapshot, direction: Direction) -> PreIgnitionResult:
        points = 0
        reasons: list[str] = []
        s15 = snapshot_15m
        s5 = snapshot_5m
        if direction == "LONG":
            if 48 <= s15.rsi <= 59:
                points += 5; reasons.append("RSI 15m در بازه شروع پامپ است.")
            elif s15.rsi > 63:
                points -= 5; reasons.append("RSI 15m بالا است؛ احتمال خستگی پامپ.")
            if 49 <= s5.rsi <= 58:
                points += 4; reasons.append("RSI 5m برای ورود لانگ هنوز دیر نیست.")
            elif s5.rsi > 62:
                points -= 5
            if s15.macd_hist >= s15.prev_macd_hist:
                points += 5; reasons.append("MACD 15m تازه رو به تقویت لانگ است.")
            if s5.macd_hist >= s5.prev_macd_hist:
                points += 3
            if 14 <= s15.adx <= 28 and s15.plus_di >= s15.minus_di:
                points += 4; reasons.append("ADX/DI در فاز شروع قدرت لانگ است.")
            if s5.close >= min(s5.ema20, s5.vwap):
                points += 2
        else:
            if 41 <= s15.rsi <= 52:
                points += 5; reasons.append("RSI 15m در بازه شروع دامپ است.")
            elif s15.rsi < 37:
                points -= 5; reasons.append("RSI 15m خیلی پایین است؛ احتمال خستگی دامپ.")
            if 42 <= s5.rsi <= 52:
                points += 4; reasons.append("RSI 5m برای ورود شورت هنوز دیر نیست.")
            elif s5.rsi < 38:
                points -= 5
            if s15.macd_hist <= s15.prev_macd_hist:
                points += 5; reasons.append("MACD 15m تازه رو به تقویت شورت است.")
            if s5.macd_hist <= s5.prev_macd_hist:
                points += 3
            if 14 <= s15.adx <= 28 and s15.minus_di >= s15.plus_di:
                points += 4; reasons.append("ADX/DI در فاز شروع قدرت شورت است.")
            if s5.close <= max(s5.ema20, s5.vwap):
                points += 2
        if 0.85 <= s15.volume_ratio <= 2.4:
            points += 3
        elif s15.volume_ratio > 3.0:
            points -= 5; reasons.append("ولوم 15m کلایمکس‌مانند است.")
        if 0.85 <= s5.volume_ratio <= 2.6:
            points += 2
        elif s5.volume_ratio > 3.3:
            points -= 4; reasons.append("ولوم 5m خیلی انفجاری است؛ ریسک دیر شدن.")
        atr_ratio = s15.atr / max(s15.prev_atr, s15.close * 0.0001)
        if 0.92 <= atr_ratio <= 1.45:
            points += 2
        elif atr_ratio > 1.8:
            points -= 4
        score = max(0, min(WEIGHTS.pre_ignition, points))
        state: DirectionState = direction if score >= 13 else "NEUTRAL"
        confidence = int(min(100, score / max(1, WEIGHTS.pre_ignition) * 100))
        reasons.append("پیش‌قدرت شکار فعال است." if state != "NEUTRAL" else "پیش‌قدرت هنوز کامل نیست؛ مناسب watch/ghost.")
        return PreIgnitionResult(state, score, confidence, tuple(reasons))
