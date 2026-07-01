from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import config
from indicators import (
    Level,
    average_volume,
    candle_body_strength,
    candle_direction,
    closes,
    detect_levels,
    ema,
    macd,
    nearest_level_above,
    nearest_level_below,
    rsi,
)
from okx_client import Candle
from utils import display_symbol, fmt_pct, pct_change, pct_distance, risk_reward, toobit_symbol

Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class DailyBias:
    direction: Direction | None
    score: int
    reasons: list[str]
    levels: list[Level]


@dataclass(frozen=True)
class EntryDecision:
    allowed: bool
    score: int
    reasons: list[str]


@dataclass(frozen=True)
class Signal:
    base_symbol: str
    okx_symbol: str
    toobit_symbol: str
    display_symbol: str
    direction: Direction
    entry_price: float
    tp_price: float
    sl_price: float
    tp_distance_pct: float
    sl_distance_pct: float
    rr: float
    score: int
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NoSignal:
    base_symbol: str
    reason: str


SignalResult = Signal | NoSignal


class SimpleStrangeStrategy:
    def __init__(self, *, min_tp_pct: float = config.MIN_DAILY_TP_ROOM_PCT, rr: float = config.RISK_REWARD) -> None:
        self.min_tp_pct = float(min_tp_pct)
        self.rr = float(rr)

    def evaluate(
        self,
        *,
        base_symbol: str,
        candles_1d: list[Candle],
        candles_15m: list[Candle],
        candles_5m: list[Candle],
        btc_1d: list[Candle],
        eth_1d: list[Candle],
    ) -> SignalResult:
        symbol_bias = self.daily_bias(candles_1d)
        if symbol_bias.direction is None:
            return NoSignal(base_symbol, "جهت روزانه ارز نامشخص است.")

        entry = float(candles_5m[-1].close if candles_5m else candles_15m[-1].close)
        if entry <= 0:
            return NoSignal(base_symbol, "قیمت ورود معتبر نیست.")

        tp_sl = self._build_daily_tp_sl(entry, symbol_bias.direction, symbol_bias.levels)
        if tp_sl is None:
            return NoSignal(base_symbol, f"فضای حرکت روزانه تا TP کمتر از {self.min_tp_pct:.1f}% است یا سطح معتبر پیدا نشد.")
        tp_price, sl_price = tp_sl
        tp_pct = pct_change(entry, tp_price, symbol_bias.direction)
        sl_pct = pct_distance(entry, sl_price)
        rr_value = risk_reward(entry, tp_price, sl_price, symbol_bias.direction)
        if tp_pct < self.min_tp_pct:
            return NoSignal(base_symbol, f"فاصله TP روزانه کمتر از {self.min_tp_pct:.1f}% است.")
        if rr_value < self.rr:
            return NoSignal(base_symbol, f"ریسک به ریوارد کمتر از {self.rr:.1f} است.")

        entry_decision = self.entry_confirmation(symbol_bias.direction, candles_15m, candles_5m)
        if not entry_decision.allowed:
            return NoSignal(base_symbol, "ورود 15M/5M هنوز تایید نشده است.")

        raw_score = int(symbol_bias.score * 0.65 + entry_decision.score * 0.35)
        # وقتی همه قفل‌های اصلی پاس شده‌اند، امتیاز فقط برای نمایش است و نباید دوباره سیگنال را کورکورانه رد کند.
        score = min(100, max(int(config.SIGNAL_THRESHOLD), raw_score))

        reasons = symbol_bias.reasons + entry_decision.reasons
        reasons.append(f"تا TP روزانه {fmt_pct(tp_pct)} فضا وجود دارد و RR برابر {rr_value:.2f} است.")
        return Signal(
            base_symbol=base_symbol,
            okx_symbol=f"{base_symbol}-USDT-SWAP",
            toobit_symbol=toobit_symbol(base_symbol),
            display_symbol=display_symbol(base_symbol),
            direction=symbol_bias.direction,
            entry_price=entry,
            tp_price=tp_price,
            sl_price=sl_price,
            tp_distance_pct=tp_pct,
            sl_distance_pct=sl_pct,
            rr=rr_value,
            score=score,
            reasons=reasons,
        )

    def daily_bias(self, candles: list[Candle]) -> DailyBias:
        """Lenient but structured 1D direction detection.

        نسخه قبلی فقط وقتی جهت می‌داد که قیمت عملاً بریک‌اوت روزانه کرده باشد؛
        برای همین اکثر ارزها «نامشخص» می‌شدند. این نسخه جهت را امتیازی تشخیص می‌دهد:
        ساختار، EMA، شیب، RSI/MACD، کندل و سطح روزانه.
        """
        if len(candles) < 80:
            return DailyBias(None, 0, ["کندل روزانه کافی نیست."], [])

        c = closes(candles)
        last = candles[-1]
        current = float(last.close)
        ema20 = ema(c, 20)
        ema50 = ema(c, 50)
        ema200 = ema(c, 200) if len(c) >= 200 else ema(c, 100)
        rs = rsi(c, 14)
        macd_line, _, hist = macd(c)
        levels = detect_levels(candles[-180:], min_touches=3)

        # Fallback daily structure levels so TP/SL is not blocked only because repeated-touch
        # level detection did not find a perfect level.
        recent_60 = candles[-60:]
        recent_high = max(float(x.high) for x in recent_60)
        recent_low = min(float(x.low) for x in recent_60)
        if recent_high > current:
            levels.append(Level(price=recent_high, kind="resistance", touches=1, strength=5.0))
        if recent_low < current:
            levels.append(Level(price=recent_low, kind="support", touches=1, strength=5.0))
        levels = sorted(levels, key=lambda x: x.price)

        long_score = 0
        short_score = 0
        long_reasons: list[str] = []
        short_reasons: list[str] = []

        close_20 = c[-20]
        close_10 = c[-10]

        # Price position versus EMA.
        if current > ema50[-1]:
            long_score += 22
            long_reasons.append("قیمت روزانه بالای EMA50 است.")
        if current < ema50[-1]:
            short_score += 22
            short_reasons.append("قیمت روزانه پایین EMA50 است.")

        # EMA alignment.
        if ema50[-1] > ema200[-1]:
            long_score += 18
            long_reasons.append("چیدمان EMA50/EMA200 صعودی است.")
        if ema50[-1] < ema200[-1]:
            short_score += 18
            short_reasons.append("چیدمان EMA50/EMA200 نزولی است.")

        # EMA slope.
        if ema50[-1] > ema50[-8]:
            long_score += 14
            long_reasons.append("شیب EMA50 روزانه رو به بالا است.")
        if ema50[-1] < ema50[-8]:
            short_score += 14
            short_reasons.append("شیب EMA50 روزانه رو به پایین است.")

        # Recent structure without requiring breakout.
        if current > close_20 and current >= close_10:
            long_score += 16
            long_reasons.append("ساختار ۲۰ کندل اخیر روزانه به نفع صعود است.")
        if current < close_20 and current <= close_10:
            short_score += 16
            short_reasons.append("ساختار ۲۰ کندل اخیر روزانه به نفع نزول است.")

        # Momentum.
        if rs[-1] >= 50:
            long_score += 12
            long_reasons.append("RSI روزانه بالای ناحیه میانی است.")
        if rs[-1] <= 50:
            short_score += 12
            short_reasons.append("RSI روزانه پایین ناحیه میانی است.")

        if len(hist) >= 4:
            if hist[-1] >= hist[-3] or macd_line[-1] > 0:
                long_score += 10
                long_reasons.append("MACD روزانه با سناریوی صعودی مخالف نیست.")
            if hist[-1] <= hist[-3] or macd_line[-1] < 0:
                short_score += 10
                short_reasons.append("MACD روزانه با سناریوی نزولی مخالف نیست.")

        # Candle should not be a strong opposite candle.
        body = candle_body_strength(last)
        last_dir = candle_direction(last)
        if last_dir != "SHORT" or body < 0.55:
            long_score += 8
        if last_dir != "LONG" or body < 0.55:
            short_score += 8

        support = nearest_level_below(levels, current, "support")
        resistance = nearest_level_above(levels, current, "resistance")
        if support:
            long_score += 5
            long_reasons.append("حمایت روزانه زیر قیمت وجود دارد.")
        if resistance:
            short_score += 5
            short_reasons.append("مقاومت روزانه بالای قیمت وجود دارد.")

        # Direction gate: not too loose, but no longer requires a fresh breakout.
        if long_score >= 60 and long_score >= short_score + 4:
            return DailyBias("LONG", min(100, long_score), long_reasons, levels)
        if short_score >= 60 and short_score >= long_score + 4:
            return DailyBias("SHORT", min(100, short_score), short_reasons, levels)

        best = max(long_score, short_score)
        return DailyBias(None, best, [f"جهت روزانه هنوز واضح نیست. long={long_score} short={short_score}"], levels)

    def entry_confirmation(self, direction: Direction, candles_15m: list[Candle], candles_5m: list[Candle]) -> EntryDecision:
        """15M creates the zone and 5M pulls the trigger.

        این مرحله فقط تایم ورود است، نه تغییر جهت. نسخه قبلی منتظر کندل خیلی قوی و
        چیدمان کامل EMA در هر دو تایم بود؛ برای همین سیگنال اتومات خشک می‌شد.
        """
        if len(candles_15m) < 60 or len(candles_5m) < 60:
            return EntryDecision(False, 0, ["کندل کافی برای ورود دقیق نیست."])

        score = 0
        reasons: list[str] = []

        for label, candles, weight in (("15M", candles_15m, 45), ("5M", candles_5m, 55)):
            c = closes(candles)
            e20 = ema(c, 20)
            e50 = ema(c, 50)
            rs = rsi(c, 14)
            _, _, hist = macd(c)
            last = candles[-1]
            candle_dir = candle_direction(last)
            body = candle_body_strength(last)
            local_score = 0

            if direction == "LONG":
                if c[-1] >= e50[-1]:
                    local_score += 25
                if c[-1] >= e20[-1] or e20[-1] >= e50[-1]:
                    local_score += 20
                if rs[-1] >= 48 and (rs[-1] >= rs[-2] or rs[-1] >= 54):
                    local_score += 25
                if hist[-1] >= hist[-2] or hist[-1] > 0:
                    local_score += 15
                if candle_dir != "SHORT" or body < 0.55:
                    local_score += 15
            else:
                if c[-1] <= e50[-1]:
                    local_score += 25
                if c[-1] <= e20[-1] or e20[-1] <= e50[-1]:
                    local_score += 20
                if rs[-1] <= 52 and (rs[-1] <= rs[-2] or rs[-1] <= 46):
                    local_score += 25
                if hist[-1] <= hist[-2] or hist[-1] < 0:
                    local_score += 15
                if candle_dir != "LONG" or body < 0.55:
                    local_score += 15

            score += int(local_score * (weight / 100))
            if local_score >= 60:
                reasons.append(f"ورود {label} با جهت روزانه هماهنگ است.")

        allowed = score >= 55
        if not allowed:
            reasons.append(f"ترکیب 15M و 5M هنوز برای ورود کافی نیست. score={score}")
        return EntryDecision(allowed, min(100, score), reasons)

    def _build_daily_tp_sl(self, entry: float, direction: Direction, levels: list[Level]) -> tuple[float, float] | None:
        """Build one 1D TP and one SL with fixed RR.

        اولویت با سطح‌های روزانه است. اگر سطح تکراری/واضح پیدا نشود ولی جهت و
        ورود تایید شده باشند، از تارگت پروجکشن روزانه با حداقل ۳٪ استفاده می‌کند
        تا ربات به خاطر نبودن سطح کامل، کامل خشک نشود.
        """
        min_tp = max(float(self.min_tp_pct), 3.0)

        if direction == "LONG":
            candidates = [l for l in levels if l.kind == "resistance" and pct_change(entry, l.price, "LONG") >= min_tp]
            if candidates:
                tp = min(candidates, key=lambda l: l.price).price
            else:
                tp = entry * (1.0 + min_tp / 100.0)
            reward_pct = pct_change(entry, tp, "LONG")
            if reward_pct < min_tp:
                return None
            sl = entry * (1.0 - (reward_pct / self.rr) / 100.0)
            return tp, sl

        candidates = [l for l in levels if l.kind == "support" and pct_change(entry, l.price, "SHORT") >= min_tp]
        if candidates:
            tp = max(candidates, key=lambda l: l.price).price
        else:
            tp = entry * (1.0 - min_tp / 100.0)
        reward_pct = pct_change(entry, tp, "SHORT")
        if reward_pct < min_tp:
            return None
        sl = entry * (1.0 + (reward_pct / self.rr) / 100.0)
        return tp, sl
