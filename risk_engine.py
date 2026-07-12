"""TP/SL ساختاری، حاشیه اطمینان و RR خالص ثابت."""
from __future__ import annotations
import config
from models import MarketSignal, RiskPlan


def _fee_rate(mode: str) -> float:
    pct = config.MAKER_FEE_PCT_PER_SIDE if str(mode).upper() == "MAKER" else config.TAKER_FEE_PCT_PER_SIDE
    return pct / 100.0


def _price(entry: float, side: str, pct: float, favorable: bool) -> float:
    direction = 1.0 if side == "LONG" else -1.0
    if not favorable:
        direction *= -1.0
    return entry * (1.0 + direction * pct / 100.0)


def _costs(notional: float, entry: float, exit_price: float) -> float:
    qty = notional / entry
    entry_fee = notional * _fee_rate(config.ENTRY_FEE_MODE)
    exit_notional = qty * exit_price
    exit_fee = exit_notional * _fee_rate(config.EXIT_FEE_MODE)
    slip = (notional + exit_notional) * (config.SLIPPAGE_PCT_PER_SIDE / 100.0)
    return entry_fee + exit_fee + slip


def build_risk_plan(signal: MarketSignal, trade_usdt: float, leverage: int) -> RiskPlan | None:
    entry = float(signal.entry)
    if entry <= 0 or trade_usdt <= 0 or leverage <= 0:
        return None
    notional = float(trade_usdt) * int(leverage)
    raw_structure_pct = abs(entry - signal.invalidation_price) / entry * 100.0
    min_stop = signal.atr_pct * config.MIN_STOP_ATR_MULTIPLIER
    base_stop = max(raw_structure_pct, min_stop)
    if signal.spread_pct > config.MAX_SPREAD_PCT * 0.75 or signal.strength == "متوسط":
        safety = config.SL_SAFETY_HIGH_PCT
    elif signal.strength == "بسیار قوی":
        safety = config.SL_SAFETY_MIN_PCT
    else:
        safety = config.SL_SAFETY_NORMAL_PCT
    sl_pct = base_stop * (1.0 + safety / 100.0)
    if sl_pct > signal.atr_pct * config.MAX_STOP_ATR_MULTIPLIER:
        return None
    sl = _price(entry, signal.side, sl_pct, favorable=False)
    sl_move_loss = notional * (sl_pct / 100.0)
    sl_fees = _costs(notional, entry, sl)
    sl_net_loss = sl_move_loss + sl_fees

    # RR خالص دقیق: سود خالص TP = RISK_REWARD × زیان خالص SL.
    target_net = config.RISK_REWARD * sl_net_loss
    # حل عددی سبک برای فاصله TP با لحاظ کارمزد خروج متغیر.
    lo, hi = 0.0, max(signal.expected_move_pct, sl_pct * 4.0)
    for _ in range(45):
        mid = (lo + hi) / 2.0
        tp_mid = _price(entry, signal.side, mid, favorable=True)
        gross = notional * (mid / 100.0)
        net = gross - _costs(notional, entry, tp_mid)
        if net < target_net:
            lo = mid
        else:
            hi = mid
    tp_pct = hi
    forecast_cap = signal.expected_move_pct * config.TP_FORECAST_FRACTION
    if tp_pct > forecast_cap:
        return None
    tp = _price(entry, signal.side, tp_pct, favorable=True)
    tp_gross = notional * (tp_pct / 100.0)
    tp_fees = _costs(notional, entry, tp)
    tp_net = tp_gross - tp_fees
    rr_net = tp_net / sl_net_loss if sl_net_loss > 0 else 0.0
    threshold = config.MIN_NET_PROFIT_USDT + config.MIN_NET_PROFIT_SAFETY_USDT
    min_ok = tp_net >= threshold and rr_net >= config.RISK_REWARD - 0.002
    if not min_ok:
        return None
    qty = notional / entry
    return RiskPlan(entry, tp, sl, rr_net, sl_pct, tp_pct, notional, qty, tp_gross, tp_fees, tp_net, sl_move_loss, sl_fees, sl_net_loss, True,
                    f"SL ساختاری+حاشیه {safety:.0f}% | ظرفیت محتاطانه {forecast_cap:.4f}% | RR خالص {rr_net:.3f}")
