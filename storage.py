"""ذخیره پایدار تنظیمات، پروفایل‌ها، سیگنال‌ها، نتایج و سلامت در SQLite."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
import json
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo
from datetime import datetime

import config


class Storage:
    def __init__(self, path: str = config.DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=NORMAL")
                db.execute("PRAGMA foreign_keys=ON")
                yield db
            finally:
                db.close()

    def _init_db(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS kv(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profiles(
                    symbol_id TEXT PRIMARY KEY,
                    okx_symbol TEXT NOT NULL,
                    toobit_symbol TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    candle_count INTEGER NOT NULL,
                    profile_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signals(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol_id TEXT NOT NULL,
                    okx_symbol TEXT NOT NULL,
                    toobit_symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry REAL NOT NULL,
                    tp REAL NOT NULL,
                    sl REAL NOT NULL,
                    tp_pct REAL NOT NULL,
                    sl_pct REAL NOT NULL,
                    rr REAL NOT NULL,
                    expected_minutes INTEGER NOT NULL,
                    trigger_window INTEGER NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_real INTEGER NOT NULL DEFAULT 0,
                    message_id INTEGER,
                    order_id TEXT,
                    quantity TEXT,
                    trade_usdt REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    notional REAL NOT NULL,
                    estimated_tp_net REAL NOT NULL DEFAULT 0,
                    estimated_sl_net_loss REAL NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    opened_at INTEGER,
                    closed_at INTEGER,
                    entry_real REAL,
                    close_price REAL,
                    gross_pnl REAL NOT NULL DEFAULT 0,
                    fees REAL NOT NULL DEFAULT 0,
                    net_pnl REAL NOT NULL DEFAULT 0,
                    result TEXT,
                    mfe_pct REAL NOT NULL DEFAULT 0,
                    mae_pct REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol_status ON signals(symbol_id,status);
                CREATE TABLE IF NOT EXISTS health_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    symbol_id TEXT,
                    created_at INTEGER NOT NULL,
                    cleared_at INTEGER
                );
                """
            )
        defaults = {
            "trading_enabled": config.TRADING_ENABLED_DEFAULT,
            "auto_signal_enabled": config.AUTO_SIGNAL_ENABLED_DEFAULT,
            "trade_usdt": config.TRADE_USDT_DEFAULT,
            "leverage": config.LEVERAGE_DEFAULT,
            "max_positions": config.MAX_POSITIONS_DEFAULT,
            "telegram_offset": 0,
            "toobit_connected": False,
            "toobit_available_usdt": 0.0,
            "toobit_total_usdt": 0.0,
            "toobit_margin_usdt": 0.0,
            "toobit_last_error": "",
            "toobit_last_update": 0,
            "profiles_ready": 0,
            "profiles_updated_at": 0,
            "stats_reset_at": int(time.time()),
            "profit_reset_at": int(time.time()),
            "profit_today": 0.0,
            "profit_total": 0.0,
            "profit_day": self._today(),
        }
        for key, value in defaults.items():
            if self.get(key, None) is None:
                self.set(key, value)

    @staticmethod
    def _today() -> str:
        return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")

    def get(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(str(row["value"]))
        except (TypeError, json.JSONDecodeError):
            return default

    def set(self, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO kv(key,value,updated_at) VALUES(?,?,?)",
                (key, json.dumps(value, ensure_ascii=False), int(time.time())),
            )

    def save_profile(self, symbol_id: str, okx_symbol: str, toobit_symbol: str, profile: dict[str, Any]) -> None:
        now = int(time.time())
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO profiles(symbol_id,okx_symbol,toobit_symbol,updated_at,candle_count,profile_json)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(symbol_id) DO UPDATE SET
                    okx_symbol=excluded.okx_symbol,
                    toobit_symbol=excluded.toobit_symbol,
                    updated_at=excluded.updated_at,
                    candle_count=excluded.candle_count,
                    profile_json=excluded.profile_json
                """,
                (
                    symbol_id,
                    okx_symbol,
                    toobit_symbol,
                    now,
                    int(profile.get("candle_count") or 0),
                    json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
                ),
            )

    def load_profile(self, symbol_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM profiles WHERE symbol_id=?", (symbol_id,)).fetchone()
        if row is None:
            return None
        try:
            profile = json.loads(str(row["profile_json"]))
            profile["_stored_updated_at"] = int(row["updated_at"])
            return profile
        except (TypeError, json.JSONDecodeError):
            return None

    def profile_rows(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT symbol_id,updated_at,candle_count FROM profiles ORDER BY symbol_id").fetchall()
        return [dict(row) for row in rows]

    def is_profile_fresh(self, symbol_id: str, max_age_hours: float = config.PROFILE_FRESH_HOURS) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT updated_at,candle_count FROM profiles WHERE symbol_id=?", (symbol_id,)).fetchone()
        if row is None:
            return False
        return (
            int(row["candle_count"]) >= config.PROFILE_MIN_CANDLES
            and time.time() - int(row["updated_at"]) <= max_age_hours * 3600
        )

    def has_active_signal(self, symbol_id: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM signals WHERE symbol_id=? AND status IN ('pending','open') LIMIT 1",
                (symbol_id,),
            ).fetchone()
        return row is not None

    def create_signal(self, data: dict[str, Any]) -> int | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM signals WHERE symbol_id=? AND status IN ('pending','open') LIMIT 1",
                (data["symbol_id"],),
            ).fetchone()
            if exists:
                db.execute("ROLLBACK")
                return None
            columns = (
                "symbol_id,okx_symbol,toobit_symbol,side,entry,tp,sl,tp_pct,sl_pct,rr,"
                "expected_minutes,trigger_window,trigger_reason,mode,status,is_real,message_id,order_id,quantity,"
                "trade_usdt,leverage,notional,estimated_tp_net,estimated_sl_net_loss,created_at,opened_at,entry_real,raw_json"
            )
            values = (
                data["symbol_id"], data["okx_symbol"], data["toobit_symbol"], data["side"],
                data["entry"], data["tp"], data["sl"], data["tp_pct"], data["sl_pct"], data["rr"],
                data["expected_minutes"], data["trigger_window"], data["trigger_reason"], data["mode"],
                data["status"], int(bool(data.get("is_real"))), data.get("message_id"), data.get("order_id"),
                data.get("quantity"), data["trade_usdt"], data["leverage"], data["notional"],
                data.get("estimated_tp_net", 0.0), data.get("estimated_sl_net_loss", 0.0),
                int(data.get("created_at") or time.time()), data.get("opened_at"), data.get("entry_real"),
                json.dumps(data.get("raw") or {}, ensure_ascii=False),
            )
            placeholders = ",".join("?" for _ in values)
            cursor = db.execute(f"INSERT INTO signals({columns}) VALUES({placeholders})", values)
            signal_id = int(cursor.lastrowid)
            db.execute("COMMIT")
            return signal_id

    def update_signal(self, signal_id: int, **fields: Any) -> None:
        allowed = {
            "status", "message_id", "order_id", "quantity", "opened_at", "entry_real", "closed_at",
            "close_price", "gross_pnl", "fees", "net_pnl", "result", "mfe_pct", "mae_pct",
            "mode", "is_real", "raw_json",
        }
        items = [(key, value) for key, value in fields.items() if key in allowed]
        if not items:
            return
        sql = ",".join(f"{key}=?" for key, _ in items)
        values: list[Any] = []
        for key, value in items:
            if key == "raw_json" and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            values.append(value)
        values.append(signal_id)
        with self.connect() as db:
            db.execute(f"UPDATE signals SET {sql} WHERE id=?", values)

    def get_signal(self, signal_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
        return dict(row) if row else None

    def get_active_signals(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM signals WHERE status IN ('pending','open') ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def count_real_active(self) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM signals WHERE is_real=1 AND status IN ('pending','open')"
            ).fetchone()
        return int(row["n"])

    def close_signal(
        self,
        signal_id: int,
        *,
        close_price: float,
        gross_pnl: float,
        fees: float,
        net_pnl: float,
        result: str,
        mfe_pct: float,
        mae_pct: float,
        entry_real: float | None = None,
        closed_at: int | None = None,
    ) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM signals WHERE id=?", (signal_id,)).fetchone()
            if row is None or str(row["status"]) == "closed":
                db.execute("ROLLBACK")
                return False
            db.execute(
                """
                UPDATE signals SET status='closed',closed_at=?,close_price=?,gross_pnl=?,fees=?,net_pnl=?,
                    result=?,mfe_pct=?,mae_pct=?,entry_real=COALESCE(?,entry_real)
                WHERE id=?
                """,
                (
                    int(closed_at or time.time()), close_price, gross_pnl, fees, net_pnl,
                    result, mfe_pct, mae_pct, entry_real, signal_id,
                ),
            )
            db.execute("COMMIT")
        self.roll_profit_day()
        self.set("profit_today", float(self.get("profit_today", 0.0)) + float(net_pnl))
        self.set("profit_total", float(self.get("profit_total", 0.0)) + float(net_pnl))
        return True

    def roll_profit_day(self) -> None:
        today = self._today()
        if self.get("profit_day", "") != today:
            self.set("profit_day", today)
            self.set("profit_today", 0.0)

    def reset_stats(self) -> None:
        self.set("stats_reset_at", int(time.time()))

    def reset_profit(self) -> None:
        self.set("profit_reset_at", int(time.time()))
        self.set("profit_today", 0.0)
        self.set("profit_total", 0.0)
        self.set("profit_day", self._today())

    def stats(self) -> dict[str, Any]:
        reset_at = int(self.get("stats_reset_at", 0) or 0)
        with self.connect() as db:
            rows = db.execute("SELECT * FROM signals WHERE created_at>=? ORDER BY id", (reset_at,)).fetchall()
        items = [dict(row) for row in rows]
        closed = [row for row in items if row["status"] == "closed"]
        tp = sum(1 for row in closed if row.get("result") == "TP")
        sl = sum(1 for row in closed if row.get("result") == "SL")
        real = [row for row in items if int(row.get("is_real") or 0)]
        virtual = [row for row in items if not int(row.get("is_real") or 0)]
        return {
            "signals": len(items),
            "open": sum(1 for row in items if row["status"] in ("pending", "open")),
            "pending": sum(1 for row in items if row["status"] == "pending"),
            "tp": tp,
            "sl": sl,
            "real": len(real),
            "virtual": len(virtual),
            "net_pnl": sum(float(row.get("net_pnl") or 0.0) for row in closed),
            "real_net": sum(float(row.get("net_pnl") or 0.0) for row in real if row["status"] == "closed"),
            "virtual_net": sum(float(row.get("net_pnl") or 0.0) for row in virtual if row["status"] == "closed"),
        }

    def add_health_event(self, component: str, severity: str, message: str, symbol_id: str | None = None) -> None:
        now = int(time.time())
        with self.connect() as db:
            duplicate = db.execute(
                """
                SELECT 1 FROM health_events
                WHERE component=? AND severity=? AND message=? AND COALESCE(symbol_id,'')=COALESCE(?, '')
                  AND cleared_at IS NULL AND created_at>=? LIMIT 1
                """,
                (component, severity, message, symbol_id, now - 300),
            ).fetchone()
            if duplicate:
                return
            db.execute(
                "INSERT INTO health_events(component,severity,message,symbol_id,created_at) VALUES(?,?,?,?,?)",
                (component, severity, message, symbol_id, now),
            )

    def clear_health(self, component: str, symbol_id: str | None = None) -> None:
        with self.connect() as db:
            if symbol_id is None:
                db.execute(
                    "UPDATE health_events SET cleared_at=? WHERE component=? AND cleared_at IS NULL",
                    (int(time.time()), component),
                )
            else:
                db.execute(
                    "UPDATE health_events SET cleared_at=? WHERE component=? AND symbol_id=? AND cleared_at IS NULL",
                    (int(time.time()), component, symbol_id),
                )

    def active_health_events(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM health_events WHERE cleared_at IS NULL ORDER BY id DESC LIMIT 20"
            ).fetchall()
        return [dict(row) for row in rows]
