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
        points = 0

        bullish = last.close > last.open
        bearish = last.close < last.open
        green_reclaim = bullish and last.close >= max(prev.close, min(s.ema20, s.vwap) * 0.9992)
        red_rejection = bearish and last.close <= min(prev.close, max(s.ema20, s.vwap) * 1.0008)

        if direction == "LONG":
            impulse_ok = bullish and last.close >= prev.high * 0.9993
            wick_ok = s.upper_wick_pct <= 0.55
            macd_ok = s.macd_hist_slope > 0
            neutral_push = s.rsi >= 49 and s.rsi_delta > 0
            reversal_ok = (s.consecutive_down >= 1 or s.rsi <= 45 or s.lower_wick_pct >= 0.30) and green_reclaim and macd_ok
        else:
            impulse_ok = bearish and last.close <= prev.low * 1.0007
            wick_ok = s.lower_wick_pct <= 0.55
            macd_ok = s.macd_hist_slope < 0
            neutral_push = s.rsi <= 51 and s.rsi_delta < 0
            reversal_ok = (s.consecutive_up >= 1 or s.rsi >= 55 or s.upper_wick_pct >= 0.30) and red_rejection and macd_ok

        if reversal_ok:
            points += 17
            reasons.append("کندل 5m برگشت بعد از مصرف حرکت قبلی را تأیید می‌کند.")
            if 0.80 <= s.volume_ratio <= 3.40:
                points += 3
            return CandleHunterResult("REVERSAL_BUILDING", min(WEIGHTS.candle_entry, points), tuple(reasons))

        # A huge candle with climax volume is useful information, but not an automatic block.
        if range_atr > 2.15 and s.body_pct > 0.66 and s.volume_ratio > 3.6:
            points += 6
            reasons.append("کندل بسیار بزرگ و ولوم کلایمکس؛ برای ورود مستقیم نیاز به تأیید بعدی دارد.")
            return CandleHunterResult("EXHAUSTION", min(WEIGHTS.candle_entry, points), tuple(reasons))

        if impulse_ok:
            points += 8; reasons.append("کندل 5m فشار میکرو در جهت شکار دارد.")
        if 0.16 <= body_atr <= 1.55 and s.body_pct >= 0.30:
            points += 5; reasons.append("اندازه کندل برای شروع/ادامه اسکالپ قابل استفاده است.")
        if wick_ok:
            points += 3
        if macd_ok:
            points += 5; reasons.append("کندل با تقویت MACD همراه است.")
        if neutral_push:
            points += 4; reasons.append("RSI از ناحیه خنثی به سمت جهت شکار فشار گرفته است.")
        if 0.65 <= s.volume_ratio <= 3.20:
            points += 4
        elif s.volume_ratio > 4.0:
            points -= 2; reasons.append("ولوم خیلی انفجاری است؛ ریسک کلایمکس لحاظ شد.")

        if points >= 18:
            label: PatternLabel = "IGNITION_START"
            reasons.append("الگوی کندلی شروع حرکت تشخیص داده شد.")
        elif points >= 13:
            label = "POWER_BUILDING"
            reasons.append("کندل نشان می‌دهد قدرت جهت در حال ساخته‌شدن است.")
        elif points >= 8:
            label = "PRE_IGNITION_WATCH"
            reasons.append("کندل نزدیک شکار است ولی بهتر است در Watch/Ghost پیگیری شود.")
        else:
            label = "NOISE"
            reasons.append("کندل هنوز شکار قطعی نیست.")
        return CandleHunterResult(label, min(WEIGHTS.candle_entry, max(0, points)), tuple(reasons))
