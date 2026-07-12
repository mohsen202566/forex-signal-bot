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
        candidate, _, _ = self.detect_with_reason(m, c5)
        return candidate

    def detect_with_reason(
        self, m: MarketAnalysis, c5: list[dict[str, Any]]
    ) -> tuple[SetupCandidate | None, str, dict[str, Any]]:
        details: dict[str, Any] = {
            "direction": m.primary_direction,
            "regime": m.regime,
            "direction_score": round(float(m.direction_score), 2),
            "strength_score": round(float(m.strength_score), 2),
            "freshness_score": round(float(m.freshness_score), 2),
        }
        if m.hard_veto:
            return None, "رد بازار: Hard Veto فعال است", details
        if m.primary_direction == "NEUTRAL":
            return None, "رد بازار: جهت معتبر LONG یا SHORT وجود ندارد", details
        if len(c5) < 25:
            details["candles_5m"] = len(c5)
            return None, "رد داده: تعداد کندل 5M کافی نیست", details

        px = float(c5[-1]["close"])
        atr = float(m.features.get("atr") or 0)
        e21 = float(m.features.get("ema21") or 0)
        details.update({"price": px, "atr": atr, "ema21": e21})
        if px <= 0 or atr <= 0 or e21 <= 0:
            return None, "رد داده: قیمت، ATR یا EMA21 نامعتبر است", details

        side = m.primary_direction
        recent = c5[-20:]
        prior = recent[:-1]
        hi = max(float(x["high"]) for x in prior)
        lo = min(float(x["low"]) for x in prior)
        local_hi = max(float(x["high"]) for x in c5[-5:-1])
        local_lo = min(float(x["low"]) for x in c5[-5:-1])
        vr = float(m.features.get("volume_ratio") or 1.0)
        eff = float(m.features.get("efficiency") or 0.0)
        value_distance_atr = abs(px - e21) / atr
        max_value_distance = 1.15 if (m.strength_score >= 65 and m.freshness_score >= 50) else 0.90
        near_value = value_distance_atr <= max_value_distance
        breakout = (side == "LONG" and px > hi) or (side == "SHORT" and px < lo)
        details.update({
            "volume_ratio": round(vr, 4),
            "efficiency": round(eff, 4),
            "value_distance_atr": round(value_distance_atr, 4),
            "near_value": near_value,
            "max_value_distance_atr": round(max_value_distance, 4),
            "breakout": breakout,
            "range_high": hi,
            "range_low": lo,
        })

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
        elif near_value and m.strength_score >= 52:
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
            if breakout and vr < 1.05:
                return None, f"رد ستاپ شکست: حجم نسبی ضعیف است ({vr:.2f} < 1.05)", details
            if not near_value and m.strength_score < 52:
                return None, f"رد ستاپ: قیمت از EMA21 دور است ({value_distance_atr:.2f} ATR) و قدرت پایین است ({m.strength_score:.1f})", details
            if not near_value:
                return None, f"رد پولبک: فاصله از ناحیه ارزش زیاد است ({value_distance_atr:.2f} ATR)", details
            return None, f"رد پولبک: قدرت روند کافی نیست ({m.strength_score:.1f} < 52)", details

        score = max(0.0, min(100.0, float(base)))
        details.update({
            "setup_type": setup_type,
            "setup_score": round(score, 2),
            "trigger_price": float(trigger),
            "invalidation_price": float(invalidation),
        })
        minimum_watch_score = config.BREAKOUT_SETUP_MIN if setup_type == "COMPRESSION_BREAKOUT" else config.SETUP_WATCH_MIN
        if score < minimum_watch_score:
            return None, f"رد ستاپ: امتیاز {score:.1f} کمتر از حد ورود به واچ {minimum_watch_score:.1f} است", details
        if (side == "LONG" and float(invalidation) >= px) or (side == "SHORT" and float(invalidation) <= px):
            return None, "رد ستاپ: سطح ابطال در سمت نادرست Entry قرار دارد", details
        if (side == "LONG" and float(trigger) <= float(invalidation)) or (side == "SHORT" and float(trigger) >= float(invalidation)):
            return None, "رد ستاپ: ترتیب Trigger و Invalidation نامعتبر است", details

        now = int(time.time())
        candidate = SetupCandidate(
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
        return candidate, f"ورود به واچ: {setup_type} با امتیاز {score:.1f}", details
