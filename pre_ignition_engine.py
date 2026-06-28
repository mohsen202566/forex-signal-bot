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
        neutral_band = min(3.5, max(1.0, s15.atr_pct * 120.0))
        if direction == "LONG":
            if s5.rsi > 50 + neutral_band or (s5.rsi >= 47 and s5.rsi_delta > 0.30):
                points += 5; reasons.append("RSI 5m به سمت لانگ فشار گرفته است.")
            if s15.rsi_delta > 0 or s15.rsi > 50 + neutral_band * 0.6:
                points += 5; reasons.append("RSI 15m برای لانگ بهتر شده است.")
            if s15.macd_hist_slope > 0:
                points += 5; reasons.append("MACD 15m در حال تقویت لانگ است.")
            if s5.macd_hist_slope > 0:
                points += 4
            if s15.plus_di >= s15.minus_di or s5.rsi_delta > 0.65:
                points += 4; reasons.append("DI یا شتاب کوتاه‌مدت لانگ را پشتیبانی می‌کند.")
            if s5.close >= min(s5.ema20, s5.vwap):
                points += 2
            if (s5.rsi <= 45 or s5.consecutive_down >= 2) and s5.rsi_delta > 0 and s5.macd_hist_slope > 0:
                points += 5; reasons.append("دامپ قبلی در حال تبدیل به برگشت لانگ است.")
        else:
            if s5.rsi < 50 - neutral_band or (s5.rsi <= 53 and s5.rsi_delta < -0.30):
                points += 5; reasons.append("RSI 5m به سمت شورت فشار گرفته است.")
            if s15.rsi_delta < 0 or s15.rsi < 50 - neutral_band * 0.6:
                points += 5; reasons.append("RSI 15m برای شورت ضعیف شده است.")
            if s15.macd_hist_slope < 0:
                points += 5; reasons.append("MACD 15m در حال تقویت شورت است.")
            if s5.macd_hist_slope < 0:
                points += 4
            if s15.minus_di >= s15.plus_di or s5.rsi_delta < -0.65:
                points += 4; reasons.append("DI یا شتاب کوتاه‌مدت شورت را پشتیبانی می‌کند.")
            if s5.close <= max(s5.ema20, s5.vwap):
                points += 2
            if (s5.rsi >= 55 or s5.consecutive_up >= 2) and s5.rsi_delta < 0 and s5.macd_hist_slope < 0:
                points += 5; reasons.append("پامپ قبلی در حال تبدیل به برگشت شورت است.")
        if 0.60 <= s15.volume_ratio <= 3.0:
            points += 3
        elif s15.volume_ratio > 4.0:
            points -= 2; reasons.append("ولوم 15m خیلی انفجاری است؛ کلایمکس محتمل است.")
        if 0.60 <= s5.volume_ratio <= 3.4:
            points += 3
        elif s5.volume_ratio > 4.4:
            points -= 2; reasons.append("ولوم 5m خیلی انفجاری است؛ باید با کندل تأیید شود.")
        atr_ratio = s15.atr / max(s15.prev_atr, s15.close * 0.0001)
        if 0.70 <= atr_ratio <= 2.05:
            points += 2
        elif atr_ratio > 2.35:
            points -= 2
        score = max(0, min(WEIGHTS.pre_ignition, points))
        state: DirectionState = direction if score >= max(10, int(WEIGHTS.pre_ignition * 0.42)) else "NEUTRAL"
        confidence = int(min(100, score / max(1, WEIGHTS.pre_ignition) * 100))
        reasons.append("پیش‌قدرت شکار فعال است." if state != "NEUTRAL" else "پیش‌قدرت کامل نیست؛ مناسب Watch/Ghost.")
        return PreIgnitionResult(state, score, confidence, tuple(reasons))
