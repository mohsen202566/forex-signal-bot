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
        else:
            base = max(snapshot.ema20, snapshot.vwap, snapshot.recent_high)
            move_from_base = max(0.0, base - snapshot.close)
        stage_pct = min(100.0, (move_from_base / max(atr * 3.2, snapshot.close * 0.0008)) * 100.0)
        reasons: list[str] = [f"Entry Stage={stage_pct:.1f}%"]
        if stage_pct <= 18:
            return EntryStageResult(stage_pct, True, 5, tuple(reasons + ["ورود نزدیک شروع حرکت است."]))
        if stage_pct <= 30:
            return EntryStageResult(stage_pct, True, 2, tuple(reasons + ["ورود قابل قبول است ولی باید سریع مدیریت شود."]))
        if stage_pct <= 45:
            return EntryStageResult(stage_pct, False, -6, tuple(reasons + ["حرکت جلو رفته؛ برای Real مناسب نیست."]))
        return EntryStageResult(stage_pct, False, -10, tuple(reasons + ["ورود وسط/آخر حرکت است."]))
