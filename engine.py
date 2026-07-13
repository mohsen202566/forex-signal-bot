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
    def _required_tp_pct(
        cls, entry: float, side: str, notional: float, sl_net_loss: float
    ) -> float:
        target_net = max(config.MIN_NET_PROFIT_USDT, config.RISK_REWARD_MIN * sl_net_loss)
        low, high = 0.0, 8.0
        for _ in range(60):
            middle = (low + high) / 2.0
            exit_price = cls._price(entry, side, middle, favorable=True)
            _, _, net = cls.pnl_for_exit(entry, exit_price, side, notional)
            if net < target_net:
                low = middle
            else:
                high = middle
        return high

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
        horizon_rows = profile["horizons"][side]
        capacities = {
            int(horizon): float(values.get("mfe_q60") or 0.0)
            for horizon, values in horizon_rows.items()
            if int(values.get("samples") or 0) > 0
        }
        if not capacities:
            return None, "NO_HISTORICAL_OUTCOME_SAMPLES", {}
        max_capacity = max(capacities.values())
        expected_minutes = max(capacities, key=capacities.get)
        capture_target = max_capacity * config.HORIZON_CAPTURE_FRACTION
        for horizon in config.HORIZONS_MINUTES:
            if capacities.get(horizon, 0.0) >= capture_target:
                expected_minutes = horizon
                break
        stats = horizon_rows[str(expected_minutes)]
        behavior_mfe = float(stats.get("mfe_q60") or 0.0)
        behavior_mae = float(stats.get("mae_q75") or 0.0)
        move_threshold = float(observation.metrics.get("move_threshold_pct") or 0.0)
        sl_pct = max(
            config.MIN_STOP_PCT,
            behavior_mae * config.STOP_BEHAVIOR_BUFFER,
            move_threshold * 0.90,
        )
        metrics: dict[str, Any] = {
            **observation.metrics,
            "expected_minutes": expected_minutes,
            "behavior_mfe_q60_pct": behavior_mfe,
            "behavior_mae_q75_pct": behavior_mae,
            "sl_pct": sl_pct,
        }
        if sl_pct > config.MAX_STOP_PCT:
            return None, "STOP_REQUIRED_TOO_WIDE", metrics

        notional = float(trade_usdt) * int(leverage)
        if price <= 0 or notional <= 0:
            return None, "INVALID_TRADE_INPUT", metrics
        sl = self._price(price, side, sl_pct, favorable=False)
        sl_gross, sl_costs, sl_net = self.pnl_for_exit(price, sl, side, notional)
        sl_net_loss = abs(sl_net)
        required_tp = self._required_tp_pct(price, side, notional, sl_net_loss)
        cautious_capacity = behavior_mfe * config.TP_BEHAVIOR_FRACTION
        behavior_floor = behavior_mfe * config.TP_BEHAVIOR_FLOOR_FRACTION
        tp_pct = max(required_tp, behavior_floor)
        metrics.update(
            {
                "notional": notional,
                "required_tp_pct": required_tp,
                "cautious_capacity_pct": cautious_capacity,
                "behavior_floor_pct": behavior_floor,
                "tp_pct": tp_pct,
            }
        )
        if cautious_capacity <= 0 or tp_pct > cautious_capacity:
            return None, "BEHAVIOR_CAPACITY_INSUFFICIENT_FOR_TP", metrics
        tp = self._price(price, side, tp_pct, favorable=True)
        tp_gross, tp_costs, tp_net = self.pnl_for_exit(price, tp, side, notional)
        rr_net = tp_net / sl_net_loss if sl_net_loss > 0 else 0.0
        metrics.update(
            {
                "tp_net_usdt": tp_net,
                "tp_costs_usdt": tp_costs,
                "sl_net_loss_usdt": sl_net_loss,
                "sl_costs_usdt": sl_costs,
                "rr_net": rr_net,
            }
        )
        if tp_net < config.MIN_NET_PROFIT_USDT:
            return None, "NET_PROFIT_BELOW_0_05", metrics
        if rr_net + 1e-6 < config.RISK_REWARD_MIN:
            return None, "NET_RR_BELOW_MINIMUM", metrics

        plan = TradePlan(
            symbol_id=symbol.id,
            okx_symbol=symbol.okx,
            toobit_symbol=symbol.toobit,
            side=side,
            entry=price,
            tp=tp,
            sl=sl,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            rr_net=rr_net,
            expected_minutes=expected_minutes,
            trigger_window=observation.window,
            trigger_reason=observation.reason,
            notional=notional,
            estimated_tp_gross=tp_gross,
            estimated_tp_costs=tp_costs,
            estimated_tp_net=tp_net,
            estimated_sl_gross_loss=abs(sl_gross),
            estimated_sl_costs=sl_costs,
            estimated_sl_net_loss=sl_net_loss,
            metrics=metrics,
        )
        return plan, "PLAN_READY", metrics
