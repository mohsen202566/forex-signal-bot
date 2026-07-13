"""موتور رفتارمحور: ساختار 1H، تشخیص پامپ/دامپ 5m و واچ تطبیقی."""
from __future__ import annotations
from statistics import median
import time
import config
from models import MarketCandidate, MarketSignal, MicroSnapshot, WatchState
from symbols import SymbolMap


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
    volume_ok = volume_ratio >= 0.85
    close = float(last["close"])
    long_near = close >= recent_high * (1 - atr * 0.003)
    short_near = close <= recent_low * (1 + atr * 0.003)
    metrics.update({"close":close,"recent_high":recent_high,"recent_low":recent_low,"older_high":older_high,"older_low":older_low,
                    "volume_ratio":volume_ratio,"highs_rising":highs_rising,"lows_rising":lows_rising,
                    "highs_falling":highs_falling,"lows_falling":lows_falling,"long_near":long_near,"short_near":short_near})
    side = ""; level = 0.0; invalidation = 0.0; reason = ""
    if highs_rising and lows_rising and long_near:
        side, level = "LONG", recent_high; invalidation = min(c["low"] for c in recent[-5:])
        reason = "ساختار 1H سقف و کف بالاتر دارد و قیمت نزدیک گسترش صعودی است"
    elif highs_falling and lows_falling and short_near:
        side, level = "SHORT", recent_low; invalidation = max(c["high"] for c in recent[-5:])
        reason = "ساختار 1H سقف و کف پایین‌تر دارد و قیمت نزدیک گسترش نزولی است"
    elif close > older_high and volume_ok:
        side, level = "LONG", older_high; invalidation = recent_low
        reason = "شکست و پذیرش صعودی ساختار 1H مشاهده شد"
    elif close < older_low and volume_ok:
        side, level = "SHORT", older_low; invalidation = recent_high
        reason = "شکست و پذیرش نزولی ساختار 1H مشاهده شد"
    else:
        failures: list[str] = []
        if not (highs_rising and lows_rising): failures.append("ساختار صعودی کامل نیست")
        if not long_near: failures.append("قیمت به ناحیه گسترش صعودی نزدیک نیست")
        if not (highs_falling and lows_falling): failures.append("ساختار نزولی کامل نیست")
        if not short_near: failures.append("قیمت به ناحیه گسترش نزولی نزدیک نیست")
        if not (close > older_high or close < older_low): failures.append("شکست معتبر سقف/کف مبنا رخ نداده")
        elif not volume_ok: failures.append(f"حجم شکست ضعیف است ratio={volume_ratio:.3f}<0.850")
        return None, "؛ ".join(failures), metrics
    stop_pct = abs(close - invalidation) / close * 100.0 if close > 0 else 0.0
    max_stop_pct = atr * 1.8
    metrics.update({"side":side,"structure_level":level,"invalidation":invalidation,"raw_stop_pct":stop_pct,"max_raw_stop_pct":max_stop_pct})
    if stop_pct <= 0: return None, "فاصله ابطال ساختاری صفر یا نامعتبر است", metrics
    if stop_pct > max_stop_pct: return None, f"استاپ خام بیش‌ازحد بزرگ است: {stop_pct:.4f}% > {max_stop_pct:.4f}% (1.8 ATR)", metrics
    total_range = max(sum(c["high"] - c["low"] for c in recent), 1e-12)
    efficiency = abs(recent[-1]["close"] - recent[0]["open"]) / total_range
    expected = atr * (1.55 if efficiency < 0.22 else 2.05)
    metrics.update({"efficiency":efficiency,"expected_move_pct":expected})
    return MarketCandidate(sym.id,sym.okx,sym.toobit,side,int(time.time()),level,invalidation,atr,expected,reason,"1H"), reason, metrics


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
    prior = closed[-(n+18):-n]
    start = float(recent[0]["open"]); end = float(recent[-1]["close"])
    move_pct = (end - start) / start * 100.0 if start > 0 else 0.0
    min_move = max(float(config.IMPULSE_MIN_MOVE_PCT), float(atr_1h_pct) * float(config.IMPULSE_MIN_MOVE_ATR))
    up_bars = sum(1 for c in recent if c["close"] > c["open"])
    down_bars = sum(1 for c in recent if c["close"] < c["open"])
    base_vol = median([_volume(c) for c in prior]) or 1.0
    recent_vol = median([_volume(c) for c in recent])
    volume_ratio = recent_vol / base_vol if base_vol > 0 else 0.0
    side = "LONG" if move_pct > 0 else "SHORT"
    directional_bars = up_bars if side == "LONG" else down_bars
    metrics.update({"move_pct":move_pct,"min_move_pct":min_move,"up_bars":up_bars,"down_bars":down_bars,
                    "directional_bars":directional_bars,"volume_ratio":volume_ratio,"side":side})
    failures: list[str] = []
    if abs(move_pct) < min_move: failures.append(f"حرکت 5m کافی نیست {abs(move_pct):.4f}%<{min_move:.4f}%")
    if directional_bars < int(config.IMPULSE_MIN_DIRECTIONAL_BARS): failures.append(f"پایداری جهت کم است {directional_bars}<{config.IMPULSE_MIN_DIRECTIONAL_BARS}")
    if volume_ratio < float(config.IMPULSE_MIN_VOLUME_RATIO): failures.append(f"حجم پامپ/دامپ کافی نیست {volume_ratio:.3f}<{config.IMPULSE_MIN_VOLUME_RATIO:.3f}")
    if failures: return None, "؛ ".join(failures), metrics
    if side == "LONG":
        level = max(float(c["high"]) for c in recent[-3:-1])
        invalidation = min(float(c["low"]) for c in recent[-4:])
        reason = f"پامپ 5m پایدار: حرکت {move_pct:+.3f}% با حجم {volume_ratio:.2f} برابر مبنا"
    else:
        level = min(float(c["low"]) for c in recent[-3:-1])
        invalidation = max(float(c["high"]) for c in recent[-4:])
        reason = f"دامپ 5m پایدار: حرکت {move_pct:+.3f}% با حجم {volume_ratio:.2f} برابر مبنا"
    stop_pct = abs(end - invalidation) / end * 100.0 if end > 0 else 0.0
    max_stop = max(float(atr_1h_pct) * 1.35, min_move * 1.6)
    metrics.update({"structure_level":level,"invalidation":invalidation,"raw_stop_pct":stop_pct,"max_stop_pct":max_stop})
    if stop_pct <= 0 or stop_pct > max_stop:
        return None, f"ابطال موج 5m نامناسب است stop={stop_pct:.4f}% max={max_stop:.4f}%", metrics
    expected = max(abs(move_pct) * 1.15, float(atr_1h_pct) * 1.25)
    return MarketCandidate(sym.id,sym.okx,sym.toobit,side,int(time.time()),level,invalidation,atr_1h_pct,expected,reason,"IMPULSE_5M"), reason, metrics


