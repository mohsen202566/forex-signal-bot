from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import config
from indicators import Snapshot, snapshot
from okx_data import Candle
from utils import clamp, okx_swap_symbol

Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class SignalPlan:
    symbol: str
    okx_symbol: str
    toobit_symbol: str
    direction: Direction
    score: float
    strength: str
    entry_price: float
    tp_price: float
    sl_price: float
    risk_reward: float
    sl_pct: float
    tp_pct: float
    estimated_profit_usdt: float
    estimated_loss_usdt: float
    estimated_net_profit_usdt: float
    round_trip_fee_usdt: float
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_legacy_dict(self) -> dict[str, object]:
        return {
            "coin": self.symbol,
            "symbol": self.symbol,
            "okx_symbol": self.okx_symbol,
            "toobit_symbol": self.toobit_symbol,
            "direction": self.direction,
            "side": "BUY" if self.direction == "LONG" else "SELL",
            "score": self.score,
            "confidence": self.score,
            "entry": self.entry_price,
            "entry_price": self.entry_price,
            "tp": self.tp_price,
            "tp_price": self.tp_price,
            "sl": self.sl_price,
            "sl_price": self.sl_price,
            "risk_reward": self.risk_reward,
            "tp_percent": self.tp_pct,
            "sl_percent": self.sl_pct,
            "estimated_profit_usdt": self.estimated_profit_usdt,
            "estimated_loss_usdt": self.estimated_loss_usdt,
            "estimated_net_profit_usdt": self.estimated_net_profit_usdt,
            "round_trip_fee_usdt": self.round_trip_fee_usdt,
            "strength": self.strength,
            "timeframe": "5M",
            "entry_model": "Compression Breakout",
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class DirectionScore:
    direction: Direction | None
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EntryScore:
    score: float
    reasons: tuple[str, ...]


class Simple5MScalperStrategy:
    """5M scalper with Compression Breakout entry.

    Hard rules:
    - 4H and 1H must align for direction.
    - 5M entry is not a generic indicator score anymore.
    - Entry happens only when price breaks out of a recent 5M compression box
      with a strong body, volume expansion, fresh RSI/MACD and anti-late checks.
    - RR stays 1.5 by default.
    - TP/SL are based only on 5M ATR/swing, not 1H or 4H.
    - Net profit after round-trip fee must be at least the panel minimum.
    - No support/resistance, no AI, no DCA, no martingale, no trailing.
    """

    def __init__(self) -> None:
        self.min_score = float(config.SIGNAL_SCORE_THRESHOLD)
        self.strong_score = float(config.STRONG_SCORE_THRESHOLD)
        self.last_reject_reason = ""

    def _reject(self, reason: str) -> None:
        self.last_reject_reason = str(reason)[:300]
        return None

    def analyze(
        self,
        symbol: str,
        candles_4h: list[Candle],
        candles_1h: list[Candle],
        candles_5m: list[Candle],
        *,
        margin_usdt: float,
        leverage: int,
        min_net_profit_usdt: float,
        toobit_symbol: str | None = None,
        round_trip_fee_usdt: float = config.ROUND_TRIP_FEE_USDT,
    ) -> SignalPlan | None:
        self.last_reject_reason = ""
        s4h = snapshot(candles_4h, swing_lookback=8)
        s1h = snapshot(candles_1h, swing_lookback=8)
        s5m = snapshot(
            candles_5m,
            swing_lookback=config.SWING_LOOKBACK_5M,
            vwap_lookback=config.VWAP_LOOKBACK_5M,
            volume_lookback=config.VOLUME_LOOKBACK_5M,
        )

        d4 = self._direction_filter("4H", s4h)
        d1 = self._direction_filter("1H", s1h)
        if d4.direction is None:
            return self._reject("رد شد: جهت 4H خنثی است")
        if d1.direction is None:
            return self._reject("رد شد: جهت 1H خنثی است")
        if d4.direction != d1.direction:
            return self._reject(f"رد شد: 4H و 1H همسو نیستند ({d4.direction} / {d1.direction})")

        direction: Direction = d4.direction
        entry_score = self._compression_breakout_entry(direction, s5m, candles_5m)
        if entry_score is None:
            return None

        score = clamp(d4.score + d1.score + entry_score.score, 0, 100)
        if score < self.min_score:
            return self._reject(f"رد شد: امتیاز کم است ({score:.1f}/{self.min_score:g})")

        rr = float(config.RR_STRONG if score >= self.strong_score else config.RR_NORMAL)
        strength = "قوی" if score >= self.strong_score else "معمولی"
        entry = s5m.close
        sl = self._make_5m_sl(direction, s5m, entry)
        if sl <= 0 or sl == entry:
            return self._reject("رد شد: SL پنج دقیقه‌ای نامعتبر است")
        risk = entry - sl if direction == "LONG" else sl - entry
        if risk <= 0:
            return self._reject("رد شد: ریسک معامله نامعتبر است")
        sl_pct = risk / entry

        if sl_pct > float(config.MAX_5M_SL_PCT):
            return self._reject(f"رد شد: SL پنج دقیقه‌ای زیادی بزرگ است ({sl_pct * 100:.2f}%)")
        if sl_pct < float(config.MIN_5M_SL_PCT):
            risk = entry * float(config.MIN_5M_SL_PCT)
            sl = entry - risk if direction == "LONG" else entry + risk
            sl_pct = risk / entry

        tp = entry + risk * rr if direction == "LONG" else entry - risk * rr
        tp_pct = abs(tp - entry) / entry
        notional = max(0.0, float(margin_usdt)) * max(1, int(leverage))
        gross_profit = notional * tp_pct
        gross_loss = notional * sl_pct
        net_profit = gross_profit - float(round_trip_fee_usdt)
        if net_profit < float(min_net_profit_usdt):
            return self._reject(f"رد شد: سود خالص بعد کارمزد کم است ({net_profit:.4f} USDT)")

        reasons = list(d4.reasons) + list(d1.reasons) + list(entry_score.reasons)
        reasons.append(f"TP/SL مخصوص 5M | RR={rr:g} | SL={sl_pct * 100:.2f}% | TP={tp_pct * 100:.2f}%")
        reasons.append(f"حداقل سود خالص پاس شد: {net_profit:.4f} USDT")

        return SignalPlan(
            symbol=symbol.upper(),
            okx_symbol=okx_swap_symbol(symbol),
            toobit_symbol=(toobit_symbol or symbol).upper(),
            direction=direction,
            score=round(score, 2),
            strength=strength,
            entry_price=float(entry),
            tp_price=float(tp),
            sl_price=float(sl),
            risk_reward=rr,
            sl_pct=float(sl_pct),
            tp_pct=float(tp_pct),
            estimated_profit_usdt=float(gross_profit),
            estimated_loss_usdt=float(gross_loss),
            estimated_net_profit_usdt=float(net_profit),
            round_trip_fee_usdt=float(round_trip_fee_usdt),
            reasons=tuple(reasons),
        )

    def _direction_filter(self, label: str, s: Snapshot) -> DirectionScore:
        reasons: list[str] = []
        if s.close > s.ema200 and s.ema50 > s.ema200:
            reasons.append(f"{label} صعودی: قیمت و EMA50 بالای EMA200")
            return DirectionScore("LONG", 15.0, tuple(reasons))
        if s.close < s.ema200 and s.ema50 < s.ema200:
            reasons.append(f"{label} نزولی: قیمت و EMA50 زیر EMA200")
            return DirectionScore("SHORT", 15.0, tuple(reasons))
        return DirectionScore(None, 0.0, tuple(reasons))

    def _compression_breakout_entry(self, direction: Direction, s5m: Snapshot, candles_5m: list[Candle]) -> EntryScore | None:
        if not bool(config.COMPRESSION_BREAKOUT_ENABLED):
            return self._reject("رد شد: ورود Compression Breakout خاموش است")

        lookback = max(3, int(config.BREAKOUT_LOOKBACK_5M))
        if len(candles_5m) < lookback + 2:
            return self._reject("رد شد: کندل کافی برای بررسی شکست فشردگی وجود ندارد")

        last = candles_5m[-1]
        previous = candles_5m[-lookback - 1:-1]
        close = float(s5m.close or last.close or 0.0)
        if close <= 0:
            return self._reject("رد شد: قیمت ورود نامعتبر است")

        prev_high = max(float(c.high) for c in previous)
        prev_low = min(float(c.low) for c in previous)
        compression_range_pct = (prev_high - prev_low) / close if close > 0 else 0.0
        max_pre_range = float(config.BREAKOUT_MAX_PRE_RANGE_PCT)
        if compression_range_pct <= 0 or compression_range_pct > max_pre_range:
            return self._reject(
                f"رد شد: فشردگی کافی قبل از شکست نیست ({compression_range_pct * 100:.2f}% > {max_pre_range * 100:.2f}%)"
            )

        break_buffer = float(config.BREAKOUT_MIN_BREAK_PCT)
        if direction == "LONG":
            required_break = prev_high * (1 + break_buffer)
            if close <= required_break:
                return self._reject(
                    f"رد شد: شکست معتبر سقف فشردگی رخ نداده است (close<=high+buffer | {break_buffer * 100:.2f}%)"
                )
        else:
            required_break = prev_low * (1 - break_buffer)
            if close >= required_break:
                return self._reject(
                    f"رد شد: شکست معتبر کف فشردگی رخ نداده است (close>=low-buffer | {break_buffer * 100:.2f}%)"
                )

        candle_range = max(0.0, float(last.high) - float(last.low))
        if candle_range <= 0:
            return self._reject("رد شد: کندل شکست رنج معتبر ندارد")
        body = abs(float(last.close) - float(last.open))
        body_ratio = body / candle_range
        min_body = float(config.BREAKOUT_MIN_BODY_RATIO)
        if body_ratio < min_body:
            return self._reject(f"رد شد: بدنه کندل شکست ضعیف است ({body_ratio * 100:.0f}% < {min_body * 100:.0f}%)")

        close_position = (float(last.close) - float(last.low)) / candle_range
        min_close_pos = float(config.BREAKOUT_MIN_CLOSE_POSITION)
        if direction == "LONG":
            if float(last.close) <= float(last.open):
                return self._reject("رد شد: کندل شکست لانگ سبز/صعودی نیست")
            if close_position < min_close_pos:
                return self._reject(f"رد شد: بسته شدن کندل لانگ نزدیک سقف نیست ({close_position * 100:.0f}%)")
        else:
            if float(last.close) >= float(last.open):
                return self._reject("رد شد: کندل شکست شورت قرمز/نزولی نیست")
            if close_position > (1 - min_close_pos):
                return self._reject(f"رد شد: بسته شدن کندل شورت نزدیک کف نیست ({(1 - close_position) * 100:.0f}%)")

        min_volume = float(config.BREAKOUT_MIN_VOLUME_RATIO)
        if float(s5m.volume_ratio) < min_volume:
            return self._reject(f"رد شد: حجم پشت شکست کافی نیست ({s5m.volume_ratio:.2f}x < {min_volume:.2f}x)")

        if direction == "LONG":
            if not (float(config.BREAKOUT_LONG_RSI_MIN) <= float(s5m.rsi) <= float(config.BREAKOUT_LONG_RSI_MAX)):
                return self._reject(f"رد شد: RSI لانگ تازه/غیرخسته نیست ({s5m.rsi:.2f})")
            if float(s5m.macd_hist) <= float(s5m.prev_macd_hist):
                return self._reject("رد شد: MACD Histogram لانگ تازه بهتر نشده")
            if not (close > float(s5m.ema20) and close > float(s5m.vwap)):
                return self._reject("رد شد: شکست لانگ بالای EMA20 و VWAP تثبیت نشده")
        else:
            if not (float(config.BREAKOUT_SHORT_RSI_MIN) <= float(s5m.rsi) <= float(config.BREAKOUT_SHORT_RSI_MAX)):
                return self._reject(f"رد شد: RSI شورت تازه/غیرخسته نیست ({s5m.rsi:.2f})")
            if float(s5m.macd_hist) >= float(s5m.prev_macd_hist):
                return self._reject("رد شد: MACD Histogram شورت تازه ضعیف‌تر نشده")
            if not (close < float(s5m.ema20) and close < float(s5m.vwap)):
                return self._reject("رد شد: شکست شورت زیر EMA20 و VWAP تثبیت نشده")

        three_candle_move = self._directional_3candle_move(direction, candles_5m, close)
        max_3move = float(config.BREAKOUT_MAX_3CANDLE_MOVE_PCT)
        if three_candle_move > max_3move:
            return self._reject(f"رد شد: حرکت سه کندل اخیر زیادی انجام شده ({three_candle_move * 100:.2f}% > {max_3move * 100:.2f}%)")

        ema50_distance = abs(close - float(s5m.ema50)) / close if float(s5m.ema50) > 0 else 0.0
        vwap_distance = abs(close - float(s5m.vwap)) / close if float(s5m.vwap) > 0 else 0.0
        max_ema = float(config.BREAKOUT_MAX_EMA50_DISTANCE_PCT)
        max_vwap = float(config.BREAKOUT_MAX_VWAP_DISTANCE_PCT)
        if ema50_distance > max_ema and vwap_distance > max_vwap:
            return self._reject(
                f"رد شد: شکست معتبر است ولی ورود دیر شده؛ قیمت از EMA50/VWAP دور است ({ema50_distance * 100:.2f}%/{vwap_distance * 100:.2f}%)"
            )

        reasons = [
            f"12 امتیاز: فشردگی {lookback} کندل قبل از شکست ({compression_range_pct * 100:.2f}%)",
            "18 امتیاز: شکست معتبر محدوده فشرده در جهت 4H/1H",
            f"15 امتیاز: کندل شکست قوی | body={body_ratio * 100:.0f}%",
            f"10 امتیاز: حجم پشت شکست {s5m.volume_ratio:.2f}x",
            f"10 امتیاز: RSI تازه و غیرخسته ({s5m.rsi:.1f})",
            "10 امتیاز: MACD Histogram تازه در جهت معامله بهتر شد",
            f"5 امتیاز: ضد دیر ورود پاس شد | 3 کندل={three_candle_move * 100:.2f}%",
        ]
        return EntryScore(70.0, tuple(reasons))

    @staticmethod
    def _directional_3candle_move(direction: Direction, candles_5m: list[Candle], close: float) -> float:
        if len(candles_5m) < 4:
            return 0.0
        base = float(candles_5m[-4].close or 0.0)
        if base <= 0:
            return 0.0
        if direction == "LONG":
            return max(0.0, (close - base) / base)
        return max(0.0, (base - close) / base)

    def _make_5m_sl(self, direction: Direction, s: Snapshot, entry: float) -> float:
        atr_stop = float(s.atr) * float(config.ATR_SL_MULT)
        if direction == "LONG":
            swing_stop = max(0.0, entry - float(s.swing_low))
            risk = max(atr_stop, swing_stop, entry * float(config.MIN_5M_SL_PCT))
            return entry - risk
        swing_stop = max(0.0, float(s.swing_high) - entry)
        risk = max(atr_stop, swing_stop, entry * float(config.MIN_5M_SL_PCT))
        return entry + risk
