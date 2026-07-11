"""SQLite persistence layer for the 15-minute trading bot.

Responsibilities:
- persistent key/value settings
- signal lifecycle and atomic close
- statistics and profit counters
- health events and temporary blacklist
- daily symbol profiles

This module contains no trading logic and performs no network requests.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import config


_JSON_SIGNAL_FIELDS = {"raw_json", "stop_analysis_json"}


class Storage:
    """Thread-safe SQLite storage used by all bot components."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured = path if path is not None else config.DB_PATH
        self.path = Path(configured).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived SQLite connection under the process lock."""
        with self._lock:
            conn = sqlite3.connect(
                str(self.path),
                timeout=15,
                isolation_level=None,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=15000")
                yield conn
            finally:
                conn.close()

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode(value: str, default: Any = None) -> Any:
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    def _init_db(self) -> None:
        now = int(time.time())
        today = datetime.now(timezone.utc).date().isoformat()

        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol_id TEXT NOT NULL,
                    okx_symbol TEXT NOT NULL,
                    toobit_symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    strength TEXT,
                    entry REAL NOT NULL,
                    tp REAL NOT NULL,
                    sl REAL NOT NULL,
                    rr REAL NOT NULL,
                    trade_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_real INTEGER NOT NULL DEFAULT 0,
                    slot_id INTEGER,
                    message_id INTEGER,
                    created_at INTEGER NOT NULL,
                    opened_at INTEGER,
                    closed_at INTEGER,
                    entry_real REAL,
                    exit_price REAL,
                    gross_pnl REAL NOT NULL DEFAULT 0,
                    fee_usdt REAL NOT NULL DEFAULT 0,
                    net_pnl REAL NOT NULL DEFAULT 0,
                    close_reason TEXT,
                    mfe REAL NOT NULL DEFAULT 0,
                    mae REAL NOT NULL DEFAULT 0,
                    order_id TEXT,
                    trade_usdt REAL NOT NULL DEFAULT 0,
                    leverage INTEGER NOT NULL DEFAULT 1,
                    notional_usdt REAL NOT NULL DEFAULT 0,
                    estimated_net_profit REAL NOT NULL DEFAULT 0,
                    estimated_net_loss REAL NOT NULL DEFAULT 0,
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    net_rr REAL NOT NULL DEFAULT 0,
                    stop_primary TEXT NOT NULL DEFAULT '',
                    stop_confidence REAL NOT NULL DEFAULT 0,
                    stop_analysis_json TEXT NOT NULL DEFAULT '{}',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    result_message_sent INTEGER NOT NULL DEFAULT 0,
                    result_message_retry_count INTEGER NOT NULL DEFAULT 0,
                    result_message_last_error TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_signals_status
                    ON signals(status, id);
                CREATE INDEX IF NOT EXISTS idx_signals_created
                    ON signals(created_at, id);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol_open
                    ON signals(symbol_id, status);
                CREATE INDEX IF NOT EXISTS idx_signals_pending_delivery
                    ON signals(status, result_message_sent, result_message_retry_count, id);

                CREATE TABLE IF NOT EXISTS health_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    symbol_id TEXT,
                    created_at INTEGER NOT NULL,
                    cleared_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_health_active
                    ON health_events(cleared_at, id);

                CREATE TABLE IF NOT EXISTS blacklist (
                    symbol_id TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    until_ts INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS profiles (
                    symbol_id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    updated_at INTEGER NOT NULL
                );
                """
            )

            # Compatible, non-destructive migration from older databases.
            existing = {
                str(row[1]) for row in db.execute("PRAGMA table_info(signals)").fetchall()
            }
            migrations = {
                "trade_usdt": "REAL NOT NULL DEFAULT 0",
                "leverage": "INTEGER NOT NULL DEFAULT 1",
                "notional_usdt": "REAL NOT NULL DEFAULT 0",
                "estimated_net_profit": "REAL NOT NULL DEFAULT 0",
                "estimated_net_loss": "REAL NOT NULL DEFAULT 0",
                "estimated_cost": "REAL NOT NULL DEFAULT 0",
                "net_rr": "REAL NOT NULL DEFAULT 0",
                "stop_primary": "TEXT NOT NULL DEFAULT ''",
                "stop_confidence": "REAL NOT NULL DEFAULT 0",
                "stop_analysis_json": "TEXT NOT NULL DEFAULT '{}'",
                "result_message_sent": "INTEGER NOT NULL DEFAULT 0",
                "result_message_retry_count": "INTEGER NOT NULL DEFAULT 0",
                "result_message_last_error": "TEXT NOT NULL DEFAULT ''",
            }
            for name, ddl in migrations.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE signals ADD COLUMN {name} {ddl}")

            defaults = {
                "trading_enabled": bool(config.TRADING_ENABLED_DEFAULT),
                "auto_signal_enabled": bool(config.AUTO_SIGNAL_ENABLED_DEFAULT),
                "trade_usdt": float(config.TRADE_USDT_DEFAULT),
                "leverage": int(config.LEVERAGE_DEFAULT),
                "max_positions": int(config.MAX_POSITIONS_DEFAULT),
                "profit_today": 0.0,
                "profit_today_date": today,
                "profit_total": 0.0,
                "stats_reset_at": now,
                "profit_reset_at": now,
                "toobit_connected": False,
                "toobit_margin_usdt": 0.0,
                "toobit_available_usdt": 0.0,
                "toobit_total_usdt": 0.0,
                "toobit_last_error": "",
                "toobit_last_update": 0,
            }
            for key, value in defaults.items():
                db.execute(
                    "INSERT OR IGNORE INTO kv(key,value,updated_at) VALUES(?,?,?)",
                    (key, self._encode(value), now),
                )

    # ---------- generic settings ----------
    def get(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (str(key),)).fetchone()
        return self._decode(row["value"], default) if row else default

    def set(self, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (str(key), self._encode(value), int(time.time())),
            )

    # ---------- signals ----------
    def create_signal(self, data: dict[str, Any]) -> int:
        now = int(time.time())
        columns = [
            "symbol_id", "okx_symbol", "toobit_symbol", "side", "strength",
            "entry", "tp", "sl", "rr", "trade_mode", "status", "is_real",
            "slot_id", "message_id", "created_at", "opened_at", "order_id",
            "trade_usdt", "leverage", "notional_usdt", "estimated_net_profit",
            "estimated_net_loss", "estimated_cost", "net_rr", "raw_json",
        ]
        values = [
            str(data.get("symbol_id") or ""),
            str(data.get("okx_symbol") or ""),
            str(data.get("toobit_symbol") or ""),
            str(data.get("side") or ""),
            data.get("strength"),
            float(data.get("entry") or 0.0),
            float(data.get("tp") or 0.0),
            float(data.get("sl") or 0.0),
            float(data.get("rr") or 0.0),
            str(data.get("trade_mode") or "virtual"),
            str(data.get("status") or "open"),
            int(bool(data.get("is_real"))),
            data.get("slot_id"),
            data.get("message_id"),
            int(data.get("created_at") or now),
            data.get("opened_at"),
            data.get("order_id"),
            float(data.get("trade_usdt") or 0.0),
            int(data.get("leverage") or 1),
            float(data.get("notional_usdt") or 0.0),
            float(data.get("estimated_net_profit") or 0.0),
            float(data.get("estimated_net_loss") or 0.0),
            float(data.get("estimated_cost") or 0.0),
            float(data.get("net_rr") or 0.0),
            self._encode(data.get("raw", data.get("raw_json", {})))
            if not isinstance(data.get("raw_json"), str)
            else str(data.get("raw_json")),
        ]
        placeholders = ",".join("?" for _ in columns)
        with self.connect() as db:
            cur = db.execute(
                f"INSERT INTO signals({','.join(columns)}) VALUES({placeholders})",
                values,
            )
            return int(cur.lastrowid)

    def update_signal(self, signal_id: int, **fields: Any) -> None:
        allowed = {
            "status", "message_id", "opened_at", "closed_at", "entry_real",
            "exit_price", "gross_pnl", "fee_usdt", "net_pnl", "close_reason",
            "mfe", "mae", "order_id", "slot_id", "raw_json", "is_real",
            "trade_mode", "trade_usdt", "leverage", "notional_usdt",
            "estimated_net_profit", "estimated_net_loss", "estimated_cost",
            "net_rr", "stop_primary", "stop_confidence", "stop_analysis_json",
            "result_message_sent", "result_message_retry_count",
            "result_message_last_error",
        }
        assignments: list[str] = []
        values: list[Any] = []
        for name, value in fields.items():
            if name not in allowed:
                continue
            if name in _JSON_SIGNAL_FIELDS and not isinstance(value, str):
                value = self._encode(value)
            assignments.append(f"{name}=?")
            values.append(value)
        if not assignments:
            return
        values.append(int(signal_id))
        with self.connect() as db:
            db.execute(
                f"UPDATE signals SET {','.join(assignments)} WHERE id=?",
                values,
            )

    def close_signal_if_open(self, signal_id: int, **fields: Any) -> bool:
        """Atomically close an open/pending signal exactly once."""
        allowed = {
            "closed_at", "exit_price", "gross_pnl", "fee_usdt", "net_pnl",
            "close_reason", "mfe", "mae", "raw_json", "stop_primary",
            "stop_confidence", "stop_analysis_json", "result_message_sent",
            "result_message_retry_count", "result_message_last_error",
        }
        assignments = ["status='closed'"]
        values: list[Any] = []
        for name, value in fields.items():
            if name not in allowed:
                continue
            if name in _JSON_SIGNAL_FIELDS and not isinstance(value, str):
                value = self._encode(value)
            assignments.append(f"{name}=?")
            values.append(value)
        if "closed_at" not in fields:
            assignments.append("closed_at=?")
            values.append(int(time.time()))
        values.append(int(signal_id))
        with self.connect() as db:
            cur = db.execute(
                f"UPDATE signals SET {','.join(assignments)} "
                "WHERE id=? AND status IN ('open','pending')",
                values,
            )
            return int(cur.rowcount or 0) == 1

    def get_signal(self, signal_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM signals WHERE id=?", (int(signal_id),)).fetchone()
        return dict(row) if row else None

    def get_open_signals(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM signals WHERE status IN ('open','pending') ORDER BY id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_pending_result_messages(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM signals
                WHERE status='closed'
                  AND result_message_sent=0
                  AND result_message_retry_count<10
                ORDER BY id ASC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_real_open(self) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS c FROM signals "
                "WHERE is_real=1 AND status IN ('open','pending')"
            ).fetchone()
        return int(row["c"] if row else 0)

    # ---------- statistics / profit ----------
    def ensure_profit_today(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if str(self.get("profit_today_date", "")) != today:
            with self.connect() as db:
                now = int(time.time())
                db.execute(
                    """
                    INSERT INTO kv(key,value,updated_at) VALUES('profit_today',?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                    """,
                    (self._encode(0.0), now),
                )
                db.execute(
                    """
                    INSERT INTO kv(key,value,updated_at) VALUES('profit_today_date',?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                    """,
                    (self._encode(today), now),
                )

    def add_profit(self, amount: float) -> None:
        """Atomically add realized net PnL to daily and total counters."""
        self.ensure_profit_today()
        delta = float(amount)
        with self.connect() as db:
            now = int(time.time())
            for key in ("profit_today", "profit_total"):
                row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
                current = float(self._decode(row["value"], 0.0) if row else 0.0)
                db.execute(
                    """
                    INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                    """,
                    (key, self._encode(current + delta), now),
                )

    def stats(self) -> dict[str, Any]:
        reset_at = int(self.get("stats_reset_at", 0) or 0)
        with self.connect() as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS signals,
                    SUM(CASE WHEN status IN ('open','pending') THEN 1 ELSE 0 END) AS open_count,
                    SUM(CASE WHEN close_reason='TP' THEN 1 ELSE 0 END) AS tp_count,
                    SUM(CASE WHEN close_reason='SL' THEN 1 ELSE 0 END) AS sl_count,
                    SUM(CASE WHEN is_real=1 THEN 1 ELSE 0 END) AS real_count,
                    SUM(CASE WHEN is_real=0 THEN 1 ELSE 0 END) AS virtual_count,
                    COALESCE(SUM(CASE WHEN status='closed' THEN net_pnl ELSE 0 END),0) AS net_pnl
                FROM signals WHERE created_at>=?
                """,
                (reset_at,),
            ).fetchone()
        return {
            "signals": int(row["signals"] or 0),
            "open": int(row["open_count"] or 0),
            "tp": int(row["tp_count"] or 0),
            "sl": int(row["sl_count"] or 0),
            "real": int(row["real_count"] or 0),
            "virtual": int(row["virtual_count"] or 0),
            "net_pnl": float(row["net_pnl"] or 0.0),
        }

    def reset_stats(self) -> None:
        # No physical deletion: open positions and audit history remain intact.
        self.set("stats_reset_at", int(time.time()) + 1)

    def reset_profit(self) -> None:
        now = int(time.time())
        today = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as db:
            values = {
                "profit_today": 0.0,
                "profit_today_date": today,
                "profit_total": 0.0,
                "profit_reset_at": now,
            }
            for key, value in values.items():
                db.execute(
                    """
                    INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                    """,
                    (key, self._encode(value), now),
                )

    # ---------- health ----------
    def add_health_event(
        self,
        component: str,
        severity: str,
        message: str,
        symbol_id: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO health_events(component,severity,message,symbol_id,created_at)
                VALUES(?,?,?,?,?)
                """,
                (str(component), str(severity), str(message), symbol_id, int(time.time())),
            )

    def clear_health_events(self, component: str, symbol_id: str | None = None) -> None:
        now = int(time.time())
        with self.connect() as db:
            if symbol_id is None:
                db.execute(
                    "UPDATE health_events SET cleared_at=? "
                    "WHERE cleared_at IS NULL AND component=?",
                    (now, str(component)),
                )
            else:
                db.execute(
                    "UPDATE health_events SET cleared_at=? "
                    "WHERE cleared_at IS NULL AND component=? AND symbol_id=?",
                    (now, str(component), str(symbol_id)),
                )

    def active_health_events(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM health_events WHERE cleared_at IS NULL "
                "ORDER BY id DESC LIMIT 20"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- blacklist ----------
    def blacklist_symbol(self, symbol_id: str, reason: str, seconds: int) -> None:
        until_ts = int(time.time()) + max(1, int(seconds))
        with self.connect() as db:
            row = db.execute(
                "SELECT count FROM blacklist WHERE symbol_id=?", (str(symbol_id),)
            ).fetchone()
            count = int(row["count"] or 0) + 1 if row else 1
            db.execute(
                """
                INSERT INTO blacklist(symbol_id,reason,until_ts,count) VALUES(?,?,?,?)
                ON CONFLICT(symbol_id) DO UPDATE SET
                    reason=excluded.reason,
                    until_ts=excluded.until_ts,
                    count=excluded.count
                """,
                (str(symbol_id), str(reason), until_ts, count),
            )

    def is_blacklisted(self, symbol_id: str) -> bool:
        now = int(time.time())
        with self.connect() as db:
            row = db.execute(
                "SELECT until_ts FROM blacklist WHERE symbol_id=?", (str(symbol_id),)
            ).fetchone()
            if not row:
                return False
            if int(row["until_ts"] or 0) <= now:
                db.execute("DELETE FROM blacklist WHERE symbol_id=?", (str(symbol_id),))
                return False
            return True

    def blacklist_rows(self) -> list[dict[str, Any]]:
        now = int(time.time())
        with self.connect() as db:
            db.execute("DELETE FROM blacklist WHERE until_ts<=?", (now,))
            rows = db.execute(
                "SELECT * FROM blacklist ORDER BY until_ts ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- symbol profiles ----------
    def upsert_profile(self, symbol_id: str, data: dict[str, Any]) -> None:
        payload = dict(data)
        updated_at = int(payload.get("updated_at") or time.time())
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO profiles(symbol_id,data_json,updated_at) VALUES(?,?,?)
                ON CONFLICT(symbol_id) DO UPDATE SET
                    data_json=excluded.data_json,
                    updated_at=excluded.updated_at
                """,
                (str(symbol_id), self._encode(payload), updated_at),
            )

    def get_profile(self, symbol_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT data_json FROM profiles WHERE symbol_id=?", (str(symbol_id),)
            ).fetchone()
        if not row:
            return None
        value = self._decode(row["data_json"], None)
        return value if isinstance(value, dict) else None

    def profile_rows(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT symbol_id,data_json,updated_at FROM profiles ORDER BY symbol_id"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            data = self._decode(row["data_json"], {})
            result.append({
                "symbol_id": row["symbol_id"],
                "updated_at": int(row["updated_at"]),
                "data": data if isinstance(data, dict) else {},
            })
        return result
