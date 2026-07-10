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
    diagnostic_context: dict[str, Any] = field(default_factory=dict)


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
    data_error_count: int = 0
    last_price: float = 0.0
    last_update: float = 0.0
    trade_history: list[float] = field(default_factory=list)
    book_history: list[float] = field(default_factory=list)
    response_history: list[float] = field(default_factory=list)
    intensity_history: list[float] = field(default_factory=list)
    last_snapshot_trade_ts: int = 0
    evidence_score: float = 0.0


@dataclass
class WatchEvaluation:
    action: str  # KEEP / SIGNAL / REMOVE / SIDE_CHANGED
    reason_fa: str
    side: str
    signal: StrategySignal | None
    metrics: dict[str, float | str]


@dataclass
class StrategyAnalysisResult:
    """خروجی تحلیل تاریخی/تستی؛ در مسیر زنده استفاده نمی‌شود."""
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
) -> tuple[WatchCandidate | None, str, dict[str, float | str]]:
    """نشانه اولیه را نرم می‌گیرد؛ این مرحله سیگنال صادر نمی‌کند."""
    if len(candles) < 24:
        return None, "داده کندلی کافی نیست", {"تعداد_کندل": len(candles)}

    current = candles[-1]
    # baseline فقط از کندل‌های بسته‌شده گرفته می‌شود. مقایسه کندل زنده نیمه‌کاره
    # با کندل کامل، دلیل اصلی خشک‌شدن واچ‌ها بود.
    completed = [c for c in candles[:-1] if int(c.get("confirm", 1)) == 1]
    prev = completed[-17:] if len(completed) >= 17 else candles[-18:-1]
    recent_completed = completed[-5:] if len(completed) >= 5 else candles[-6:-1]
    current_range = pct_range(current)
    base_ranges = [pct_range(c) for c in prev]
    recent_ranges = [pct_range(c) for c in recent_completed]
    base_range = _safe_median(base_ranges, 1e-9) or 1e-9

    ts_ms = int(current.get("ts") or 0)
    elapsed_sec = max(1.0, min(300.0, (time.time() * 1000.0 - ts_ms) / 1000.0)) if ts_ms > 0 else 300.0
    progress = max(0.08, min(1.0, elapsed_sec / 300.0))
    # حجم تقریباً با زمان و دامنه تقریباً با ریشه زمان مقیاس می‌شود.
    projected_volume = _volume(current) / progress
    normalized_range = current_range / max(progress ** 0.5, 0.28)
    range_ratio = normalized_range / base_range
    compression_ratio = _safe_median(recent_ranges, base_range) / base_range

    base_vol = _safe_median([_volume(c) for c in prev], 1e-9) or 1e-9
    volume_ratio = projected_volume / base_vol
    flow = pre_move_flow_bias(candles)

    open_px = float(current["open"])
    close_px = float(current["close"])
    current_move = abs(close_px - open_px) / max(open_px, 1e-9) * 100.0

    # حد دیرشدن از TP ثابت پنج‌دقیقه‌ای گرفته می‌شود؛ هیچ پروفایل تاریخی دخالت ندارد.
    expected = float(config.FIXED_TP_PCT_5M)
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
        "پیشرفت_کندل": round(progress, 3),
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
    elif flow_hint and (volume_ratio >= 0.88 or range_ratio >= 0.88):
        # ورود نرم به واچ است، نه سیگنال؛ این مسیر حرکت‌های خوبی را که هنوز
        # آستانه کامل حجم/دامنه را لمس نکرده‌اند از دست نمی‌دهد.
        trigger = "فشار اولیه زودهنگام"
    elif compression_ready and (volume_ratio >= 0.82 or range_ratio >= 0.82):
        trigger = "آمادگی فشردگی بدون جهت اولیه"
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


def _trim_append(values: list[float], value: float, limit: int) -> None:
    values.append(float(value))
    if len(values) > limit:
        del values[:-limit]


