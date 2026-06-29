from __future__ import annotations

import os
from dataclasses import dataclass


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _env_int(*names: str, default: int) -> int:
    value = _env_first(*names, default=str(default))
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _env_float(*names: str, default: float) -> float:
    value = _env_first(*names, default=str(default))
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _env_bool(*names: str, default: bool) -> bool:
    value = _env_first(*names, default="1" if default else "0").strip().lower()
    return value in {"1", "true", "yes", "on", "enabled", "فعال", "روشن"}


@dataclass(frozen=True)
class ScoreWeights:
    direction: int = 12
    pre_ignition: int = 16
    candle_entry: int = 16
    entry_precision: int = 12
    ai_memory: int = 18
    tp_sl: int = 10
    market_mode: int = 8
    session: int = 4
    net_sync: int = 4


DATA_DIR = _env_first("BOT_DATA_DIR", default="data")
DB_PATH = _env_first("BOT_DB_PATH", default=os.path.join(DATA_DIR, "forex_scalper_ai.sqlite3"))

TELEGRAM_BOT_TOKEN = _env_first("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
TELEGRAM_CHAT_ID = _env_first("TELEGRAM_CHAT_ID", "OWNER_ID")
OWNER_ID = _env_first("OWNER_ID", "TELEGRAM_CHAT_ID")

OKX_BASE_URL = _env_first("OKX_BASE_URL", default="https://www.okx.com").rstrip("/")
OKX_CANDLE_LIMIT = _env_int("OKX_CANDLE_LIMIT", default=260)

TIMEFRAME_4H = "4H"
TIMEFRAME_1H = "1H"
TIMEFRAME_15M = "15m"
TIMEFRAME_5M = "5m"
TIMEFRAMES = (TIMEFRAME_4H, TIMEFRAME_1H, TIMEFRAME_15M, TIMEFRAME_5M)
MARKET_CONTEXT_SYMBOLS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")

FULL_SCAN_SECONDS = _env_int("FULL_SCAN_SECONDS", "SCAN_INTERVAL_SECONDS", default=12)
WATCH_SCAN_SECONDS = _env_int("WATCH_SCAN_SECONDS", default=1)
MONITOR_INTERVAL_SECONDS = _env_int("MONITOR_INTERVAL_SECONDS", default=1)
TOOBIT_PANEL_CACHE_SECONDS = _env_int("TOOBIT_PANEL_CACHE_SECONDS", default=20)
MAX_WATCH_SYMBOLS = _env_int("MAX_WATCH_SYMBOLS", default=6)
WATCH_EXPIRE_SECONDS = _env_int("WATCH_EXPIRE_SECONDS", default=120)
READY_ALERT_COOLDOWN_SECONDS = _env_int("READY_ALERT_COOLDOWN_SECONDS", default=45)

# Starting thresholds only. AI learns real per-symbol/per-direction thresholds from results.
# These are not permanent strategy rules.
BASE_SIGNAL_THRESHOLD = _env_int("BASE_SIGNAL_THRESHOLD", default=70)
BASE_REAL_THRESHOLD = _env_int("BASE_REAL_THRESHOLD", default=78)

# Compatibility names used by older code and panels.
SIGNAL_THRESHOLD = BASE_SIGNAL_THRESHOLD
REAL_SIGNAL_THRESHOLD = BASE_REAL_THRESHOLD

WATCH_THRESHOLD = _env_int("WATCH_THRESHOLD", default=45)
GHOST_THRESHOLD = _env_int("GHOST_THRESHOLD", default=60)

# Guard rails only, not fixed trading thresholds. AI can move thresholds inside this range.
MIN_DYNAMIC_SIGNAL_THRESHOLD = _env_int("MIN_DYNAMIC_SIGNAL_THRESHOLD", default=55)
MAX_DYNAMIC_SIGNAL_THRESHOLD = _env_int("MAX_DYNAMIC_SIGNAL_THRESHOLD", default=88)
MIN_DYNAMIC_REAL_THRESHOLD = _env_int("MIN_DYNAMIC_REAL_THRESHOLD", default=60)
MAX_DYNAMIC_REAL_THRESHOLD = _env_int("MAX_DYNAMIC_REAL_THRESHOLD", default=92)
WEIGHTS = ScoreWeights()

DEFAULT_TRADE_ENABLED = _env_bool("DEFAULT_TRADE_ENABLED", default=False)
DEFAULT_MARGIN_USDT = _env_float("DEFAULT_MARGIN_USDT", default=10.0)
DEFAULT_LEVERAGE = _env_int("DEFAULT_LEVERAGE", default=5)
DEFAULT_MAX_POSITIONS = _env_int("DEFAULT_MAX_POSITIONS", default=3)

MIN_REAL_NET_PROFIT_USDT = _env_float("MIN_REAL_NET_PROFIT_USDT", "MIN_NET_PROFIT_USDT", default=0.01)
ESTIMATED_FIXED_ROUND_FEE_USDT = _env_float("ESTIMATED_FIXED_ROUND_FEE_USDT", default=0.0)
DEFAULT_MIN_PROFIT_USDT = MIN_REAL_NET_PROFIT_USDT
DEFAULT_MIN_PROFIT_PCT = 0.0

MARGIN_MIN_USDT = 1.0
MARGIN_MAX_USDT = 10000.0
LEVERAGE_MIN = 1
LEVERAGE_MAX = 100
MAX_POSITIONS_MIN = 1
MAX_POSITIONS_MAX = 100

TOOBIT_TAKER_FEE = _env_float("TOOBIT_TAKER_FEE", "TOBIT_TAKER_FEE", default=0.0006)
SPREAD_BUFFER = _env_float("SPREAD_BUFFER", default=0.00025)
SLIPPAGE_BUFFER = _env_float("SLIPPAGE_BUFFER", default=0.00035)
MIN_RISK_REWARD = _env_float("MIN_RISK_REWARD", default=1.10)
MIN_OKX_TOOBIT_SYNC_PCT = _env_float("MIN_OKX_TOOBIT_SYNC_PCT", default=0.0025)

MIN_SCALP_SL_PCT = _env_float("MIN_SCALP_SL_PCT", default=0.0012)
MIN_SCALP_TP_PCT = _env_float("MIN_SCALP_TP_PCT", default=0.0018)
MAX_SCALP_SL_PCT = _env_float("MAX_SCALP_SL_PCT", default=0.0200)

LEARNING_DAYS = _env_int("LEARNING_DAYS", default=10)
AI_MIN_SAMPLES_SOFT = 5
AI_MIN_SAMPLES_MEDIUM = 10
AI_MIN_SAMPLES_VALID = 30
AI_MIN_REPLACEMENT_DAYS = 5

SYMBOL_ERROR_DISABLE_AFTER = _env_int("SYMBOL_ERROR_DISABLE_AFTER", default=3)
OKX_DISABLE_MINUTES = _env_int("OKX_DISABLE_MINUTES", default=30)
TOOBIT_REAL_DISABLE_HOURS = _env_int("TOOBIT_REAL_DISABLE_HOURS", default=6)
MAX_OPEN_SIGNAL_PER_SYMBOL = 1
BOT_NAME = _env_first("BOT_NAME", default="Forex Scalper AI Helper")


def ensure_runtime_config() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN یا BOT_TOKEN تنظیم نشده است.")
    if not TELEGRAM_CHAT_ID and not OWNER_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID یا OWNER_ID تنظیم نشده است.")
