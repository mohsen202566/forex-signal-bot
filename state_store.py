"""حافظه سبک ربات: تنظیمات، سیگنال‌ها، اسلات‌ها و آمار جداگانه توبیت/سیگنال.

قفل‌های اجرایی:
- سیگنال عادی و سیگنال توبیت جدا ثبت و جدا آمارگیری می‌شوند.
- برای هر کوین فقط یک REAL فعال یا در انتظار باز شدن مجاز است.
- وضعیت‌های اصلی: ACTIVE, PENDING_OPEN, OPEN, TP, SL, EXPIRED, REPLACED, FAILED_OPEN.
- سیگنال عادی ۳ دقیقه اعتبار دارد و در صورت سیگنال قوی‌تر با REPLACED بسته می‌شود.
- اسلات REAL با PENDING_OPEN پر می‌شود و با FAILED_OPEN / TP / SL / EXPIRED آزاد می‌شود.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import config
from config import RuntimeSettings

STATE_PATH = Path("state_store.json")

ACTIVE_STATUSES = {"ACTIVE", "PENDING_OPEN", "OPEN"}
CLOSED_STATUSES = {"TP", "SL", "EXPIRED", "REPLACED", "FAILED_OPEN"}
VALID_KINDS = {"SIGNAL", "TOBIT"}


def now_ts() -> int:
    return int(time.time())


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _stats_template(kind: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "total": 0,
        "tp": 0,
        "sl": 0,
        "expired": 0,
        "replaced": 0,
        "win_rate": 0.0,
        "last_result": None,
        "last_signal_id": None,
    }
    if kind == "tobit":
        base.update({"failed_open": 0, "net_pnl": 0.0})
    return base


class StateStore:
    def __init__(self, path: Path = STATE_PATH):
        self.path = path
        self.data = self._load()
        self._migrate()
        self.save()

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
            "active_signals": {},
            "stats": {
                "signal": _stats_template("signal"),
                "tobit": _stats_template("tobit"),
            },
            "runtime": {
                "last_scan": None,
                "last_signal_id": None,
                "last_result": None,
                "engine_health": "UNKNOWN",
            },
        }

    def _migrate(self) -> None:
        """قدیمی بودن state_store.json نباید ربات را خراب کند."""
        default = self._default_state()
        self.data.setdefault("settings", default["settings"])
        self.data.setdefault("active_signals", {})
        self.data.setdefault("stats", {})
        self.data.setdefault("runtime", {})

        # سازگاری با نسخه قبلی که last_scan در ریشه بود.
        if "last_scan" in self.data and not self.data["runtime"].get("last_scan"):
            self.data["runtime"]["last_scan"] = self.data.get("last_scan")

        for key, value in default["settings"].items():
            self.data["settings"].setdefault(key, value)

        for bucket in ("signal", "tobit"):
            self.data["stats"].setdefault(bucket, _stats_template(bucket))
            template = _stats_template(bucket)
            for key, value in template.items():
                self.data["stats"][bucket].setdefault(key, value)

        for key, value in default["runtime"].items():
            self.data["runtime"].setdefault(key, value)

        # تکمیل فیلدهای ضروری سیگنال‌های قدیمی.
        for sig in self.data["active_signals"].values():
            kind = self._normalize_kind(sig.get("kind"))
            sig["kind"] = kind
            sig.setdefault("status", "ACTIVE")
            sig.setdefault("created_at", now_ts())
            if kind == "SIGNAL":
                sig.setdefault("expires_at", int(sig["created_at"]) + int(config.SIGNAL_VALID_SECONDS))

    def save(self) -> None:
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def settings(self) -> dict[str, Any]:
        return self.data["settings"]

    def update_setting(self, key: str, value: Any) -> None:
        self.data["settings"][key] = value
        self.save()

    def update_runtime(self, **kwargs: Any) -> None:
        self.data.setdefault("runtime", {}).update(kwargs)
        self.save()

    def active_by_coin(self, coin: str, kind: str | None = None) -> list[dict[str, Any]]:
        coin = coin.upper()
        normalized_kind = self._normalize_kind(kind) if kind else None
        out: list[dict[str, Any]] = []
        for sig in self.data["active_signals"].values():
            if str(sig.get("coin", "")).upper() != coin:
                continue
            if normalized_kind and self._normalize_kind(sig.get("kind")) != normalized_kind:
                continue
            if sig.get("status") in ACTIVE_STATUSES:
                out.append(sig)
        return out

    def has_active_real_for_coin(self, coin: str) -> bool:
        return any(s.get("status") in {"PENDING_OPEN", "OPEN"} for s in self.active_by_coin(coin, "TOBIT"))

    def open_real_count(self) -> int:
        return sum(
            1 for s in self.data["active_signals"].values()
            if self._normalize_kind(s.get("kind")) == "TOBIT" and s.get("status") in {"PENDING_OPEN", "OPEN"}
        )

    def can_open_real(self, coin: str) -> bool:
        max_positions = int(self.settings().get("max_open_positions", 1))
        return (not self.has_active_real_for_coin(coin)) and self.open_real_count() < max_positions

    def add_signal(self, signal: dict[str, Any]) -> str:
        sig = dict(signal)
        kind = self._normalize_kind(sig.get("kind"))
        coin = str(sig.get("coin", "")).upper()
        if not coin:
            raise ValueError("signal.coin الزامی است.")
        sig["coin"] = coin
        sig["kind"] = kind

        if kind == "TOBIT" and self.has_active_real_for_coin(coin):
            raise RuntimeError(f"برای {coin} سیگنال توبیت فعال یا PENDING وجود دارد.")

        sid = sig.get("id") or new_id("sig" if kind == "SIGNAL" else "tobit")
        sig["id"] = sid
        sig.setdefault("created_at", now_ts())
        sig.setdefault("status", "ACTIVE" if kind == "SIGNAL" else "PENDING_OPEN")
        if kind == "SIGNAL":
            sig.setdefault("expires_at", int(sig["created_at"]) + int(config.SIGNAL_VALID_SECONDS))

        self.data["active_signals"][sid] = sig
        bucket = self._bucket(sig)
        self.data["stats"][bucket]["total"] += 1
        self.data["stats"][bucket]["last_signal_id"] = sid
        self.data["runtime"]["last_signal_id"] = sid
        self.save()
        return sid

    def close_signal(self, signal_id: str, result: str, extra: dict[str, Any] | None = None) -> bool:
        sig = self.data["active_signals"].get(signal_id)
        if not sig:
            return False
        if sig.get("status") in CLOSED_STATUSES:
            return False

        result = result.upper()
        sig["status"] = result
        sig["closed_at"] = now_ts()
        if extra:
            sig.update(extra)

        bucket = self._bucket(sig)
        key = result.lower()
        if key in self.data["stats"][bucket]:
            self.data["stats"][bucket][key] += 1
        if bucket == "tobit" and extra and "net_pnl" in extra:
            self.data["stats"][bucket]["net_pnl"] += float(extra["net_pnl"])

        self.data["stats"][bucket]["last_result"] = result
        self.data["stats"][bucket]["last_signal_id"] = signal_id
        self.data["runtime"]["last_result"] = result
        self._refresh_win_rate(bucket)
        self.save()
        return True

    def replace_signal(self, signal_id: str, extra: dict[str, Any] | None = None) -> bool:
        return self.close_signal(signal_id, "REPLACED", extra)

    def mark_open(
        self,
        signal_id: str,
        exchange_position_id: str | None = None,
        order_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        sig = self.data["active_signals"].get(signal_id)
        if not sig or sig.get("status") in CLOSED_STATUSES:
            return False
        sig["status"] = "OPEN"
        sig["opened_at"] = now_ts()
        if exchange_position_id:
            sig["exchange_position_id"] = exchange_position_id
        if order_id:
            sig["order_id"] = order_id
        if extra:
            sig.update(extra)
        self.save()
        return True

    def mark_failed_open(self, signal_id: str, extra: dict[str, Any] | None = None) -> bool:
        return self.close_signal(signal_id, "FAILED_OPEN", extra)

    def all_active(self) -> list[dict[str, Any]]:
        return [
            s for s in self.data["active_signals"].values()
            if s.get("status") in ACTIVE_STATUSES
        ]

    def expired_signals(self, ts: int | None = None) -> list[dict[str, Any]]:
        current = ts or now_ts()
        return [
            s for s in self.all_active()
            if self._normalize_kind(s.get("kind")) == "SIGNAL" and int(s.get("expires_at", 0)) <= current
        ]

    def _refresh_win_rate(self, bucket: str) -> None:
        stats = self.data["stats"][bucket]
        resolved = int(stats.get("tp", 0)) + int(stats.get("sl", 0))
        stats["win_rate"] = round((int(stats.get("tp", 0)) / resolved * 100), 2) if resolved else 0.0

    @staticmethod
    def _normalize_kind(kind: Any) -> str:
        normalized = str(kind or "SIGNAL").upper()
        if normalized not in VALID_KINDS:
            raise ValueError("kind باید SIGNAL یا TOBIT باشد.")
        return normalized

    @staticmethod
    def _bucket(sig: dict[str, Any]) -> str:
        return "signal" if str(sig.get("kind", "SIGNAL")).upper() == "SIGNAL" else "tobit"
