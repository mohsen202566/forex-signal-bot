from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import config
from market_engine import MarketAnalysis


@dataclass
class SetupCandidate:
    setup_id: str
    symbol_id: str
    side: str
    setup_type: str
    state: str
    score: float
    anchor_price: float
    invalidation_price: float
    trigger_price: float
    expires_at: int
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class SetupEngine:
    def detect(self, m: MarketAnalysis, c5: list[dict[str, Any]]) -> SetupCandidate | None:
        if m.hard_veto or m.primary_direction == "NEUTRAL" or len(c5) < 25:
            return None

        px = float(c5[-1]["close"])
        atr = float(m.features.get("atr") or 0)
        e21 = float(m.features.get("ema21") or 0)
        if px <= 0 or atr <= 0 or e21 <= 0:
            return None

        side = m.primary_direction
        recent = c5[-20:]
        prior = recent[:-1]
        hi = max(float(x["high"]) for x in prior)
        lo = min(float(x["low"]) for x in prior)
        local_hi = max(float(x["high"]) for x in c5[-5:-1])
        local_lo = min(float(x["low"]) for x in c5[-5:-1])
        vr = float(m.features.get("volume_ratio") or 1.0)
        eff = float(m.features.get("efficiency") or 0.0)
        near_value = abs(px - e21) <= 0.8 * atr
        breakout = (side == "LONG" and px > hi) or (side == "SHORT" and px < lo)

        # Breakout has priority. Otherwise a fresh breakout near EMA could be mislabeled as a pullback.
        if breakout and vr >= 1.05:
            setup_type = "COMPRESSION_BREAKOUT"
            base = (
                0.20 * m.direction_score
                + 0.20 * m.strength_score
                + 0.25 * m.freshness_score
                + 20 * min(1.0, vr / 1.5)
                + 15 * min(1.0, eff / 0.6)
            )
            trigger = hi if side == "LONG" else lo
            invalidation = local_lo if side == "LONG" else local_hi
            obstacle = None
        elif near_value and m.strength_score >= 55:
            setup_type = "PULLBACK_CONTINUATION"
            base = (
                0.30 * m.direction_score
                + 0.20 * m.strength_score
                + 0.20 * m.freshness_score
                + 20 * (1 - min(1.0, m.value_distance_atr))
                + 10 * min(1.0, vr / 1.5)
            )
            trigger = local_hi if side == "LONG" else local_lo
            invalidation = (
                (m.features.get("recent_swing_low") or lo)
                if side == "LONG"
                else (m.features.get("recent_swing_high") or hi)
            )
            obstacle = hi if side == "LONG" else lo
        else:
            return None

        score = max(0.0, min(100.0, float(base)))
        if score < config.SETUP_WATCH_MIN:
            return None
        if (side == "LONG" and float(invalidation) >= px) or (side == "SHORT" and float(invalidation) <= px):
            return None
        if (side == "LONG" and float(trigger) <= float(invalidation)) or (side == "SHORT" and float(trigger) >= float(invalidation)):
            return None

        now = int(time.time())
        return SetupCandidate(
            setup_id=f"{m.symbol_id}-{side}-{setup_type}-{now}",
            symbol_id=m.symbol_id,
            side=side,
            setup_type=setup_type,
            state="READY" if score >= config.SETUP_MIN else "WATCH",
            score=round(score, 2),
            anchor_price=px,
            invalidation_price=float(invalidation),
            trigger_price=float(trigger),
            expires_at=now + int(config.WATCH_TTL_SECONDS),
            reasons=[f"{setup_type} با امتیاز {score:.1f}"],
            risks=list(m.contradictions),
            meta={
                "atr": atr,
                "regime": m.regime,
                "obstacle_price": obstacle,
            },
        )
