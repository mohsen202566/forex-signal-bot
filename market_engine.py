"""موتور واحد رفتارمحور: جهت 1H، قدرت جریان و زمان ورود.

هر تابع تشخیصی علاوه بر خروجی اصلی، علت دقیق پذیرش/رد و متریک‌های همان تصمیم را برمی‌گرداند.
"""
from __future__ import annotations
from statistics import median
import time
import config
from models import MarketCandidate, MarketSignal, MicroSnapshot
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

    metrics.update({
        "close": close, "recent_high": recent_high, "recent_low": recent_low,
        "older_high": older_high, "older_low": older_low, "volume_ratio": volume_ratio,
        "highs_rising": highs_rising, "lows_rising": lows_rising,
        "highs_falling": highs_falling, "lows_falling": lows_falling,
    })

    side = ""
    level = 0.0
    invalidation = 0.0
    reason = ""
    long_near = close >= recent_high * (1 - atr * 0.003)
    short_near = close <= recent_low * (1 + atr * 0.003)
    metrics.update({"long_near": long_near, "short_near": short_near})

    if highs_rising and lows_rising and long_near:
        side, level = "LONG", recent_high
        invalidation = min(c["low"] for c in recent[-5:])
        reason = "ساختار 1H سقف و کف بالاتر دارد و قیمت نزدیک ناحیه گسترش صعودی است"
    elif highs_falling and lows_falling and short_near:
        side, level = "SHORT", recent_low
        invalidation = max(c["high"] for c in recent[-5:])
        reason = "ساختار 1H سقف و کف پایین‌تر دارد و قیمت نزدیک ناحیه گسترش نزولی است"
    elif close > older_high and volume_ok:
        side, level = "LONG", older_high
        invalidation = recent_low
        reason = "شکست و پذیرش صعودی ساختار 1H مشاهده شد"
    elif close < older_low and volume_ok:
        side, level = "SHORT", older_low
        invalidation = recent_high
        reason = "شکست و پذیرش نزولی ساختار 1H مشاهده شد"
    else:
        failures: list[str] = []
        if not (highs_rising and lows_rising):
            failures.append("ساختار صعودی کامل نیست")
        if not long_near:
            failures.append("قیمت به ناحیه گسترش صعودی نزدیک نیست")
        if not (highs_falling and lows_falling):
            failures.append("ساختار نزولی کامل نیست")
        if not short_near:
            failures.append("قیمت به ناحیه گسترش نزولی نزدیک نیست")
        if not (close > older_high or close < older_low):
            failures.append("شکست معتبر سقف/کف مبنا رخ نداده")
        elif not volume_ok:
            failures.append(f"حجم شکست ضعیف است ratio={volume_ratio:.3f}<0.850")
        return None, "؛ ".join(failures), metrics

    stop_pct = abs(close - invalidation) / close * 100.0 if close > 0 else 0.0
    max_stop_pct = atr * 1.8
    metrics.update({"side": side, "structure_level": level, "invalidation": invalidation, "raw_stop_pct": stop_pct, "max_raw_stop_pct": max_stop_pct})
    if stop_pct <= 0:
        return None, "فاصله ابطال ساختاری صفر یا نامعتبر است", metrics
    if stop_pct > max_stop_pct:
        return None, f"استاپ خام بیش‌ازحد بزرگ است: {stop_pct:.4f}% > {max_stop_pct:.4f}% (1.8 ATR)", metrics

    total_range = max(sum(c["high"] - c["low"] for c in recent), 1e-12)
    efficiency = abs(recent[-1]["close"] - recent[0]["open"]) / total_range
    expected = atr * (1.55 if efficiency < 0.22 else 2.05)
    metrics.update({"efficiency": efficiency, "expected_move_pct": expected})
    candidate = MarketCandidate(sym.id, sym.okx, sym.toobit, side, int(time.time()), level, invalidation, atr, expected, reason)
    return candidate, reason, metrics


def detect_candidate(sym: SymbolMap, candles: list[dict[str, float]]) -> MarketCandidate | None:
    return detect_candidate_diagnostic(sym, candles)[0]


