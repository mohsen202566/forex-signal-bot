from __future__ import annotations

from dataclasses import dataclass

from config import WEIGHTS
from indicators import IndicatorSnapshot
from scorer import Direction, DirectionState


@dataclass(frozen=True)
class DirectionResult:
    state: DirectionState
    score: int
    confidence: int
    raw_strength: int
    reasons: tuple[str, ...]


class DirectionEngine:
    def analyze_15m_scalp(self, snapshot_15m: IndicatorSnapshot, snapshot_5m: IndicatorSnapshot) -> DirectionResult:
        long_raw, long_reasons = self._scalp_side_strength(snapshot_15m, snapshot_5m, "LONG")
        short_raw, short_reasons = self._scalp_side_strength(snapshot_15m, snapshot_5m, "SHORT")
        if long_raw >= short_raw + 8 and long_raw >= 18:
            confidence = min(100, int(long_raw * 2.2))
            score = min(WEIGHTS.direction, 4 + confidence // 22)
            return DirectionResult("LONG", score, confidence, int(long_raw), tuple(long_reasons + ["15m/5m جهت اسکالپ لانگ را می‌دهد."]))
        if short_raw >= long_raw + 8 and short_raw >= 18:
            confidence = min(100, int(short_raw * 2.2))
            score = min(WEIGHTS.direction, 4 + confidence // 22)
            return DirectionResult("SHORT", score, confidence, int(-short_raw), tuple(short_reasons + ["15m/5m جهت اسکالپ شورت را می‌دهد."]))
        raw = int(long_raw - short_raw)
        confidence = min(100, abs(raw) * 2)
        return DirectionResult("NEUTRAL", min(3, confidence // 15), confidence, raw, ("15m/5m جهت شروع حرکت را واضح نشان نمی‌دهد.",))

    def analyze_1h_context(self, snapshot: IndicatorSnapshot, direction: Direction) -> DirectionResult:
        raw, reasons = self._raw_strength(snapshot)
        if raw >= 45:
            state: DirectionState = "LONG"
        elif raw <= -45:
            state = "SHORT"
        else:
            state = "NEUTRAL"
        confidence = min(100, int(abs(raw)))
        if state == direction:
            score = 4
            reasons.append("1H فقط context است و با جهت سیگنال موافق است.")
        elif state == "NEUTRAL":
            score = 3
            reasons.append("1H خنثی است؛ برای اسکالپ رد کامل نمی‌شود.")
        else:
            score = 0
            reasons.append("1H خلاف جهت است؛ فقط هشدار/کاهش امتیاز، نه قفل ورود.")
        return DirectionResult(state, score, confidence, raw, tuple(reasons))

    # Backward-compatible methods kept for older imports/tests.
    def analyze_1h(self, snapshot: IndicatorSnapshot) -> DirectionResult:
        raw, reasons = self._raw_strength(snapshot)
        if raw >= 52:
            state: DirectionState = "LONG"
        elif raw <= -52:
            state = "SHORT"
        else:
            state = "NEUTRAL"
        confidence = min(100, int(abs(raw)))
        score = min(WEIGHTS.direction, max(0, int(confidence * WEIGHTS.direction / 100)))
        return DirectionResult(state, score, confidence, raw, tuple(reasons))

    def analyze_4h_bias(self, snapshot: IndicatorSnapshot, direction: Direction) -> DirectionResult:
        raw, reasons = self._raw_strength(snapshot)
        if raw >= 45:
            state: DirectionState = "LONG"
        elif raw <= -45:
            state = "SHORT"
        else:
            state = "NEUTRAL"
        confidence = min(100, int(abs(raw)))
        if state == direction:
            score = 2
            reasons.append("4H با جهت سیگنال موافق است.")
        elif state == "NEUTRAL":
            score = 1
            reasons.append("4H خنثی است؛ رد کامل نمی‌شود.")
        else:
            score = 0
            reasons.append("4H خلاف جهت است؛ فقط امتیاز کم می‌شود.")
        return DirectionResult(state, score, confidence, raw, tuple(reasons))

    def _scalp_side_strength(self, s15: IndicatorSnapshot, s5: IndicatorSnapshot, direction: Direction) -> tuple[int, list[str]]:
        points = 0
        reasons: list[str] = []
        if direction == "LONG":
            if 48 <= s15.rsi <= 59:
                points += 8; reasons.append("RSI 15m در بازه شروع لانگ است، نه ته حرکت.")
            elif 59 < s15.rsi <= 64:
                points += 2; reasons.append("RSI 15m کمی کشیده است؛ با احتیاط.")
            elif s15.rsi > 64:
                points -= 8; reasons.append("RSI 15m بالا است؛ احتمال دیر شدن لانگ.")
            if 49 <= s5.rsi <= 58:
                points += 6; reasons.append("RSI 5m برای شروع پامپ مناسب است.")
            elif s5.rsi > 62:
                points -= 7; reasons.append("RSI 5m بالا است؛ قدرت کورکورانه حساب نمی‌شود.")
            if s15.macd_hist >= s15.prev_macd_hist:
                points += 7; reasons.append("MACD 15m در فاز تقویت اولیه لانگ است.")
            if s5.macd_hist >= s5.prev_macd_hist:
                points += 5
            if 14 <= s15.adx <= 28 and s15.plus_di >= s15.minus_di:
                points += 7; reasons.append("ADX/DI شروع قدرت لانگ را نشان می‌دهد.")
            elif s15.adx > 34:
                points -= 5; reasons.append("ADX خیلی بالا؛ ممکن است حرکت مصرف شده باشد.")
            if s5.close >= s5.ema20:
                points += 4
        else:
            if 41 <= s15.rsi <= 52:
                points += 8; reasons.append("RSI 15m در بازه شروع شورت است.")
            elif 36 <= s15.rsi < 41:
                points += 2; reasons.append("RSI 15m کمی پایین است؛ با احتیاط.")
            elif s15.rsi < 36:
                points -= 8; reasons.append("RSI 15m خیلی پایین است؛ احتمال ته دامپ.")
            if 42 <= s5.rsi <= 52:
                points += 6; reasons.append("RSI 5m برای شروع دامپ مناسب است.")
            elif s5.rsi < 38:
                points -= 7; reasons.append("RSI 5m خیلی پایین است؛ احتمال ورود دیر شورت.")
            if s15.macd_hist <= s15.prev_macd_hist:
                points += 7; reasons.append("MACD 15m در فاز تقویت اولیه شورت است.")
            if s5.macd_hist <= s5.prev_macd_hist:
                points += 5
            if 14 <= s15.adx <= 28 and s15.minus_di >= s15.plus_di:
                points += 7; reasons.append("ADX/DI شروع قدرت شورت را نشان می‌دهد.")
            elif s15.adx > 34:
                points -= 5; reasons.append("ADX خیلی بالا؛ ممکن است دامپ مصرف شده باشد.")
            if s5.close <= s5.ema20:
                points += 4
        if 0.8 <= s15.volume_ratio <= 2.4:
            points += 4; reasons.append("Volume 15m شروع فشار را نشان می‌دهد، نه کلایمکس.")
        elif s15.volume_ratio > 3.0:
            points -= 6; reasons.append("Volume 15m خیلی انفجاری است؛ احتمال کلایمکس.")
        if 0.8 <= s5.volume_ratio <= 2.6:
            points += 4
        elif s5.volume_ratio > 3.2:
            points -= 6
        atr_ratio = s15.atr / max(s15.prev_atr, s15.close * 0.0001)
        if 0.92 <= atr_ratio <= 1.45:
            points += 3; reasons.append("ATR در فاز شروع نوسان است.")
        elif atr_ratio > 1.8:
            points -= 4; reasons.append("ATR بیش از حد باز شده؛ خطر ورود دیر.")
        return max(0, points), reasons

    def _raw_strength(self, s: IndicatorSnapshot) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        atr_pct = s.atr_pct
        slope50 = s.ema50_slope_pct
        slope200 = s.ema200_slope_pct
        if s.close > s.ema50:
            score += 15; reasons.append("قیمت بالای EMA50 است.")
        else:
            score -= 15; reasons.append("قیمت پایین EMA50 است.")
        score += 10 if s.ema20 > s.ema50 else -10
        score += 8 if s.close > s.ema200 else -8
        slope_gate = max(0.00004, atr_pct * 0.02)
        if slope50 > slope_gate:
            score += 13; reasons.append("شیب EMA50 مثبت است.")
        elif slope50 < -slope_gate:
            score -= 13; reasons.append("شیب EMA50 منفی است.")
        else:
            reasons.append("EMA50 تقریباً صاف است.")
        score += 4 if slope200 > 0 else -4 if slope200 < 0 else 0
        di_gap = abs(s.plus_di - s.minus_di)
        if s.plus_di > s.minus_di and di_gap >= 2.5:
            score += 12; reasons.append("+DI از -DI قوی‌تر است.")
        elif s.minus_di > s.plus_di and di_gap >= 2.5:
            score -= 12; reasons.append("-DI از +DI قوی‌تر است.")
        if s.adx >= 16:
            add = min(9, int((s.adx - 14) / 2))
            if s.plus_di > s.minus_di:
                score += add
            elif s.minus_di > s.plus_di:
                score -= add
        if 49 <= s.rsi <= 58:
            score += 5
        elif 42 <= s.rsi <= 51:
            score -= 5
        elif s.rsi > 66:
            score -= 4
        elif s.rsi < 34:
            score += 4
        if s.macd_hist > 0 and s.macd_hist >= s.prev_macd_hist:
            score += 8
        elif s.macd_hist < 0 and s.macd_hist <= s.prev_macd_hist:
            score -= 8
        return max(-100, min(100, score)), reasons
