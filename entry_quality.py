from __future__ import annotations

from dataclasses import dataclass

from candle_hunter_engine import CandleHunterResult
from entry_stage_engine import EntryStageResult
from indicators import IndicatorSnapshot
from scorer import Direction


@dataclass(frozen=True)
class EntryQualityResult:
    quality: str
    ok_for_real: bool
    score_bonus: int
    reasons: tuple[str, ...]


class EntryQualityEngine:
    """Grades whether the current 5m/15m state is usable for Real.

    There is deliberately no separate timing output. A move is either building power,
    reversing after exhaustion, ready, watch-only, or fake-risk.
    """

    def analyze(self, *, direction: Direction, snapshot_5m: IndicatorSnapshot, snapshot_15m: IndicatorSnapshot, candle: CandleHunterResult, stage: EntryStageResult) -> EntryQualityResult:
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
            exhaustion_against_direction = s5.rsi > 73 and s5.rsi_delta < -0.35 and s5.upper_wick_pct > 0.35
        else:
            rsi_power = (s5.rsi < 50 and s5.rsi_delta <= 0.10) or (s5.rsi <= 53 and s5.rsi_delta < -0.35)
            rsi_15_ok = s15.rsi_delta < 0 or 38 <= s15.rsi <= 53
            macd_start = s5.macd_hist_slope < 0 and s15.macd_hist_slope <= 0
            di_ok = s15.minus_di >= s15.plus_di or s5.rsi_delta < -0.65
            price_ok = s5.close <= max(s5.ema20, s5.vwap)
            exhaustion_against_direction = s5.rsi < 27 and s5.rsi_delta > 0.35 and s5.lower_wick_pct > 0.35

        if exhaustion_against_direction and candle.label not in {"REVERSAL_BUILDING"}:
            return EntryQualityResult("FAKE_MOVE_RISK", False, -7, ("حرکت کلایمکس و خلاف مومنتوم تازه دیده شد؛ Real ممنوع.",))

        if rsi_power:
            score += 5; reasons.append("RSI از محدوده تعادل به سمت جهت معامله فشار گرفته است.")
        if rsi_15_ok:
            score += 3; reasons.append("RSI 15m با شروع/ادامه جهت هماهنگ است.")
        if macd_start:
            score += 5; reasons.append("MACD در فاز تقویت جهت است.")
        if di_ok:
            score += 4; reasons.append("DI یا شتاب کوتاه‌مدت جهت را تأیید می‌کند.")
        if price_ok:
            score += 3; reasons.append("قیمت نسبت به EMA20/VWAP موقعیت قابل اجرا دارد.")
        if 0.65 <= s5.volume_ratio <= 3.4 and 0.60 <= s15.volume_ratio <= 3.0:
            score += 3; reasons.append("ولوم برای شکار سریع قابل قبول است.")
        elif s5.volume_ratio > 4.2 or s15.volume_ratio > 4.0:
            score -= 3; reasons.append("ولوم بسیار انفجاری است؛ ریسک کلایمکس لحاظ شد.")
        atr_ratio = s15.atr / max(s15.prev_atr, s15.close * 0.0001)
        if 0.70 <= atr_ratio <= 2.05:
            score += 2
        elif atr_ratio > 2.35:
            score -= 2; reasons.append("ATR خیلی باز شده؛ برای Real نیاز به تایید قوی‌تر است.")

        if candle.label == "REVERSAL_BUILDING" and score >= 10:
            return EntryQualityResult("REVERSAL_BUILDING", True, min(8, score), tuple(reasons + ["EntryQuality: برگشت بعد از پامپ/دامپ مصرف‌شده قابل شکار است."]))
        if candle.label == "IGNITION_START" and score >= 13 and stage.stage_pct <= 35:
            return EntryQualityResult("EARLY_IGNITION", True, min(8, score), tuple(reasons + ["EntryQuality: نقطه ورود شروع قدرت است."]))
        if candle.label == "IGNITION_START" and score >= 10:
            return EntryQualityResult("GOOD_ENTRY", True, min(7, score), tuple(reasons + ["EntryQuality: ورود خوب و قابل اجرا است."]))
        if candle.label == "POWER_BUILDING" and score >= 10:
            return EntryQualityResult("POWER_BUILDING", True, min(6, score), tuple(reasons + ["EntryQuality: قدرت جهت در حال ساخته شدن است."]))
        if candle.label in {"PRE_IGNITION_WATCH", "EXHAUSTION"} and score >= 7:
            return EntryQualityResult("WEAK_ENTRY", False, min(4, score), tuple(reasons + ["EntryQuality: برای Watch/Ghost مناسب‌تر است."]))
        return EntryQualityResult("NO_ENTRY", False, max(-3, min(2, score - 8)), tuple(reasons + ["EntryQuality: هنوز تریگر کافی برای Real ندارد."]))
