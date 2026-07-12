"""موتور واحد رفتارمحور: جهت 1H، قدرت جریان و زمان ورود."""
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


def detect_candidate(sym: SymbolMap, candles: list[dict[str, float]]) -> MarketCandidate | None:
    closed = [c for c in candles if int(c.get("confirm", 1)) == 1]
    if len(closed) < 50:
        return None
    recent = closed[-12:]
    base = closed[-36:-12]
    last = recent[-1]
    atr = _atr_pct(closed)
    if atr <= 0:
        return None
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
    volume_ok = vol_recent >= vol_base * 0.85
    close = last["close"]

    side = ""
    level = 0.0
    invalidation = 0.0
    reason = ""
    if highs_rising and lows_rising and close >= recent_high * (1 - atr * 0.003):
        side, level = "LONG", recent_high
        invalidation = min(c["low"] for c in recent[-5:])
        reason = "ساختار 1H سقف و کف بالاتر دارد و قیمت نزدیک ناحیه گسترش صعودی است"
    elif highs_falling and lows_falling and close <= recent_low * (1 + atr * 0.003):
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
        return None

    stop_pct = abs(close - invalidation) / close * 100.0 if close > 0 else 0.0
    if stop_pct <= 0 or stop_pct > atr * 1.8:
        return None
    efficiency = abs(recent[-1]["close"] - recent[0]["open"]) / max(sum(c["high"] - c["low"] for c in recent), 1e-12)
    expected = atr * (1.55 if efficiency < 0.22 else 2.05)
    return MarketCandidate(sym.id, sym.okx, sym.toobit, side, int(time.time()), level, invalidation, atr, expected, reason)


def confirm_signal(candidate: MarketCandidate, snapshot: MicroSnapshot) -> MarketSignal | None:
    if snapshot.last <= 0 or snapshot.spread_pct > config.MAX_SPREAD_PCT:
        return None
    sign = 1.0 if candidate.side == "LONG" else -1.0
    trade_aligned = sign * snapshot.trade_imbalance >= config.MIN_ABS_TRADE_IMBALANCE
    book_aligned = sign * snapshot.book_imbalance >= config.MIN_ABS_BOOK_IMBALANCE
    micro_aligned = sign * snapshot.microprice_bias_pct >= config.MICROPRICE_MIN_BIAS_PCT
    level_crossed = snapshot.last >= candidate.structure_level if candidate.side == "LONG" else snapshot.last <= candidate.structure_level
    chase_pct = abs(snapshot.last - candidate.structure_level) / snapshot.last * 100.0
    if chase_pct > candidate.atr_pct * config.MAX_ENTRY_CHASE_ATR:
        return None
    if not (level_crossed and trade_aligned and micro_aligned):
        return None
    if not book_aligned and abs(snapshot.trade_imbalance) < 0.24:
        return None

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

    return MarketSignal(
        candidate.symbol_id, candidate.okx_symbol, candidate.toobit_symbol, candidate.side,
        snapshot.ask if candidate.side == "LONG" else snapshot.bid,
        candidate.invalidation_price, candidate.atr_pct, move, strength,
        candidate.direction_reason,
        f"جریان معاملات {snapshot.trade_imbalance:+.3f} و دفتر سفارش {snapshot.book_imbalance:+.3f}",
        f"Microprice هم‌جهت {snapshot.microprice_bias_pct:+.5f}% و عبور معتبر از سطح",
        snapshot.spread_pct, snapshot.trade_imbalance, snapshot.book_imbalance, snapshot.microprice_bias_pct,
    )
