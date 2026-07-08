"""استراتژی ابداعی DIFT-5M بدون سیستم امتیازی.

اصل: Direction Lock → Compression → Impulse Break → Flow Confirm → Risk Gate
اگر حتی یک قفل رد شود، سیگنال صادر نمی‌شود.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import config
from indicators import Candle, adx, atr, closes, ema, highs, last_valid, lows, rolling_vwap, sma, volumes
from okx_client import MarketData, OrderFlow
from utils import human_price, now_ms, pct_distance


@dataclass(slots=True)
class Rejection:
    symbol: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradeSignal:
    symbol: str
    side: str               # BUY / SELL
    direction: str          # LONG / SHORT
    entry_price: float
    sl_price: float
    tp_price: float
    rr: float
    sl_pct: float
    tp_pct: float
    created_ms: int
    strategy: str = "DIFT-5M"
    data_source: str = "OKX"
    execution_source: str = "TOOBIT_WHEN_REAL"
    reason: str = ""
    gates: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def text(self) -> str:
        side_emoji = "🟢" if self.direction == "LONG" else "🔴"
        strength = "قوی" if self.rr >= 1.5 else "معمولی"
        return (
            "📊 سیگنال عادی 5M\n"
            f"#{str(self.created_ms)[-6:]} | {self.symbol}\n\n"
            f"{side_emoji} جهت: {self.direction}\n"
            f"قدرت: {strength}\n"
            f"RR: {self.rr:.1f}\n"
            "مدل ورود: DIFT-5M Trap Hunt | 5M Trend Context + Flow\n\n"
            f"Entry: {human_price(self.entry_price)}\n"
            f"TP 5M: {human_price(self.tp_price)}\n"
            f"SL 5M: {human_price(self.sl_price)}\n"
            f"فاصله استاپ: {self.sl_pct:.2f}% | تارگت: {self.tp_pct:.2f}%\n"
            f"منبع دیتا: {self.data_source} | اجرای واقعی: Toobit"
        )


class DIFT5MStrategy:
    def analyze(self, market: MarketData) -> TradeSignal | Rejection:
        c5 = market.candles_5m
        c15 = market.candles_15m
        c1h = market.candles_1h
        min_needed = max(config.EMA_SLOW + 5, config.COMPRESSION_LOOKBACK + config.ATR_LENGTH + 5)
        if len(c5) < min_needed or len(c15) < config.EMA_SLOW + 5 or len(c1h) < config.EMA_SLOW + 5:
            return Rejection(market.symbol, "دیتای کندل کافی نیست")

        last = c5[-1]
        if not last.confirm:
            return Rejection(market.symbol, "کندل ۵ دقیقه هنوز بسته/تایید نشده است")

        side = self._detect_impulse_side(c5)
        if side is None:
            return Rejection(market.symbol, "ایمپالس شکست معتبر شکل نگرفته")

        direction = "LONG" if side == "BUY" else "SHORT"
        gates: list[str] = []

        trend_ok, trend_meta = self._gate_direction_lock(side, c15, c1h)
        if not trend_ok:
            return Rejection(market.symbol, "جهت ۱۵M و ۱H همسو نیست", trend_meta)
        gates.append("DIRECTION_LOCK")

        compression_ok, comp_meta = self._gate_compression(c5)
        if not compression_ok:
            return Rejection(market.symbol, "قبل از حرکت، فشردگی سالم وجود ندارد", comp_meta)
        gates.append("COMPRESSION")

        impulse_ok, impulse_meta = self._gate_impulse(side, c5)
        if not impulse_ok:
            return Rejection(market.symbol, "کیفیت کندل شکست کافی نیست", impulse_meta)
        gates.append("IMPULSE_BREAK")

        flow_ok, flow_meta = self._gate_flow(side, market.flow)
        if not flow_ok:
            return Rejection(market.symbol, "جریان سفارش/حجم پشت سیگنال تایید نکرد", flow_meta)
        gates.append("ORDER_FLOW")

        risk_ok, risk_meta = self._gate_risk(side, c5, c15, market.flow)
        if not risk_ok:
            return Rejection(market.symbol, "استاپ/تارگت/RR منطقی نیست", risk_meta)
        gates.append("RISK_RR")

        entry = float(last.close)
        sl = float(risk_meta["sl_price"])
        rr = float(risk_meta["rr"])
        risk = abs(entry - sl)
        if side == "BUY":
            tp = entry + risk * rr
        else:
            tp = entry - risk * rr
        sl_pct = abs(entry - sl) / entry * 100
        tp_pct = abs(tp - entry) / entry * 100

        reason = " + ".join(gates)
        return TradeSignal(
            symbol=market.symbol,
            side=side,
            direction=direction,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            rr=rr,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            created_ms=now_ms(),
            reason=reason,
            gates=gates,
            meta={**trend_meta, **comp_meta, **impulse_meta, **flow_meta, **risk_meta},
        )

    def _detect_impulse_side(self, candles: list[Candle]) -> str | None:
        last = candles[-1]
        pre = candles[-1 - config.COMPRESSION_LOOKBACK:-1]
        pre_high = max(c.high for c in pre)
        pre_low = min(c.low for c in pre)
        if last.close > pre_high:
            return "BUY"
        if last.close < pre_low:
            return "SELL"
        return None

    def _gate_direction_lock(self, side: str, c15: list[Candle], c1h: list[Candle]) -> tuple[bool, dict[str, Any]]:
        def trend(candles: list[Candle], min_adx: float) -> tuple[str, dict[str, Any]]:
            cls = closes(candles)
            ef = ema(cls, config.EMA_FAST)
            es = ema(cls, config.EMA_SLOW)
            vw = rolling_vwap(candles, config.VWAP_LENGTH)
            ax = adx(candles, config.ADX_LENGTH)
            fast = last_valid(ef)
            slow = last_valid(es)
            vwap = last_valid(vw, cls[-1])
            cur_adx = last_valid(ax, 0.0)
            slope_fast = fast - (ef[-4] if len(ef) >= 4 and ef[-4] is not None else fast)
            last_close = cls[-1]
            if cur_adx < min_adx:
                return "RANGE", {"adx": cur_adx, "min_adx": min_adx}
            if last_close > vwap and fast > slow and slope_fast > 0:
                return "UP", {"adx": cur_adx, "fast": fast, "slow": slow, "vwap": vwap, "slope_fast": slope_fast}
            if last_close < vwap and fast < slow and slope_fast < 0:
                return "DOWN", {"adx": cur_adx, "fast": fast, "slow": slow, "vwap": vwap, "slope_fast": slope_fast}
            return "MIXED", {"adx": cur_adx, "fast": fast, "slow": slow, "vwap": vwap, "slope_fast": slope_fast}

        t15, m15 = trend(c15, config.MIN_ADX_15M)
        t1h, m1h = trend(c1h, config.MIN_ADX_1H)
        want = "UP" if side == "BUY" else "DOWN"
        ok = t15 == want and t1h == want
        return ok, {"trend_15m": t15, "trend_1h": t1h, "trend_15m_meta": m15, "trend_1h_meta": m1h}

    def _gate_compression(self, candles: list[Candle]) -> tuple[bool, dict[str, Any]]:
        last = candles[-1]
        pre = candles[-1 - config.COMPRESSION_LOOKBACK:-1]
        pre_high = max(c.high for c in pre)
        pre_low = min(c.low for c in pre)
        pre_range = max(0.0, pre_high - pre_low)
        pre_range_pct = pre_range / last.close * 100 if last.close else 0.0
        current_atr = last_valid(atr(candles, config.ATR_LENGTH), 0.0)
        atr_mult = pre_range / current_atr if current_atr > 0 else 999
        ok = (
            config.MIN_PRE_RANGE_PCT <= pre_range_pct <= config.MAX_PRE_RANGE_PCT
            and atr_mult <= config.MAX_PRE_RANGE_ATR_MULT
        )
        return ok, {"pre_high": pre_high, "pre_low": pre_low, "pre_range_pct": pre_range_pct, "pre_range_atr_mult": atr_mult, "atr_5m": current_atr}

    def _gate_impulse(self, side: str, candles: list[Candle]) -> tuple[bool, dict[str, Any]]:
        last = candles[-1]
        vols = volumes(candles[:-1])
        avg_vol = last_valid(sma(vols, 20), 0.0)
        volume_ratio = last.volume / avg_vol if avg_vol > 0 else 0.0
        current_atr = last_valid(atr(candles, config.ATR_LENGTH), 0.0)
        impulse_atr_mult = last.range / current_atr if current_atr > 0 else 999

        if side == "BUY":
            close_ok = last.close_position >= config.MIN_CLOSE_POSITION_LONG
        else:
            close_ok = last.close_position <= config.MAX_CLOSE_POSITION_SHORT

        ok = (
            last.body_ratio >= config.MIN_BODY_RATIO
            and close_ok
            and volume_ratio >= config.MIN_VOLUME_RATIO
            and impulse_atr_mult <= config.MAX_IMPULSE_ATR_MULT
        )
        return ok, {"body_ratio": last.body_ratio, "close_position": last.close_position, "volume_ratio": volume_ratio, "impulse_atr_mult": impulse_atr_mult}

    def _gate_flow(self, side: str, flow: OrderFlow) -> tuple[bool, dict[str, Any]]:
        meta = {
            "bid_ratio": flow.bid_ratio,
            "taker_ratio": flow.taker_ratio,
            "spread_pct": flow.spread_pct,
            "funding_rate": flow.funding_rate,
            "open_interest": flow.open_interest,
        }
        if flow.spread_pct > config.MAX_SPREAD_PCT:
            return False, {**meta, "flow_reject": "spread_high"}

        funding = flow.funding_rate
        if funding is not None:
            if abs(funding) > config.MAX_ABS_FUNDING_RATE:
                return False, {**meta, "flow_reject": "funding_abs_high"}
            if side == "BUY" and funding > config.MAX_DIRECTIONAL_FUNDING_RATE:
                return False, {**meta, "flow_reject": "long_crowded_funding"}
            if side == "SELL" and funding < -config.MAX_DIRECTIONAL_FUNDING_RATE:
                return False, {**meta, "flow_reject": "short_crowded_funding"}

        if not config.REQUIRE_ORDER_FLOW:
            return True, meta

        if side == "BUY":
            ok = flow.taker_ratio >= config.MIN_TAKER_RATIO_LONG and flow.bid_ratio >= config.MIN_BOOK_BID_RATIO_LONG
        else:
            sell_ratio = (flow.taker_sell_qty / max(flow.taker_buy_qty, 1e-12))
            ok = sell_ratio >= config.MIN_TAKER_RATIO_SHORT and flow.bid_ratio <= config.MAX_BOOK_BID_RATIO_SHORT
            meta["sell_taker_ratio"] = sell_ratio
        return ok, meta

    def _gate_risk(self, side: str, c5: list[Candle], c15: list[Candle], flow: OrderFlow) -> tuple[bool, dict[str, Any]]:
        last = c5[-1]
        entry = last.close
        pre = c5[-1 - config.COMPRESSION_LOOKBACK:-1]
        current_atr = last_valid(atr(c5, config.ATR_LENGTH), 0.0)
        buffer = current_atr * config.SL_ATR_BUFFER

        if side == "BUY":
            raw_sl = min(min(c.low for c in pre), last.low) - buffer
            min_sl = entry * (1 - config.MIN_SL_DISTANCE_PCT / 100)
            sl = min(raw_sl, min_sl)
            risk = entry - sl
            recent_highs = highs(c15[-24:-1]) or highs(c15[-24:])
            nearest_ceiling = max(recent_highs) if recent_highs else entry
            # اگر قیمت بالای سقف اخیر شکسته باشد، مقاومت نزدیک نداریم و فضا را باز حساب می‌کنیم.
            recent_room = nearest_ceiling - entry if nearest_ceiling > entry else 999999.0
        else:
            raw_sl = max(max(c.high for c in pre), last.high) + buffer
            min_sl = entry * (1 + config.MIN_SL_DISTANCE_PCT / 100)
            sl = max(raw_sl, min_sl)
            risk = sl - entry
            recent_lows = lows(c15[-24:-1]) or lows(c15[-24:])
            nearest_floor = min(recent_lows) if recent_lows else entry
            # اگر قیمت زیر کف اخیر شکسته باشد، حمایت نزدیک نداریم و فضا را باز حساب می‌کنیم.
            recent_room = entry - nearest_floor if nearest_floor < entry else 999999.0

        if entry <= 0 or risk <= 0:
            return False, {"risk_reject": "invalid_risk"}

        sl_pct = risk / entry * 100
        if sl_pct < config.MIN_SL_DISTANCE_PCT:
            return False, {"sl_pct": sl_pct, "risk_reject": "sl_too_small"}
        if sl_pct > config.MAX_SL_DISTANCE_PCT:
            return False, {"sl_pct": sl_pct, "risk_reject": "sl_too_large"}

        rr = config.DEFAULT_RR
        if config.USE_DYNAMIC_RR:
            strong_long = side == "BUY" and flow.taker_ratio >= config.STRONG_TAKER_RATIO and flow.bid_ratio >= config.STRONG_BOOK_EDGE
            sell_ratio = flow.taker_sell_qty / max(flow.taker_buy_qty, 1e-12)
            strong_short = side == "SELL" and sell_ratio >= config.STRONG_TAKER_RATIO and flow.bid_ratio <= (1 - config.STRONG_BOOK_EDGE)
            if strong_long or strong_short:
                rr = config.STRONG_FLOW_RR

        # اگر تا سقف/کف اخیر ۱۵M فضا کم باشد، RR را تا حداقل 1 پایین می‌آوریم؛ زیر 1 ممنوع است.
        max_room_r = recent_room / risk if risk > 0 else 0.0
        if max_room_r < rr:
            rr = max(config.MIN_RR, min(config.DEFAULT_RR, max_room_r))
        if rr < config.MIN_RR or max_room_r < config.MIN_TARGET_ROOM_R_MULT:
            return False, {"sl_pct": sl_pct, "rr": rr, "max_room_r": max_room_r, "risk_reject": "target_room_low"}

        return True, {"sl_price": sl, "sl_pct": sl_pct, "rr": rr, "max_room_r": max_room_r}
