from __future__ import annotations

from dataclasses import dataclass

from config import ESTIMATED_FIXED_ROUND_FEE_USDT, MIN_NET_EDGE, MIN_NET_PROFIT_USDT, SLIPPAGE_BUFFER, SPREAD_BUFFER, TOOBIT_TAKER_FEE
from scorer import Direction


@dataclass(frozen=True)
class CostResult:
    ok: bool
    net_edge: float
    estimated_cost_pct: float
    estimated_profit_usdt: float
    estimated_profit_pct: float
    score_bonus: int
    reasons: tuple[str, ...]


class CostEngine:
    def evaluate(self, *, direction: Direction, entry: float, tp: float, margin_usdt: float, leverage: int) -> CostResult:
        if entry <= 0 or tp <= 0:
            return CostResult(False, 0.0, 0.0, 0.0, 0.0, 0, ("قیمت ورود یا TP نامعتبر است.",))
        gross_move = (tp - entry) / entry if direction == "LONG" else (entry - tp) / entry
        percent_cost = (TOOBIT_TAKER_FEE * 2.0) + SPREAD_BUFFER + SLIPPAGE_BUFFER
        variable_cost_usdt = margin_usdt * max(1, leverage) * percent_cost
        fixed_fee = ESTIMATED_FIXED_ROUND_FEE_USDT
        gross_profit_usdt = margin_usdt * max(1, leverage) * gross_move
        net_profit_usdt = gross_profit_usdt - variable_cost_usdt - fixed_fee
        net_edge = net_profit_usdt / max(margin_usdt * max(1, leverage), 1e-9)
        estimated_cost_pct = percent_cost
        profit_pct = net_edge * 100.0
        reasons = [
            f"سود خالص تخمینی={net_profit_usdt:.2f} USDT بعد از fee/slippage.",
            f"حداقل سود خالص ثابت={MIN_NET_PROFIT_USDT:.2f} USDT.",
        ]
        ok = True
        if net_edge < MIN_NET_EDGE:
            reasons.append("Net Edge پایه کافی نیست.")
            ok = False
        if net_profit_usdt < MIN_NET_PROFIT_USDT:
            reasons.append("سود خالص کمتر از 0.10 دلار است؛ رد کامل.")
            ok = False
        return CostResult(ok, net_edge, estimated_cost_pct, net_profit_usdt, profit_pct, 0, tuple(reasons))
