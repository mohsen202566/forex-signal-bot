"""موتور تحلیل زنده ۵ دقیقه‌ای.

معماری:
۱) اسکن سبک همه ارزها و ورود نرم به واچ‌لیست.
۲) مانیتور سریع ارزهای واچ با معاملات اخیر و عمق سفارش OKX.
۳) صدور سیگنال فقط وقتی «شروع حرکت» و «جهت بدون تناقض» هم‌زمان تأیید شوند.

هیچ کار شبکه‌ای یا محاسبه روزانه داخل این فایل انجام نمی‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any
import time

import config


@dataclass
class StrategySignal:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    side: str
    entry: float
    strength: str
    strength_score: float
    compression_score: float
    flow_bias: float
    absorption_score: float
    reason: str


@dataclass
class WatchCandidate:
    side: str  # LONG / SHORT / UNCERTAIN
    trigger: str
    start_price: float
    early_flow: float
    compression_score: float
    volume_ratio: float
    range_ratio: float
    expected_move_pct: float
    late_limit_pct: float
    details: dict[str, float | str] = field(default_factory=dict)


@dataclass
class WatchState:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    side: str
    trigger: str
    start_price: float
    created_at: float
    expected_move_pct: float
    late_limit_pct: float
    early_flow: float
    compression_score: float
    direction_locked: bool = False
    side_changes: int = 0
    confirm_count: int = 0
    bad_count: int = 0
    last_price: float = 0.0
    last_update: float = 0.0


@dataclass
class WatchEvaluation:
    action: str  # KEEP / SIGNAL / REMOVE / SIDE_CHANGED
    reason_fa: str
    side: str
    signal: StrategySignal | None
    metrics: dict[str, float | str]


@dataclass
class StrategyAnalysisResult:
    """فقط برای سازگاری با پروفایل‌ساز قدیمی."""
    signal: StrategySignal | None
    reject_reason: str
    details: dict[str, float | str]


def pct_range(c: dict[str, float]) -> float:
    close = float(c["close"])
    return (float(c["high"]) - float(c["low"])) / close * 100.0 if close > 0 else 0.0


def _volume(c: dict[str, float]) -> float:
    return max(float(c.get("vol_quote") or c.get("volume") or 0.0), 0.0)


def _safe_median(values: list[float], default: float = 0.0) -> float:
    return median(values) if values else default


def pre_move_flow_bias(candles: list[dict[str, float]]) -> float:
    """پروکسی سبک جریان سفارش برای مرحله اسکن عمومی.

    در مرحله واچ، جهت از معاملات واقعی و دفتر سفارش گرفته می‌شود؛ بنابراین
    این عدد فقط برای ورود نرم به واچ است و قفل جهت نیست.
    """
    recent = candles[-max(3, int(config.FLOW_BIAS_LOOKBACK)):]
    total_vol = sum(_volume(c) for c in recent) or 1e-9
    value = 0.0
    for c in recent:
        rng = max(float(c["high"]) - float(c["low"]), 1e-12)
        body = (float(c["close"]) - float(c["open"])) / rng
        close_location = ((float(c["close"]) - float(c["low"])) / rng - 0.5) * 2.0
        value += (0.65 * max(-1.0, min(1.0, body)) + 0.35 * close_location) * (_volume(c) / total_vol)
    return max(-1.0, min(1.0, value))


def detect_watch_candidate(
    candles: list[dict[str, float]],
    profile: dict[str, Any] | None = None,
) -> tuple[WatchCandidate | None, str, dict[str, float | str]]:
    """نشانه اولیه را نرم می‌گیرد؛ این مرحله سیگنال صادر نمی‌کند."""
    if len(candles) < 24:
        return None, "داده کندلی کافی نیست", {"تعداد_کندل": len(candles)}

    current = candles[-1]
    prev = candles[-18:-1]
    recent = candles[-6:]
    current_range = pct_range(current)
    base_ranges = [pct_range(c) for c in prev]
    recent_ranges = [pct_range(c) for c in recent]
    base_range = _safe_median(base_ranges, 1e-9) or 1e-9
    range_ratio = current_range / base_range
    compression_ratio = _safe_median(recent_ranges, base_range) / base_range

    current_vol = _volume(current)
    base_vol = _safe_median([_volume(c) for c in prev], 1e-9) or 1e-9
    volume_ratio = current_vol / base_vol
    flow = pre_move_flow_bias(candles)

    open_px = float(current["open"])
    close_px = float(current["close"])
    current_move = abs(close_px - open_px) / max(open_px, 1e-9) * 100.0

    profile = profile or {}
    expected = float(profile.get("tp_p70") or profile.get("tp_median") or 0.0)
    if expected <= 0:
        expected = max(float(profile.get("noise_p70") or 0.0) * 2.2, 0.35)
    # فقط وقتی بخش بزرگی از موج احتمالی طی شده باشد دیر محسوب می‌شود؛ نه با حد خشک کوچک.
    late_limit = max(
        float(getattr(config, "WATCH_LATE_MIN_PCT", 0.10)),
        min(float(getattr(config, "WATCH_LATE_MAX_PCT", 0.45)), expected * float(getattr(config, "WATCH_LATE_EXPECTED_FRACTION", 0.30))),
    )

    compression_ready = compression_ratio <= float(getattr(config, "WATCH_COMPRESSION_SOFT_RATIO", 0.92))
    volume_ignition = volume_ratio >= float(getattr(config, "WATCH_VOLUME_RATIO_MIN", 1.18))
    range_ignition = range_ratio >= float(getattr(config, "WATCH_RANGE_RATIO_MIN", 1.12))
    flow_hint = abs(flow) >= float(getattr(config, "WATCH_EARLY_FLOW_MIN", 0.045))

    details: dict[str, float | str] = {
        "فشار_اولیه": round(flow, 4),
        "نسبت_حجم": round(volume_ratio, 3),
        "نسبت_دامنه": round(range_ratio, 3),
        "نسبت_فشردگی": round(compression_ratio, 3),
        "حرکت_فعلی_درصد": round(current_move, 4),
        "حد_دیرشدن_درصد": round(late_limit, 4),
    }

    # ورود به واچ عمداً OR است تا حرکت‌ها با یک الگوی اجباری خفه نشوند.
    trigger = ""
    if compression_ready and flow_hint:
        trigger = "فشردگی در حال آزاد شدن"
    elif volume_ignition and flow_hint:
        trigger = "افزایش اولیه شدت معاملات"
    elif range_ignition and flow_hint:
        trigger = "شروع گسترش دامنه همراه فشار جهت‌دار"
    elif volume_ignition and range_ignition:
        trigger = "شتاب هم‌زمان حجم و دامنه"
    else:
        return None, "نشانه اولیه شروع حرکت کافی نبود", details

    if current_move > late_limit:
        return None, "حرکت قبل از ورود به واچ بیش‌ازحد جلو رفته بود", details

    if flow >= float(getattr(config, "WATCH_TENTATIVE_SIDE_MIN", 0.06)):
        side = "LONG"
    elif flow <= -float(getattr(config, "WATCH_TENTATIVE_SIDE_MIN", 0.06)):
        side = "SHORT"
    else:
        side = "UNCERTAIN"

    comp_score = max(0.0, min(1.0, 1.0 - compression_ratio))
    return WatchCandidate(
        side=side,
        trigger=trigger,
        start_price=close_px,
        early_flow=flow,
        compression_score=comp_score,
        volume_ratio=volume_ratio,
        range_ratio=range_ratio,
        expected_move_pct=expected,
        late_limit_pct=late_limit,
        details=details,
    ), "ورود به واچ", details


def _direction_from_micro(trade_imbalance: float, book_imbalance: float, response_pct: float) -> tuple[str, bool, float]:
    """جهت را از توافق فشار اجراشده و واکنش قیمت می‌گیرد.

    همه مؤلفه‌ها اجباری نیستند؛ دو شاهد هم‌جهت و نبود تناقض شدید کافی است.
    """
    trade_min = float(getattr(config, "WATCH_TRADE_IMBALANCE_MIN", 0.10))
    book_min = float(getattr(config, "WATCH_BOOK_IMBALANCE_MIN", 0.07))
    response_min = float(getattr(config, "WATCH_PRICE_RESPONSE_MIN_PCT", 0.004))
    conflict = float(getattr(config, "WATCH_STRONG_CONFLICT", 0.16))

    long_votes = int(trade_imbalance >= trade_min) + int(book_imbalance >= book_min) + int(response_pct >= response_min)
    short_votes = int(trade_imbalance <= -trade_min) + int(book_imbalance <= -book_min) + int(response_pct <= -response_min)

    long_conflict = trade_imbalance <= -conflict or (book_imbalance <= -conflict and response_pct < 0)
    short_conflict = trade_imbalance >= conflict or (book_imbalance >= conflict and response_pct > 0)

    confidence = max(long_votes, short_votes) / 3.0
    if long_votes >= 2 and not long_conflict and long_votes > short_votes:
        return "LONG", True, confidence
    if short_votes >= 2 and not short_conflict and short_votes > long_votes:
        return "SHORT", True, confidence
    return "UNCERTAIN", False, confidence


def evaluate_watch(state: WatchState, snapshot: dict[str, Any], now: float | None = None) -> WatchEvaluation:
    now = now or time.time()
    age = now - state.created_at
    price = float(snapshot.get("mid_price") or snapshot.get("last_price") or 0.0)
    if price <= 0:
        return WatchEvaluation("KEEP", "قیمت معتبر دریافت نشد؛ واچ حفظ شد", state.side, None, {"سن_واچ_ثانیه": round(age, 1)})

    trade_imbalance = float(snapshot.get("trade_imbalance") or 0.0)
    book_imbalance = float(snapshot.get("book_imbalance") or 0.0)
    intensity_accel = float(snapshot.get("intensity_acceleration") or 0.0)
    response_pct = (price - state.start_price) / max(state.start_price, 1e-9) * 100.0
    displacement = abs(response_pct)
    side, locked, confidence = _direction_from_micro(trade_imbalance, book_imbalance, response_pct)

    metrics: dict[str, float | str] = {
        "سن_واچ_ثانیه": round(age, 1),
        "عدم_تعادل_معاملات": round(trade_imbalance, 4),
        "عدم_تعادل_دفتر": round(book_imbalance, 4),
        "شتاب_معاملات": round(intensity_accel, 4),
        "واکنش_قیمت_درصد": round(response_pct, 4),
        "اعتماد_جهت": round(confidence * 100.0, 1),
        "حد_دیرشدن_درصد": round(state.late_limit_pct, 4),
    }

    if age > float(getattr(config, "WATCH_TTL_SECONDS", 300)):
        return WatchEvaluation("REMOVE", "زمان منطقی واچ تمام شد", state.side, None, metrics)
    if displacement > state.late_limit_pct:
        return WatchEvaluation("REMOVE", "قیمت پیش از تأیید بیش‌ازحد حرکت کرد و ورود دیر شد", state.side, None, metrics)

    # قبل از قفل جهت، تنها یک بار اجازه چرخش داریم تا حرکت معکوس واقعی از دست نرود.
    if locked and side != "UNCERTAIN" and side != state.side and not state.direction_locked:
        if state.side_changes < int(getattr(config, "WATCH_MAX_SIDE_CHANGES", 1)):
            return WatchEvaluation("SIDE_CHANGED", "جریان سفارش به‌طور واضح چرخید", side, None, metrics)
        state.bad_count += 1

    # شروع حرکت: یک شاهد بسیار قوی یا دو شاهد متوسط. Compression اجباری نیست.
    strong_trade = abs(trade_imbalance) >= float(getattr(config, "WATCH_STRONG_TRADE_IMBALANCE", 0.24))
    strong_book = abs(book_imbalance) >= float(getattr(config, "WATCH_STRONG_BOOK_IMBALANCE", 0.20))
    accelerated = intensity_accel >= float(getattr(config, "WATCH_INTENSITY_ACCEL_MIN", 0.18))
    price_started = displacement >= float(getattr(config, "WATCH_MIN_START_DISPLACEMENT_PCT", 0.003))
    start_confirmed = strong_trade or (accelerated and (strong_book or price_started)) or (strong_book and price_started)

    # تناقض واضح و پایدار حذف می‌کند؛ یک نوسان کوتاه واچ را نمی‌کشد.
    contradiction = (
        (state.side == "LONG" and trade_imbalance < -0.18 and response_pct < -0.01)
        or (state.side == "SHORT" and trade_imbalance > 0.18 and response_pct > 0.01)
    )
    if contradiction:
        state.bad_count += 1
    else:
        state.bad_count = max(0, state.bad_count - 1)
    if state.bad_count >= int(getattr(config, "WATCH_BAD_OBSERVATIONS_TO_REMOVE", 3)):
        return WatchEvaluation("REMOVE", "تناقض پایدار بین جهت واچ و جریان واقعی بازار", state.side, None, metrics)

    if not locked or side == "UNCERTAIN":
        return WatchEvaluation("KEEP", "شروع زیر نظر است اما جهت هنوز بدون تناقض قفل نشده", state.side, None, metrics)

    if not start_confirmed:
        return WatchEvaluation("KEEP", "جهت روشن‌تر شده اما شتاب شروع حرکت هنوز کافی نیست", side, None, metrics)

    # سیگنال قوی در یک مشاهده صادر می‌شود؛ حالت متوسط دو مشاهده متوالی می‌خواهد.
    strong_confirmation = strong_trade and (strong_book or price_started)
    state.confirm_count = state.confirm_count + 1 if side == state.side or state.side == "UNCERTAIN" else 1
    needed = 1 if strong_confirmation else int(getattr(config, "WATCH_CONFIRMATIONS_REQUIRED", 2))
    if state.confirm_count < needed:
        return WatchEvaluation("KEEP", "تأیید اول دریافت شد؛ برای حذف نویز یک مشاهده دیگر لازم است", side, None, metrics)

    strength_score = min(100.0, (
        abs(trade_imbalance) * 38.0
        + abs(book_imbalance) * 24.0
        + min(max(intensity_accel, 0.0), 1.5) * 20.0
        + confidence * 18.0
    ))
    if strength_score >= 76:
        strength = "خیلی قوی"
    elif strength_score >= 60:
        strength = "قوی"
    else:
        strength = "متوسط"

    signal = StrategySignal(
        symbol_id=state.symbol_id,
        okx_symbol=state.okx_symbol,
        toobit_symbol=state.toobit_symbol,
        side=side,
        entry=price,
        strength=strength,
        strength_score=round(strength_score, 2),
        compression_score=round(state.compression_score * 100.0, 2),
        flow_bias=round(trade_imbalance, 4),
        absorption_score=round(confidence * 100.0, 2),
        reason=(
            f"شروع حرکت زنده + قفل جهت | ماشه={state.trigger} | "
            f"معاملات={trade_imbalance:.3f} دفتر={book_imbalance:.3f} پاسخ={response_pct:.4f}%"
        ),
    )
    return WatchEvaluation("SIGNAL", "شروع حرکت و جهت هم‌زمان تأیید شدند", side, signal, metrics)


# ---------------------------------------------------------------------------
# سازگاری با ProfileBuilder قدیمی: فقط برای ساخت پروفایل روزانه از کندل‌ها.
# در مسیر زنده استفاده نمی‌شود.
# ---------------------------------------------------------------------------
def analyze_symbol_detailed(symbol_id: str, okx_symbol: str, toobit_symbol: str, candles: list[dict[str, float]]) -> StrategyAnalysisResult:
    candidate, reason, details = detect_watch_candidate(candles, profile=None)
    if not candidate:
        return StrategyAnalysisResult(None, "watch_candidate_fail", details)
    if candidate.side == "UNCERTAIN":
        return StrategyAnalysisResult(None, "direction_uncertain", details)
    score = min(100.0, 45.0 + abs(candidate.early_flow) * 100.0 + min(candidate.volume_ratio, 2.0) * 8.0)
    strength = "قوی" if score >= 65 else "متوسط"
    signal = StrategySignal(
        symbol_id=symbol_id,
        okx_symbol=okx_symbol,
        toobit_symbol=toobit_symbol,
        side=candidate.side,
        entry=candidate.start_price,
        strength=strength,
        strength_score=round(score, 2),
        compression_score=round(candidate.compression_score * 100.0, 2),
        flow_bias=round(candidate.early_flow, 4),
        absorption_score=0.0,
        reason=f"پروکسی تاریخی واچ: {candidate.trigger}",
    )
    return StrategyAnalysisResult(signal, "accepted", details)


def analyze_symbol(symbol_id: str, okx_symbol: str, toobit_symbol: str, candles: list[dict[str, float]]) -> StrategySignal | None:
    return analyze_symbol_detailed(symbol_id, okx_symbol, toobit_symbol, candles).signal
