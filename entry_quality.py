from __future__ import annotations

from dataclasses import dataclass

from candle_hunter_engine import CandleHunterResult
from entry_precision_engine import EntryPrecisionResult
from indicators import IndicatorSnapshot
from scorer import Direction


@dataclass(frozen=True)
class EntryQualityResult:
    quality: str
    ok_for_signal: bool
    score_bonus: int
    confidence: int
    reasons: tuple[str, ...]


class EntryQualityEngine:
    def analyze(self, *, direction: Direction, snapshot_5m: IndicatorSnapshot, snapshot_15m: IndicatorSnapshot, candle: CandleHunterResult, precision: EntryPrecisionResult) -> EntryQualityResult:
        reasons: list[str] = []
        s5 = snapshot_5m
        s15 = snapshot_15m
        score = 0
        if direction == "LONG":
            rsi_power = (s5.rsi > 50 and s5.rsi_delta >= -0.10) or (s5.rsi >= 47 and s5.rsi_delta > 0.35)
            rsi_15_ok = s15.rsi_delta > 0 or 47 <= s15.rsi <= 62
            macd_start = s5.macd_hist_slope > 0 and s15.macd_hist_slope >= 0
            di_ok = s15.plus_di >= s15.minus_di or s5.rsi_delta > 0.65
            price_ok = s5.close >= min(s5.ema20, s5.vwap)
            exhaustion_risk = s5.rsi > 73 and s5.rsi_delta < -0.35 and s5.upper_wick_pct > 0.35
        else:
            rsi_power = (s5.rsi < 50 and s5.rsi_delta <= 0.10) or (s5.rsi <= 53 and s5.rsi_delta < -0.35)
            rsi_15_ok = s15.rsi_delta < 0 or 38 <= s15.rsi <= 53
            macd_start = s5.macd_hist_slope < 0 and s15.macd_hist_slope <= 0
            di_ok = s15.minus_di >= s15.plus_di or s5.rsi_delta < -0.65
            price_ok = s5.close <= max(s5.ema20, s5.vwap)
            exhaustion_risk = s5.rsi < 27 and s5.rsi_delta > 0.35 and s5.lower_wick_pct > 0.35
        if rsi_power:
            score += 4; reasons.append("RSI از محدوده تعادل به سمت جهت معامله فشار گرفته است.")
        if rsi_15_ok:
            score += 3; reasons.append("RSI 15m با شروع/ادامه جهت هماهنگ است.")
        if macd_start:
            score += 4; reasons.append("MACD در فاز تقویت جهت است.")
        if di_ok:
            score += 3; reasons.append("DI یا شتاب کوتاه‌مدت جهت را تأیید می‌کند.")
        if price_ok:
            score += 2; reasons.append("قیمت نسبت به EMA20/VWAP موقعیت قابل اجرا دارد.")
        if 0.65 <= s5.volume_ratio <= 3.4 and 0.60 <= s15.volume_ratio <= 3.0:
            score += 2; reasons.append("ولوم برای شکار سریع قابل قبول است.")
        elif s5.volume_ratio > 4.2 or s15.volume_ratio > 4.0:
            score -= 2; reasons.append("ولوم بسیار انفجاری است؛ ریسک کلایمکس در TP/SL لحاظ شد.")
        atr_ratio = s15.atr / max(s15.prev_atr, s15.close * 0.0001)
        if 0.70 <= atr_ratio <= 2.05:
            score += 1
        elif atr_ratio > 2.35:
            score -= 2; reasons.append("ATR خیلی باز شده؛ AI باید با احتیاط بیشتری TP/SL بچیند.")
        if precision.state == "READY":
            score += min(5, max(1, precision.score // 2))
        elif precision.state == "WAIT":
            return EntryQualityResult("PRECISION_WAIT", False, -3, precision.confidence, tuple(reasons + list(precision.reasons)))
        if exhaustion_risk and candle.label != "REVERSAL_BUILDING":
            return EntryQualityResult("EXHAUSTION_RISK", False, -2, 45, tuple(reasons + ["ریسک مصرف‌شدن حرکت دیده شد؛ AI باید فقط Watch/Normal یادگیری کند."]))
        if candle.label == "REVERSAL_BUILDING" and score >= 9:
            return EntryQualityResult("REVERSAL_BUILDING", True, min(8, score), 84, tuple(reasons + ["برگشت بعد از حرکت مصرف‌شده قابل شکار است."]))
        if candle.label == "IGNITION_START" and score >= 12 and precision.precision_pct >= 78:
            return EntryQualityResult("EARLY_IGNITION", True, min(8, score), 90, tuple(reasons + ["AI ورود دقیق شروع قدرت را تایید کرد."]))
        if candle.label == "IGNITION_START" and score >= 10:
            return EntryQualityResult("GOOD_ENTRY", True, min(7, score), 80, tuple(reasons + ["AI ورود را قابل اجرا می‌داند."]))
        if candle.label == "POWER_BUILDING" and score >= 8:
            return EntryQualityResult("POWER_BUILDING", True, min(6, score), 74, tuple(reasons + ["قدرت در حال ساخت است و AI آماده شکار است."]))
        if score >= 7:
            return EntryQualityResult("WEAK_MOVEMENT", False, max(0, min(4, score)), 50, tuple(reasons + ["حرکت قابل مشاهده است اما هنوز سیگنال تمیز نیست."]))
        return EntryQualityResult("NO_ENTRY", False, 0, 30, tuple(reasons + ["AI ورود دقیق را تایید نکرد." ]))
