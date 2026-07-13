"""موتور یکپارچه UEM: جهت 1H، مرحله حرکت، ظرفیت باقی‌مانده و ورود رفتارمحور."""
from __future__ import annotations

from statistics import median
import math
import time

import config
from models import MarketCandidate, MarketSignal, MicroSnapshot, WatchState
from symbols import SymbolMap


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _atr_pct(candles: list[dict[str, float]], n: int = 14) -> float:
    values: list[float] = []
    for i in range(max(1, len(candles) - n), len(candles)):
        cur, prev = candles[i], candles[i - 1]
        tr = max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]), abs(cur["low"] - prev["close"]))
        if cur["close"] > 0:
            values.append(tr / cur["close"] * 100.0)
    return median(values) if values else 0.0


def _volume(candle: dict[str, float]) -> float:
    return max(float(candle.get("vol_quote") or candle.get("volume") or 0.0), 0.0)


def _mean_tail(values: list[float], n: int) -> float:
    tail = values[-max(1, n):]
    return sum(tail) / len(tail) if tail else 0.0


def _directional_move_pct(start: float, end: float, side: str) -> float:
    if start <= 0:
        return 0.0
    raw = (end - start) / start * 100.0
    return raw if side == "LONG" else -raw


def _phase_from_consumed(consumed: float) -> str:
    if consumed < 18:
        return "FRESH"
    if consumed < float(config.MATURE_MOVE_CONSUMED_PCT):
        return "EXPANSION"
    if consumed < float(config.EXHAUSTION_MOVE_CONSUMED_PCT):
        return "MATURE"
    return "EXHAUSTION"


def _candidate_confidence(structure_score: float, volume_ratio: float, efficiency: float) -> float:
    volume_score = _clamp((volume_ratio - 0.75) / 0.85)
    efficiency_score = _clamp(efficiency / 0.42)
    return _clamp(0.52 * structure_score + 0.28 * volume_score + 0.20 * efficiency_score)


