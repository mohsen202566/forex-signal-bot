from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import config
import indicators as ind
from setup_engine import SetupCandidate


@dataclass
class WatchEvaluation:
    watch_id: str
    state: str
    trigger_score: float
    confirmed: bool
    entry_price: float
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


class WatchEngine:
    def evaluate(self, s: SetupCandidate, c1: list[dict[str, Any]]) -> WatchEvaluation:
        now = int(time.time())
        if now > s.expires_at:
            return WatchEvaluation(s.setup_id, "EXPIRED", 0, False, 0, "واچ منقضی شد")
        if len(c1) < 20:
            return WatchEvaluation(s.setup_id, "WAITING", 0, False, 0, "داده 1M کافی نیست")

        live_price = float(c1[-1]["close"])
        if live_price <= 0:
            return WatchEvaluation(s.setup_id, "WAITING", 0, False, 0, "قیمت 1M نامعتبر است")
        if (s.side == "LONG" and live_price <= s.invalidation_price) or (
            s.side == "SHORT" and live_price >= s.invalidation_price
        ):
            return WatchEvaluation(s.setup_id, "INVALIDATED", 0, False, live_price, "سطح ابطال شکسته شد")

        confirmed = [x for x in c1 if int(x.get("confirm", 1)) == 1]
        if len(confirmed) < 20:
            return WatchEvaluation(s.setup_id, "WAITING", 0, False, live_price, "کندل تأییدشده 1M کافی نیست")

        closes = ind.closes(confirmed)
        cf = ind.candle_features(confirmed[-1])
        rs = ind.rsi(closes, 7)
        _, _, hist = ind.macd(closes, 6, 13, 4)
        if len(rs) < 2 or len(hist) < 2:
            return WatchEvaluation(s.setup_id, "WAITING", 0, False, live_price, "مومنتوم 1M کافی نیست")

        atr = max(float(s.meta.get("atr") or 0), 1e-12)
        late_distance = max(0.0, live_price - s.trigger_price) if s.side == "LONG" else max(0.0, s.trigger_price - live_price)
        late_atr = late_distance / atr
        if late_atr > config.WATCH_LATE_LIMIT_ATR:
            return WatchEvaluation(s.setup_id, "INVALIDATED", 0, False, live_price, "ورود دیر شده است", {"late_atr": late_atr})

        price_ok = live_price > s.trigger_price if s.side == "LONG" else live_price < s.trigger_price
        momentum_ok = (rs[-1] > 52 and hist[-1] > hist[-2]) if s.side == "LONG" else (rs[-1] < 48 and hist[-1] < hist[-2])
        candle_ok = (
            cf["direction"] == 1 and cf["close_location"] > 0.65
            if s.side == "LONG"
            else cf["direction"] == -1 and cf["close_location"] < 0.35
        )
        score = 45.0 * float(price_ok) + 30.0 * float(momentum_ok) + 25.0 * float(candle_ok)
        is_confirmed = score >= config.TRIGGER_MIN
        return WatchEvaluation(
            s.setup_id,
            "TRIGGER_CONFIRMED" if is_confirmed else "WAITING",
            round(score, 2),
            is_confirmed,
            live_price,
            "تریگر تأیید شد" if is_confirmed else "در انتظار تأیید",
            {
                "price_ok": price_ok,
                "momentum_ok": momentum_ok,
                "candle_ok": candle_ok,
                "late_atr": late_atr,
                "confirmed_candle_ts": int(confirmed[-1].get("ts") or 0),
            },
        )
