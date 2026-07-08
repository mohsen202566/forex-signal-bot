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
    entry_model: str = "HMT-5 Trap Hunt"
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
            "timeframe": "5M setup / 1M trigger",
            "entry_model": self.entry_model,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class DirectionScore:
    direction: Direction | None
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SetupScore:
    kind: str
    level: float
    sl_anchor: float
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TriggerScore:
    entry: float
    score: float
    reasons: tuple[str, ...]


class Simple5MScalperStrategy:
    """HMT-5 Trap Hunt scalper.

    Hard rules:
    - 1H gives the main direction and 15M confirms momentum.
    - 4H is only a danger filter; it does not choke every setup.
    - 5M creates only hunting context; direct entry on 5M is forbidden.
    - The preferred edge is trap/sweep/reclaim: enter after the market fails to continue the fake move.
    - 1M must give the final trap/reclaim trigger before entry.
    - SL is placed behind the 1M trigger/trap wick and capped for scalping.
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
        candles_15m: list[Candle],
        candles_5m: list[Candle],
        candles_1m: list[Candle],
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
        s15m = snapshot(candles_15m, swing_lookback=8)
        s5m = snapshot(
            candles_5m,
            swing_lookback=config.SWING_LOOKBACK_5M,
            vwap_lookback=config.VWAP_LOOKBACK_5M,
            volume_lookback=config.VOLUME_LOOKBACK_5M,
        )
        s1m = snapshot(
            candles_1m,
            swing_lookback=max(5, int(config.TRIGGER_SL_LOOKBACK_1M)),
            vwap_lookback=min(48, max(20, int(config.VWAP_LOOKBACK_5M))),
            volume_lookback=max(10, int(config.VOLUME_LOOKBACK_5M)),
        )

        d1h = self._direction_filter("1H", s1h, min_flags=int(config.DIRECTION_MIN_FLAGS_1H), score=20.0)
        d15m = self._direction_filter("15M", s15m, min_flags=int(config.DIRECTION_MIN_FLAGS_15M), score=20.0)
        if d1h.direction is None:
            return self._reject("رد شد: جهت 1H برای اسکالپ واضح نیست")
        if d15m.direction is None:
            return self._reject("رد شد: جهت 15M برای ورود واضح نیست")
        if d1h.direction != d15m.direction:
            return self._reject(f"رد شد: 1H و 15M همسو نیستند ({d1h.direction} / {d15m.direction})")

        direction: Direction = d1h.direction
        danger = self._danger_4h_against(direction, s4h)
        if danger:
            return self._reject("رد شد: 4H شدیداً خلاف معامله است - " + danger)

        dead_market = self._dead_market_reject(s5m)
        if dead_market:
            return self._reject("رد شد: بازار 5M حرکت قابل استفاده ندارد - " + dead_market)

        setup = self._find_5m_setup(direction, candles_5m, s5m)
        if setup is None:
            return None

        trigger = self._trigger_1m(direction, setup, candles_1m, s1m)
        if trigger is None:
            return None

        entry = float(trigger.entry)
        sl = self._make_trigger_sl(direction, setup, candles_1m, entry)
        if sl <= 0 or sl == entry:
            return self._reject("رد شد: SL تریگر نامعتبر است")
        risk = entry - sl if direction == "LONG" else sl - entry
        if risk <= 0:
            return self._reject("رد شد: ریسک معامله نامعتبر است")
        sl_pct = risk / entry

        if sl_pct > float(config.MAX_5M_SL_PCT):
            return self._reject(f"رد شد: SL برای اسکالپ بزرگ است ({sl_pct * 100:.2f}% > {float(config.MAX_5M_SL_PCT) * 100:.2f}%)")
        if sl_pct < float(config.MIN_5M_SL_PCT):
            risk = entry * float(config.MIN_5M_SL_PCT)
            sl = entry - risk if direction == "LONG" else entry + risk
            sl_pct = risk / entry

        score = clamp(d1h.score + d15m.score + 5.0 + setup.score + trigger.score, 0, 100)
        if score < self.min_score:
            return self._reject(f"رد شد: امتیاز کم است ({score:.1f}/{self.min_score:g})")

        rr = float(config.RR_STRONG if score >= self.strong_score else config.RR_NORMAL)
        strength = "قوی" if score >= self.strong_score else "معمولی"
        tp = entry + risk * rr if direction == "LONG" else entry - risk * rr
        tp_pct = abs(tp - entry) / entry
        notional = max(0.0, float(margin_usdt)) * max(1, int(leverage))
        gross_profit = notional * tp_pct
        gross_loss = notional * sl_pct
        net_profit = gross_profit - float(round_trip_fee_usdt)
        if net_profit < float(min_net_profit_usdt):
            return self._reject(f"رد شد: سود خالص بعد کارمزد کم است ({net_profit:.4f} USDT)")

        reasons = list(d1h.reasons) + list(d15m.reasons)
        reasons.append("4H خلاف شدید نبود؛ فقط فیلتر خطر پاس شد")
        reasons.extend(setup.reasons)
        reasons.extend(trigger.reasons)
        reasons.append(f"SL پشت wick/trigger | RR={rr:g} | SL={sl_pct * 100:.2f}% | TP={tp_pct * 100:.2f}%")
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
            entry_model="HMT-5 Trap Hunt | " + setup.kind + " + 1M",
            reasons=tuple(reasons),
        )

    def _direction_filter(self, label: str, s: Snapshot, *, min_flags: int, score: float) -> DirectionScore:
        close = float(s.close or 0.0)
        if close <= 0:
            return DirectionScore(None, 0.0, tuple())
        slope_pct = (float(s.ema50) - float(s.prev_ema50)) / close
        min_slope = float(config.DIRECTION_EMA50_SLOPE_MIN_PCT)

        long_flags: list[str] = []
        short_flags: list[str] = []

        if close > float(s.ema50):
            long_flags.append("قیمت بالای EMA50")
        if slope_pct > min_slope:
            long_flags.append(f"شیب EMA50 مثبت:{slope_pct * 100:.2f}%")
        if close > float(s.vwap):
            long_flags.append("قیمت بالای VWAP")
        if float(s.macd_hist) > float(s.prev_macd_hist):
            long_flags.append("MACD در حال بهتر شدن")
        if float(s.rsi) >= 50.0:
            long_flags.append(f"RSI بالای 50:{s.rsi:.1f}")

        if close < float(s.ema50):
            short_flags.append("قیمت زیر EMA50")
        if slope_pct < -min_slope:
            short_flags.append(f"شیب EMA50 منفی:{slope_pct * 100:.2f}%")
        if close < float(s.vwap):
            short_flags.append("قیمت زیر VWAP")
        if float(s.macd_hist) < float(s.prev_macd_hist):
            short_flags.append("MACD در حال ضعیف‌تر شدن")
        if float(s.rsi) <= 50.0:
            short_flags.append(f"RSI زیر 50:{s.rsi:.1f}")

        if len(long_flags) >= int(min_flags) and len(long_flags) > len(short_flags):
            return DirectionScore("LONG", score, (f"{label} صعودی: " + " | ".join(long_flags[:4]),))
        if len(short_flags) >= int(min_flags) and len(short_flags) > len(long_flags):
            return DirectionScore("SHORT", score, (f"{label} نزولی: " + " | ".join(short_flags[:4]),))
        return DirectionScore(None, 0.0, tuple())

    def _danger_4h_against(self, direction: Direction, s4h: Snapshot) -> str | None:
        if not bool(config.DANGER_4H_FILTER_ENABLED):
            return None
        close = float(s4h.close or 0.0)
        if close <= 0:
            return None
        slope_down = float(s4h.ema50) < float(s4h.prev_ema50)
        slope_up = float(s4h.ema50) > float(s4h.prev_ema50)
        strong_bull = close > float(s4h.ema200) and float(s4h.ema50) > float(s4h.ema200) and slope_up and float(s4h.rsi) >= 55.0
        strong_bear = close < float(s4h.ema200) and float(s4h.ema50) < float(s4h.ema200) and slope_down and float(s4h.rsi) <= 45.0
        if direction == "LONG" and strong_bear:
            return "4H نزولی قوی است"
        if direction == "SHORT" and strong_bull:
            return "4H صعودی قوی است"
        return None

    def _dead_market_reject(self, s5m: Snapshot) -> str | None:
        close = float(s5m.close or 0.0)
        if close <= 0:
            return "قیمت 5M نامعتبر است"

        # Softer dead-market guard:
        # Before, one quiet metric (low ATR OR low volume) blocked the coin immediately.
        # That choked the scanner in normal calm-before-move conditions.
        # Now we reject only when enough dead-market signs are present.
        flags: list[str] = []
        atr_pct = float(s5m.atr) / close if float(s5m.atr) > 0 else 0.0
        if atr_pct < float(config.MIN_5M_ATR_PCT):
            flags.append(f"ATR کم:{atr_pct * 100:.2f}%")
        if float(s5m.volume_ratio) < float(config.MIN_5M_VOLUME_RATIO):
            flags.append(f"حجم 5M مرده:{s5m.volume_ratio:.2f}x")

        if len(flags) >= int(config.DEAD_MARKET_MIN_FLAGS):
            return " | ".join(flags)
        return None

    def _find_5m_setup(self, direction: Direction, candles_5m: list[Candle], s5m: Snapshot) -> SetupScore | None:
        if not bool(config.SETUP_1M_TRIGGER_ENABLED):
            return self._reject("رد شد: مدل HMT-5 Trap Hunt خاموش است")
        # HMT-5: the best quality setup is always a trap/sweep first.
        # If a perfect 5M trap is not available, a healthy 5M context may still
        # proceed, but the actual 1M trigger must pass the HMT trap gate.
        setup = self._liquidity_sweep_setup(direction, candles_5m)
        if setup is not None:
            return setup
        setup = self._breakout_retest_setup(direction, candles_5m)
        if setup is not None:
            return setup
        setup = self._momentum_continuation_setup(direction, candles_5m, s5m)
        if setup is not None:
            return setup
        setup = self._trend_context_setup(direction, candles_5m, s5m)
        if setup is not None:
            return setup
        return self._reject("رد شد: 5M هنوز Context سالم برای شکار تله 1M نداده")

    def _candidate_5m_indices(self, candles_5m: list[Candle], lookback: int) -> list[int]:
        valid = max(1, int(config.SETUP_VALID_5M_CANDLES))
        last = len(candles_5m) - 1
        start = max(lookback, last - valid + 1)
        return list(range(last, start - 1, -1))

    def _liquidity_sweep_setup(self, direction: Direction, candles_5m: list[Candle]) -> SetupScore | None:
        if not bool(config.LIQUIDITY_SWEEP_ENABLED):
            return None
        lookback = max(4, int(config.SWEEP_LOOKBACK_5M))
        if len(candles_5m) < lookback + int(config.SETUP_VALID_5M_CANDLES) + 1:
            return None
        sweep_break = float(config.SWEEP_MIN_BREAK_PCT)
        reclaim_buffer = float(config.SWEEP_RECLAIM_BUFFER_PCT)

        for idx in self._candidate_5m_indices(candles_5m, lookback):
            c = candles_5m[idx]
            previous = candles_5m[idx - lookback:idx]
            prev_high = max(float(x.high) for x in previous)
            prev_low = min(float(x.low) for x in previous)
            if direction == "LONG":
                swept = float(c.low) <= prev_low * (1 - sweep_break)
                reclaimed = float(c.close) > prev_low * (1 + reclaim_buffer)
                body_ok = float(c.close) > float(c.open)
                if swept and reclaimed and body_ok:
                    return SetupScore(
                        "Liquidity Sweep Reclaim",
                        level=prev_low,
                        sl_anchor=float(c.low),
                        score=25.0,
                        reasons=(
                            f"5M ستاپ لانگ: sweep کف {lookback} کندل و برگشت بالای محدوده",
                            f"استاپ پشت wick sweep | low={float(c.low):.8g}",
                        ),
                    )
            else:
                swept = float(c.high) >= prev_high * (1 + sweep_break)
                reclaimed = float(c.close) < prev_high * (1 - reclaim_buffer)
                body_ok = float(c.close) < float(c.open)
                if swept and reclaimed and body_ok:
                    return SetupScore(
                        "Liquidity Sweep Reclaim",
                        level=prev_high,
                        sl_anchor=float(c.high),
                        score=25.0,
                        reasons=(
                            f"5M ستاپ شورت: sweep سقف {lookback} کندل و برگشت زیر محدوده",
                            f"استاپ پشت wick sweep | high={float(c.high):.8g}",
                        ),
                    )
        return None

    def _breakout_retest_setup(self, direction: Direction, candles_5m: list[Candle]) -> SetupScore | None:
        if not bool(config.BREAKOUT_RETEST_ENABLED):
            return None
        lookback = max(4, int(config.BREAKOUT_LOOKBACK_5M))
        if len(candles_5m) < lookback + int(config.SETUP_VALID_5M_CANDLES) + 1:
            return None
        max_range = float(config.BREAKOUT_MAX_PRE_RANGE_PCT)
        break_buffer = float(config.BREAKOUT_MIN_BREAK_PCT)

        for idx in self._candidate_5m_indices(candles_5m, lookback):
            c = candles_5m[idx]
            previous = candles_5m[idx - lookback:idx]
            prev_high = max(float(x.high) for x in previous)
            prev_low = min(float(x.low) for x in previous)
            close = float(c.close)
            if close <= 0:
                continue
            box_range = (prev_high - prev_low) / close
            if box_range <= 0 or box_range > max_range:
                continue
            if direction == "LONG" and close > prev_high * (1 + break_buffer):
                return SetupScore(
                    "Breakout Retest",
                    level=prev_high,
                    sl_anchor=prev_high,
                    score=25.0,
                    reasons=(
                        f"5M ستاپ لانگ: شکست سقف فشردگی {lookback} کندل، ورود فقط بعد ری‌تست 1M",
                        f"فشردگی قبل شکست:{box_range * 100:.2f}%",
                    ),
                )
            if direction == "SHORT" and close < prev_low * (1 - break_buffer):
                return SetupScore(
                    "Breakout Retest",
                    level=prev_low,
                    sl_anchor=prev_low,
                    score=25.0,
                    reasons=(
                        f"5M ستاپ شورت: شکست کف فشردگی {lookback} کندل، ورود فقط بعد ری‌تست 1M",
                        f"فشردگی قبل شکست:{box_range * 100:.2f}%",
                    ),
                )
        return None

    def _momentum_continuation_setup(self, direction: Direction, candles_5m: list[Candle], s5m: Snapshot) -> SetupScore | None:
        """Controlled trend-continuation setup.

        This setup fixes the scanner being too quiet when there is a healthy trend
        but no exact sweep/retest. It still does not enter directly on 5M; it only
        lets the coin continue to the 1M trigger gate.
        """
        if not bool(config.MOMENTUM_CONTINUATION_ENABLED):
            return None
        lookback = max(4, int(config.MOMENTUM_LOOKBACK_5M))
        if len(candles_5m) < lookback + 4:
            return None
        close = float(s5m.close or 0.0)
        if close <= 0:
            return None

        recent = candles_5m[-lookback:]
        last = candles_5m[-1]
        max_dist = float(config.MOMENTUM_MAX_DISTANCE_FROM_EMA_VWAP_PCT)
        max_move = float(config.MOMENTUM_MAX_3CANDLE_MOVE_PCT)
        min_volume = float(config.MOMENTUM_MIN_VOLUME_RATIO)
        flags: list[str] = []

        candle_range = max(0.0, float(last.high) - float(last.low))
        close_pos = 0.5 if candle_range <= 0 else (float(last.close) - float(last.low)) / candle_range
        move = self._directional_3candle_move(direction, candles_5m, close)
        if move > max_move:
            return None

        if direction == "LONG":
            ref_candidates = [x for x in (float(s5m.ema20), float(s5m.vwap)) if x > 0]
            if not ref_candidates:
                return None
            ref = max(ref_candidates)
            if not (close > float(s5m.ema20) and close > float(s5m.vwap)):
                return None
            dist = max(0.0, (close - ref) / close)
            if dist > max_dist:
                return None
            if close > float(s5m.ema20) and close > float(s5m.vwap):
                flags.append(f"قیمت بالای EMA20/VWAP و فاصله سالم:{dist * 100:.2f}%")
            if close > float(s5m.ema50):
                flags.append("قیمت بالای EMA50 5M")
            if float(s5m.macd_hist) > float(s5m.prev_macd_hist):
                flags.append("MACD 5M در جهت لانگ بهتر شده")
            if float(config.MOMENTUM_LONG_RSI_MIN) <= float(s5m.rsi) <= float(config.MOMENTUM_LONG_RSI_MAX):
                flags.append(f"RSI 5M ادامه‌روند سالم:{s5m.rsi:.1f}")
            if float(s5m.volume_ratio) >= min_volume:
                flags.append(f"حجم 5M قابل قبول:{s5m.volume_ratio:.2f}x")
            if float(last.close) > float(last.open) or close_pos >= 0.50:
                flags.append("کندل آخر 5M ضد لانگ نیست")
            # Momentum is only a context setup; SL must be behind the 1M trigger, not a far 5M swing.
            sl_anchor = close
        else:
            ref_candidates = [x for x in (float(s5m.ema20), float(s5m.vwap)) if x > 0]
            if not ref_candidates:
                return None
            ref = min(ref_candidates)
            if not (close < float(s5m.ema20) and close < float(s5m.vwap)):
                return None
            dist = max(0.0, (ref - close) / close)
            if dist > max_dist:
                return None
            if close < float(s5m.ema20) and close < float(s5m.vwap):
                flags.append(f"قیمت زیر EMA20/VWAP و فاصله سالم:{dist * 100:.2f}%")
            if close < float(s5m.ema50):
                flags.append("قیمت زیر EMA50 5M")
            if float(s5m.macd_hist) < float(s5m.prev_macd_hist):
                flags.append("MACD 5M در جهت شورت ضعیف‌تر شده")
            if float(config.MOMENTUM_SHORT_RSI_MIN) <= float(s5m.rsi) <= float(config.MOMENTUM_SHORT_RSI_MAX):
                flags.append(f"RSI 5M ادامه‌روند سالم:{s5m.rsi:.1f}")
            if float(s5m.volume_ratio) >= min_volume:
                flags.append(f"حجم 5M قابل قبول:{s5m.volume_ratio:.2f}x")
            if float(last.close) < float(last.open) or close_pos <= 0.50:
                flags.append("کندل آخر 5M ضد شورت نیست")
            # Momentum is only a context setup; SL must be behind the 1M trigger, not a far 5M swing.
            sl_anchor = close

        if len(flags) < int(config.MOMENTUM_MIN_FLAGS):
            return None
        return SetupScore(
            "Momentum Continuation",
            level=float(ref),
            sl_anchor=float(sl_anchor),
            score=20.0,
            reasons=(
                "5M ستاپ Momentum Continuation: روند سالم است، ورود هنوز فقط با 1M Trigger مجاز است",
                " | ".join(flags[:4]),
            ),
        )

    def _trend_context_setup(self, direction: Direction, candles_5m: list[Candle], s5m: Snapshot) -> SetupScore | None:
        """Soft 5M context fallback for anti-choke behavior.

        Sweep/Reclaim and Breakout/Retest are high-quality patterns but do not
        appear on every healthy move. This fallback does NOT open a trade. It
        only says: 5M is alive, not too late, and not against the selected
        1H/15M direction, so the coin may continue to the 1M trigger gate.
        The actual entry, SL and final quality still come from 1M.
        """
        if not bool(config.CONTEXT_SETUP_ENABLED):
            return None
        if len(candles_5m) < 8:
            return None
        close = float(s5m.close or 0.0)
        if close <= 0:
            return None

        max_dist = float(config.CONTEXT_MAX_DISTANCE_FROM_EMA_VWAP_PCT)
        max_move = float(config.CONTEXT_MAX_3CANDLE_MOVE_PCT)
        move = self._directional_3candle_move(direction, candles_5m, close)
        if move > max_move:
            return None

        flags: list[str] = []
        refs = [x for x in (float(s5m.ema20), float(s5m.vwap), float(s5m.ema50)) if x > 0]
        if not refs:
            return None

        if direction == "LONG":
            # At least one fast reference must be reclaimed; requiring both EMA20
            # and VWAP choked the scanner in normal trend continuation.
            above_ema20 = close > float(s5m.ema20)
            above_vwap = close > float(s5m.vwap)
            above_ema50 = close > float(s5m.ema50)
            if not (above_ema20 or above_vwap):
                return None
            nearest_ref = max([r for r in (float(s5m.ema20), float(s5m.vwap)) if r > 0 and close >= r] or [min(refs)])
            dist = max(0.0, (close - nearest_ref) / close)
            if dist > max_dist:
                return None
            if above_ema20:
                flags.append("5M بالای EMA20")
            if above_vwap:
                flags.append("5M بالای VWAP")
            if above_ema50:
                flags.append("5M بالای EMA50")
            if float(config.CONTEXT_LONG_RSI_MIN) <= float(s5m.rsi) <= float(config.CONTEXT_LONG_RSI_MAX):
                flags.append(f"RSI 5M قابل قبول:{s5m.rsi:.1f}")
            if float(s5m.macd_hist) >= float(s5m.prev_macd_hist):
                flags.append("MACD 5M خلاف لانگ نیست")
            level = close
            sl_anchor = close
        else:
            below_ema20 = close < float(s5m.ema20)
            below_vwap = close < float(s5m.vwap)
            below_ema50 = close < float(s5m.ema50)
            if not (below_ema20 or below_vwap):
                return None
            nearest_ref = min([r for r in (float(s5m.ema20), float(s5m.vwap)) if r > 0 and close <= r] or [max(refs)])
            dist = max(0.0, (nearest_ref - close) / close)
            if dist > max_dist:
                return None
            if below_ema20:
                flags.append("5M زیر EMA20")
            if below_vwap:
                flags.append("5M زیر VWAP")
            if below_ema50:
                flags.append("5M زیر EMA50")
            if float(config.CONTEXT_SHORT_RSI_MIN) <= float(s5m.rsi) <= float(config.CONTEXT_SHORT_RSI_MAX):
                flags.append(f"RSI 5M قابل قبول:{s5m.rsi:.1f}")
            if float(s5m.macd_hist) <= float(s5m.prev_macd_hist):
                flags.append("MACD 5M خلاف شورت نیست")
            level = close
            sl_anchor = close

        if len(flags) < int(config.CONTEXT_MIN_FLAGS):
            return None
        return SetupScore(
            "5M Trend Context",
            level=float(level),
            sl_anchor=float(sl_anchor),
            score=15.0,
            reasons=(
                "5M Context سالم: ستاپ کلاسیک نبود، ولی بازار برای بررسی 1M Trigger خفه نمی‌شود",
                " | ".join(flags[:4]) + f" | حرکت 3 کندل:{move * 100:.2f}%",
            ),
        )

    def _trigger_1m(self, direction: Direction, setup: SetupScore, candles_1m: list[Candle], s1m: Snapshot) -> TriggerScore | None:
        if len(candles_1m) < max(10, int(config.TRIGGER_LOOKBACK_1M) + 4):
            return self._reject("رد شد: کندل 1M کافی برای تریگر ورود نیست")
        last = candles_1m[-1]
        entry = float(last.close)
        if entry <= 0:
            return self._reject("رد شد: قیمت 1M نامعتبر است")

        candle_range = max(0.0, float(last.high) - float(last.low))
        if candle_range <= 0:
            return self._reject("رد شد: کندل 1M رنج معتبر ندارد")
        body_ratio = abs(float(last.close) - float(last.open)) / candle_range
        if body_ratio < float(config.TRIGGER_MIN_BODY_RATIO):
            return self._reject(f"رد شد: بدنه کندل 1M ضعیف است ({body_ratio * 100:.0f}%)")

        close_position = (float(last.close) - float(last.low)) / candle_range
        min_pos = float(config.TRIGGER_MIN_CLOSE_POSITION)
        if direction == "LONG":
            if float(last.close) <= float(last.open):
                return self._reject("رد شد: تریگر 1M لانگ صعودی نیست")
            if close_position < min_pos:
                return self._reject(f"رد شد: کندل 1M لانگ نزدیک سقف بسته نشده ({close_position * 100:.0f}%)")
        else:
            if float(last.close) >= float(last.open):
                return self._reject("رد شد: تریگر 1M شورت نزولی نیست")
            if close_position > (1 - min_pos):
                return self._reject(f"رد شد: کندل 1M شورت نزدیک کف بسته نشده ({(1 - close_position) * 100:.0f}%)")

        if float(s1m.volume_ratio) < float(config.TRIGGER_MIN_VOLUME_RATIO):
            return self._reject(f"رد شد: حجم تریگر 1M کم است ({s1m.volume_ratio:.2f}x)")

        if direction == "LONG":
            if not (float(config.TRIGGER_LONG_RSI_MIN) <= float(s1m.rsi) <= float(config.TRIGGER_LONG_RSI_MAX)):
                return self._reject(f"رد شد: RSI تریگر لانگ خسته/نامناسب است ({s1m.rsi:.1f})")
            if float(s1m.macd_hist) <= float(s1m.prev_macd_hist):
                return self._reject("رد شد: MACD 1M لانگ تازه بهتر نشده")
            if not (entry > float(s1m.ema20) and entry > float(s1m.vwap)):
                return self._reject("رد شد: 1M لانگ EMA20 و VWAP را پس نگرفته")
        else:
            if not (float(config.TRIGGER_SHORT_RSI_MIN) <= float(s1m.rsi) <= float(config.TRIGGER_SHORT_RSI_MAX)):
                return self._reject(f"رد شد: RSI تریگر شورت خسته/نامناسب است ({s1m.rsi:.1f})")
            if float(s1m.macd_hist) >= float(s1m.prev_macd_hist):
                return self._reject("رد شد: MACD 1M شورت تازه ضعیف‌تر نشده")
            if not (entry < float(s1m.ema20) and entry < float(s1m.vwap)):
                return self._reject("رد شد: 1M شورت EMA20 و VWAP را از دست نداده")

        trap_ok, trap_reasons = self._hmt_1m_trap_gate(direction, setup, candles_1m, s1m, body_ratio, close_position)
        if not trap_ok:
            return self._reject("رد شد: HMT شکار تله 1M هنوز تأیید نشده")

        try:
            self._check_setup_retest_or_reclaim(direction, setup, candles_1m, entry)
        except _Rejected:
            return None

        move = self._directional_3candle_move(direction, candles_1m, entry)
        if move > float(config.TRIGGER_MAX_3CANDLE_MOVE_PCT):
            return self._reject(f"رد شد: حرکت 1M قبل ورود زیاد شده ({move * 100:.2f}%)")

        reasons = [
            f"1M تریگر HMT داد؛ ورود مستقیم 5M حذف شد | body={body_ratio * 100:.0f}%",
            f"1M EMA20/VWAP در جهت معامله پس گرفته شد | volume={s1m.volume_ratio:.2f}x",
            f"1M RSI سالم:{s1m.rsi:.1f} | MACD تازه در جهت معامله",
        ]
        reasons.extend(trap_reasons)
        return TriggerScore(entry=entry, score=30.0, reasons=tuple(reasons))

    def _hmt_1m_trap_gate(
        self,
        direction: Direction,
        setup: SetupScore,
        candles_1m: list[Candle],
        s1m: Snapshot,
        body_ratio: float,
        close_position: float,
    ) -> tuple[bool, list[str]]:
        """HMT-5 final gate: enter only after a 1M trap/reclaim/ignition.

        This prevents the old failure mode: chasing a 5M move at the bottom/top.
        A perfect 5M sweep counts as trap context, but continuation/context setups
        still need 1M to show a local sweep, micro-reclaim, or silent ignition.
        """
        if not bool(config.HMT_TRAP_GATE_ENABLED):
            return True, ["HMT Trap Gate خاموش است"]
        lookback = max(4, int(config.HMT_TRAP_LOOKBACK_1M))
        if len(candles_1m) < lookback + 2:
            return False, []

        last = candles_1m[-1]
        prior = candles_1m[-lookback - 1:-1]
        if not prior:
            return False, []
        entry = float(last.close)
        if entry <= 0:
            return False, []

        sweep_pct = float(config.HMT_TRAP_MIN_SWEEP_PCT)
        reclaim_buf = float(config.HMT_TRAP_RECLAIM_BUFFER_PCT)
        micro_lb = max(2, int(config.HMT_MICRO_RECLAIM_LOOKBACK_1M))
        micro = candles_1m[-micro_lb - 1:-1]
        recent_with_last = micro + [last]
        prev_high = max(float(c.high) for c in prior)
        prev_low = min(float(c.low) for c in prior)

        # A 5M liquidity sweep already tells us the trap location; the 1M candle
        # still had to pass body, close position, RSI, MACD and EMA/VWAP before this gate.
        if setup.kind == "Liquidity Sweep Reclaim":
            return True, ["HMT Trap: 5M شکار نقدینگی تأیید شد و 1M برگشت سالم داد"]

        # A real retest after a 5M breakout is accepted as trap/hold only when
        # the 1M wick touches the broken level and closes back in the intended direction.
        if setup.kind == "Breakout Retest":
            level = float(setup.level)
            if level > 0:
                if direction == "LONG":
                    touched = min(float(c.low) for c in recent_with_last) <= level * (1 + float(config.BREAKOUT_RETEST_MAX_DISTANCE_PCT))
                    held = entry > level * (1 + reclaim_buf)
                    if touched and held:
                        return True, ["HMT Trap: ری‌تست 1M سطح شکست را نگه داشت"]
                else:
                    touched = max(float(c.high) for c in recent_with_last) >= level * (1 - float(config.BREAKOUT_RETEST_MAX_DISTANCE_PCT))
                    held = entry < level * (1 - reclaim_buf)
                    if touched and held:
                        return True, ["HMT Trap: ری‌تست 1M سطح شکست را نگه داشت"]

        ema20 = float(s1m.ema20 or 0.0)
        vwap = float(s1m.vwap or 0.0)
        if ema20 <= 0 or vwap <= 0:
            return False, []

        reasons: list[str] = []
        if direction == "LONG":
            # Trap Reversal: wick sweeps recent lows, then closes back above.
            swept_local_low = float(last.low) <= prev_low * (1 - sweep_pct) and entry > prev_low * (1 + reclaim_buf)
            if swept_local_low:
                reasons.append(f"HMT Trap: 1M کف {lookback} کندل را زد و پس گرفت")

            # Micro reclaim: price briefly loses EMA20/VWAP liquidity zone, then reclaims both.
            ref_low = min(ema20, vwap)
            lost_ref = min(float(c.low) for c in recent_with_last) <= ref_low * (1 - reclaim_buf)
            reclaimed_ref = entry > max(ema20, vwap)
            if bool(config.HMT_ALLOW_MICRO_RECLAIM) and lost_ref and reclaimed_ref:
                reasons.append("HMT Trap: 1M زیر EMA20/VWAP نقدینگی جمع کرد و برگشت")

            # Silent ignition: calm pullback/fake-down then strong 1M close through local high.
            broke_local_high = entry > prev_high * (1 + sweep_pct)
            had_pullback = any(float(c.close) < min(ema20, vwap) for c in prior[-micro_lb:])
            strong_close = body_ratio >= float(config.TRIGGER_MIN_BODY_RATIO) and close_position >= float(config.TRIGGER_MIN_CLOSE_POSITION)
            if bool(config.HMT_ALLOW_IGNITION_TRAP) and broke_local_high and had_pullback and strong_close:
                reasons.append("HMT Trap: Silent Ignition بعد از fake-down در 1M")
        else:
            swept_local_high = float(last.high) >= prev_high * (1 + sweep_pct) and entry < prev_high * (1 - reclaim_buf)
            if swept_local_high:
                reasons.append(f"HMT Trap: 1M سقف {lookback} کندل را زد و پس گرفت")

            ref_high = max(ema20, vwap)
            took_ref = max(float(c.high) for c in recent_with_last) >= ref_high * (1 + reclaim_buf)
            reclaimed_ref = entry < min(ema20, vwap)
            if bool(config.HMT_ALLOW_MICRO_RECLAIM) and took_ref and reclaimed_ref:
                reasons.append("HMT Trap: 1M بالای EMA20/VWAP نقدینگی جمع کرد و برگشت")

            broke_local_low = entry < prev_low * (1 - sweep_pct)
            had_pullback = any(float(c.close) > max(ema20, vwap) for c in prior[-micro_lb:])
            strong_close = body_ratio >= float(config.TRIGGER_MIN_BODY_RATIO) and close_position <= (1 - float(config.TRIGGER_MIN_CLOSE_POSITION))
            if bool(config.HMT_ALLOW_IGNITION_TRAP) and broke_local_low and had_pullback and strong_close:
                reasons.append("HMT Trap: Silent Ignition بعد از fake-up در 1M")

        return (len(reasons) > 0), reasons

    def _check_setup_retest_or_reclaim(self, direction: Direction, setup: SetupScore, candles_1m: list[Candle], entry: float) -> None:
        lookback = max(2, int(config.TRIGGER_LOOKBACK_1M))
        recent = candles_1m[-lookback:]
        level = float(setup.level)
        if level <= 0 or entry <= 0:
            return
        max_entry_dist = float(config.TRIGGER_MAX_ENTRY_DISTANCE_PCT)
        if direction == "LONG":
            if setup.kind == "Breakout Retest":
                touched = min(float(c.low) for c in recent) <= level * (1 + float(config.BREAKOUT_RETEST_MAX_DISTANCE_PCT))
                held = entry > level
                if not (touched and held):
                    self._reject("رد شد: 1M ری‌تست سقف شکسته‌شده را نگه نداشت")
                    raise _Rejected
            dist = max(0.0, (entry - level) / entry)
            if dist > max_entry_dist:
                self._reject(f"رد شد: ورود لانگ از سطح ستاپ دور شده ({dist * 100:.2f}%)")
                raise _Rejected
        else:
            if setup.kind == "Breakout Retest":
                touched = max(float(c.high) for c in recent) >= level * (1 - float(config.BREAKOUT_RETEST_MAX_DISTANCE_PCT))
                held = entry < level
                if not (touched and held):
                    self._reject("رد شد: 1M ری‌تست کف شکسته‌شده را نگه نداشت")
                    raise _Rejected
            dist = max(0.0, (level - entry) / entry)
            if dist > max_entry_dist:
                self._reject(f"رد شد: ورود شورت از سطح ستاپ دور شده ({dist * 100:.2f}%)")
                raise _Rejected

    def _make_trigger_sl(self, direction: Direction, setup: SetupScore, candles_1m: list[Candle], entry: float) -> float:
        lookback = max(2, int(config.TRIGGER_SL_LOOKBACK_1M))
        recent = candles_1m[-lookback:]
        buffer = entry * float(config.TRIGGER_SL_BUFFER_PCT)
        if direction == "LONG":
            anchor = min(float(setup.sl_anchor), min(float(c.low) for c in recent))
            risk = max(entry - anchor + buffer, entry * float(config.MIN_5M_SL_PCT))
            return entry - risk
        anchor = max(float(setup.sl_anchor), max(float(c.high) for c in recent))
        risk = max(anchor - entry + buffer, entry * float(config.MIN_5M_SL_PCT))
        return entry + risk

    @staticmethod
    def _directional_3candle_move(direction: Direction, candles: list[Candle], close: float) -> float:
        if len(candles) < 4:
            return 0.0
        base = float(candles[-4].close or 0.0)
        if base <= 0:
            return 0.0
        if direction == "LONG":
            return max(0.0, (close - base) / base)
        return max(0.0, (base - close) / base)


class _Rejected(Exception):
    pass