def _mean_tail(values: list[float], n: int = 3) -> float:
    tail = values[-n:]
    return sum(tail) / len(tail) if tail else 0.0


def update_watch_state(state: WatchState, snapshot: MicroSnapshot) -> tuple[str, str, dict[str, float | int | str | bool]]:
    c = state.candidate
    sign = 1.0 if c.side == "LONG" else -1.0
    state.append_snapshot(snapshot.last, snapshot.trade_imbalance, snapshot.book_imbalance, snapshot.microprice_bias_pct, int(config.WATCH_HISTORY_SIZE))
    aligned_trade = sign * _mean_tail(state.trade_values, 3)
    aligned_book = sign * _mean_tail(state.book_values, 3)
    aligned_micro = sign * _mean_tail(state.micro_values, 3)
    opposite = aligned_trade <= -config.MIN_ABS_TRADE_IMBALANCE and aligned_micro < 0
    aligned = aligned_trade >= config.MIN_ABS_TRADE_IMBALANCE and aligned_micro >= 0
    state.opposite_pressure_count = state.opposite_pressure_count + 1 if opposite else 0
    state.aligned_pressure_count = state.aligned_pressure_count + 1 if aligned else 0
    crossed = snapshot.last >= c.structure_level if c.side == "LONG" else snapshot.last <= c.structure_level
    state.break_seen_count = state.break_seen_count + 1 if crossed else 0
    invalidation_buffer = c.atr_pct * float(config.WATCH_INVALIDATION_ATR_BUFFER) / 100.0
    invalidated = snapshot.last <= c.invalidation_price * (1 - invalidation_buffer) if c.side == "LONG" else snapshot.last >= c.invalidation_price * (1 + invalidation_buffer)
    adverse_move_pct = 0.0
    if state.prices:
        anchor = state.prices[0]
        adverse_move_pct = ((anchor - snapshot.last) / anchor * 100.0) if c.side == "LONG" else ((snapshot.last - anchor) / anchor * 100.0)
    reversal_move = adverse_move_pct >= c.atr_pct * float(config.WATCH_REVERSAL_MOVE_ATR)
    metrics = {"side":c.side,"source":c.source,"last":snapshot.last,"level":c.structure_level,"invalidation":c.invalidation_price,
               "aligned_trade_3":aligned_trade,"aligned_book_3":aligned_book,"aligned_micro_3":aligned_micro,
               "opposite_count":state.opposite_pressure_count,"aligned_count":state.aligned_pressure_count,
               "break_count":state.break_seen_count,"invalidated":invalidated,"adverse_move_pct":adverse_move_pct,"reversal_move":reversal_move}
    if invalidated:
        return "REANALYZE", "سناریوی فعلی از نقطه ابطال عبور کرد", metrics
    if state.opposite_pressure_count >= int(config.WATCH_OPPOSITE_CONFIRMATIONS) and reversal_move:
        return "REANALYZE", "فشار پایدار خلاف جهت همراه حرکت معکوس معنادار دیده شد", metrics
    return "CONTINUE", "سناریو هنوز قابل بررسی است", metrics


