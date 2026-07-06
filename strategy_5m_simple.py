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
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class DirectionScore:
    direction: Direction | None
    score: float
    reasons: tuple[str, ...]


class Simple5MScalperStrategy:
    """Simple score-based 5M scalper.

    Hard rules:
    - 4H and 1H must align.
    - 5M is the entry timeframe.
    - No candle confirmation, because in 5M the confirmation candle can be the profit.
    - score >= 70 emits a signal.
    - RR is 1.5.
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

        anti_chase_reason = self._anti_chase_reject(direction, s5m, candles_5m)
        if anti_chase_reason:
            # Trend may be right, but the 5M entry is late/tired.
            # Hard reject so the bot does not buy the top or short the bottom.
            return self._reject("رد شد: ورود دیر/خسته در 5M - " + anti_chase_reason)

        score, reasons = self._score(direction, s4h, s1h, s5m)
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

        # 5M scalping guard rails.
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

        reasons = list(reasons)
        reasons.append("فیلتر ضد دیر ورود پاس شد: قیمت خسته/دور از EMA50 و VWAP نیست")
        reasons.append(f"TP/SL مخصوص 5M | SL={sl_pct * 100:.2f}% | TP={tp_pct * 100:.2f}%")
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
            return DirectionScore("LONG", 20.0, tuple(reasons))
        if s.close < s.ema200 and s.ema50 < s.ema200:
            reasons.append(f"{label} نزولی: قیمت و EMA50 زیر EMA200")
            return DirectionScore("SHORT", 20.0, tuple(reasons))
        return DirectionScore(None, 0.0, tuple(reasons))

    def _anti_chase_reject(self, direction: Direction, s5m: Snapshot, candles_5m: list[Candle]) -> str | None:
        if not bool(config.ANTI_CHASE_ENABLED):
            return None
        close = float(s5m.close or 0.0)
        ema50 = float(s5m.ema50 or 0.0)
        vwap = float(s5m.vwap or 0.0)
        if close <= 0:
            return "invalid_close"

        ema50_distance = abs(close - ema50) / close if ema50 > 0 else 0.0
        vwap_distance = abs(close - vwap) / close if vwap > 0 else 0.0

        # Directional move of the last three completed 5M candles.
        three_candle_move = 0.0
        if len(candles_5m) >= 4:
            base = float(candles_5m[-4].close or 0.0)
            if base > 0:
                if direction == "LONG":
                    three_candle_move = max(0.0, (close - base) / base)
                else:
                    three_candle_move = max(0.0, (base - close) / base)

        if direction == "LONG":
            if float(s5m.rsi) > float(config.ANTI_CHASE_LONG_MAX_RSI):
                return f"anti_chase_rsi_tired_long:{s5m.rsi:.2f}"
            if ema50 > 0 and close > ema50 and ema50_distance > float(config.ANTI_CHASE_MAX_EMA50_DISTANCE_PCT):
                return f"anti_chase_far_from_ema50_long:{ema50_distance * 100:.2f}%"
            if vwap > 0 and close > vwap and vwap_distance > float(config.ANTI_CHASE_MAX_VWAP_DISTANCE_PCT):
                return f"anti_chase_far_from_vwap_long:{vwap_distance * 100:.2f}%"
            if three_candle_move > float(config.ANTI_CHASE_MAX_3CANDLE_MOVE_PCT):
                return f"anti_chase_3candle_move_long:{three_candle_move * 100:.2f}%"
        else:
            if float(s5m.rsi) < float(config.ANTI_CHASE_SHORT_MIN_RSI):
                return f"anti_chase_rsi_tired_short:{s5m.rsi:.2f}"
            if ema50 > 0 and close < ema50 and ema50_distance > float(config.ANTI_CHASE_MAX_EMA50_DISTANCE_PCT):
                return f"anti_chase_far_from_ema50_short:{ema50_distance * 100:.2f}%"
            if vwap > 0 and close < vwap and vwap_distance > float(config.ANTI_CHASE_MAX_VWAP_DISTANCE_PCT):
                return f"anti_chase_far_from_vwap_short:{vwap_distance * 100:.2f}%"
            if three_candle_move > float(config.ANTI_CHASE_MAX_3CANDLE_MOVE_PCT):
                return f"anti_chase_3candle_move_short:{three_candle_move * 100:.2f}%"

        return None

    def _score(self, direction: Direction, s4h: Snapshot, s1h: Snapshot, s5m: Snapshot) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        # 4H direction: 20
        if direction == "LONG" and s4h.close > s4h.ema200:
            score += 10
            reasons.append("10 امتیاز: 4H قیمت بالای EMA200")
        if direction == "LONG" and s4h.ema50 > s4h.ema200:
            score += 10
            reasons.append("10 امتیاز: 4H EMA50 بالای EMA200")
        if direction == "SHORT" and s4h.close < s4h.ema200:
            score += 10
            reasons.append("10 امتیاز: 4H قیمت زیر EMA200")
        if direction == "SHORT" and s4h.ema50 < s4h.ema200:
            score += 10
            reasons.append("10 امتیاز: 4H EMA50 زیر EMA200")

        # 1H direction: 20
        if direction == "LONG" and s1h.close > s1h.ema200:
            score += 10
            reasons.append("10 امتیاز: 1H قیمت بالای EMA200")
        if direction == "LONG" and s1h.ema50 > s1h.ema200:
            score += 10
            reasons.append("10 امتیاز: 1H EMA50 بالای EMA200")
        if direction == "SHORT" and s1h.close < s1h.ema200:
            score += 10
            reasons.append("10 امتیاز: 1H قیمت زیر EMA200")
        if direction == "SHORT" and s1h.ema50 < s1h.ema200:
            score += 10
            reasons.append("10 امتیاز: 1H EMA50 زیر EMA200")

        # 5M EMA: 20
        if direction == "LONG":
            if s5m.close > s5m.ema200:
                score += 7
                reasons.append("7 امتیاز: 5M قیمت بالای EMA200")
            if s5m.ema50 > s5m.ema200:
                score += 7
                reasons.append("7 امتیاز: 5M EMA50 بالای EMA200")
            if s5m.close > s5m.ema50:
                score += 6
                reasons.append("6 امتیاز: 5M قیمت بالای EMA50")
        else:
            if s5m.close < s5m.ema200:
                score += 7
                reasons.append("7 امتیاز: 5M قیمت زیر EMA200")
            if s5m.ema50 < s5m.ema200:
                score += 7
                reasons.append("7 امتیاز: 5M EMA50 زیر EMA200")
            if s5m.close < s5m.ema50:
                score += 6
                reasons.append("6 امتیاز: 5M قیمت زیر EMA50")

        # RSI 5M: 15. No candle confirmation.
        if direction == "LONG":
            if s5m.rsi > 75:
                reasons.append("رد نرم: RSI 5M بالای 75 است")
                return 0.0, reasons
            if 52 <= s5m.rsi <= 70:
                score += 10
                reasons.append("10 امتیاز: RSI 5M در محدوده لانگ 52 تا 70")
            elif 50 < s5m.rsi < 75:
                score += 6
                reasons.append("6 امتیاز: RSI 5M بالای 50")
            if s5m.rsi > s5m.prev_rsi:
                score += 5
                reasons.append("5 امتیاز: RSI 5M رو به بالا")
        else:
            if s5m.rsi < 25:
                reasons.append("رد نرم: RSI 5M زیر 25 است")
                return 0.0, reasons
            if 30 <= s5m.rsi <= 48:
                score += 10
                reasons.append("10 امتیاز: RSI 5M در محدوده شورت 30 تا 48")
            elif 25 < s5m.rsi < 50:
                score += 6
                reasons.append("6 امتیاز: RSI 5M زیر 50")
            if s5m.rsi < s5m.prev_rsi:
                score += 5
                reasons.append("5 امتیاز: RSI 5M رو به پایین")

        # MACD 5M: 15
        if direction == "LONG":
            if s5m.macd > s5m.macd_signal:
                score += 8
                reasons.append("8 امتیاز: MACD 5M بالای Signal")
            if s5m.macd_hist > 0 or s5m.macd_hist >= s5m.prev_macd_hist:
                score += 7
                reasons.append("7 امتیاز: Histogram 5M مثبت/روبه‌رشد")
        else:
            if s5m.macd < s5m.macd_signal:
                score += 8
                reasons.append("8 امتیاز: MACD 5M زیر Signal")
            if s5m.macd_hist < 0 or s5m.macd_hist <= s5m.prev_macd_hist:
                score += 7
                reasons.append("7 امتیاز: Histogram 5M منفی/روبه‌رشد نزولی")

        # VWAP 5M: 5
        if direction == "LONG" and s5m.close > s5m.vwap:
            score += 5
            reasons.append("5 امتیاز: قیمت 5M بالای VWAP")
        elif direction == "SHORT" and s5m.close < s5m.vwap:
            score += 5
            reasons.append("5 امتیاز: قیمت 5M زیر VWAP")

        # ATR/SL quality 5M: 5
        atr_pct = s5m.atr / s5m.close if s5m.close > 0 else 0.0
        if float(config.MIN_5M_SL_PCT) <= max(atr_pct, float(config.MIN_5M_SL_PCT)) <= float(config.MAX_5M_SL_PCT):
            score += 5
            reasons.append("5 امتیاز: ATR/SL پنج دقیقه‌ای منطقی")

        return clamp(score, 0, 100), reasons

    def _make_5m_sl(self, direction: Direction, s: Snapshot, entry: float) -> float:
        atr_stop = float(s.atr) * float(config.ATR_SL_MULT)
        if direction == "LONG":
            swing_stop = max(0.0, entry - float(s.swing_low))
            risk = max(atr_stop, swing_stop, entry * float(config.MIN_5M_SL_PCT))
            return entry - risk
        swing_stop = max(0.0, float(s.swing_high) - entry)
        risk = max(atr_stop, swing_stop, entry * float(config.MIN_5M_SL_PCT))
        return entry + risk
