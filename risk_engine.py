"""موتور سبک و قطعی مدیریت ریسک.

قانون اصلی: نسبت سود به زیان ۱.۳۵ بر اساس PnL خالص پس از هزینه رفت‌وبرگشت
محاسبه می‌شود، نه صرفاً فاصله قیمت. در مسیر زنده فقط lookup پروفایل و چند
محاسبه عددی انجام می‌شود.
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
    """net_profit, net_loss_abs, cost, net_rr."""
    cost = round_trip_cost(notional)
    net_profit = notional * tp_pct / 100.0 - cost
    net_loss = notional * sl_pct / 100.0 + cost
    net_rr = net_profit / net_loss if net_loss > 0 else 0.0
    return net_profit, net_loss, cost, net_rr


def required_tp_pct_for_net_rr(notional: float, sl_pct: float, target_rr: float, min_net_profit: float) -> float:
    """حل دقیق فاصله TP برای RR خالص و کف سود خالص."""
    if notional <= 0:
        return 0.0
    cost = round_trip_cost(notional)
    net_loss = notional * sl_pct / 100.0 + cost
    gross_for_rr = target_rr * net_loss + cost
    gross_for_min = min_net_profit + cost
    return max(gross_for_rr, gross_for_min) / notional * 100.0


def build_risk_plan(signal: StrategySignal, storage: Storage) -> RiskPlan | None:
    entry = float(signal.entry)
    if entry <= 0:
        return None

    profile = storage.get_profile(signal.symbol_id) or {}
    min_sl_pct = float(profile.get("min_sl_pct") or 0.0)
    if min_sl_pct <= 0:
        # نبود پروفایل نباید موتور شکار را خاموش کند؛ fallback محافظه‌کارانه فقط در ریسک استفاده می‌شود.
        min_sl_pct = float(getattr(config, "RISK_FALLBACK_MIN_SL_PCT", 0.55))
    sl_pct = max(min_sl_pct, float(getattr(config, "RISK_ABSOLUTE_MIN_SL_PCT", 0.05)))

    trade_usdt = float(storage.get("trade_usdt", config.TRADE_USDT_DEFAULT))
    leverage = int(storage.get("leverage", config.LEVERAGE_DEFAULT))
    if trade_usdt <= 0 or leverage <= 0:
        return None
    notional = trade_usdt * leverage

    tp_pct = required_tp_pct_for_net_rr(
        notional=notional,
        sl_pct=sl_pct,
        target_rr=float(config.RISK_REWARD),
        min_net_profit=float(config.MIN_NET_PROFIT_USDT),
    )
    net_profit, net_loss, cost, net_rr = estimate_net_outcomes(notional, tp_pct, sl_pct)

    # پروفایل TP نباید RR خالص کامل را به فیلتر ورود تبدیل کند؛ نقش آن طبق
    # معماری پروژه فقط این است که بسنجد آیا حداقل سود خالص ۵ سنت در حرکت‌های
    # مشابه واقع‌بینانه بوده است یا نه. RR خالص ۱.۳۵ همچنان در خود TP حفظ می‌شود.
    tp_p70 = float(profile.get("tp_p70") or 0.0)
    samples = int(profile.get("signal_count") or 0)
    profile_ready = samples >= int(getattr(config, "PROFILE_MIN_SIGNALS", 8)) and tp_p70 > 0
    min_profit_tp_pct = (float(config.MIN_NET_PROFIT_USDT) + cost) / notional * 100.0
    profile_ok = (not profile_ready) or tp_p70 >= min_profit_tp_pct * float(getattr(config, "TP_PROFILE_TOLERANCE", 0.85))

    # پروفایل TP در نسخه فعلی از داده کندلی ساخته می‌شود و میکروساختار زنده
    # واچ‌لیست را بازسازی نمی‌کند؛ بنابراین نباید سیگنال معتبر را خفه کند.
    # فقط به‌صورت هشدار/اطلاعات نگه داشته می‌شود. دو شرط قطعی، RR خالص و کف سودند.
    valid = (
        net_profit + 1e-9 >= float(config.MIN_NET_PROFIT_USDT)
        and net_rr + 1e-9 >= float(config.RISK_REWARD)
    )
    reason = "RR خالص ۱.۳۵ + کف سود خالص + استاپ نویز هر ارز"
    if profile_ready and not profile_ok:
        reason += " | هشدار: پروفایل تاریخی حرکت محافظه‌کارانه‌تر است"

    return RiskPlan(
        entry=entry,
        tp=price_from_pct(entry, signal.side, tp_pct),
        sl=sl_from_pct(entry, signal.side, sl_pct),
        rr=float(config.RISK_REWARD),
        net_rr=net_rr,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        min_net_profit_ok=valid,
        estimated_net_profit=net_profit,
        estimated_net_loss=net_loss,
        fee_estimate=cost,
        notional_usdt=notional,
        trade_usdt=trade_usdt,
        leverage=leverage,
        reason=reason,
    )
