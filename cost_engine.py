from __future__ import annotations

from dataclasses import dataclass

from config import ESTIMATED_FIXED_ROUND_FEE_USDT, SLIPPAGE_BUFFER, SPREAD_BUFFER, TOOBIT_TAKER_FEE
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
        notional_usdt = margin_usdt * max(1, leverage)
        net_edge = net_profit_usdt / max(notional_usdt, 1e-9)
        estimated_cost_pct = percent_cost
        gross_profit_pct = gross_move * 100.0

        # Profit/cost is informational only. It must not block scalper signals.
        reasons = [
            f"سود کل تخمینی={gross_profit_usdt:.2f} USDT.",
            f"سود خالص نمایشی بعد از fee/slippage={net_profit_usdt:.2f} USDT.",
            "شرط حداقل سود برای ورود حذف شده است؛ این بخش فقط برای نمایش و آمار است.",
        ]

        return CostResult(True, net_edge, estimated_cost_pct, gross_profit_usdt, gross_profit_pct, 0, tuple(reasons))
