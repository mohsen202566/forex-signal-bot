"""موتور ساده و تطبیقی: شروع حرکت، جهت همان حرکت، افق و TP/SL رفتاری."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any
import time

import config
from profiles import SymbolSpec


@dataclass(frozen=True)
class Tick:
    ts: float
    price: float


@dataclass
class WatchState:
    side: str
    started_at: float
    last_candidate_at: float
    window: int
    last_reason: str = ""


@dataclass(frozen=True)
class Observation:
    status: str
    symbol_id: str
    side: str | None
    window: int | None
    reason: str
    metrics: dict[str, float | int | str | bool]
    transition: str = ""


@dataclass(frozen=True)
class TradePlan:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    side: str
    entry: float
    tp: float
    sl: float
    tp_pct: float
    sl_pct: float
    rr_net: float
    expected_minutes: int
    trigger_window: int
    trigger_reason: str
    notional: float
    estimated_tp_gross: float
    estimated_tp_costs: float
    estimated_tp_net: float
    estimated_sl_gross_loss: float
    estimated_sl_costs: float
    estimated_sl_net_loss: float
    metrics: dict[str, Any] = field(default_factory=dict)


class AdaptiveStartEngine:
    def __init__(self) -> None:
        self.buffers: dict[str, deque[Tick]] = {}
        self.watches: dict[str, WatchState] = {}

    def _buffer(self, symbol_id: str) -> deque[Tick]:
        if symbol_id not in self.buffers:
            self.buffers[symbol_id] = deque(maxlen=180)
        return self.buffers[symbol_id]

    @staticmethod
    def _window_metrics(points: list[Tick], window: int, threshold: dict[str, float]) -> dict[str, float | int]:
        if len(points) < 3:
            return {}
        start = points[0].price
        end = points[-1].price
        if start <= 0:
            return {}
        signed_move = (end - start) / start * 100.0
        path = 0.0
        for previous, current in zip(points, points[1:]):
            if previous.price > 0:
                path += abs(current.price - previous.price) / previous.price * 100.0
        directionality = abs(signed_move) / path if path > 0 else 0.0
        high = max(point.price for point in points)
        low = min(point.price for point in points)
        range_pct = (high - low) / start * 100.0
        half_ts = points[0].ts + (points[-1].ts - points[0].ts) / 2.0
        middle = min(points, key=lambda point: abs(point.ts - half_ts)).price
        first_signed = (middle - start) / start * 100.0
        second_signed = (end - middle) / middle * 100.0 if middle > 0 else 0.0
        side_sign = 1.0 if signed_move >= 0 else -1.0
        acceleration = side_sign * second_signed - side_sign * first_signed
        move_threshold = float(threshold["move_threshold_pct"])
        range_threshold = float(threshold["range_threshold_pct"])
        return {
            "window": window,
            "signed_move_pct": signed_move,
            "abs_move_pct": abs(signed_move),
            "path_pct": path,
            "directionality": directionality,
            "range_pct": range_pct,
            "move_threshold_pct": move_threshold,
            "range_threshold_pct": range_threshold,
            "move_ratio": abs(signed_move) / move_threshold if move_threshold > 0 else 0.0,
            "range_ratio": range_pct / range_threshold if range_threshold > 0 else 0.0,
            "acceleration": acceleration,
        }

    def evaluate(
        self,
        symbol: SymbolSpec,
        profile: dict[str, Any],
        price: float,
        *,
        now: float | None = None,
        volume_quote: float | None = None,
        append_tick: bool = True,
    ) -> Observation:
        now = float(now or time.time())
        buffer = self._buffer(symbol.id)
        if append_tick:
            if not buffer or now > buffer[-1].ts or price != buffer[-1].price:
                buffer.append(Tick(now, float(price)))
        while buffer and now - buffer[0].ts > 125:
            buffer.popleft()
        if not buffer or now - buffer[0].ts < min(config.TRIGGER_WINDOWS_SECONDS) * 0.85:
            return Observation("WARMING", symbol.id, None, None, "LIVE_WINDOW_WARMING", {"buffer_seconds": now - buffer[0].ts if buffer else 0.0})

        observations: list[dict[str, float | int]] = []
        for window in config.TRIGGER_WINDOWS_SECONDS:
            cutoff = now - window
            points = [point for point in buffer if point.ts >= cutoff]
            earlier = [point for point in buffer if point.ts < cutoff]
            if earlier:
                points.insert(0, earlier[-1])
            if not points or points[-1].ts - points[0].ts < window * 0.72:
                continue
            thresholds = profile["windows"][str(window)]
            metrics = self._window_metrics(points, window, thresholds)
            if metrics:
                observations.append(metrics)
        if not observations:
            return Observation("WARMING", symbol.id, None, None, "WINDOWS_INCOMPLETE", {})

        full = [
            item for item in observations
            if float(item["move_ratio"]) >= 1.0
            and float(item["directionality"]) >= config.TRIGGER_MIN_DIRECTIONALITY
        ]
        soft = [
            item for item in observations
            if float(item["move_ratio"]) >= config.WATCH_MOVE_FACTOR
            and float(item["directionality"]) >= config.WATCH_MIN_DIRECTIONALITY
        ]
        chosen: dict[str, float | int] | None = None
        if full:
            chosen = sorted(full, key=lambda item: int(item["window"]))[0]
        elif soft:
            chosen = max(soft, key=lambda item: float(item["move_ratio"]))

        if chosen is None:
            watch = self.watches.get(symbol.id)
            if watch and now - watch.last_candidate_at > config.WATCH_CANCEL_SECONDS:
                self.watches.pop(symbol.id, None)
                return Observation("NORMAL", symbol.id, None, None, "WATCH_CANCELLED_BEHAVIOR_NORMALIZED", {}, "CANCEL")
            return Observation("NORMAL", symbol.id, None, None, "MOVE_INSIDE_NORMAL_BEHAVIOR", {
                "best_move_ratio": max(float(item["move_ratio"]) for item in observations),
                "best_directionality": max(float(item["directionality"]) for item in observations),
            })

        side = "LONG" if float(chosen["signed_move_pct"]) > 0 else "SHORT"
        previous = self.watches.get(symbol.id)
        transition = ""
        if previous is None:
            transition = "NEW"
            self.watches[symbol.id] = WatchState(side, now, now, int(chosen["window"]))
        else:
            if previous.side != side:
                transition = f"FLIP_{previous.side}_TO_{side}"
                previous.side = side
                previous.started_at = now
            previous.last_candidate_at = now
            previous.window = int(chosen["window"])
        watch = self.watches[symbol.id]
        if now - watch.started_at > config.WATCH_MAX_SECONDS:
            self.watches.pop(symbol.id, None)
            return Observation("NORMAL", symbol.id, None, None, "WATCH_MAX_AGE_REACHED", chosen, "CANCEL")

        is_full_price = (
            float(chosen["move_ratio"]) >= 1.0
            and float(chosen["directionality"]) >= config.TRIGGER_MIN_DIRECTIONALITY
        )
        if not is_full_price:
            return Observation("WATCH", symbol.id, side, int(chosen["window"]), "EARLY_MOVE_WATCH", chosen, transition)

        if float(chosen["move_ratio"]) >= config.LATE_MOVE_RATIO and float(chosen["acceleration"]) <= 0:
            return Observation("REJECT", symbol.id, side, int(chosen["window"]), "LATE_EXHAUSTED_MOVE", chosen, transition)

        range_confirmed = float(chosen["range_ratio"]) >= 1.0
        volume_threshold = float(profile["windows"][str(int(chosen["window"]))]["volume_threshold_quote"])
        volume_confirmed = volume_quote is not None and float(volume_quote) >= volume_threshold
        metrics = dict(chosen)
        metrics.update(
            {
                "range_confirmed": range_confirmed,
                "volume_quote": float(volume_quote or 0.0),
                "volume_threshold_quote": volume_threshold,
                "volume_confirmed": volume_confirmed,
            }
        )
        if range_confirmed or volume_confirmed:
            support = "RANGE_EXPANSION" if range_confirmed else "VOLUME_EXPANSION"
            reason = (
                f"شروع حرکت {side} در {int(chosen['window'])} ثانیه؛ "
                f"حرکت {float(chosen['move_ratio']):.2f} برابر رفتار معمول و تأیید {support}"
            )
            return Observation("TRIGGER", symbol.id, side, int(chosen["window"]), reason, metrics, transition)
        if volume_quote is None:
            return Observation("NEEDS_VOLUME", symbol.id, side, int(chosen["window"]), "PRICE_TRIGGER_NEEDS_SUPPORT", metrics, transition)
        return Observation("WATCH", symbol.id, side, int(chosen["window"]), "PRICE_TRIGGER_WITHOUT_SUPPORT", metrics, transition)

    def mark_signal(self, symbol_id: str) -> None:
        self.watches.pop(symbol_id, None)

    def reset_after_close(self, symbol_id: str) -> None:
        """سهمیه یا کول‌داون نیست؛ فقط موج قبلی از حافظه زنده پاک می‌شود."""
        self.watches.pop(symbol_id, None)
        self.buffers.pop(symbol_id, None)

    @staticmethod
    def _price(entry: float, side: str, pct: float, favorable: bool) -> float:
        sign = 1.0 if side == "LONG" else -1.0
        if not favorable:
            sign *= -1.0
        return entry * (1.0 + sign * pct / 100.0)

    @staticmethod
    def _costs(notional: float, entry: float, exit_price: float) -> float:
        qty = notional / entry if entry > 0 else 0.0
        exit_notional = qty * exit_price
        fee_rate = config.TAKER_FEE_PCT_PER_SIDE / 100.0
        slip_rate = config.SLIPPAGE_PCT_PER_SIDE / 100.0
        return (notional + exit_notional) * (fee_rate + slip_rate)

    @classmethod
    def pnl_for_exit(
        cls, entry: float, exit_price: float, side: str, notional: float
    ) -> tuple[float, float, float]:
        move = (exit_price - entry) / entry if side == "LONG" else (entry - exit_price) / entry
        gross = notional * move
        costs = cls._costs(notional, entry, exit_price)
        return gross, costs, gross - costs

    @classmethod
    def _minimum_profit_tp_pct(
        cls, entry: float, side: str, notional: float
    ) -> float:
        """Smallest TP distance that leaves the configured net profit after costs."""
        low, high = 0.0, 8.0
        for _ in range(60):
            middle = (low + high) / 2.0
            exit_price = cls._price(entry, side, middle, favorable=True)
            _, _, net = cls.pnl_for_exit(entry, exit_price, side, notional)
            if net < config.MIN_NET_PROFIT_USDT:
                low = middle
            else:
                high = middle
        return high

    @staticmethod
    def _behavior_mae_to_mfe(stats: dict[str, Any]) -> float:
        """Read the pre-MFE adverse move; old profiles get a conservative fallback."""
        direct = float(stats.get("mae_to_mfe_q55") or 0.0)
        if direct > 0:
            return direct
        # Version-1 profiles measured MAE across the whole horizon, including the
        # reversal after MFE. Discount it until the automatic v2 rebuild finishes.
        old_q70 = float(stats.get("mae_q70") or 0.0)
        old_q75 = float(stats.get("mae_q75") or 0.0)
        return max(0.0, old_q70 * 0.58, old_q75 * 0.52)

    def build_plan(
        self,
        symbol: SymbolSpec,
        profile: dict[str, Any],
        observation: Observation,
        price: float,
        trade_usdt: float,
        leverage: int,
    ) -> tuple[TradePlan | None, str, dict[str, Any]]:
        if observation.status != "TRIGGER" or observation.side is None or observation.window is None:
            return None, "NOT_A_CONFIRMED_TRIGGER", {}

        side = observation.side
        notional = float(trade_usdt) * int(leverage)
        if price <= 0 or notional <= 0:
            return None, "INVALID_TRADE_INPUT", {"price": price, "notional": notional}

        horizon_rows = profile.get("horizons", {}).get(side, {})
        if not horizon_rows:
            return None, "NO_HISTORICAL_OUTCOME_SAMPLES", {}

        min_profit_tp_pct = self._minimum_profit_tp_pct(price, side, notional)
        move_threshold = float(observation.metrics.get("move_threshold_pct") or 0.0)
        preferred: list[dict[str, Any]] = []
        fallback: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for horizon in config.HORIZONS_MINUTES:
            stats = horizon_rows.get(str(horizon)) or {}
            samples = int(stats.get("samples") or 0)
            if samples <= 0:
                continue

            mfe_q40 = float(stats.get("mfe_q40") or 0.0)
            if mfe_q40 <= 0:
                mfe_q40 = float(stats.get("mfe_q50") or 0.0) * 0.88
            mfe_q60 = float(stats.get("mfe_q60") or stats.get("mfe_q50") or 0.0)
            mae_to_mfe = self._behavior_mae_to_mfe(stats)

            sl_pct = max(
                config.MIN_STOP_PCT,
                mae_to_mfe * config.STOP_BEHAVIOR_BUFFER,
                move_threshold * 0.55,
            )
            if sl_pct > config.MAX_STOP_PCT:
                rejected.append({
                    "horizon": horizon,
                    "reason": "STOP_REQUIRED_TOO_WIDE",
                    "sl_pct": sl_pct,
                    "hard_capacity_pct": mfe_q60,
                })
                continue

            # Standard RR is the price-distance ratio. Fees/slippage are not added
            # to the RR distance; instead the separate 0.05 USDT net-profit rule is
            # enforced below. Mixing both was the main reason all signals died.
            rr_required_tp_pct = sl_pct * config.RISK_REWARD_MIN
            required_tp_pct = max(rr_required_tp_pct, min_profit_tp_pct)
            preferred_capacity = mfe_q40 * config.TP_BEHAVIOR_TARGET_FRACTION
            hard_capacity = mfe_q60 * config.TP_BEHAVIOR_HARD_FRACTION

            if hard_capacity <= 0 or required_tp_pct > hard_capacity:
                rejected.append({
                    "horizon": horizon,
                    "reason": "BEHAVIOR_CAPACITY_INSUFFICIENT_FOR_TP",
                    "sl_pct": sl_pct,
                    "required_tp_pct": required_tp_pct,
                    "preferred_capacity_pct": preferred_capacity,
                    "hard_capacity_pct": hard_capacity,
                    "samples": samples,
                })
                continue

            is_preferred = required_tp_pct <= preferred_capacity
            tp_pct = max(required_tp_pct, preferred_capacity if is_preferred else required_tp_pct)
            tp_pct = min(tp_pct, hard_capacity)
            tp = self._price(price, side, tp_pct, favorable=True)
            sl = self._price(price, side, sl_pct, favorable=False)
            tp_gross, tp_costs, tp_net = self.pnl_for_exit(price, tp, side, notional)
            sl_gross, sl_costs, sl_net = self.pnl_for_exit(price, sl, side, notional)
            sl_net_loss = abs(sl_net)
            rr_distance = tp_pct / sl_pct if sl_pct > 0 else 0.0

            if tp_net < config.MIN_NET_PROFIT_USDT:
                rejected.append({
                    "horizon": horizon,
                    "reason": "NET_PROFIT_BELOW_0_05",
                    "tp_pct": tp_pct,
                    "tp_net_usdt": tp_net,
                })
                continue
            if rr_distance + 1e-9 < config.RISK_REWARD_MIN:
                rejected.append({
                    "horizon": horizon,
                    "reason": "RR_DISTANCE_BELOW_MINIMUM",
                    "tp_pct": tp_pct,
                    "sl_pct": sl_pct,
                    "rr": rr_distance,
                })
                continue

            candidate = {
                "horizon": horizon,
                "samples": samples,
                "mfe_q40": mfe_q40,
                "mfe_q60": mfe_q60,
                "mae_to_mfe_q55": mae_to_mfe,
                "preferred_capacity_pct": preferred_capacity,
                "hard_capacity_pct": hard_capacity,
                "required_tp_pct": required_tp_pct,
                "minimum_profit_tp_pct": min_profit_tp_pct,
                "tp_pct": tp_pct,
                "sl_pct": sl_pct,
                "tp": tp,
                "sl": sl,
                "tp_gross": tp_gross,
                "tp_costs": tp_costs,
                "tp_net": tp_net,
                "sl_gross": sl_gross,
                "sl_costs": sl_costs,
                "sl_net_loss": sl_net_loss,
                "rr": rr_distance,
                "preferred": is_preferred,
                "time_to_mfe_median": float(stats.get("time_to_mfe_median") or horizon),
            }
            (preferred if is_preferred else fallback).append(candidate)

        candidates = preferred or fallback
        if not candidates:
            if not rejected:
                return None, "NO_HISTORICAL_OUTCOME_SAMPLES", {"notional": notional}
            # Show the closest horizon, not dozens of repeated metrics.
            closest = max(
                rejected,
                key=lambda item: float(item.get("hard_capacity_pct") or 0.0)
                / max(float(item.get("required_tp_pct") or 999.0), 1e-9),
            )
            return None, str(closest.get("reason") or "NO_FEASIBLE_HORIZON"), {
                **observation.metrics,
                "horizon": int(closest.get("horizon") or 0),
                "sl_pct": float(closest.get("sl_pct") or 0.0),
                "required_tp_pct": float(closest.get("required_tp_pct") or 0.0),
                "behavior_capacity_pct": float(closest.get("hard_capacity_pct") or 0.0),
                "min_profit_tp_pct": min_profit_tp_pct,
                "notional": notional,
            }

        # Prefer the shortest horizon that supports the target at the cautious
        # behavior level. If none does, use the shortest hard-feasible horizon.
        chosen = min(candidates, key=lambda item: (int(item["horizon"]), float(item["time_to_mfe_median"])))
        metrics: dict[str, Any] = {
            **observation.metrics,
            "expected_minutes": int(chosen["horizon"]),
            "samples": int(chosen["samples"]),
            "behavior_mfe_q40_pct": float(chosen["mfe_q40"]),
            "behavior_mfe_q60_pct": float(chosen["mfe_q60"]),
            "behavior_mae_to_mfe_q55_pct": float(chosen["mae_to_mfe_q55"]),
            "behavior_capacity_pct": float(chosen["hard_capacity_pct"]),
            "required_tp_pct": float(chosen["required_tp_pct"]),
            "tp_pct": float(chosen["tp_pct"]),
            "sl_pct": float(chosen["sl_pct"]),
            "rr": float(chosen["rr"]),
            "tp_net_usdt": float(chosen["tp_net"]),
            "sl_net_loss_usdt": float(chosen["sl_net_loss"]),
            "plan_quality": "CAUTIOUS" if bool(chosen["preferred"]) else "STANDARD",
            "notional": notional,
        }

        plan = TradePlan(
            symbol_id=symbol.id,
            okx_symbol=symbol.okx,
            toobit_symbol=symbol.toobit,
            side=side,
            entry=price,
            tp=float(chosen["tp"]),
            sl=float(chosen["sl"]),
            tp_pct=float(chosen["tp_pct"]),
            sl_pct=float(chosen["sl_pct"]),
            rr_net=float(chosen["rr"]),
            expected_minutes=int(chosen["horizon"]),
            trigger_window=observation.window,
            trigger_reason=observation.reason,
            notional=notional,
            estimated_tp_gross=float(chosen["tp_gross"]),
            estimated_tp_costs=float(chosen["tp_costs"]),
            estimated_tp_net=float(chosen["tp_net"]),
            estimated_sl_gross_loss=abs(float(chosen["sl_gross"])),
            estimated_sl_costs=float(chosen["sl_costs"]),
            estimated_sl_net_loss=float(chosen["sl_net_loss"]),
            metrics=metrics,
        )
        return plan, "PLAN_READY", metrics

