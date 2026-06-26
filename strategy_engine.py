"""موتور تکنیکال ۱۵ تا ۳۰ دقیقه‌ای.

قفل‌های معماری:
- تحلیل اصلی روی 15m و فیلتر جهت روی 1H است.
- تصمیم بر اساس شتاب تغییرات است، نه فقط مقدار فعلی اندیکاتورها.
- سنسورها: RSI Slope، ATR Expansion، ADX Rising، Volume Growth، Open Interest Growth.
- خروجی فقط TradePlan است؛ این فایل معامله واقعی باز نمی‌کند و سیگنال قبلی را هم خودش نمی‌بندد.
- Confidence فقط جریمه‌کننده است، نه سیگنال‌ساز.
- بازار رنج/خواب رد می‌شود، مگر چند سنسور شتابی هم‌زمان حرکت قوی نشان بدهند.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite
from typing import Any

import config


# =========================
# Locked score weights
# =========================
ENTRY_WEIGHTS: dict[str, float] = {
    "rsi_slope_direction": 25.0,
    "atr_expansion": 20.0,
    "market_structure_bias": 15.0,
    "ema50_direction": 10.0,
    "volume_growth": 15.0,
    "oi_direction": 10.0,
    "adx_rising": 5.0,
}

CONTINUATION_WEIGHTS: dict[str, float] = {
    "atr_acceleration": 25.0,
    "rsi_slope_continuation": 20.0,
    "volume_stability": 15.0,
    "oi_growth_with_price": 15.0,
    "adx_rising": 15.0,
    "candle_not_exhausted": 10.0,
}

# Strength targets for normalization. These are intentionally conservative for 15m.
STRONG_RSI_SLOPE = 8.0
STRONG_ATR_GROWTH = 18.0
STRONG_ATR_CONTINUATION = 20.0
STRONG_VOLUME_GROWTH = 35.0
STRONG_OI_GROWTH = 10.0
STRONG_ADX_GROWTH = 20.0

# Range/sleep market rule: normally no trade, except when early acceleration is strong.
RANGE_ATR_WEAK = 3.0
RANGE_ADX_WEAK = 3.0
RANGE_VOLUME_WEAK = 5.0
RANGE_ESCAPE_RSI = 5.0
RANGE_ESCAPE_ATR = 10.0
RANGE_ESCAPE_VOLUME = 20.0
RANGE_ESCAPE_OI = 5.0


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
    can_replace: bool = True  # bot/state_store تصمیم جایگزینی را می‌گیرند، نه این فایل.

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
        gains.append(max(d, 0.0))
        losses.append(abs(min(d, 0.0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period or 1e-9
    out.append(100 - 100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        gain = max(d, 0.0)
        loss = abs(min(d, 0.0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period or 1e-9
        out.append(100 - 100 / (1 + avg_gain / avg_loss))
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    trs: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    if len(trs) < period:
        return trs
    out: list[float] = []
    for i in range(len(trs)):
        start = max(0, i - period + 1)
        out.append(sum(trs[start:i + 1]) / (i - start + 1))
    return out


def adx_proxy(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """پروکسی سبک ADX؛ بعداً اگر خواستیم می‌تواند با TA-Lib جایگزین شود."""
    a = atr(highs, lows, closes, period)
    out: list[float] = []
    for i in range(len(closes)):
        if i < period or closes[i] == 0:
            out.append(15.0)
        else:
            move = abs(closes[i] - closes[i - period]) / closes[i] * 100
            vol = (a[i] / closes[i] * 100) if i < len(a) and closes[i] else 0.0
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
        penalty += 5.0
    if body / rng > 0.85 and rng / atr_value > 1.4:
        penalty += 5.0
    return penalty


def estimated_net_profit_usdt(margin_usdt: float, leverage: int, tp_percent: float, fee_rate: float, slippage_rate: float) -> float:
    """فقط محاسبه سود خالص تخمینی؛ تصمیم REAL در bot.py گرفته می‌شود."""
    notional = margin_usdt * leverage
    gross_profit = notional * tp_percent
    fees = notional * fee_rate * 2
    slippage = notional * slippage_rate
    return gross_profit - fees - slippage


class StrategyEngine:
    def analyze(
        self,
        coin: str,
        candles_15m: list[dict[str, float]],
        candles_1h: list[dict[str, float]] | None = None,
        oi_values: list[float] | None = None,
    ) -> TradePlan | None:
        if len(candles_15m) < 60:
            return None

        c = candles_15m
        opens = [float(x["open"]) for x in c]
        highs = [float(x["high"]) for x in c]
        lows = [float(x["low"]) for x in c]
        closes = [float(x["close"]) for x in c]
        volumes = [float(x.get("volume", 0.0)) for x in c]
        last = closes[-1]
        if last <= 0:
            return None

        rsi_values = rsi(closes)
        atr_values = atr(highs, lows, closes)
        adx_values = adx_proxy(highs, lows, closes)
        if not atr_values or atr_values[-1] <= 0:
            return None

        rsi_slope = slope(rsi_values, 4)
        atr_growth = pct_change(atr_values, 4)
        adx_growth = pct_change(adx_values, 4)
        vol_growth = pct_change(volumes, 4)
        oi_has_data = bool(oi_values and len(oi_values) > 4)
        oi_growth = pct_change(oi_values or [], 4) if oi_has_data else 0.0

        ema50_15 = ema(closes[-60:], 50)
        if candles_1h and len(candles_1h) >= 55:
            h1_closes = [float(x["close"]) for x in candles_1h]
            ema50_1h = ema(h1_closes[-60:], 50)
            bias_up = h1_closes[-1] > ema50_1h
            bias_down = h1_closes[-1] < ema50_1h
        else:
            bias_up = last > ema50_15
            bias_down = last < ema50_15

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
        dir_oi = oi_growth * direction_sign if oi_has_data else 0.0

        market_structure = 1.0 if dir_price > 0 else 0.0
        ema_direction = 1.0 if ((side == "LONG" and last > ema50_15) or (side == "SHORT" and last < ema50_15)) else 0.0

        range_sleep = atr_growth < RANGE_ATR_WEAK and adx_growth < RANGE_ADX_WEAK and vol_growth < RANGE_VOLUME_WEAK
        range_escape = (
            dir_rsi >= RANGE_ESCAPE_RSI
            and atr_growth >= RANGE_ESCAPE_ATR
            and vol_growth >= RANGE_ESCAPE_VOLUME
            and (not oi_has_data or dir_oi >= RANGE_ESCAPE_OI)
        )
        if range_sleep and not range_escape:
            return None

        entry_components = {
            "rsi_slope_direction": normalize_pos(dir_rsi, STRONG_RSI_SLOPE) * ENTRY_WEIGHTS["rsi_slope_direction"],
            "atr_expansion": normalize_pos(atr_growth, STRONG_ATR_GROWTH) * ENTRY_WEIGHTS["atr_expansion"],
            "market_structure_bias": market_structure * ENTRY_WEIGHTS["market_structure_bias"],
            "ema50_direction": ema_direction * ENTRY_WEIGHTS["ema50_direction"],
            "volume_growth": normalize_pos(vol_growth, STRONG_VOLUME_GROWTH) * ENTRY_WEIGHTS["volume_growth"],
            "oi_direction": (normalize_pos(dir_oi, STRONG_OI_GROWTH) if oi_has_data else 0.5) * ENTRY_WEIGHTS["oi_direction"],
            "adx_rising": normalize_pos(adx_growth, STRONG_ADX_GROWTH) * ENTRY_WEIGHTS["adx_rising"],
        }
        entry_score = sum(entry_components.values())

        vol_stability = 1.0 if 5 <= vol_growth <= 90 else (0.5 if vol_growth > 0 else 0.0)
        exhaustion_penalty = candle_exhaustion_penalty(opens[-1], highs[-1], lows[-1], closes[-1], atr_values[-1])
        candle_ok = max(0.0, 1.0 - exhaustion_penalty / 10.0)
        cont_components = {
            "atr_acceleration": normalize_pos(atr_growth, STRONG_ATR_CONTINUATION) * CONTINUATION_WEIGHTS["atr_acceleration"],
            "rsi_slope_continuation": normalize_pos(dir_rsi, STRONG_RSI_SLOPE) * CONTINUATION_WEIGHTS["rsi_slope_continuation"],
            "volume_stability": vol_stability * CONTINUATION_WEIGHTS["volume_stability"],
            "oi_growth_with_price": (normalize_pos(dir_oi, STRONG_OI_GROWTH) if oi_has_data else 0.5) * CONTINUATION_WEIGHTS["oi_growth_with_price"],
            "adx_rising": normalize_pos(adx_growth, STRONG_ADX_GROWTH) * CONTINUATION_WEIGHTS["adx_rising"],
            "candle_not_exhausted": candle_ok * CONTINUATION_WEIGHTS["candle_not_exhausted"],
        }
        continuation_score = sum(cont_components.values())

        # Confidence Penalty: فقط جریمه‌کننده است.
        penalty = 0.0
        penalty_reasons: list[str] = []
        if entry_score < config.MIN_ENTRY_SCORE:
            penalty += 6.0
            penalty_reasons.append("Entry زیر حد")
        if continuation_score < config.MIN_CONTINUATION_SCORE:
            penalty += 6.0
            penalty_reasons.append("Continuation زیر حد")
        if range_sleep:
            penalty += 12.0
            penalty_reasons.append("بازار رنج/خواب")
        if dir_rsi > 0 and dir_price <= 0:
            penalty += 8.0
            penalty_reasons.append("RSI با قیمت هماهنگ نیست")
        if volumes[-1] > 0 and vol_growth > 120:
            penalty += 6.0
            penalty_reasons.append("اسپایک حجم غیرطبیعی")
        if exhaustion_penalty:
            penalty += exhaustion_penalty
            penalty_reasons.append("کندل کشیده/دیرهنگام")
        if oi_has_data and dir_oi < -2:
            penalty += 5.0
            penalty_reasons.append("OI خلاف جهت")

        final_score = entry_score * 0.55 + continuation_score * 0.45 - penalty
        market_state = "RANGE_ESCAPE" if range_sleep and range_escape else "RANGE_PENALIZED" if range_sleep else "ACTIVE"

        if entry_score < config.MIN_ENTRY_SCORE or continuation_score < config.MIN_CONTINUATION_SCORE or final_score < config.MIN_FINAL_SCORE:
            return None

        reasons = [
            f"RSI slope={rsi_slope:.2f}",
            f"Price slope={price_slope:.2f}%",
            f"ATR growth={atr_growth:.2f}%",
            f"ADX rising={adx_growth:.2f}%",
            f"Volume growth={vol_growth:.2f}%",
            f"OI growth={oi_growth:.2f}%" if oi_has_data else "OI data=unavailable",
            f"Entry={entry_score:.2f}",
            f"Continuation={continuation_score:.2f}",
            f"Penalty={penalty:.1f}" + (f" ({', '.join(penalty_reasons)})" if penalty_reasons else ""),
            f"Market={market_state}",
        ]

        return self._make_tp_sl(
            coin=coin,
            side=side,
            entry=last,
            atr_value=atr_values[-1],
            entry_score=entry_score,
            continuation_score=continuation_score,
            confidence_penalty=penalty,
            final_score=final_score,
            market_state=market_state,
            reasons=reasons,
        )

    def _make_tp_sl(
        self,
        coin: str,
        side: str,
        entry: float,
        atr_value: float,
        entry_score: float,
        continuation_score: float,
        confidence_penalty: float,
        final_score: float,
        market_state: str,
        reasons: list[str],
    ) -> TradePlan:
        quality = max(0.0, min(1.0, (final_score - config.MIN_FINAL_SCORE) / 20.0))
        rr = config.BASE_RR + (config.MAX_RR - config.BASE_RR) * quality
        rr = max(config.MIN_RR, min(config.MAX_RR, rr))

        # پنالتی بیشتر یعنی عدم قطعیت بیشتر، پس SL کمی فضای بیشتر می‌گیرد اما کنترل‌شده می‌ماند.
        sl_mult = config.ATR_SL_MULT_BASE + (config.ATR_SL_MULT_MAX - config.ATR_SL_MULT_BASE) * (confidence_penalty / 25.0)
        sl_mult = max(config.ATR_SL_MULT_MIN, min(config.ATR_SL_MULT_MAX, sl_mult))
        sl_distance = max(atr_value * sl_mult, entry * 0.0015)  # حداقل فاصله برای نویز 15m
        tp_distance = sl_distance * rr

        if side == "LONG":
            sl = entry - sl_distance
            tp = entry + tp_distance
        else:
            sl = entry + sl_distance
            tp = entry - tp_distance

        return TradePlan(
            coin=coin,
            side=side,
            entry=entry,
            tp=tp,
            sl=sl,
            tp_percent=abs(tp - entry) / entry,
            sl_percent=abs(sl - entry) / entry,
            rr=round(rr, 3),
            entry_score=round(entry_score, 2),
            continuation_score=round(continuation_score, 2),
            confidence_penalty=round(confidence_penalty, 2),
            final_score=round(final_score, 2),
            market_state=market_state,
            reasons=reasons,
            valid_seconds=config.SIGNAL_VALID_SECONDS,
            can_replace=True,
        )
