"""حافظه سبک ربات: تنظیمات، سیگنال‌ها، آمار جداگانه توبیت و عادی."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from config import RuntimeSettings

STATE_PATH = Path("state_store.json")


def now_ts() -> int:
    return int(time.time())


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class StateStore:
    def __init__(self, path: Path = STATE_PATH):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return self._default_state()

    def _default_state(self) -> dict[str, Any]:
        s = RuntimeSettings.from_env()
        return {
            "settings": {
                "real_trade_enabled": s.real_trade_enabled,
                "trade_margin_usdt": s.trade_margin_usdt,
                "leverage": s.leverage,
                "max_open_positions": s.max_open_positions,
                "min_net_profit_usdt": s.min_net_profit_usdt,
            },
            "active_signals": {},       # همه سیگنال‌های عادی و توبیت
            "stats": {
                "signal": {"total": 0, "tp": 0, "sl": 0, "expired": 0, "replaced": 0},
                "tobit": {"total": 0, "tp": 0, "sl": 0, "failed_open": 0, "expired": 0, "net_pnl": 0.0},
            },
            "last_scan": None,
        }

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def settings(self) -> dict[str, Any]:
        return self.data["settings"]

    def update_setting(self, key: str, value: Any) -> None:
        self.data["settings"][key] = value
        self.save()

    def active_by_coin(self, coin: str, kind: str | None = None) -> list[dict[str, Any]]:
        out = []
        for sig in self.data["active_signals"].values():
            if sig.get("coin") != coin:
                continue
            if kind and sig.get("kind") != kind:
                continue
            if sig.get("status") in {"ACTIVE", "PENDING_OPEN", "OPEN"}:
                out.append(sig)
        return out

    def has_active_real_for_coin(self, coin: str) -> bool:
        return any(s.get("status") in {"PENDING_OPEN", "OPEN"} for s in self.active_by_coin(coin, "TOBIT"))

    def open_real_count(self) -> int:
        return sum(
            1 for s in self.data["active_signals"].values()
            if s.get("kind") == "TOBIT" and s.get("status") in {"PENDING_OPEN", "OPEN"}
        )

    def add_signal(self, signal: dict[str, Any]) -> str:
        sid = signal.get("id") or new_id("sig" if signal.get("kind") == "SIGNAL" else "tobit")
        signal["id"] = sid
        signal.setdefault("created_at", now_ts())
        self.data["active_signals"][sid] = signal
        self.data["stats"]["signal" if signal.get("kind") == "SIGNAL" else "tobit"]["total"] += 1
        self.save()
        return sid

    def close_signal(self, signal_id: str, result: str, extra: dict[str, Any] | None = None) -> None:
        sig = self.data["active_signals"].get(signal_id)
        if not sig:
            return
        sig["status"] = result
        sig["closed_at"] = now_ts()
        if extra:
            sig.update(extra)
        bucket = "signal" if sig.get("kind") == "SIGNAL" else "tobit"
        key = result.lower()
        if key in self.data["stats"][bucket]:
            self.data["stats"][bucket][key] += 1
        if bucket == "tobit" and extra and "net_pnl" in extra:
            self.data["stats"][bucket]["net_pnl"] += float(extra["net_pnl"])
        self.save()

    def mark_open(self, signal_id: str, exchange_position_id: str | None = None) -> None:
        sig = self.data["active_signals"].get(signal_id)
        if not sig:
            return
        sig["status"] = "OPEN"
        if exchange_position_id:
            sig["exchange_position_id"] = exchange_position_id
        self.save()

    def all_active(self) -> list[dict[str, Any]]:
        return [
            s for s in self.data["active_signals"].values()
            if s.get("status") in {"ACTIVE", "PENDING_OPEN", "OPEN"}
        ]
