"""موتور قطعی TP/SL مخصوص تایم‌فریم ۵ دقیقه.

هیچ پروفایل، ATR، نویز یا تخمین تاریخی اجازه تغییر فاصله‌ها را ندارد:
SL = 0.55% و TP = 0.6875% و RR قیمتی دقیقاً 1.25 است.
هزینه‌ها فقط برای نمایش سود/زیان خالص و کنترل کف سود ۵ سنت محاسبه می‌شوند.
"""
from __future__ import annotations

from dataclasses import dataclass

import config
from storage import Storage
from strategy import StrategySignal


@dataclass(frozen=True)
class RiskPlan:
    entry: float
    tp: float
    sl: float
    rr: float
    net_rr: float
    sl_pct: float
    tp_pct: float
    min_net_profit_ok: bool
    estimated_net_profit: float
    estimated_net_loss: float
    fee_estimate: float
    notional_usdt: float
    trade_usdt: float
    leverage: int
    reason: str


def price_from_pct(entry: float, side: str, pct: float) -> float:
    return entry * (1.0 + pct / 100.0) if side.upper() == "LONG" else entry * (1.0 - pct / 100.0)


def sl_from_pct(entry: float, side: str, pct: float) -> float:
    return entry * (1.0 - pct / 100.0) if side.upper() == "LONG" else entry * (1.0 + pct / 100.0)


def round_trip_cost(notional: float) -> float:
    pct = 2.0 * (float(config.FALLBACK_FEE_PCT_PER_SIDE) + float(config.SLIPPAGE_PCT_PER_SIDE))
    return float(notional) * pct / 100.0


def estimate_net_outcomes(notional: float, tp_pct: float, sl_pct: float) -> tuple[float, float, float, float]:
    cost = round_trip_cost(notional)
    net_profit = notional * tp_pct / 100.0 - cost
    net_loss = notional * sl_pct / 100.0 + cost
    net_rr = net_profit / net_loss if net_loss > 0 else 0.0
    return net_profit, net_loss, cost, net_rr


def build_risk_plan(signal: StrategySignal, storage: Storage) -> RiskPlan | None:
    entry = float(signal.entry)
    if entry <= 0:
        return None

    sl_pct = float(config.FIXED_SL_PCT_5M)
    tp_pct = float(config.FIXED_TP_PCT_5M)
    rr = float(config.RISK_REWARD)

    # محافظ ساختاری: حتی اگر کسی یکی از ثابت‌ها را اشتباه تغییر داد، ربات اجرا نمی‌شود.
    if sl_pct <= 0 or tp_pct <= 0 or abs((tp_pct / sl_pct) - rr) > 1e-12:
        raise RuntimeError("ثابت‌های TP/SL پنج‌دقیقه‌ای ناسازگارند؛ RR باید دقیقاً 1.25 باشد")

    trade_usdt = float(storage.get("trade_usdt", config.TRADE_USDT_DEFAULT))
    leverage = int(storage.get("leverage", config.LEVERAGE_DEFAULT))
    if trade_usdt <= 0 or leverage <= 0:
        return None
    notional = trade_usdt * leverage

    net_profit, net_loss, cost, net_rr = estimate_net_outcomes(notional, tp_pct, sl_pct)
    min_profit_ok = net_profit + 1e-9 >= float(config.MIN_NET_PROFIT_USDT)

    return RiskPlan(
        entry=entry,
        tp=price_from_pct(entry, signal.side, tp_pct),
        sl=sl_from_pct(entry, signal.side, sl_pct),
        rr=rr,
        net_rr=net_rr,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        min_net_profit_ok=min_profit_ok,
        estimated_net_profit=net_profit,
        estimated_net_loss=net_loss,
        fee_estimate=cost,
        notional_usdt=notional,
        trade_usdt=trade_usdt,
        leverage=leverage,
        reason=(
            f"TP/SL ثابت 5M | SL={sl_pct:.4f}% | TP={tp_pct:.4f}% | RR={rr:.2f}"
            if min_profit_ok
            else f"سود خالص TP ثابت کمتر از حداقل {float(config.MIN_NET_PROFIT_USDT):.2f} USDT است"
        ),
    )
