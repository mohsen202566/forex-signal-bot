from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["LONG", "SHORT"]
DirectionState = Literal["LONG", "SHORT", "NEUTRAL", "DANGEROUS"]
DecisionAction = Literal["REJECT", "WATCH", "SIGNAL"]
EntryState = Literal["IGNITION_READY", "PRE_WATCH", "LATE", "CHASE", "NO_ENTRY", "EARLY_IGNITION", "GOOD_ENTRY", "WEAK_ENTRY", "LATE_ENTRY", "FAKE_MOVE_RISK"]
PatternLabel = Literal["IGNITION_START", "PRE_IGNITION_WATCH", "MID_MOVE", "LATE_CHASE", "PULLBACK", "EXHAUSTION", "NOISE"]
SessionState = Literal["GOOD", "NORMAL", "BAD_REAL_ONLY_NORMAL"]
OrderBlockState = Literal["WITH_SIGNAL", "AGAINST_SIGNAL", "NEUTRAL"]


@dataclass(frozen=True)
class ScoreBreakdown:
    score_direction: int = 0
    score_pre_ignition: int = 0
    score_candle_entry: int = 0
    score_ai_memory: int = 0
    score_risk_net: int = 0
    score_session: int = 0
    score_order_block: int = 0

    @property
    def total(self) -> int:
        return int(
            self.score_direction
            + self.score_pre_ignition
            + self.score_candle_entry
            + self.score_ai_memory
            + self.score_risk_net
            + self.score_session
            + self.score_order_block
        )


@dataclass(frozen=True)
class SignalDecision:
    action: DecisionAction
    accepted: bool
    direction: Direction | None
    entry: float
    tp: float
    sl: float
    score: int
    threshold: int
    breakdown: ScoreBreakdown
    reason: str
    hard_reject: bool = False
    reject_code: str | None = None
    ready_alert: bool = False
    hunter: bool = False
    signal_label: str = "عادی"
    direction_state_1h: DirectionState = "NEUTRAL"
    direction_confidence_1h: int = 0
    bias_4h: DirectionState = "NEUTRAL"
    setup_15m: DirectionState = "NEUTRAL"
    entry_5m: EntryState = "NO_ENTRY"
    candle_pattern: PatternLabel = "NOISE"
    entry_stage_pct: float = 100.0
    entry_quality: str = "NO_ENTRY"
    technical_zone: str = "NEUTRAL"
    indicator_profile: str = ""
    ai_confidence: int = 0
    ai_experience: int = 0
    ai_adjustment: int = 0
    ai_effect: str = "neutral"
    net_edge: float = 0.0
    estimated_profit_usdt: float = 0.0
    estimated_profit_pct: float = 0.0
    risk_reward: float = 0.0
    estimated_cost_pct: float = 0.0
    market_bias: DirectionState = "NEUTRAL"
    session_state: SessionState = "NORMAL"
    order_block_state: OrderBlockState = "NEUTRAL"
    rsi_5m: float = 0.0
    rsi_15m: float = 0.0
    macd_hist_5m: float = 0.0
    macd_hist_15m: float = 0.0
    adx_15m: float = 0.0
    atr_pct_15m: float = 0.0
    volume_ratio_5m: float = 0.0
    volume_ratio_15m: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def real_priority(self) -> float:
        # Size is not changed by score; this is only for picking which signal gets a real slot first.
        q_bonus = 20 if self.entry_quality == "EARLY_IGNITION" else 12 if self.entry_quality == "GOOD_ENTRY" else 0
        return self.score + q_bonus + self.ai_confidence * 0.20 + max(0.0, self.net_edge * 1000.0)


@dataclass(frozen=True)
class EngineResult:
    state: str
    score: int
    confidence: int
    reasons: tuple[str, ...]
