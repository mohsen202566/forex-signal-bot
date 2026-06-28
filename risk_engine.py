from __future__ import annotations

from dataclasses import dataclass

from config import MIN_RISK_REWARD, WEIGHTS
from indicators import IndicatorSnapshot
from levels_engine import LevelsResult
from scorer import Direction


@dataclass(frozen=True)
class RiskResult:
    ok: bool
    tp: float
    sl: float
    risk_reward: float
    score: int
    expected_move_pct: float
    reasons: tuple[str, ...]


class RiskEngine:
    def build_tp_sl(self, *, direction: Direction, entry: float, snapshot_15m: IndicatorSnapshot, levels: LevelsResult, learned_expected_pct: float | None = None) -> RiskResult:
        # Faster TP/SL for 5m-15m scalping; avoid very wide 1H-style targets.
        atr = max(snapshot_15m.atr, entry * 0.0008)
        buffer = atr * 0.12
        reasons: list[str] = []
        if direction == "LONG":
            raw_sl = min(levels.support - buffer, entry - atr * 0.38)
            sl = max(raw_sl, entry - atr * 1.35)
            risk = entry - sl
            candidate_tp = max(levels.resistance, entry + risk * 1.12, entry + atr * 0.48)
            cap_tp = entry + atr * 1.25
            if learned_expected_pct and learned_expected_pct > 0:
                cap_tp = min(cap_tp, entry * (1.0 + learned_expected_pct * 1.10))
            tp = min(candidate_tp, cap_tp)
            reward = tp - entry
        else:
            raw_sl = max(levels.resistance + buffer, entry + atr * 0.38)
            sl = min(raw_sl, entry + atr * 1.35)
            risk = sl - entry
            candidate_tp = min(levels.support, entry - risk * 1.12, entry - atr * 0.48)
            cap_tp = entry - atr * 1.25
            if learned_expected_pct and learned_expected_pct > 0:
                cap_tp = max(cap_tp, entry * (1.0 - learned_expected_pct * 1.10))
            tp = max(candidate_tp, cap_tp)
            reward = entry - tp
        if risk <= 0 or reward <= 0 or tp <= 0 or sl <= 0:
            return RiskResult(False, float(tp), float(sl), 0.0, 0, 0.0, ("TP/SL معتبر ساخته نشد.",))
        rr = reward / risk
        risk_pct = risk / entry if entry > 0 else 0.0
        expected_move_pct = reward / entry if entry > 0 else 0.0
        ok = rr >= MIN_RISK_REWARD and 0.00030 <= risk_pct <= 0.020
        if ok:
            reasons.append("TP/SL اسکالپی با ATR و محدوده تکنیکال قابل قبول است.")
        else:
            reasons.append("ریسک/ریوارد یا فاصله SL برای اسکالپ قابل قبول نیست.")
        return RiskResult(ok, float(tp), float(sl), float(rr), 0, float(expected_move_pct), tuple(reasons))
