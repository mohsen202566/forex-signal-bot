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
    def analyze(self, *, direction: Direction, snapshot_5m: IndicatorSnapshot, snapshot_15m: IndicatorSnapshot, candle: CandleHunterResult, stage: EntryStageResult) -> EntryQualityResult:
        reasons: list[str] = []
        if candle.label in {"LATE_CHASE", "EXHAUSTION", "MID_MOVE"}:
            return EntryQualityResult("LATE_ENTRY", False, -10, ("کندل نشان می‌دهد حرکت مصرف شده یا خسته است.",))
        if not stage.ok_for_real:
            return EntryQualityResult("LATE_ENTRY", False, -8, tuple(stage.reasons + ("EntryQuality: ورود برای Real دیر است.",)))
        if direction == "LONG":
            rsi_good = 49 <= snapshot_5m.rsi <= 58 and 46 <= snapshot_15m.rsi <= 60
            rsi_late = snapshot_5m.rsi > 62 or snapshot_15m.rsi > 64
            macd_start = snapshot_5m.macd_hist >= snapshot_5m.prev_macd_hist and snapshot_15m.macd_hist >= snapshot_15m.prev_macd_hist
            di_ok = snapshot_15m.plus_di >= snapshot_15m.minus_di
        else:
            rsi_good = 42 <= snapshot_5m.rsi <= 52 and 40 <= snapshot_15m.rsi <= 54
            rsi_late = snapshot_5m.rsi < 38 or snapshot_15m.rsi < 36
            macd_start = snapshot_5m.macd_hist <= snapshot_5m.prev_macd_hist and snapshot_15m.macd_hist <= snapshot_15m.prev_macd_hist
            di_ok = snapshot_15m.minus_di >= snapshot_15m.plus_di
        if rsi_late:
            return EntryQualityResult("LATE_ENTRY", False, -8, ("RSI به محدوده خستگی رسیده؛ قدرت کورکورانه محسوب نمی‌شود.",))
        score = 0
        if rsi_good:
            score += 5; reasons.append("RSI داخل بازه شروع حرکت است.")
        if macd_start:
            score += 5; reasons.append("MACD در فاز شروع تقویت است.")
        if 14 <= snapshot_15m.adx <= 28 and di_ok:
            score += 4; reasons.append("ADX/DI شروع روند را تأیید می‌کند.")
        elif snapshot_15m.adx > 34:
            score -= 4; reasons.append("ADX خیلی بالا است؛ احتمال ورود دیر.")
        if 0.85 <= snapshot_5m.volume_ratio <= 2.6 and 0.80 <= snapshot_15m.volume_ratio <= 2.4:
            score += 3; reasons.append("ولوم شروع فشار است، نه کلایمکس.")
        elif snapshot_5m.volume_ratio > 3.2 or snapshot_15m.volume_ratio > 3.0:
            score -= 5; reasons.append("ولوم کلایمکس‌مانند است.")
        atr_ratio = snapshot_15m.atr / max(snapshot_15m.prev_atr, snapshot_15m.close * 0.0001)
        if 0.90 <= atr_ratio <= 1.55:
            score += 2; reasons.append("ATR در فاز شروع نوسان است.")
        elif atr_ratio > 1.85:
            score -= 4; reasons.append("ATR خیلی باز شده؛ ریسک ورود دیر.")
        if candle.label == "IGNITION_START" and stage.stage_pct <= 18 and score >= 12:
            return EntryQualityResult("EARLY_IGNITION", True, min(8, score), tuple(reasons + ["EntryQuality: نقطه ورود شروع حرکت است."]))
        if candle.label == "IGNITION_START" and score >= 8:
            return EntryQualityResult("GOOD_ENTRY", True, min(6, score), tuple(reasons + ["EntryQuality: ورود خوب و قابل اجرا است."]))
        if candle.label == "PRE_IGNITION_WATCH" and score >= 7:
            return EntryQualityResult("WEAK_ENTRY", False, min(4, score), tuple(reasons + ["EntryQuality: برای watch/ghost مناسب‌تر است."]))
        return EntryQualityResult("NO_ENTRY", False, max(-5, score - 8), tuple(reasons + ["EntryQuality: نقطه ورود هنوز کامل نیست."]))