def _direction_from_micro(
    trade_history: list[float],
    book_history: list[float],
    response_history: list[float],
) -> tuple[str, bool, float, str]:
    """قفل جهت با شواهد پایدار، نه الزام چند شرط کاملاً هم‌زمان.

    فشار معاملات علت اصلی است؛ پاسخ قیمت باید هم‌جهت یا دست‌کم غیرمخالف باشد.
    دفتر سفارش فقط اعتماد را تنظیم می‌کند و هرگز به‌تنهایی جهت نمی‌سازد.
    """
    trade_min = float(getattr(config, "WATCH_TRADE_IMBALANCE_MIN", 0.075))
    book_min = float(getattr(config, "WATCH_BOOK_IMBALANCE_MIN", 0.07))
    response_min = float(getattr(config, "WATCH_PRICE_RESPONSE_MIN_PCT", 0.003))
    adverse_max = float(getattr(config, "WATCH_MAX_ADVERSE_RESPONSE_PCT", 0.012))
    needed = int(getattr(config, "WATCH_MIN_CONSISTENT_SAMPLES", 2))

    if len(trade_history) < needed or not response_history:
        return "UNCERTAIN", False, 0.0, "نمونه تازه کافی برای قفل جهت نیست"

    n = max(needed, 3)
    recent_trade = trade_history[-n:]
    recent_resp = response_history[-n:]
    recent_book = book_history[-n:] if book_history else [0.0]
    avg_trade = sum(recent_trade) / len(recent_trade)
    avg_resp = sum(recent_resp) / len(recent_resp)
    avg_book = sum(recent_book) / len(recent_book)
    long_votes = sum(v >= trade_min for v in recent_trade)
    short_votes = sum(v <= -trade_min for v in recent_trade)

    long_pressure = long_votes >= needed and avg_trade >= trade_min * 0.65
    short_pressure = short_votes >= needed and avg_trade <= -trade_min * 0.65
    long_response_ok = avg_resp >= response_min * 0.45 and min(recent_resp) > -adverse_max
    short_response_ok = avg_resp <= -response_min * 0.45 and max(recent_resp) < adverse_max

    if long_pressure and long_response_ok:
        consistency = long_votes / len(recent_trade)
        confidence = 0.60 + 0.24 * consistency + min(0.09, max(0.0, avg_resp) * 6.0)
        if avg_book >= book_min:
            confidence += 0.07
        elif avg_book <= -float(getattr(config, "WATCH_STRONG_BOOK_IMBALANCE", 0.20)):
            confidence -= 0.06
        return "LONG", True, max(0.0, min(confidence, 0.97)), "فشار خرید پایدار است و قیمت خلاف آن مقاومت نکرده"
    if short_pressure and short_response_ok:
        consistency = short_votes / len(recent_trade)
        confidence = 0.60 + 0.24 * consistency + min(0.09, max(0.0, -avg_resp) * 6.0)
        if avg_book <= -book_min:
            confidence += 0.07
        elif avg_book >= float(getattr(config, "WATCH_STRONG_BOOK_IMBALANCE", 0.20)):
            confidence -= 0.06
        return "SHORT", True, max(0.0, min(confidence, 0.97)), "فشار فروش پایدار است و قیمت خلاف آن مقاومت نکرده"

    return "UNCERTAIN", False, max(0.0, min(0.58, abs(avg_trade) * 0.75 + abs(avg_resp) * 4.0)), "فشار و پاسخ قیمت هنوز توافق قابل اتکا ندارند"