def detect_candidate_diagnostic(sym: SymbolMap, candles: list[dict[str, float]]) -> tuple[MarketCandidate | None, str, dict[str, float | int | str | bool]]:
    closed = [c for c in candles if int(c.get("confirm", 1)) == 1]
    metrics: dict[str, float | int | str | bool] = {"closed_bars": len(closed)}
    if len(closed) < 50:
        return None, f"داده ناکافی 1H: {len(closed)}/50 کندل بسته", metrics

    recent = closed[-12:]
    base = closed[-36:-12]
    last = recent[-1]
    atr = _atr_pct(closed)
    metrics["atr_pct"] = atr
    if atr <= 0:
        return None, "ATR یک‌ساعته صفر یا نامعتبر است", metrics

    recent_high = max(c["high"] for c in recent[:-1])
    recent_low = min(c["low"] for c in recent[:-1])
    older_high = max(c["high"] for c in base)
    older_low = min(c["low"] for c in base)
    highs_rising = max(c["high"] for c in recent[-6:]) >= max(c["high"] for c in recent[:6])
    lows_rising = min(c["low"] for c in recent[-6:]) >= min(c["low"] for c in recent[:6])
    highs_falling = max(c["high"] for c in recent[-6:]) <= max(c["high"] for c in recent[:6])
    lows_falling = min(c["low"] for c in recent[-6:]) <= min(c["low"] for c in recent[:6])

    vol_base = median([_volume(c) for c in base]) or 1.0
    vol_recent = median([_volume(c) for c in recent[-4:]])
    volume_ratio = vol_recent / vol_base if vol_base > 0 else 0.0
    close = float(last["close"])
    total_range = max(sum(c["high"] - c["low"] for c in recent[-6:]), 1e-12)
    efficiency = abs(recent[-1]["close"] - recent[-6]["open"]) / total_range

    side = ""
    level = 0.0
    invalidation = 0.0
    reason = ""
    structure_score = 0.0
    origin = float(recent[-4]["open"])

    long_near = close >= recent_high * (1 - atr * 0.003)
    short_near = close <= recent_low * (1 + atr * 0.003)
    if highs_rising and lows_rising and long_near:
        side, level = "LONG", recent_high
        invalidation = min(c["low"] for c in recent[-5:])
        origin = min(float(c["low"]) for c in recent[-4:])
        structure_score = 0.78
        reason = "ساختار 1H سقف و کف بالاتر دارد و قیمت نزدیک گسترش صعودی است"
    elif highs_falling and lows_falling and short_near:
        side, level = "SHORT", recent_low
        invalidation = max(c["high"] for c in recent[-5:])
        origin = max(float(c["high"]) for c in recent[-4:])
        structure_score = 0.78
        reason = "ساختار 1H سقف و کف پایین‌تر دارد و قیمت نزدیک گسترش نزولی است"
    elif close > older_high and volume_ratio >= 0.85:
        side, level = "LONG", older_high
        invalidation = recent_low
        origin = min(float(c["low"]) for c in recent[-4:])
        structure_score = 0.88
        reason = "شکست و پذیرش صعودی ساختار 1H مشاهده شد"
    elif close < older_low and volume_ratio >= 0.85:
        side, level = "SHORT", older_low
        invalidation = recent_high
        origin = max(float(c["high"]) for c in recent[-4:])
        structure_score = 0.88
        reason = "شکست و پذیرش نزولی ساختار 1H مشاهده شد"
    else:
        failures: list[str] = []
        if not (highs_rising and lows_rising): failures.append("ساختار صعودی کامل نیست")
        if not long_near: failures.append("قیمت به ناحیه گسترش صعودی نزدیک نیست")
        if not (highs_falling and lows_falling): failures.append("ساختار نزولی کامل نیست")
        if not short_near: failures.append("قیمت به ناحیه گسترش نزولی نزدیک نیست")
        if not (close > older_high or close < older_low): failures.append("شکست معتبر سقف/کف مبنا رخ نداده")
        elif volume_ratio < 0.85: failures.append(f"حجم شکست ضعیف است ratio={volume_ratio:.3f}<0.850")
        metrics.update({"volume_ratio": volume_ratio, "efficiency": efficiency})
        return None, "؛ ".join(failures), metrics

    stop_pct = abs(close - invalidation) / close * 100.0 if close > 0 else 0.0
    if stop_pct <= 0:
        return None, "فاصله ابطال ساختاری صفر یا نامعتبر است", metrics
    if stop_pct > atr * 1.8:
        return None, f"استاپ خام بیش‌ازحد بزرگ است: {stop_pct:.4f}% > {atr*1.8:.4f}% (1.8 ATR)", metrics

    expected = atr * (1.45 + 0.55 * _clamp(efficiency / 0.38))
    consumed = _clamp(_directional_move_pct(origin, close, side) / max(expected, 1e-9), 0.0, 1.5) * 100.0
    confidence = _candidate_confidence(structure_score, volume_ratio, efficiency)
    phase = _phase_from_consumed(consumed)
    metrics.update({
        "side": side, "structure_level": level, "invalidation": invalidation,
        "raw_stop_pct": stop_pct, "volume_ratio": volume_ratio, "efficiency": efficiency,
        "expected_move_pct": expected, "move_origin": origin, "consumed_pct": consumed,
        "direction_confidence": confidence, "phase": phase,
    })
    if confidence < float(config.MIN_DIRECTION_CONFIDENCE):
        return None, f"اطمینان جهت کافی نیست: {confidence:.3f}<{config.MIN_DIRECTION_CONFIDENCE:.3f}", metrics
    if consumed >= float(config.EXHAUSTION_MOVE_CONSUMED_PCT):
        return None, f"حرکت 1H در مرحله فرسودگی است: مصرف {consumed:.1f}%", metrics

    return MarketCandidate(
        sym.id, sym.okx, sym.toobit, side, int(time.time()), level, invalidation,
        atr, expected, reason, "1H", close, origin, consumed, confidence, phase,
    ), reason, metrics


