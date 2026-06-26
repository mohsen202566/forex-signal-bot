"""موتور تکنیکال ۱۵ تا ۳۰ دقیقه‌ای.

قفل‌ها:
- تصمیم بر اساس شتاب تغییرات: RSI Slope، ATR Expansion، ADX Rising، Volume/OI Growth
- Entry Score + Continuation Score + Confidence Penalty
- سیگنال ۳ دقیقه معتبر است و فقط سیگنال قوی‌تر می‌تواند جایگزین شود.
- بازار رنج جریمه سنگین دارد، مگر شتاب حرکت واقعاً قوی باشد.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite
from typing import Any

import config


@dataclass
class TradePlan:
    coin: str
    side: str                 # LONG / SHORT
    entry: float
    tp: float
    sl: float
    tp_percent: float
    sl_percent: float
    rr: float
    entry_score: float
    continuation_score: float
    confidence_penalty: float
    final_score: float
    market_state: str
    reasons: list[str]
    valid_seconds: int = config.SIGNAL_VALID_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < period + 2:
        return [50.0] * len(closes)
    out = [50.0] * period
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(abs(min(d, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period or 1e-9
    out.append(100 - 100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        gain = max(d, 0)
        loss = abs(min(d, 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period or 1e-9
        out.append(100 - 100 / (1 + avg_gain / avg_loss))
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    if len(trs) < period:
        return trs
    out = []
    for i in range(len(trs)):
        start = max(0, i - period + 1)
        out.append(sum(trs[start:i + 1]) / (i - start + 1))
    return out


def adx_proxy(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    # پروکسی سبک ADX برای اسکلت؛ در نسخه نهایی می‌توان با TA-Lib/pandas-ta جایگزین کرد.
    a = atr(highs, lows, closes, period)
    out = []
    for i in range(len(closes)):
        if i < period or closes[i] == 0:
            out.append(15.0)
        else:
            move = abs(closes[i] - closes[i - period]) / closes[i] * 100
            vol = (a[i] / closes[i] * 100) if i < len(a) and closes[i] else 0
            out.append(min(50.0, max(5.0, move * 4 + vol * 3)))
    return out


def slope(values: list[float], lookback: int = 4) -> float:
    if len(values) <= lookback:
        return 0.0
    return values[-1] - values[-1 - lookback]


def pct_change(values: list[float], lookback: int = 4) -> float:
    if len(values) <= lookback or values[-1 - lookback] == 0:
        return 0.0
    return (values[-1] - values[-1 - lookback]) / abs(values[-1 - lookback]) * 100


def normalize_pos(value: float, strong: float) -> float:
    if not isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value / strong))


def candle_exhaustion_penalty(open_: float, high: float, low: float, close: float, atr_value: float) -> float:
    body = abs(close - open_)
    rng = max(high - low, 1e-9)
    if atr_value <= 0:
        return 0.0
    penalty = 0.0
    if body / atr_value > 1.25:
        penalty += 5
    if body / rng > 0.85 and rng / atr_value > 1.4:
        penalty += 5
    return penalty


class StrategyEngine:
    def analyze(self, coin: str, candles_15m: list[dict[str, float]], candles_1h: list[dict[str, float]] | None = None, oi_values: list[float] | None = None) -> TradePlan | None:
        if len(candles_15m) < 40:
            return None

        c = candles_15m
        opens = [x["open"] for x in c]
        highs = [x["high"] for x in c]
        lows = [x["low"] for x in c]
        closes = [x["close"] for x in c]
        volumes = [x.get("volume", 0.0) for x in c]
        last = closes[-1]

        rsi_values = rsi(closes)
        atr_values = atr(highs, lows, closes)
        adx_values = adx_proxy(highs, lows, closes)

        rsi_slope = slope(rsi_values, 4)
        atr_growth = pct_change(atr_values, 4)
        adx_growth = pct_change(adx_values, 4)
        vol_growth = pct_change(volumes, 4)
        oi_growth = pct_change(oi_values or [], 4) if oi_values else 0.0

        ema50_15 = ema(closes[-60:], 50)
        ema50_1h = None
        if candles_1h and len(candles_1h) >= 55:
            ema50_1h = ema([x["close"] for x in candles_1h][-60:], 50)
            bias_up = closes[-1] > ema50_1h
            bias_down = closes[-1] < ema50_1h
        else:
            bias_up = closes[-1] > ema50_15
            bias_down = closes[-1] < ema50_15

        price_slope = pct_change(closes, 4)
        if rsi_slope > 1.5 and price_slope > 0 and bias_up:
            side = "LONG"
        elif rsi_slope < -1.5 and price_slope < 0 and bias_down:
            side = "SHORT"
        else:
            return None

        direction_sign = 1 if side == "LONG" else -1
        dir_rsi = rsi_slope * direction_sign
        dir_price = price_slope * direction_sign
        dir_oi = oi_growth * direction_sign if oi_values else 0.0

        market_structure = 1.0 if dir_price > 0 else 0.0
        ema_direction = 1.0 if ((side == "LONG" and last > ema50_15) or (side == "SHORT" and last < ema50_15)) else 0.0

        entry_score = (
            normalize_pos(dir_rsi, 8.0) * 25 +
            normalize_pos(atr_growth, 18.0) * 20 +
            market_structure * 15 +
            ema_direction * 10 +
            normalize_pos(vol_growth, 35.0) * 15 +
            normalize_pos(dir_oi, 10.0) * 10 +
            normalize_pos(adx_growth, 20.0) * 5
        )

        atr_acc = normalize_pos(atr_growth, 20.0)
        rsi_cont = normalize_pos(dir_rsi, 8.0)
        vol_stability = 1.0 if 5 <= vol_growth <= 90 else (0.5 if vol_growth > 0 else 0.0)
        oi_cont = normalize_pos(dir_oi, 10.0) if oi_values else 0.5
        adx_rising = normalize_pos(adx_growth, 20.0)
        exhaustion_penalty = candle_exhaustion_penalty(opens[-1], highs[-1], lows[-1], closes[-1], atr_values[-1])
        candle_ok = max(0.0, 1.0 - exhaustion_penalty / 10.0)

        continuation_score = (
            atr_acc * 25 + rsi_cont * 20 + vol_stability * 15 + oi_cont * 15 + adx_rising * 15 + candle_ok * 10
        )

        # Confidence فقط جریمه‌کننده است، نه سیگنال‌ساز.
        penalty = 0.0
        if entry_score < config.MIN_ENTRY_SCORE:
            penalty += 6
        if continuation_score < config.MIN_CONTINUATION_SCORE:
            penalty += 6
        if atr_growth < 3 and adx_growth < 3 and vol_growth < 5:
            penalty += 12  # بازار خواب/رنج
        if dir_rsi > 0 and dir_price <= 0:
            penalty += 8
        if volumes[-1] > 0 and vol_growth > 120:
            penalty += 6   # اسپایک غیرطبیعی
        penalty += exhaustion_penalty

        final_score = entry_score * 0.55 + continuation_score * 0.45 - penalty
        market_state = "RANGE_PENALIZED" if penalty >= 12 else "ACTIVE"

        if entry_score < config.MIN_ENTRY_SCORE or continuation_score < config.MIN_CONTINUATION_SCORE or final_score < config.MIN_FINAL_SCORE:
            return None

        plan = self._make_tp_sl(
            coin=coin, side=side, entry=last, atr_value=atr_values[-1],
            entry_score=entry_score, continuation_score=continuation_score,
            confidence_penalty=penalty, final_score=final_score, market_state=market_state,
            reasons=[
                f"RSI slope={rsi_slope:.2f}", f"ATR growth={atr_growth:.2f}%",
                f"ADX rising={adx_growth:.2f}%", f"Volume growth={vol_growth:.2f}%",
                f"OI growth={oi_growth:.2f}%", f"Penalty={penalty:.1f}",
            ],
        )
        return plan

    def _make_tp_sl(self, coin: str, side: str, entry: float, atr_value: float, entry_score: float, continuation_score: float, confidence_penalty: float, final_score: float, market_state: str, reasons: list[str]) -> TradePlan:
        quality = max(0.0, min(1.0, (final_score - 75) / 20))
        rr = config.BASE_RR + (config.MAX_RR - config.BASE_RR) * quality
        rr = max(config.MIN_RR, min(config.MAX_RR, rr))
        sl_mult = config.ATR_SL_MULT_BASE + (config.ATR_SL_MULT_MAX - config.ATR_SL_MULT_BASE) * (confidence_penalty / 25)
        sl_mult = max(config.ATR_SL_MULT_MIN, min(config.ATR_SL_MULT_MAX, sl_mult))
        sl_distance = max(atr_value * sl_mult, entry * 0.0015)  # حداقل فاصله برای نویز
        tp_distance = sl_distance * rr
        if side == "LONG":
            sl = entry - sl_distance
            tp = entry + tp_distance
        else:
            sl = entry + sl_distance
            tp = entry - tp_distance
        return TradePlan(
            coin=coin, side=side, entry=entry, tp=tp, sl=sl,
            tp_percent=abs(tp - entry) / entry,
            sl_percent=abs(sl - entry) / entry,
            rr=rr,
            entry_score=round(entry_score, 2),
            continuation_score=round(continuation_score, 2),
            confidence_penalty=round(confidence_penalty, 2),
            final_score=round(final_score, 2),
            market_state=market_state,
            reasons=reasons,
        )


def estimated_net_profit_usdt(margin_usdt: float, leverage: int, tp_percent: float, fee_rate: float, slippage_rate: float) -> float:
    notional = margin_usdt * leverage
    gross_profit = notional * tp_percent
    fees = notional * fee_rate * 2
    slippage = notional * slippage_rate
    return gross_profit - fees - slippage
