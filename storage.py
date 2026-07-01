from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import config


@dataclass
class BotSettings:
    trade_enabled: bool = config.DEFAULT_TRADE_ENABLED
    margin_usdt: float = config.DEFAULT_MARGIN_USDT
    leverage: int = config.DEFAULT_LEVERAGE
    max_positions: int = config.DEFAULT_MAX_POSITIONS


@dataclass
class StoredSignal:
    signal_id: str
    base_symbol: str
    toobit_symbol: str
    direction: str
    entry_price: float
    tp_price: float
    sl_price: float
    margin_usdt: float
    leverage: int
    telegram_message_id: int | None = None
    opened_at_ms: int | None = None
    status: str = "open"
    # real = opened on Toobit. Everything else is tracked as paper/virtual so the bot performance is still measurable.
    execution_mode: str = "real"
    execution_reason: str = ""
    order_id: str | None = None


@dataclass
class StorageState:
    settings: BotSettings = field(default_factory=BotSettings)
    signals: dict[str, StoredSignal] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)


class JsonStorage:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.BOT_DATA_DIR / "runtime_state.json")
        self._lock = threading.RLock()
        self.state = StorageState()
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._init_stats()
                self.save()
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            settings = BotSettings(**data.get("settings", {}))
            signals = {k: StoredSignal(**v) for k, v in data.get("signals", {}).items()}
            stats = data.get("stats", {})
            self.state = StorageState(settings=settings, signals=signals, stats=stats)
            self._init_stats()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "settings": asdict(self.state.settings),
                "signals": {k: asdict(v) for k, v in self.state.signals.items()},
                "stats": self.state.stats,
            }
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _init_stats(self) -> None:
        defaults = {
            "signals": 0,
            "real_signals": 0,
            "paper_signals": 0,
            "trade_off_signals": 0,
            "blocked_slot_signals": 0,
            "order_failed_signals": 0,
            "tp": 0,
            "sl": 0,
            "smart_exit": 0,
            "manual_close": 0,
            "estimated_pnl_usdt": 0.0,
            "by_symbol": {},
        }
        for key, value in defaults.items():
            self.state.stats.setdefault(key, value)

    def update_settings(self, **kwargs: Any) -> BotSettings:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.state.settings, key):
                    setattr(self.state.settings, key, value)
            self.save()
            return self.state.settings

    def add_signal(self, signal: StoredSignal) -> None:
        with self._lock:
            self.state.signals[signal.signal_id] = signal
            self.state.stats["signals"] = int(self.state.stats.get("signals", 0)) + 1
            if signal.execution_mode == "real":
                self.state.stats["real_signals"] = int(self.state.stats.get("real_signals", 0)) + 1
            else:
                self.state.stats["paper_signals"] = int(self.state.stats.get("paper_signals", 0)) + 1
                if signal.execution_mode == "paper_trade_off":
                    self.state.stats["trade_off_signals"] = int(self.state.stats.get("trade_off_signals", 0)) + 1
                elif signal.execution_mode == "paper_slots_full":
                    self.state.stats["blocked_slot_signals"] = int(self.state.stats.get("blocked_slot_signals", 0)) + 1
                elif signal.execution_mode == "paper_order_failed":
                    self.state.stats["order_failed_signals"] = int(self.state.stats.get("order_failed_signals", 0)) + 1

            by_symbol = self.state.stats.setdefault("by_symbol", {})
            by_symbol.setdefault(signal.base_symbol, {"signals": 0, "tp": 0, "sl": 0, "smart_exit": 0})
            by_symbol[signal.base_symbol]["signals"] += 1
            self.save()

    def set_signal_message_id(self, signal_id: str, message_id: int) -> None:
        with self._lock:
            if signal_id in self.state.signals:
                self.state.signals[signal_id].telegram_message_id = int(message_id)
                self.save()

    def close_signal(self, signal_id: str, status: str, pnl_usdt: float = 0.0) -> StoredSignal | None:
        with self._lock:
            sig = self.state.signals.get(signal_id)
            if not sig or sig.status != "open":
                return sig
            sig.status = status
            if status in {"tp", "sl", "smart_exit", "manual_close"}:
                self.state.stats[status] = int(self.state.stats.get(status, 0)) + 1
            self.state.stats["estimated_pnl_usdt"] = float(self.state.stats.get("estimated_pnl_usdt", 0.0)) + float(pnl_usdt)
            by_symbol = self.state.stats.setdefault("by_symbol", {})
            by_symbol.setdefault(sig.base_symbol, {"signals": 0, "tp": 0, "sl": 0, "smart_exit": 0})
            if status in by_symbol[sig.base_symbol]:
                by_symbol[sig.base_symbol][status] += 1
            self.save()
            return sig

    def open_signals(self) -> list[StoredSignal]:
        return [s for s in self.state.signals.values() if s.status == "open"]

    def real_open_signals(self) -> list[StoredSignal]:
        return [s for s in self.open_signals() if s.execution_mode == "real"]

    def paper_open_signals(self) -> list[StoredSignal]:
        return [s for s in self.open_signals() if s.execution_mode != "real"]

    def slot_status(self) -> tuple[int, int, int]:
        used = len(self.real_open_signals())
        total = int(self.state.settings.max_positions)
        free = max(0, total - used)
        return used, total, free

    def has_open_signal(self, base_symbol: str, direction: str | None = None) -> bool:
        base = base_symbol.upper().strip()
        direction = direction.upper().strip() if direction else None
        for sig in self.open_signals():
            if sig.base_symbol.upper() != base:
                continue
            if direction and sig.direction.upper() != direction:
                continue
            return True
        return False

    def reset_stats(self) -> None:
        with self._lock:
            self.state.stats = {}
            self._init_stats()
            self.save()

    def delete_all(self) -> None:
        with self._lock:
            self.state = StorageState()
            self._init_stats()
            self.save()
