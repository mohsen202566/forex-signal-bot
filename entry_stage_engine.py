from __future__ import annotations

from dataclasses import dataclass

from indicators import IndicatorSnapshot
from scorer import Direction


@dataclass(frozen=True)
class EntryStageResult:
    stage_pct: float
    ok_for_real: bool
    score_bonus: int
    reasons: tuple[str, ...]


class EntryStageEngine:
    def analyze(self, snapshot: IndicatorSnapshot, direction: Direction) -> EntryStageResult:
        atr = max(snapshot.atr, snapshot.close * 0.0001)
        if direction == "LONG":
            base = min(snapshot.ema20, snapshot.vwap, snapshot.recent_low)
            move_from_base = max(0.0, snapshot.close - base)
            reclaim_bonus = snapshot.rsi_delta > 0 and snapshot.macd_hist_slope > 0
        else:
            base = max(snapshot.ema20, snapshot.vwap, snapshot.recent_high)
            move_from_base = max(0.0, base - snapshot.close)
            reclaim_bonus = snapshot.rsi_delta < 0 and snapshot.macd_hist_slope < 0
        stage_pct = min(100.0, (move_from_base / max(atr * 3.2, snapshot.close * 0.0008)) * 100.0)
        reasons: list[str] = [f"Entry Stage={stage_pct:.1f}%"]

        # This layer no longer blocks Real. It only grades location quality.
        if stage_pct <= 18:
            return EntryStageResult(stage_pct, True, 5, tuple(reasons + ["ورود نزدیک مبنای حرکت است."]))
        if stage_pct <= 35:
            return EntryStageResult(stage_pct, True, 3, tuple(reasons + ["موقعیت ورود قابل اجراست و نیاز به مدیریت سریع دارد."]))
        if stage_pct <= 58:
            bonus = 1 if reclaim_bonus else -1
            return EntryStageResult(stage_pct, True, bonus, tuple(reasons + ["حرکت جلو رفته اما با تأیید قدرت/برگشت هنوز قابل بررسی است."]))
        return EntryStageResult(stage_pct, True, -3, tuple(reasons + ["فاصله از مبنای حرکت زیاد است؛ فقط با امتیاز کندل و قدرت قوی اجرا شود."]))