def confirm_signal_diagnostic(candidate: MarketCandidate, snapshot: MicroSnapshot) -> tuple[MarketSignal | None, str, dict[str, float | int | str | bool]]:
    sign = 1.0 if candidate.side == "LONG" else -1.0
    trade_value = sign * snapshot.trade_imbalance
    book_value = sign * snapshot.book_imbalance
    micro_value = sign * snapshot.microprice_bias_pct
    trade_aligned = trade_value >= config.MIN_ABS_TRADE_IMBALANCE
    book_aligned = book_value >= config.MIN_ABS_BOOK_IMBALANCE
    micro_aligned = micro_value >= config.MICROPRICE_MIN_BIAS_PCT
    level_crossed = snapshot.last >= candidate.structure_level if candidate.side == "LONG" else snapshot.last <= candidate.structure_level
    chase_pct = abs(snapshot.last - candidate.structure_level) / snapshot.last * 100.0 if snapshot.last > 0 else float("inf")
    chase_limit = candidate.atr_pct * config.MAX_ENTRY_CHASE_ATR

    metrics: dict[str, float | int | str | bool] = {
        "side": candidate.side, "last": snapshot.last, "bid": snapshot.bid, "ask": snapshot.ask,
        "spread_pct": snapshot.spread_pct, "spread_limit_pct": config.MAX_SPREAD_PCT,
        "trade_imbalance": snapshot.trade_imbalance, "trade_aligned_value": trade_value,
        "trade_min": config.MIN_ABS_TRADE_IMBALANCE,
        "book_imbalance": snapshot.book_imbalance, "book_aligned_value": book_value,
        "book_min": config.MIN_ABS_BOOK_IMBALANCE,
        "micro_bias_pct": snapshot.microprice_bias_pct, "micro_aligned_value": micro_value,
        "micro_min_pct": config.MICROPRICE_MIN_BIAS_PCT,
        "level": candidate.structure_level, "level_crossed": level_crossed,
        "chase_pct": chase_pct, "chase_limit_pct": chase_limit,
    }

    if snapshot.last <= 0:
        return None, "قیمت لحظه‌ای نامعتبر یا صفر است", metrics
    if snapshot.spread_pct > config.MAX_SPREAD_PCT:
        return None, f"اسپرد زیاد است: {snapshot.spread_pct:.5f}% > {config.MAX_SPREAD_PCT:.5f}%", metrics
    if chase_pct > chase_limit:
        return None, f"ورود دیر شده: فاصله از سطح {chase_pct:.5f}% > حد {chase_limit:.5f}%", metrics

    failures: list[str] = []
    if not level_crossed:
        failures.append(f"سطح ساختاری هنوز عبور نکرده last={snapshot.last:.8g} level={candidate.structure_level:.8g}")
    if not trade_aligned:
        failures.append(f"جریان معاملات هم‌جهت کافی نیست {trade_value:+.3f}<{config.MIN_ABS_TRADE_IMBALANCE:.3f}")
    if not micro_aligned:
        failures.append(f"Microprice هم‌جهت کافی نیست {micro_value:+.5f}%<{config.MICROPRICE_MIN_BIAS_PCT:.5f}%")
    if failures:
        return None, "؛ ".join(failures), metrics
    if not book_aligned and abs(snapshot.trade_imbalance) < 0.24:
        return None, (f"دفتر سفارش هم‌جهت نیست {book_value:+.3f}<{config.MIN_ABS_BOOK_IMBALANCE:.3f} "
                      f"و جریان معاملات جایگزین نیز ضعیف است |trade|={abs(snapshot.trade_imbalance):.3f}<0.240"), metrics

    aligned_count = sum((trade_aligned, book_aligned, micro_aligned))
    if aligned_count == 3 and abs(snapshot.trade_imbalance) >= 0.28 and abs(snapshot.book_imbalance) >= 0.18:
        strength = "بسیار قوی"
        move = candidate.expected_move_pct * 1.20
    elif aligned_count == 3:
        strength = "قوی"
        move = candidate.expected_move_pct
    else:
        strength = "متوسط"
        move = candidate.expected_move_pct * 0.82

    signal = MarketSignal(
        candidate.symbol_id, candidate.okx_symbol, candidate.toobit_symbol, candidate.side,
        snapshot.ask if candidate.side == "LONG" else snapshot.bid,
        candidate.invalidation_price, candidate.atr_pct, move, strength,
        candidate.direction_reason,
        f"جریان معاملات {snapshot.trade_imbalance:+.3f} و دفتر سفارش {snapshot.book_imbalance:+.3f}",
        f"Microprice هم‌جهت {snapshot.microprice_bias_pct:+.5f}% و عبور معتبر از سطح",
        snapshot.spread_pct, snapshot.trade_imbalance, snapshot.book_imbalance, snapshot.microprice_bias_pct,
    )
    metrics.update({"strength": strength, "expected_move_pct": move})
    return signal, "تمام شروط ورود تأیید شد", metrics


def confirm_signal(candidate: MarketCandidate, snapshot: MicroSnapshot) -> MarketSignal | None:
    return confirm_signal_diagnostic(candidate, snapshot)[0]