def evaluate_watch(state: WatchState, snapshot: dict[str, Any], now: float | None = None) -> WatchEvaluation:
    now = now or time.time()
    age = now - state.created_at
    price = float(snapshot.get("mid_price") or snapshot.get("last_price") or 0.0)
    if price <= 0:
        return WatchEvaluation("KEEP", "قیمت معتبر دریافت نشد؛ واچ حفظ شد", state.side, None, {"سن_واچ_ثانیه": round(age, 1)})

    trade_imbalance = float(snapshot.get("trade_imbalance") or 0.0)
    book_imbalance = float(snapshot.get("book_imbalance") or 0.0)
    intensity_accel = float(snapshot.get("intensity_acceleration") or 0.0)
    newest_trade_ts = int(float(snapshot.get("newest_trade_ts") or 0.0))
    is_fresh_snapshot = newest_trade_ts <= 0 or newest_trade_ts > state.last_snapshot_trade_ts
    response_pct = (price - state.start_price) / max(state.start_price, 1e-9) * 100.0
    step_base = state.last_price if state.last_price > 0 else state.start_price
    step_response_pct = (price - step_base) / max(step_base, 1e-9) * 100.0
    displacement = abs(response_pct)

    # پاسخ مؤثر ترکیبی است: بخش اصلی از جابه‌جایی از نقطه شروع و بخش کوچک‌تر
    # از آخرین مشاهده. این کار هم شروع موج را می‌بیند و هم جلوی قفل‌شدن روی
    # یک جهش قدیمی که دیگر ادامه ندارد را می‌گیرد.
    effective_response = 0.70 * response_pct + 0.30 * step_response_pct

    hist_limit = int(getattr(config, "WATCH_DIRECTION_HISTORY", 5))
    if is_fresh_snapshot:
        _trim_append(state.trade_history, trade_imbalance, hist_limit)
        _trim_append(state.book_history, book_imbalance, hist_limit)
        _trim_append(state.response_history, effective_response, hist_limit)
        _trim_append(state.intensity_history, intensity_accel, hist_limit)
        state.last_snapshot_trade_ts = newest_trade_ts
    else:
        # داده تکراری نه تأیید است و نه رد؛ فقط واچ را نگه می‌داریم.
        state.last_price = price
        state.last_update = now
        return WatchEvaluation("KEEP", "معامله تازه‌ای از نمونه قبلی نرسیده؛ واچ بدون تغییر حفظ شد", state.side, None, {
            "سن_واچ_ثانیه": round(age, 1), "عدم_تعادل_معاملات": round(trade_imbalance, 4),
            "واکنش_قیمت_از_شروع_درصد": round(response_pct, 4), "نمونه_تازه": 0,
        })
    side, locked, confidence, lock_reason = _direction_from_micro(
        state.trade_history, state.book_history, state.response_history
    )

    state.last_price = price
    state.last_update = now

    metrics: dict[str, float | str] = {
        "سن_واچ_ثانیه": round(age, 1),
        "عدم_تعادل_معاملات": round(trade_imbalance, 4),
        "عدم_تعادل_دفتر": round(book_imbalance, 4),
        "شتاب_معاملات": round(intensity_accel, 4),
        "واکنش_قیمت_از_شروع_درصد": round(response_pct, 4),
        "واکنش_قیمت_آخرین_نمونه_درصد": round(step_response_pct, 4),
        "اعتماد_جهت": round(confidence * 100.0, 1),
        "نمونه_جهت": len(state.trade_history),
        "حد_دیرشدن_درصد": round(state.late_limit_pct, 4),
    }

    if age > float(getattr(config, "WATCH_TTL_SECONDS", 300)):
        return WatchEvaluation("REMOVE", "زمان منطقی واچ تمام شد", state.side, None, metrics)
    if displacement > state.late_limit_pct:
        return WatchEvaluation("REMOVE", "قیمت پیش از تأیید بیش‌ازحد حرکت کرد و ورود دیر شد", state.side, None, metrics)

    # تغییر جهت فقط پس از قفل پایدار جهت جدید مجاز است.
    if locked and side != "UNCERTAIN" and side != state.side and state.side != "UNCERTAIN" and not state.direction_locked:
        if state.side_changes < int(getattr(config, "WATCH_MAX_SIDE_CHANGES", 1)):
            return WatchEvaluation("SIDE_CHANGED", "چرخش پایدار فشار و پاسخ قیمت تأیید شد", side, None, metrics)
        state.bad_count += 1

    recent_trade = state.trade_history[-3:]
    recent_accel = state.intensity_history[-3:]
    avg_abs_trade = sum(abs(v) for v in recent_trade) / max(len(recent_trade), 1)
    max_accel = max(recent_accel) if recent_accel else 0.0
    strong_trade = avg_abs_trade >= float(getattr(config, "WATCH_STRONG_TRADE_IMBALANCE", 0.18))
    accelerated = max_accel >= float(getattr(config, "WATCH_INTENSITY_ACCEL_MIN", 0.08))
    micro_return = abs(float(snapshot.get("micro_return_pct") or 0.0))
    price_started = max(displacement, micro_return) >= float(getattr(config, "WATCH_MIN_START_DISPLACEMENT_PCT", 0.0015))
    # یکی از دو شاهد شدت یا شتاب کافی است؛ جهت همچنان باید جداگانه قفل شده باشد.
    start_confirmed = price_started and (strong_trade or accelerated or avg_abs_trade >= float(getattr(config, "WATCH_TRADE_IMBALANCE_MIN", 0.075)) * 1.15)

    adverse = float(getattr(config, "WATCH_MAX_ADVERSE_RESPONSE_PCT", 0.012))
    contradiction = (
        (state.side == "LONG" and response_pct < -adverse and trade_imbalance < 0)
        or (state.side == "SHORT" and response_pct > adverse and trade_imbalance > 0)
    )
    state.bad_count = state.bad_count + 1 if contradiction else max(0, state.bad_count - 1)
    if state.bad_count >= int(getattr(config, "WATCH_BAD_OBSERVATIONS_TO_REMOVE", 3)):
        return WatchEvaluation("REMOVE", "تناقض پایدار بین جهت واچ و جریان واقعی بازار", state.side, None, metrics)

    if not locked or side == "UNCERTAIN":
        # یک نمونه خنثی نباید تمام تأییدهای قبلی را نابود کند؛ شمارنده آرام
        # کم می‌شود، اما تناقض واقعی همچنان با bad_count واچ را حذف می‌کند.
        return WatchEvaluation("KEEP", f"{lock_reason}؛ واچ ادامه دارد", state.side, None, metrics)
    if not start_confirmed:
        return WatchEvaluation("KEEP", "جهت معتبر است اما شتاب شروع موج هنوز کافی نیست", side, None, metrics)

    state.side = side
    state.direction_locked = True
    state.confirm_count += 1
    strong_confirmation = strong_trade and accelerated and confidence >= 0.78 and displacement >= float(getattr(config, "WATCH_MIN_START_DISPLACEMENT_PCT", 0.002))
    needed = int(getattr(config, "WATCH_STRONG_CONFIRMATIONS_REQUIRED", 2)) if strong_confirmation else int(getattr(config, "WATCH_CONFIRMATIONS_REQUIRED", 3))
    if state.confirm_count < needed:
        return WatchEvaluation("KEEP", f"تأیید {state.confirm_count} از {needed} دریافت شد؛ نویز کوتاه حذف می‌شود", side, None, metrics)

    avg_trade = sum(state.trade_history[-3:]) / min(3, len(state.trade_history))
    avg_book = sum(state.book_history[-3:]) / min(3, len(state.book_history))
    avg_accel = sum(state.intensity_history[-3:]) / min(3, len(state.intensity_history))
    strength_score = min(100.0, 45.0 + abs(avg_trade) * 80.0 + max(avg_accel, 0.0) * 18.0 + confidence * 22.0 + abs(avg_book) * 8.0)
    strength = "خیلی قوی" if strength_score >= 82 else ("قوی" if strength_score >= 68 else "متوسط")

    signal = StrategySignal(
        symbol_id=state.symbol_id,
        okx_symbol=state.okx_symbol,
        toobit_symbol=state.toobit_symbol,
        side=side,
        entry=price,
        strength=strength,
        strength_score=round(strength_score, 2),
        compression_score=round(state.compression_score * 100.0, 2),
        flow_bias=round(avg_trade, 4),
        absorption_score=round(confidence * 100.0, 2),
        reason=(
            f"شروع موج + قفل جهت پایدار | ماشه={state.trigger} | "
            f"میانگین معاملات={avg_trade:.3f} دفتر={avg_book:.3f} پاسخ={response_pct:.4f}% تأیید={state.confirm_count}"
        ),
        diagnostic_context={
            "watch_trigger": state.trigger,
            "watch_age_seconds": round(age, 2),
            "watch_start_price": state.start_price,
            "pre_entry_displacement_pct": round(response_pct, 6),
            "late_limit_pct": round(state.late_limit_pct, 6),
            "avg_trade_imbalance": round(avg_trade, 6),
            "avg_book_imbalance": round(avg_book, 6),
            "avg_intensity_acceleration": round(avg_accel, 6),
            "direction_confidence_pct": round(confidence * 100.0, 2),
            "confirm_count": state.confirm_count,
            "side_changes": state.side_changes,
            "trade_history": [round(x, 6) for x in state.trade_history[-5:]],
            "book_history": [round(x, 6) for x in state.book_history[-5:]],
            "response_history": [round(x, 6) for x in state.response_history[-5:]],
            "intensity_history": [round(x, 6) for x in state.intensity_history[-5:]],
        },
    )
    return WatchEvaluation("SIGNAL", "شروع موج و جهت پایدار هم‌زمان تأیید شدند", side, signal, metrics)


# ---------------------------------------------------------------------------
# سازگاری با تست‌های تاریخی؛ در مسیر زنده استفاده نمی‌شود.
# ---------------------------------------------------------------------------
def analyze_symbol_detailed(symbol_id: str, okx_symbol: str, toobit_symbol: str, candles: list[dict[str, float]]) -> StrategyAnalysisResult:
    candidate, reason, details = detect_watch_candidate(candles)
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
