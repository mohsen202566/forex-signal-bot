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
    """Fast 5m/15m direction engine.

    The engine scores fresh continuation and reversal pressure directly. It uses:
    1) fresh continuation pressure, and
    2) reversal pressure after a consumed pump/dump.

    RSI is treated as a dynamic pressure meter around its neutral zone, not a fixed
    overbought/oversold trigger. Slope, MACD histogram change, DI, price position,
    candle structure, volume and ATR must agree before a direction gets selected.
    """

    def analyze_15m_scalp(self, snapshot_15m: IndicatorSnapshot, snapshot_5m: IndicatorSnapshot) -> DirectionResult:
        long_raw, long_reasons = self._scalp_side_strength(snapshot_15m, snapshot_5m, "LONG")
        short_raw, short_reasons = self._scalp_side_strength(snapshot_15m, snapshot_5m, "SHORT")
        edge = abs(long_raw - short_raw)

        # Strong direction: clean enough for the normal scoring path.
        min_raw = 11
        min_edge = 2
        if long_raw >= min_raw and long_raw >= short_raw + min_edge:
            confidence = min(100, int(long_raw * 3.0 + edge * 2.0))
            score = min(WEIGHTS.direction, 4 + confidence // 14)
            return DirectionResult("LONG", score, confidence, int(long_raw), tuple(long_reasons + ["15m/5m فشار غالب را برای لانگ نشان می‌دهد."]))
        if short_raw >= min_raw and short_raw >= long_raw + min_edge:
            confidence = min(100, int(short_raw * 3.0 + edge * 2.0))
            score = min(WEIGHTS.direction, 4 + confidence // 14)
            return DirectionResult("SHORT", score, confidence, int(-short_raw), tuple(short_reasons + ["15m/5m فشار غالب را برای شورت نشان می‌دهد."]))

        # Soft direction: Direction must not be a hard blocker. If one side has
        # usable pressure but is not fully clean yet, let the rest of AI score it
        # with lower direction confidence instead of stopping the whole analysis.
        best_direction: Direction = "LONG" if long_raw >= short_raw else "SHORT"
        best_raw = max(long_raw, short_raw)
        other_raw = min(long_raw, short_raw)
        soft_edge = best_raw - other_raw
        if best_raw >= 8 and (soft_edge >= 1 or best_raw >= 10):
            confidence = min(74, max(28, int(best_raw * 3.0 + soft_edge * 2.0)))
            score = min(WEIGHTS.direction, max(3, 3 + confidence // 18))
            if best_direction == "LONG":
                reasons = list(long_reasons)
                raw_strength = int(best_raw)
                side_text = "لانگ"
            else:
                reasons = list(short_reasons)
                raw_strength = int(-best_raw)
                side_text = "شورت"
            reasons.append(f"Direction نرم است: فشار {side_text} دیده شده ولی کامل نیست؛ AI ادامه تحلیل را با اعتماد کمتر انجام می‌دهد.")
            reasons.append(f"raw_long={long_raw:.1f} raw_short={short_raw:.1f} edge={soft_edge:.1f}")
            return DirectionResult(best_direction, score, confidence, raw_strength, tuple(reasons))

        raw = int(long_raw - short_raw)
        confidence = min(100, abs(raw) * 5)
        return DirectionResult("NEUTRAL", min(WEIGHTS.direction, max(1, confidence // 10)), confidence, raw, (f"فشار دوطرفه نزدیک/ضعیف است؛ فقط Watch/Ghost مناسب است. raw_long={long_raw:.1f} raw_short={short_raw:.1f}",))

    def analyze_1h_context(self, snapshot: IndicatorSnapshot, direction: Direction) -> DirectionResult:
        raw, reasons = self._raw_strength(snapshot)
        if raw >= 42:
            state: DirectionState = "LONG"
        elif raw <= -42:
            state = "SHORT"
        else:
            state = "NEUTRAL"
        confidence = min(100, int(abs(raw)))
        if state == direction:
            score = 4
            reasons.append("1H فقط context است و با جهت سیگنال موافق است.")
        elif state == "NEUTRAL":
            score = 3
            reasons.append("1H خنثی است؛ برای اسکالپ قفل ورود نیست.")
        else:
            score = 1
            reasons.append("1H خلاف جهت است؛ فقط هشدار و کاهش امتیاز، نه رد کامل.")
        return DirectionResult(state, score, confidence, raw, tuple(reasons))

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

        # Continuation / fresh pressure.
        points += self._rsi_pressure(s5, s15, direction, reasons)
        points += self._slope_pressure(s5, s15, direction, reasons)
        points += self._macd_pressure(s5, s15, direction, reasons)
        points += self._di_pressure(s15, direction, reasons)
        points += self._price_pressure(s5, direction, reasons)
        points += self._volume_atr_pressure(s5, s15, reasons)

        # Reversal after a consumed pump/dump. This is what catches: dump -> long bounce,
        # pump -> short rejection, without a separate timing gate.
        reversal = self._reversal_pressure(s5, s15, direction, reasons)
        points += reversal

        # Clamp only at the end so negative warnings can reduce weak signals.
        return max(0, points), reasons

    def _rsi_pressure(self, s5: IndicatorSnapshot, s15: IndicatorSnapshot, direction: Direction, reasons: list[str]) -> int:
        pts = 0
        # Dynamic neutral width: more volatile symbols get a slightly wider neutral band.
        neutral_band = min(3.5, max(1.0, s15.atr_pct * 120.0))
        if direction == "LONG":
            if s5.rsi > 50.0 + neutral_band:
                pts += 4; reasons.append("RSI 5m از محدوده خنثی به سمت لانگ فشار گرفته است.")
            elif s5.rsi >= 49.0 and s5.rsi_delta > 0.25:
                pts += 3; reasons.append("RSI 5m از نزدیکی خنثی رو به بالا برگشته است.")
            if s15.rsi > 50.0 + neutral_band * 0.7 or s15.rsi_delta > 0.20:
                pts += 4; reasons.append("RSI 15m تمایل لانگ/بهبود مومنتوم را نشان می‌دهد.")
            if s5.rsi > 70 and s5.rsi_delta < 0:
                pts -= 3; reasons.append("RSI 5m کشیده و در حال سرد شدن است؛ فقط با تأییدهای دیگر معتبر است.")
        else:
            if s5.rsi < 50.0 - neutral_band:
                pts += 4; reasons.append("RSI 5m از محدوده خنثی به سمت شورت فشار گرفته است.")
            elif s5.rsi <= 51.0 and s5.rsi_delta < -0.25:
                pts += 3; reasons.append("RSI 5m از نزدیکی خنثی رو به پایین برگشته است.")
            if s15.rsi < 50.0 - neutral_band * 0.7 or s15.rsi_delta < -0.20:
                pts += 4; reasons.append("RSI 15m تمایل شورت/ضعف مومنتوم را نشان می‌دهد.")
            if s5.rsi < 30 and s5.rsi_delta > 0:
                pts -= 3; reasons.append("RSI 5m پایین و در حال برگشت است؛ فقط با تأییدهای دیگر معتبر است.")
        return pts

    def _slope_pressure(self, s5: IndicatorSnapshot, s15: IndicatorSnapshot, direction: Direction, reasons: list[str]) -> int:
        pts = 0
        slope_gate5 = max(0.000015, s5.atr_pct * 0.010)
        slope_gate15 = max(0.000020, s15.atr_pct * 0.012)
        s5_ok = s5.ema20_slope_pct > slope_gate5 if direction == "LONG" else s5.ema20_slope_pct < -slope_gate5
        s15_ok = s15.ema20_slope_pct > slope_gate15 if direction == "LONG" else s15.ema20_slope_pct < -slope_gate15
        if s5_ok:
            pts += 4; reasons.append("شیب EMA20 در 5m به نفع جهت شکار است.")
        if s15_ok:
            pts += 4; reasons.append("شیب EMA20 در 15m با جهت شکار هماهنگ است.")
        return pts

    def _macd_pressure(self, s5: IndicatorSnapshot, s15: IndicatorSnapshot, direction: Direction, reasons: list[str]) -> int:
        pts = 0
        if direction == "LONG":
            if s5.macd_hist_slope > 0:
                pts += 5; reasons.append("MACD Histogram 5m در حال تقویت لانگ است.")
            if s15.macd_hist_slope > 0:
                pts += 5; reasons.append("MACD Histogram 15m به نفع لانگ بهتر شده است.")
            if s5.macd_hist > 0 and s5.macd_hist_slope >= 0:
                pts += 2
        else:
            if s5.macd_hist_slope < 0:
                pts += 5; reasons.append("MACD Histogram 5m در حال تقویت شورت است.")
            if s15.macd_hist_slope < 0:
                pts += 5; reasons.append("MACD Histogram 15m به نفع شورت بدتر شده است.")
            if s5.macd_hist < 0 and s5.macd_hist_slope <= 0:
                pts += 2
        return pts

    def _di_pressure(self, s15: IndicatorSnapshot, direction: Direction, reasons: list[str]) -> int:
        pts = 0
        di_gap = abs(s15.plus_di - s15.minus_di)
        if direction == "LONG" and s15.plus_di >= s15.minus_di:
            pts += 4; reasons.append("+DI در 15m دست بالا را دارد.")
            if di_gap >= 4:
                pts += 2
        elif direction == "SHORT" and s15.minus_di >= s15.plus_di:
            pts += 4; reasons.append("-DI در 15m دست بالا را دارد.")
            if di_gap >= 4:
                pts += 2
        if 10 <= s15.adx <= 34:
            pts += 3; reasons.append("ADX در محدوده قابل استفاده برای شروع/ادامه اسکالپ است.")
        elif s15.adx > 42:
            pts -= 2; reasons.append("ADX خیلی باز شده؛ نیاز به تأیید کندل و برگشت دارد.")
        return pts

    def _price_pressure(self, s5: IndicatorSnapshot, direction: Direction, reasons: list[str]) -> int:
        pts = 0
        if direction == "LONG":
            if s5.close >= s5.ema20:
                pts += 3; reasons.append("قیمت 5m بالای EMA20 یا در حال reclaim است.")
            if s5.close >= s5.vwap:
                pts += 2
        else:
            if s5.close <= s5.ema20:
                pts += 3; reasons.append("قیمت 5m زیر EMA20 یا در حال شکست آن است.")
            if s5.close <= s5.vwap:
                pts += 2
        return pts

    def _volume_atr_pressure(self, s5: IndicatorSnapshot, s15: IndicatorSnapshot, reasons: list[str]) -> int:
        pts = 0
        if 0.65 <= s5.volume_ratio <= 3.20:
            pts += 3
        elif s5.volume_ratio > 4.0:
            pts -= 3; reasons.append("Volume 5m خیلی انفجاری است؛ احتمال کلایمکس بررسی شد.")
        if 0.65 <= s15.volume_ratio <= 2.90:
            pts += 3; reasons.append("Volume 15m برای شروع فشار قابل قبول است.")
        elif s15.volume_ratio > 3.8:
            pts -= 3; reasons.append("Volume 15m حالت کلایمکس دارد.")
        atr_ratio = s15.atr / max(s15.prev_atr, s15.close * 0.0001)
        if 0.75 <= atr_ratio <= 1.85:
            pts += 2
        elif atr_ratio > 2.25:
            pts -= 2; reasons.append("ATR خیلی باز شده؛ کیفیت کندل باید تأیید کند.")
        return pts

    def _reversal_pressure(self, s5: IndicatorSnapshot, s15: IndicatorSnapshot, direction: Direction, reasons: list[str]) -> int:
        pts = 0
        if direction == "LONG":
            dump_consumed = s5.rsi <= 44 or s15.rsi <= 43 or s5.consecutive_down >= 2
            sellers_fading = s5.rsi_delta > 0.35 and s5.macd_hist_slope > 0
            reclaim = s5.close > s5.open or s5.close >= min(s5.ema20, s5.vwap)
            support_reaction = s5.lower_wick_pct >= 0.28 or s5.close > s5.prev_close
            if dump_consumed and sellers_fading and reclaim and support_reaction:
                pts += 13; reasons.append("دامپ مصرف‌شده و نشانه برگشت لانگ/حمایت دیده می‌شود.")
        else:
            pump_consumed = s5.rsi >= 56 or s15.rsi >= 57 or s5.consecutive_up >= 2
            buyers_fading = s5.rsi_delta < -0.35 and s5.macd_hist_slope < 0
            reject = s5.close < s5.open or s5.close <= max(s5.ema20, s5.vwap)
            resistance_reaction = s5.upper_wick_pct >= 0.28 or s5.close < s5.prev_close
            if pump_consumed and buyers_fading and reject and resistance_reaction:
                pts += 13; reasons.append("پامپ مصرف‌شده و نشانه برگشت شورت/مقاومت دیده می‌شود.")
        return pts

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
        if s.rsi > 52 and s.rsi_delta >= 0:
            score += 5
        elif s.rsi < 48 and s.rsi_delta <= 0:
            score -= 5
        if s.macd_hist_slope > 0:
            score += 6
        elif s.macd_hist_slope < 0:
            score -= 6
        return max(-100, min(100, score)), reasons