def detect_candidate(sym: SymbolMap, candles: list[dict[str, float]]) -> MarketCandidate | None:
    return detect_candidate_diagnostic(sym, candles)[0]


def detect_impulse_candidate_diagnostic(sym: SymbolMap, candles_5m: list[dict[str, float]], atr_1h_pct: float) -> tuple[MarketCandidate | None, str, dict[str, float | int | str | bool]]:
    closed = [c for c in candles_5m if int(c.get("confirm", 1)) == 1]
    metrics: dict[str, float | int | str | bool] = {"closed_5m": len(closed), "atr_1h_pct": atr_1h_pct}
    need = max(20, int(config.IMPULSE_LOOKBACK_BARS) + 10)
    if len(closed) < need:
        return None, f"داده 5m ناکافی: {len(closed)}/{need}", metrics

    n = int(config.IMPULSE_LOOKBACK_BARS)
    recent = closed[-n:]
    prior = closed[-(n + 18):-n]
    start = float(recent[0]["open"])
    end = float(recent[-1]["close"])
    raw_move = (end - start) / start * 100.0 if start > 0 else 0.0
    side = "LONG" if raw_move > 0 else "SHORT"
    directional_move = abs(raw_move)
    min_move = max(float(config.IMPULSE_MIN_MOVE_PCT), float(atr_1h_pct) * float(config.IMPULSE_MIN_MOVE_ATR))
    directional_bars = sum(1 for c in recent if (c["close"] > c["open"]) == (side == "LONG"))
    base_vol = median([_volume(c) for c in prior]) or 1.0
    recent_vol = median([_volume(c) for c in recent])
    volume_ratio = recent_vol / base_vol if base_vol > 0 else 0.0
    total_range = max(sum(float(c["high"] - c["low"]) for c in recent), 1e-12)
    efficiency = abs(end - start) / total_range

    failures: list[str] = []
    if directional_move < min_move: failures.append(f"حرکت 5m کافی نیست {directional_move:.4f}%<{min_move:.4f}%")
    if directional_bars < int(config.IMPULSE_MIN_DIRECTIONAL_BARS): failures.append(f"پایداری جهت کم است {directional_bars}<{config.IMPULSE_MIN_DIRECTIONAL_BARS}")
    if volume_ratio < float(config.IMPULSE_MIN_VOLUME_RATIO): failures.append(f"حجم پامپ/دامپ کافی نیست {volume_ratio:.3f}<{config.IMPULSE_MIN_VOLUME_RATIO:.3f}")
    if efficiency < 0.34: failures.append(f"حرکت 5m پرنویز است efficiency={efficiency:.3f}<0.340")
    metrics.update({"move_pct": raw_move, "directional_bars": directional_bars, "volume_ratio": volume_ratio, "efficiency": efficiency, "side": side})
    if failures:
        return None, "؛ ".join(failures), metrics

    if side == "LONG":
        level = max(float(c["high"]) for c in recent[-3:-1])
        invalidation = min(float(c["low"]) for c in recent[-4:])
    else:
        level = min(float(c["low"]) for c in recent[-3:-1])
        invalidation = max(float(c["high"]) for c in recent[-4:])
    stop_pct = abs(end - invalidation) / end * 100.0 if end > 0 else 0.0
    max_stop = max(float(atr_1h_pct) * 1.35, min_move * 1.6)
    if stop_pct <= 0 or stop_pct > max_stop:
        return None, f"ابطال موج 5m نامناسب است stop={stop_pct:.4f}% max={max_stop:.4f}%", metrics

    expected = max(float(atr_1h_pct) * 1.20, directional_move * (1.30 if efficiency >= 0.55 else 1.12))
    consumed = _clamp(directional_move / max(expected, 1e-9), 0.0, 1.5) * 100.0
    confidence = _candidate_confidence(0.76, volume_ratio, efficiency)
    phase = _phase_from_consumed(consumed)
    metrics.update({"expected_move_pct": expected, "consumed_pct": consumed, "direction_confidence": confidence, "phase": phase})
    if consumed >= float(config.EXHAUSTION_MOVE_CONSUMED_PCT):
        return None, f"پامپ/دامپ 5m بخش عمده ظرفیت را مصرف کرده: {consumed:.1f}%", metrics
    if confidence < float(config.MIN_DIRECTION_CONFIDENCE):
        return None, f"اطمینان موج 5m کافی نیست: {confidence:.3f}", metrics

    reason = f"{'پامپ' if side=='LONG' else 'دامپ'} 5m تازه و کارا: حرکت {raw_move:+.3f}%، حجم {volume_ratio:.2f}x، کارایی {efficiency:.2f}"
    return MarketCandidate(
        sym.id, sym.okx, sym.toobit, side, int(time.time()), level, invalidation,
        atr_1h_pct, expected, reason, "IMPULSE_5M", end, start, consumed, confidence, phase,
    ), reason, metrics


