from __future__ import annotations

from dataclasses import dataclass

from candle_hunter_engine import CandleHunterResult
from entry_stage_engine import EntryStageResult
from scorer import EntryState


@dataclass(frozen=True)
class IgnitionEntryResult:
    state: EntryState
    score: int
    reasons: tuple[str, ...]


class IgnitionEntryEngine:
    def analyze(self, candle: CandleHunterResult, stage: EntryStageResult) -> IgnitionEntryResult:
        reasons = list(candle.reasons) + list(stage.reasons)
        base_score = max(0, candle.score + stage.score_bonus)
        if candle.label == "REVERSAL_BUILDING":
            return IgnitionEntryResult("REVERSAL_BUILDING", min(25, base_score + 3), tuple(reasons))
        if candle.label == "IGNITION_START" and stage.stage_pct <= 25:
            return IgnitionEntryResult("EARLY_IGNITION", min(25, base_score), tuple(reasons))
        if candle.label == "IGNITION_START":
            return IgnitionEntryResult("GOOD_ENTRY", min(24, base_score), tuple(reasons))
        if candle.label == "POWER_BUILDING":
            return IgnitionEntryResult("POWER_BUILDING", min(22, base_score), tuple(reasons))
        if candle.label == "EXHAUSTION":
            return IgnitionEntryResult("EXHAUSTION", min(14, base_score), tuple(reasons))
        if candle.label == "PRE_IGNITION_WATCH":
            return IgnitionEntryResult("PRE_WATCH", min(17, base_score), tuple(reasons))
        return IgnitionEntryResult("NO_ENTRY", max(0, candle.score), tuple(reasons))
