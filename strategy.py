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

        btc_bias = self.daily_bias(btc_1d)
        eth_bias = self.daily_bias(eth_1d)
        if btc_bias.direction != symbol_bias.direction:
            return NoSignal(base_symbol, "بیتکوین با جهت روزانه ارز هم‌جهت نیست.")
        if eth_bias.direction != symbol_bias.direction:
            return NoSignal(base_symbol, "اتریوم با جهت روزانه ارز هم‌جهت نیست.")

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

        score = min(100, int(symbol_bias.score * 0.65 + entry_decision.score * 0.35))
        if score < config.SIGNAL_THRESHOLD:
            return NoSignal(base_symbol, f"امتیاز نهایی کمتر از حداقل {config.SIGNAL_THRESHOLD} است.")

        reasons = symbol_bias.reasons + ["BTC و ETH روی 1D هم‌جهت هستند."] + entry_decision.reasons
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
        if len(candles) < 60:
            return DailyBias(None, 0, ["کندل روزانه کافی نیست."], [])
        c = closes(candles)
        last = candles[-1]
        ema50 = ema(c, 50)
        ema200 = ema(c, 200) if len(c) >= 200 else ema(c, 100)
        r = rsi(c, 14)
        _, _, hist = macd(c)
        levels = detect_levels(candles[-180:], min_touches=3)

        long_score = 0
        short_score = 0
        long_reasons: list[str] = []
        short_reasons: list[str] = []

        # Structure using recent closes and swing tendency.
        recent = c[-20:]
        if recent[-1] > max(recent[:10]):
            long_score += 22
            long_reasons.append("ساختار روزانه تمایل صعودی دارد.")
        if recent[-1] < min(recent[:10]):
            short_score += 22
            short_reasons.append("ساختار روزانه تمایل نزولی دارد.")

        if c[-1] > ema50[-1] and ema50[-1] > ema200[-1] and ema50[-1] > ema50[-5]:
            long_score += 25
            long_reasons.append("قیمت بالای EMA50 و روند میانگین‌ها صعودی است.")
        if c[-1] < ema50[-1] and ema50[-1] < ema200[-1] and ema50[-1] < ema50[-5]:
            short_score += 25
            short_reasons.append("قیمت پایین EMA50 و روند میانگین‌ها نزولی است.")

        body = candle_body_strength(last)
        last_dir = candle_direction(last)
        if last_dir == "LONG" and body >= 0.45:
            long_score += 15
            long_reasons.append("کندل روزانه قدرت صعودی دارد.")
        if last_dir == "SHORT" and body >= 0.45:
            short_score += 15
            short_reasons.append("کندل روزانه قدرت نزولی دارد.")

        avg_vol = average_volume(candles, 20)
        if avg_vol > 0 and last.volume >= avg_vol * 0.8:
            if last_dir == "LONG":
                long_score += 10
                long_reasons.append("حجم روزانه با حرکت صعودی مخالف نیست.")
            elif last_dir == "SHORT":
                short_score += 10
                short_reasons.append("حجم روزانه با حرکت نزولی مخالف نیست.")
            else:
                long_score += 4
                short_score += 4

        if r[-1] > 52 and hist[-1] >= hist[-2]:
            long_score += 18
            long_reasons.append("RSI/MACD روزانه صعود را تایید می‌کند.")
        if r[-1] < 48 and hist[-1] <= hist[-2]:
            short_score += 18
            short_reasons.append("RSI/MACD روزانه نزول را تایید می‌کند.")

        # Support/resistance context.
        support = nearest_level_below(levels, c[-1], "support")
        resistance = nearest_level_above(levels, c[-1], "resistance")
        if support and pct_distance(c[-1], support.price) <= 8:
            long_score += 10
            long_reasons.append("قیمت بالای حمایت معتبر روزانه قرار دارد.")
        if resistance and pct_distance(c[-1], resistance.price) <= 8:
            short_score += 10
            short_reasons.append("قیمت زیر مقاومت معتبر روزانه قرار دارد.")

        if long_score >= 75 and long_score > short_score + 10:
            return DailyBias("LONG", min(100, long_score), long_reasons, levels)
        if short_score >= 75 and short_score > long_score + 10:
            return DailyBias("SHORT", min(100, short_score), short_reasons, levels)
        return DailyBias(None, max(long_score, short_score), ["جهت روزانه به اندازه کافی واضح نیست."], levels)

    def entry_confirmation(self, direction: Direction, candles_15m: list[Candle], candles_5m: list[Candle]) -> EntryDecision:
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
            local_score = 0
            if direction == "LONG":
                if c[-1] >= e20[-1] >= e50[-1]:
                    local_score += 30
                if 45 <= rs[-1] <= 70 and rs[-1] >= rs[-2]:
                    local_score += 25
                if hist[-1] >= hist[-2]:
                    local_score += 20
                if candle_dir == "LONG" and candle_body_strength(last) >= 0.35:
                    local_score += 25
            else:
                if c[-1] <= e20[-1] <= e50[-1]:
                    local_score += 30
                if 30 <= rs[-1] <= 55 and rs[-1] <= rs[-2]:
                    local_score += 25
                if hist[-1] <= hist[-2]:
                    local_score += 20
                if candle_dir == "SHORT" and candle_body_strength(last) >= 0.35:
                    local_score += 25
            score += int(local_score * (weight / 100))
            if local_score >= 70:
                reasons.append(f"ورود {label} در جهت سیگنال تایید شد.")
        allowed = score >= 70
        if not allowed:
            reasons.append("ترکیب 15M و 5M هنوز برای ماشه ورود کافی نیست.")
        return EntryDecision(allowed, min(100, score), reasons)

    def _build_daily_tp_sl(self, entry: float, direction: Direction, levels: list[Level]) -> tuple[float, float] | None:
        if direction == "LONG":
            candidates = [l for l in levels if l.kind == "resistance" and pct_change(entry, l.price, "LONG") >= self.min_tp_pct]
            if not candidates:
                return None
            tp = min(candidates, key=lambda l: l.price).price
            reward_pct = pct_change(entry, tp, "LONG")
            sl = entry * (1.0 - (reward_pct / self.rr) / 100.0)
            return tp, sl
        candidates = [l for l in levels if l.kind == "support" and pct_change(entry, l.price, "SHORT") >= self.min_tp_pct]
        if not candidates:
            return None
        tp = max(candidates, key=lambda l: l.price).price
        reward_pct = pct_change(entry, tp, "SHORT")
        sl = entry * (1.0 + (reward_pct / self.rr) / 100.0)
        return tp, sl