def _flow_diagnostics(candidate: MarketCandidate, state: WatchState, snapshot: MicroSnapshot) -> dict[str, float | int | str | bool]:
    sign = 1.0 if candidate.side == "LONG" else -1.0
    window = min(int(config.FLOW_WINDOW), len(state.prices))
    trade = sign * _mean_tail(state.trade_values, window)
    book = sign * _mean_tail(state.book_values, window)
    micro = sign * _mean_tail(state.micro_values, window)

    start_price = state.prices[-window] if window else snapshot.last
    directional_price = _directional_move_pct(start_price, snapshot.last, candidate.side)
    price_impact_atr = directional_price / max(candidate.atr_pct, 1e-9)
    pressure = max(abs(trade), 0.04)
    impact_efficiency = max(0.0, price_impact_atr) / pressure

    half = max(2, window // 2)
    early_trade = sign * _mean_tail(state.trade_values[:-half] or state.trade_values, half)
    recent_trade = sign * _mean_tail(state.trade_values, half)
    if len(state.prices) >= half * 2:
        early_move = _directional_move_pct(state.prices[-half * 2], state.prices[-half], candidate.side)
        late_move = _directional_move_pct(state.prices[-half], state.prices[-1], candidate.side)
    else:
        early_move = late_move = directional_price

    pressure_rising = recent_trade > early_trade + 0.025
    impact_fading = late_move < max(early_move * 0.55, candidate.atr_pct * 0.006)
    no_price_response = directional_price < candidate.atr_pct * float(config.MIN_PRICE_IMPACT_ATR)
    absorption = _clamp(
        (0.48 if trade >= config.MIN_ABS_TRADE_IMBALANCE and no_price_response else 0.0)
        + (0.34 if pressure_rising and impact_fading else 0.0)
        + (0.18 if micro < 0 else 0.0)
    )

    move_since_detection = _directional_move_pct(candidate.detected_price or candidate.structure_level, snapshot.last, candidate.side)
    consumed = max(0.0, candidate.consumed_at_detection_pct + move_since_detection / max(candidate.expected_move_pct, 1e-9) * 100.0)
    remaining_capacity = max(0.0, candidate.expected_move_pct * (1.0 - min(consumed, 100.0) / 100.0))
    phase = _phase_from_consumed(consumed)

    age = max(0.0, time.time() - state.started_at)
    fast_accept = (
        trade >= float(config.FAST_ACCEPTANCE_TRADE_IMBALANCE)
        and micro >= float(config.MICROPRICE_MIN_BIAS_PCT) * float(config.FAST_ACCEPTANCE_MICRO_MULTIPLIER)
        and price_impact_atr >= float(config.MIN_PRICE_IMPACT_ATR) * 1.5
        and age >= float(config.FAST_ACCEPTANCE_SECONDS)
    )
    normal_accept = age >= float(config.NORMAL_ACCEPTANCE_SECONDS)
    accepted = state.break_seen_count >= 2 and (normal_accept or fast_accept) and state.reclaim_count <= int(config.MAX_RECLAIM_COUNT)

    flow_score = _clamp((trade - config.MIN_ABS_TRADE_IMBALANCE) / 0.28)
    micro_score = _clamp((micro - config.MICROPRICE_MIN_BIAS_PCT) / 0.018)
    impact_score = _clamp((impact_efficiency - config.MIN_PRICE_IMPACT_EFFICIENCY) / 0.20)
    freshness = _clamp((100.0 - consumed) / 65.0)
    acceptance_score = 1.0 if accepted else 0.0
    book_score = _clamp((book + 0.04) / 0.30)

    continuation = _clamp(
        0.24 * candidate.direction_confidence
        + 0.21 * flow_score
        + 0.17 * micro_score
        + 0.19 * impact_score
        + 0.11 * freshness
        + 0.08 * acceptance_score
        + float(config.BOOK_WEIGHT_IN_SCORE) * book_score
    )
    exhaustion = _clamp((consumed - 48.0) / 42.0)
    reclaim_risk = _clamp(state.reclaim_count / 2.0)
    reversal = _clamp(0.44 * absorption + 0.28 * exhaustion + 0.18 * reclaim_risk + 0.10 * (1.0 - candidate.direction_confidence))

    return {
        "aligned_trade": trade, "aligned_book": book, "aligned_micro": micro,
        "directional_price_pct": directional_price, "price_impact_atr": price_impact_atr,
        "impact_efficiency": impact_efficiency, "absorption_risk": absorption,
        "move_consumed_pct": consumed, "remaining_capacity_pct": remaining_capacity,
        "phase": phase, "accepted": accepted, "age_seconds": age,
        "continuation_probability": continuation, "reversal_probability": reversal,
        "scenario_gap": continuation - reversal,
        "pressure_rising": pressure_rising, "impact_fading": impact_fading,
    }


def update_watch_state(state: WatchState, snapshot: MicroSnapshot) -> tuple[str, str, dict[str, float | int | str | bool]]:
    c = state.candidate
    sign = 1.0 if c.side == "LONG" else -1.0
    state.append_snapshot(snapshot.last, snapshot.trade_imbalance, snapshot.book_imbalance, snapshot.microprice_bias_pct, int(config.WATCH_HISTORY_SIZE))
    aligned_trade = sign * _mean_tail(state.trade_values, 3)
    aligned_micro = sign * _mean_tail(state.micro_values, 3)
    opposite = aligned_trade <= -config.MIN_ABS_TRADE_IMBALANCE and aligned_micro < 0
    aligned = aligned_trade >= config.MIN_ABS_TRADE_IMBALANCE and aligned_micro >= 0
    state.opposite_pressure_count = state.opposite_pressure_count + 1 if opposite else 0
    state.aligned_pressure_count = state.aligned_pressure_count + 1 if aligned else 0

    crossed = snapshot.last >= c.structure_level if c.side == "LONG" else snapshot.last <= c.structure_level
    state.break_seen_count = state.break_seen_count + 1 if crossed else 0
    state.reclaim_count = state.reclaim_count + 1 if not crossed and len(state.prices) >= 2 else max(0, state.reclaim_count - 1)

    invalidation_buffer = c.atr_pct * float(config.WATCH_INVALIDATION_ATR_BUFFER) / 100.0
    invalidated = snapshot.last <= c.invalidation_price * (1 - invalidation_buffer) if c.side == "LONG" else snapshot.last >= c.invalidation_price * (1 + invalidation_buffer)
    diag = _flow_diagnostics(c, state, snapshot)
    metrics = {"side": c.side, "source": c.source, "last": snapshot.last, "level": c.structure_level,
               "invalidation": c.invalidation_price, "opposite_count": state.opposite_pressure_count,
               "aligned_count": state.aligned_pressure_count, "break_count": state.break_seen_count,
               "reclaim_count": state.reclaim_count, "invalidated": invalidated, **diag}

    if invalidated:
        return "REANALYZE", "سناریوی فعلی از نقطه ابطال عبور کرد", metrics
    if state.opposite_pressure_count >= int(config.WATCH_OPPOSITE_CONFIRMATIONS) and diag["reversal_probability"] >= config.MAX_REVERSAL_PROBABILITY:
        return "REANALYZE", "فشار مخالف پایدار و سناریوی برگشت قوی شد", metrics
    if float(diag["move_consumed_pct"]) >= float(config.EXHAUSTION_MOVE_CONSUMED_PCT):
        return "REANALYZE", "حرکت وارد مرحله فرسودگی شد و ورود تعقیبی ممنوع است", metrics
    return "CONTINUE", "سناریو هنوز قابل بررسی است", metrics


def confirm_signal_diagnostic(candidate: MarketCandidate, snapshot: MicroSnapshot, state: WatchState | None = None) -> tuple[MarketSignal | None, str, dict[str, float | int | str | bool]]:
    if state is None:
        state = WatchState(candidate.symbol_id, candidate.okx_symbol, candidate.toobit_symbol, time.time(), candidate)
        state.append_snapshot(snapshot.last, snapshot.trade_imbalance, snapshot.book_imbalance, snapshot.microprice_bias_pct)
    diag = _flow_diagnostics(candidate, state, snapshot)
    sign = 1.0 if candidate.side == "LONG" else -1.0
    level_crossed = snapshot.last >= candidate.structure_level if candidate.side == "LONG" else snapshot.last <= candidate.structure_level
    trade_value = float(diag["aligned_trade"])
    book_value = float(diag["aligned_book"])
    micro_value = float(diag["aligned_micro"])
    chase_pct = abs(snapshot.last - candidate.structure_level) / snapshot.last * 100.0 if snapshot.last > 0 else float("inf")
    chase_limit = candidate.atr_pct * config.MAX_ENTRY_CHASE_ATR

    metrics: dict[str, float | int | str | bool] = {
        "side": candidate.side, "source": candidate.source, "last": snapshot.last,
        "spread_pct": snapshot.spread_pct, "spread_limit_pct": config.MAX_SPREAD_PCT,
        "level": candidate.structure_level, "level_crossed": level_crossed,
        "chase_pct": chase_pct, "chase_limit_pct": chase_limit,
        "history_size": len(state.prices), "direction_confidence": candidate.direction_confidence,
        **diag,
    }
    failures: list[str] = []
    if snapshot.last <= 0: failures.append("قیمت لحظه‌ای نامعتبر یا صفر است")
    if snapshot.spread_pct > config.MAX_SPREAD_PCT: failures.append(f"اسپرد زیاد است {snapshot.spread_pct:.5f}%>{config.MAX_SPREAD_PCT:.5f}%")
    if len(state.prices) < int(config.MIN_ENTRY_HISTORY): failures.append(f"تاریخچه ورود ناکافی است {len(state.prices)}/{config.MIN_ENTRY_HISTORY}")
    if not level_crossed: failures.append("سطح ساختاری هنوز عبور نکرده")
    if not bool(diag["accepted"]): failures.append("شکست هنوز پذیرش زمانی/رفتاری کافی ندارد")
    if chase_pct > chase_limit: failures.append(f"ورود دیر شده؛ فاصله از سطح {chase_pct:.5f}%>{chase_limit:.5f}%")
    if trade_value < config.MIN_ABS_TRADE_IMBALANCE: failures.append(f"جریان معاملات هم‌جهت کافی نیست {trade_value:+.3f}")
    if micro_value < config.MICROPRICE_MIN_BIAS_PCT: failures.append(f"Microprice هم‌جهت کافی نیست {micro_value:+.5f}%")
    if float(diag["impact_efficiency"]) < float(config.MIN_PRICE_IMPACT_EFFICIENCY): failures.append(f"فشار روی قیمت اثر کافی ندارد efficiency={diag['impact_efficiency']:.3f}")
    if float(diag["absorption_risk"]) >= float(config.MAX_ABSORPTION_RISK): failures.append(f"ریسک جذب/فرسودگی زیاد است {diag['absorption_risk']:.2f}")
    if float(diag["move_consumed_pct"]) > float(config.MAX_MOVE_CONSUMED_PCT): failures.append(f"بخش زیادی از حرکت مصرف شده {diag['move_consumed_pct']:.1f}%")
    if float(diag["remaining_capacity_pct"]) < candidate.atr_pct * float(config.MIN_REMAINING_CAPACITY_ATR): failures.append(f"ظرفیت باقی‌مانده کم است {diag['remaining_capacity_pct']:.4f}%")
    if float(diag["continuation_probability"]) < float(config.MIN_CONTINUATION_PROBABILITY): failures.append(f"احتمال ادامه کافی نیست {diag['continuation_probability']:.2f}")
    if float(diag["reversal_probability"]) > float(config.MAX_REVERSAL_PROBABILITY): failures.append(f"احتمال برگشت زیاد است {diag['reversal_probability']:.2f}")
    if float(diag["scenario_gap"]) < float(config.MIN_SCENARIO_PROBABILITY_GAP): failures.append(f"برتری سناریوی ادامه واضح نیست gap={diag['scenario_gap']:.2f}")
    if not (book_value >= -0.18 or trade_value >= 0.30): failures.append(f"تضاد شدید دفتر سفارش بدون جریان اجرایی جبران‌کننده book={book_value:+.3f}")
    if failures:
        return None, "؛ ".join(failures), metrics

    continuation = float(diag["continuation_probability"])
    if continuation >= 0.78 and float(diag["absorption_risk"]) <= 0.20:
        strength = "بسیار قوی"
    elif continuation >= 0.70:
        strength = "قوی"
    else:
        strength = "متوسط"

    # Order flow فقط زمان ورود را تأیید می‌کند؛ TP از ظرفیت مستقل باقی‌مانده می‌آید.
    remaining_move = float(diag["remaining_capacity_pct"])
    entry = snapshot.ask if candidate.side == "LONG" else snapshot.bid
    sig = MarketSignal(
        candidate.symbol_id, candidate.okx_symbol, candidate.toobit_symbol, candidate.side,
        entry, candidate.invalidation_price, candidate.atr_pct, remaining_move, strength,
        candidate.direction_reason,
        f"ادامه {continuation:.0%} در برابر برگشت {float(diag['reversal_probability']):.0%}",
        f"مرحله {diag['phase']} | مصرف {float(diag['move_consumed_pct']):.1f}% | اثر فشار {float(diag['impact_efficiency']):.3f}",
        snapshot.spread_pct, snapshot.trade_imbalance, snapshot.book_imbalance, snapshot.microprice_bias_pct,
        str(diag["phase"]), float(diag["move_consumed_pct"]), remaining_move,
        continuation, float(diag["reversal_probability"]), float(diag["absorption_risk"]), float(diag["impact_efficiency"]),
    )
    metrics.update({"strength": strength, "expected_move_pct": remaining_move})
    return sig, "جهت، مرحله، ظرفیت و ورود مستقل هم‌زمان تأیید شدند", metrics


def confirm_signal(candidate: MarketCandidate, snapshot: MicroSnapshot) -> MarketSignal | None:
    return confirm_signal_diagnostic(candidate, snapshot)[0]