def confirm_signal_diagnostic(candidate: MarketCandidate, snapshot: MicroSnapshot, state: WatchState | None = None) -> tuple[MarketSignal | None, str, dict[str, float | int | str | bool]]:
    sign = 1.0 if candidate.side == "LONG" else -1.0
    trade_value = sign * snapshot.trade_imbalance
    book_value = sign * snapshot.book_imbalance
    micro_value = sign * snapshot.microprice_bias_pct
    if state is not None and len(state.trade_values) >= 2:
        trade_value = sign * _mean_tail(state.trade_values, 3)
        book_value = sign * _mean_tail(state.book_values, 3)
        micro_value = sign * _mean_tail(state.micro_values, 3)
    trade_aligned = trade_value >= config.MIN_ABS_TRADE_IMBALANCE
    book_aligned = book_value >= config.MIN_ABS_BOOK_IMBALANCE
    micro_aligned = micro_value >= config.MICROPRICE_MIN_BIAS_PCT
    level_crossed = snapshot.last >= candidate.structure_level if candidate.side == "LONG" else snapshot.last <= candidate.structure_level
    persistent_break = state.break_seen_count >= 2 if state is not None else level_crossed
    chase_pct = abs(snapshot.last - candidate.structure_level) / snapshot.last * 100.0 if snapshot.last > 0 else float("inf")
    chase_limit = candidate.atr_pct * config.MAX_ENTRY_CHASE_ATR
    metrics: dict[str, float | int | str | bool] = {"side":candidate.side,"source":candidate.source,"last":snapshot.last,"bid":snapshot.bid,"ask":snapshot.ask,
        "spread_pct":snapshot.spread_pct,"spread_limit_pct":config.MAX_SPREAD_PCT,"trade_imbalance":snapshot.trade_imbalance,"trade_aligned_value":trade_value,
        "trade_min":config.MIN_ABS_TRADE_IMBALANCE,"book_imbalance":snapshot.book_imbalance,"book_aligned_value":book_value,"book_min":config.MIN_ABS_BOOK_IMBALANCE,
        "micro_bias_pct":snapshot.microprice_bias_pct,"micro_aligned_value":micro_value,"micro_min_pct":config.MICROPRICE_MIN_BIAS_PCT,
        "level":candidate.structure_level,"level_crossed":level_crossed,"persistent_break":persistent_break,"chase_pct":chase_pct,"chase_limit_pct":chase_limit}
    if snapshot.last <= 0: return None, "قیمت لحظه‌ای نامعتبر یا صفر است", metrics
    if snapshot.spread_pct > config.MAX_SPREAD_PCT: return None, f"اسپرد زیاد است: {snapshot.spread_pct:.5f}% > {config.MAX_SPREAD_PCT:.5f}%", metrics
    if chase_pct > chase_limit: return None, f"ورود دیر شده: فاصله از سطح {chase_pct:.5f}% > حد {chase_limit:.5f}%", metrics
    failures: list[str] = []
    if not level_crossed: failures.append(f"سطح ساختاری هنوز عبور نکرده last={snapshot.last:.8g} level={candidate.structure_level:.8g}")
    elif not persistent_break: failures.append("عبور سطح هنوز در دو بررسی متوالی حفظ نشده")
    if not trade_aligned: failures.append(f"جریان معاملات پایدار هم‌جهت کافی نیست {trade_value:+.3f}<{config.MIN_ABS_TRADE_IMBALANCE:.3f}")
    if not micro_aligned: failures.append(f"Microprice پایدار هم‌جهت کافی نیست {micro_value:+.5f}%<{config.MICROPRICE_MIN_BIAS_PCT:.5f}%")
    if failures: return None, "؛ ".join(failures), metrics
    if not book_aligned and trade_value < 0.24:
        return None, f"دفتر سفارش هم‌جهت نیست {book_value:+.3f} و جریان جایگزین نیز ضعیف است {trade_value:.3f}<0.240", metrics
    aligned_count = sum((trade_aligned,book_aligned,micro_aligned))
    if aligned_count == 3 and trade_value >= 0.28 and book_value >= 0.18:
        strength="بسیار قوی"; move=candidate.expected_move_pct*1.20
    elif aligned_count == 3:
        strength="قوی"; move=candidate.expected_move_pct
    else:
        strength="متوسط"; move=candidate.expected_move_pct*0.82
    sig = MarketSignal(candidate.symbol_id,candidate.okx_symbol,candidate.toobit_symbol,candidate.side,
        snapshot.ask if candidate.side=="LONG" else snapshot.bid,candidate.invalidation_price,candidate.atr_pct,move,strength,
        candidate.direction_reason,f"فشار پایدار معاملات {trade_value:+.3f} و دفتر {book_value:+.3f}",
        f"عبور سطح حفظ شد و Microprice پایدار {micro_value:+.5f}% است",snapshot.spread_pct,snapshot.trade_imbalance,snapshot.book_imbalance,snapshot.microprice_bias_pct)
    metrics.update({"strength":strength,"expected_move_pct":move})
    return sig, "تمام شروط ترتیبی ورود تأیید شد", metrics


def confirm_signal(candidate: MarketCandidate, snapshot: MicroSnapshot) -> MarketSignal | None:
    return confirm_signal_diagnostic(candidate, snapshot)[0]
