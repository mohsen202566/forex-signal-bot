from __future__ import annotations

from dataclasses import dataclass

from config import MAX_SCALP_SL_PCT, MIN_RISK_REWARD, MIN_SCALP_SL_PCT, MIN_SCALP_TP_PCT, WEIGHTS
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
        # Indicators use completed candles, but entry should be live price.
        # TP/SL must have a minimum distance so a signal cannot be stopped by normal spread/noise.
        if entry <= 0:
            return RiskResult(False, 0.0, 0.0, 0.0, 0, 0.0, ("قیمت ورود برای ساخت TP/SL نامعتبر است.",))

        atr = max(snapshot_15m.atr, entry * 0.0008)
        buffer = atr * 0.12

        min_sl_distance = max(entry * MIN_SCALP_SL_PCT, atr * 0.30)
        min_tp_distance = max(entry * MIN_SCALP_TP_PCT, atr * 0.45)
        max_sl_distance = max(min_sl_distance * 1.25, entry * MAX_SCALP_SL_PCT)
        rr_floor = max(MIN_RISK_REWARD, 1.10)

        reasons: list[str] = [
            f"حداقل فاصله SL={MIN_SCALP_SL_PCT * 100:.3f}% و حداقل فاصله TP={MIN_SCALP_TP_PCT * 100:.3f}% روی قیمت زنده اعمال شد.",
        ]

        if direction == "LONG":
            raw_sl = min(levels.support - buffer, entry - atr * 0.42)
            sl_distance = entry - raw_sl
            sl_distance = min(max(sl_distance, min_sl_distance), max_sl_distance)
            sl = entry - sl_distance

            raw_tp = max(levels.resistance, entry + sl_distance * rr_floor, entry + atr * 0.62)
            reward_floor = max(sl_distance * rr_floor, min_tp_distance)
            reward_distance = max(raw_tp - entry, reward_floor)
            if learned_expected_pct and learned_expected_pct > 0:
                learned_cap = max(min_tp_distance, entry * learned_expected_pct * 1.20)
                if learned_cap > reward_floor:
                    reward_distance = min(reward_distance, learned_cap)
            tp = entry + reward_distance
            risk = entry - sl
            reward = tp - entry
        else:
            raw_sl = max(levels.resistance + buffer, entry + atr * 0.42)
            sl_distance = raw_sl - entry
            sl_distance = min(max(sl_distance, min_sl_distance), max_sl_distance)
            sl = entry + sl_distance

            raw_tp = min(levels.support, entry - sl_distance * rr_floor, entry - atr * 0.62)
            reward_floor = max(sl_distance * rr_floor, min_tp_distance)
            reward_distance = max(entry - raw_tp, reward_floor)
            if learned_expected_pct and learned_expected_pct > 0:
                learned_cap = max(min_tp_distance, entry * learned_expected_pct * 1.20)
                if learned_cap > reward_floor:
                    reward_distance = min(reward_distance, learned_cap)
            tp = entry - reward_distance
            risk = sl - entry
            reward = entry - tp

        if risk <= 0 or reward <= 0 or tp <= 0 or sl <= 0:
            return RiskResult(False, float(tp), float(sl), 0.0, 0, 0.0, ("TP/SL معتبر ساخته نشد.",))

        rr = reward / risk
        risk_pct = risk / entry
        expected_move_pct = reward / entry

        ok = (
            rr >= MIN_RISK_REWARD
            and risk_pct >= MIN_SCALP_SL_PCT
            and expected_move_pct >= MIN_SCALP_TP_PCT
            and risk_pct <= MAX_SCALP_SL_PCT
        )

        if ok:
            reasons.append("TP/SL اسکالپی با حداقل فاصله امن و RR قابل قبول ساخته شد.")
        else:
            reasons.append("TP/SL رد شد: فاصله SL/TP یا RR خارج از محدوده امن اسکالپ است.")

        return RiskResult(ok, float(tp), float(sl), float(rr), 0, float(expected_move_pct), tuple(reasons))
