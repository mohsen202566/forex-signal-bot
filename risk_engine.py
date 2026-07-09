"""Smart TP/SL Engine.
کار لحظه‌ای این فایل فقط چند محاسبه سبک و خواندن پروفایل آماده است.
"""
from __future__ import annotations

from dataclasses import dataclass

import config
from storage import Storage
from strategy import StrategySignal

@dataclass
class RiskPlan:
    entry: float
    tp: float
    sl: float
    rr: float
    sl_pct: float
    tp_pct: float
    min_net_profit_ok: bool
    estimated_net_profit: float
    fee_estimate: float
    reason: str

def price_from_pct(entry: float, side: str, pct: float) -> float:
    if side.upper() == "LONG":
        return entry * (1.0 + pct / 100.0)
    return entry * (1.0 - pct / 100.0)

def sl_from_pct(entry: float, side: str, pct: float) -> float:
    if side.upper() == "LONG":
        return entry * (1.0 - pct / 100.0)
    return entry * (1.0 + pct / 100.0)

def estimate_net_profit(trade_usdt: float, leverage: int, tp_pct: float) -> tuple[float, float]:
    notional = float(trade_usdt) * float(leverage)
    gross = notional * (float(tp_pct) / 100.0)
    fee = notional * ((config.FALLBACK_FEE_PCT_PER_SIDE * 2.0) / 100.0)
    slip = notional * ((config.SLIPPAGE_PCT_PER_SIDE * 2.0) / 100.0)
    net = gross - fee - slip
    return net, fee + slip

def build_risk_plan(signal: StrategySignal, storage: Storage) -> RiskPlan | None:
    entry = float(signal.entry)
    if entry <= 0:
        return None
    profile = storage.get_profile(signal.symbol_id) or {}
    min_sl_pct = float(profile.get("min_sl_pct") or 0.0)
    if min_sl_pct <= 0:
        # fallback سبک برای وقتی هنوز پروفایل روزانه ساخته نشده
        min_sl_pct = 0.35
    sl_pct = max(min_sl_pct, 0.05)
    base_tp_pct = sl_pct * config.RISK_REWARD
    trade_usdt = float(storage.get("trade_usdt", config.TRADE_USDT_DEFAULT))
    leverage = int(storage.get("leverage", config.LEVERAGE_DEFAULT))
    net, fee_est = estimate_net_profit(trade_usdt, leverage, base_tp_pct)
    final_tp_pct = base_tp_pct
    if net < config.MIN_NET_PROFIT_USDT:
        notional = trade_usdt * leverage
        required_gross = config.MIN_NET_PROFIT_USDT + fee_est
        final_tp_pct = (required_gross / max(notional, 1e-9)) * 100.0
        net, fee_est = estimate_net_profit(trade_usdt, leverage, final_tp_pct)
    tp_profile_p70 = float(profile.get("tp_p70") or 0.0)
    # پروفایل فقط حداقل سود خالص را واقعی‌بودن‌سنجی می‌کند، نه اینکه سیگنال‌های خوب را خفه کند.
    if tp_profile_p70 > 0:
        min_profit_tp_pct = final_tp_pct if net >= config.MIN_NET_PROFIT_USDT else base_tp_pct
        profile_ok = tp_profile_p70 >= min_profit_tp_pct * 0.85
    else:
        profile_ok = True
    if net < config.MIN_NET_PROFIT_USDT or not profile_ok:
        return RiskPlan(
            entry=entry,
            tp=price_from_pct(entry, signal.side, final_tp_pct),
            sl=sl_from_pct(entry, signal.side, sl_pct),
            rr=config.RISK_REWARD,
            sl_pct=sl_pct,
            tp_pct=final_tp_pct,
            min_net_profit_ok=False,
            estimated_net_profit=net,
            fee_estimate=fee_est,
            reason="حداقل سود خالص ۵ سنت یا پروفایل TP کافی نیست",
        )
    return RiskPlan(
        entry=entry,
        tp=price_from_pct(entry, signal.side, final_tp_pct),
        sl=sl_from_pct(entry, signal.side, sl_pct),
        rr=config.RISK_REWARD,
        sl_pct=sl_pct,
        tp_pct=final_tp_pct,
        min_net_profit_ok=True,
        estimated_net_profit=net,
        fee_estimate=fee_est,
        reason="RR ثابت + حداقل سود خالص + پروفایل آماده",
    )
