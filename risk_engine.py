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


def build_risk_plan_diagnostic(signal: MarketSignal, trade_usdt: float, leverage: int) -> tuple[RiskPlan | None, str, dict[str, float | int | str]]:
    entry = float(signal.entry)
    metrics: dict[str, float | int | str] = {"entry": entry, "trade_usdt": trade_usdt, "leverage": leverage}
    if entry <= 0:
        return None, "Entry نامعتبر یا صفر است", metrics
    if trade_usdt <= 0:
        return None, "دلار هر پوزیشن باید بزرگ‌تر از صفر باشد", metrics
    if leverage <= 0:
        return None, "لوریج باید بزرگ‌تر از صفر باشد", metrics

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
    max_sl_pct = signal.atr_pct * config.MAX_STOP_ATR_MULTIPLIER
    metrics.update({
        "notional": notional, "raw_structure_pct": raw_structure_pct, "min_stop_pct": min_stop,
        "base_stop_pct": base_stop, "safety_pct": safety, "sl_pct": sl_pct, "max_sl_pct": max_sl_pct,
    })
    if sl_pct > max_sl_pct:
        return None, f"استاپ نهایی بیش‌ازحد بزرگ است: {sl_pct:.4f}% > {max_sl_pct:.4f}%", metrics

    sl = _price(entry, signal.side, sl_pct, favorable=False)
    sl_move_loss = notional * (sl_pct / 100.0)
    sl_fees = _costs(notional, entry, sl)
    sl_net_loss = sl_move_loss + sl_fees
    target_net = config.RISK_REWARD * sl_net_loss

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
    metrics.update({"tp_required_pct": tp_pct, "forecast_cap_pct": forecast_cap, "expected_move_pct": signal.expected_move_pct})
    if tp_pct > forecast_cap:
        return None, f"ظرفیت حرکت برای RR کافی نیست: TP لازم {tp_pct:.4f}% > ظرفیت محتاطانه {forecast_cap:.4f}%", metrics

    tp = _price(entry, signal.side, tp_pct, favorable=True)
    tp_gross = notional * (tp_pct / 100.0)
    tp_fees = _costs(notional, entry, tp)
    tp_net = tp_gross - tp_fees
    rr_net = tp_net / sl_net_loss if sl_net_loss > 0 else 0.0
    threshold = config.MIN_NET_PROFIT_USDT + config.MIN_NET_PROFIT_SAFETY_USDT
    metrics.update({
        "tp_net_usdt": tp_net, "sl_net_loss_usdt": sl_net_loss, "rr_net": rr_net,
        "min_net_threshold_usdt": threshold, "tp_fees_usdt": tp_fees, "sl_fees_usdt": sl_fees,
    })
    if tp_net < threshold:
        return None, f"سود خالص تخمینی کم است: {tp_net:.4f} < {threshold:.4f} USDT", metrics
    if rr_net < config.RISK_REWARD - 0.002:
        return None, f"RR خالص کافی نیست: {rr_net:.4f} < {config.RISK_REWARD:.4f}", metrics

    qty = notional / entry
    plan = RiskPlan(entry, tp, sl, rr_net, sl_pct, tp_pct, notional, qty, tp_gross, tp_fees, tp_net, sl_move_loss, sl_fees, sl_net_loss, True,
                    f"SL ساختاری+حاشیه {safety:.0f}% | ظرفیت محتاطانه {forecast_cap:.4f}% | RR خالص {rr_net:.3f}")
    return plan, "برنامه ریسک تأیید شد", metrics


def build_risk_plan(signal: MarketSignal, trade_usdt: float, leverage: int) -> RiskPlan | None:
    return build_risk_plan_diagnostic(signal, trade_usdt, leverage)[0]
