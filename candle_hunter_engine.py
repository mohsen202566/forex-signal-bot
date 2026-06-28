from __future__ import annotations

from dataclasses import dataclass

from config import WEIGHTS
from indicators import calculate_indicators
from okx_data import Candle
from scorer import Direction, PatternLabel


@dataclass(frozen=True)
class CandleHunterResult:
    label: PatternLabel
    score: int
    reasons: tuple[str, ...]


class CandleHunterEngine:
    def analyze(self, candles_5m: list[Candle], direction: Direction) -> CandleHunterResult:
        if len(candles_5m) < 84:
            return CandleHunterResult("NOISE", 0, ("کندل کافی برای شکار وجود ندارد.",))
        s = calculate_indicators(candles_5m)
        last = candles_5m[-1]
        prev = candles_5m[-2]
        atr = max(s.atr, s.close * 0.0001)
        body = abs(last.close - last.open)
        body_atr = body / atr
        range_atr = max(0.0, last.high - last.low) / atr
        reasons: list[str] = []
        if direction == "LONG":
            same_push = s.consecutive_up
            candle_ok = last.close > last.open and last.close >= prev.high * 0.9995
            wick_ok = s.upper_wick_pct <= 0.48
            rsi_late = s.rsi > 62
            macd_ok = s.macd_hist >= s.prev_macd_hist
            rsi_start = 49 <= s.rsi <= 58
        else:
            same_push = s.consecutive_down
            candle_ok = last.close < last.open and last.close <= prev.low * 1.0005
            wick_ok = s.lower_wick_pct <= 0.48
            rsi_late = s.rsi < 38
            macd_ok = s.macd_hist <= s.prev_macd_hist
            rsi_start = 42 <= s.rsi <= 52
        if same_push >= 3:
            return CandleHunterResult("LATE_CHASE", 0, ("چند کندل هم‌جهت پشت‌سرهم؛ ورود دیر/تعقیبی است.",))
        if range_atr > 1.85 and s.body_pct > 0.62 and s.volume_ratio > 2.75:
            return CandleHunterResult("EXHAUSTION", 0, ("کندل بزرگ + ولوم کلایمکس؛ احتمال ته حرکت.",))
        if rsi_late:
            return CandleHunterResult("LATE_CHASE", 2, ("RSI برای اسکالپ به محدوده خستگی/دیر شدن رسیده است.",))
        points = 0
        if candle_ok:
            points += 8; reasons.append("کندل 5m شکست/فشار میکرو در جهت درست دارد.")
        if 0.25 <= body_atr <= 1.20 and s.body_pct >= 0.38:
            points += 5; reasons.append("اندازه کندل برای شروع حرکت مناسب است، نه کلایمکس.")
        if wick_ok:
            points += 3
        if macd_ok:
            points += 4
        if rsi_start:
            points += 3; reasons.append("RSI 5m داخل بازه شروع حرکت است.")
        if 0.85 <= s.volume_ratio <= 2.6:
            points += 3
        elif s.volume_ratio > 3.2:
            points -= 4; reasons.append("ولوم 5m خیلی زیاد است؛ خطر دیر شدن.")
        if points >= 16:
            label: PatternLabel = "IGNITION_START"
            reasons.append("الگوی کندلی شروع حرکت تشخیص داده شد.")
        elif points >= 9:
            label = "PRE_IGNITION_WATCH"
            reasons.append("کندل نزدیک شروع است ولی تریگر کامل نیست.")
        else:
            label = "NOISE"
            reasons.append("کندل هنوز شکار قطعی نیست.")
        return CandleHunterResult(label, min(WEIGHTS.candle_entry, max(0, points)), tuple(reasons))
