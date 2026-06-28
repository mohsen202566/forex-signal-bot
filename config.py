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
    # Scalping score: quality of start/entry is more important than a high strict score.
    direction: int = 10         # 15m/5m direction and reversal pressure
    pre_ignition: int = 25      # pump/dump start pressure
    candle_entry: int = 27      # entry trigger, power building, reversal building
    ai_memory: int = 20         # real AI pattern/range learning
    risk_net: int = 0           # profit/cost is informational only
    session: int = 3
    order_block: int = 15       # technical zone / 1H context / OB


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

# Fast 5m-15m scalping loops
FULL_SCAN_SECONDS = _env_int("FULL_SCAN_SECONDS", "SCAN_INTERVAL_SECONDS", default=15)
WATCH_SCAN_SECONDS = _env_int("WATCH_SCAN_SECONDS", default=5)
MONITOR_INTERVAL_SECONDS = _env_int("MONITOR_INTERVAL_SECONDS", default=5)
TOOBIT_PANEL_CACHE_SECONDS = _env_int("TOOBIT_PANEL_CACHE_SECONDS", default=20)
MAX_WATCH_SYMBOLS = _env_int("MAX_WATCH_SYMBOLS", default=6)
WATCH_EXPIRE_SECONDS = _env_int("WATCH_EXPIRE_SECONDS", default=120)
READY_ALERT_COOLDOWN_SECONDS = _env_int("READY_ALERT_COOLDOWN_SECONDS", default=45)

SIGNAL_THRESHOLD = _env_int("SIGNAL_THRESHOLD", "ACCEPT_SCORE", default=60)
WATCH_THRESHOLD = _env_int("WATCH_THRESHOLD", default=45)
WEIGHTS = ScoreWeights()

DEFAULT_TRADE_ENABLED = _env_bool("DEFAULT_TRADE_ENABLED", default=False)
DEFAULT_MARGIN_USDT = _env_float("DEFAULT_MARGIN_USDT", default=10.0)
DEFAULT_LEVERAGE = _env_int("DEFAULT_LEVERAGE", default=5)
DEFAULT_MAX_POSITIONS = _env_int("DEFAULT_MAX_POSITIONS", default=3)

# Compatibility only; profit gate is removed and this value is not used to block entries.
MIN_NET_PROFIT_USDT = _env_float("MIN_NET_PROFIT_USDT", default=0.0)
ESTIMATED_FIXED_ROUND_FEE_USDT = _env_float("ESTIMATED_FIXED_ROUND_FEE_USDT", default=0.07)
DEFAULT_MIN_PROFIT_USDT = MIN_NET_PROFIT_USDT
DEFAULT_MIN_PROFIT_PCT = 0.0

MARGIN_MIN_USDT = 1.0
MARGIN_MAX_USDT = 10000.0
LEVERAGE_MIN = 1
LEVERAGE_MAX = 100
MAX_POSITIONS_MIN = 1
MAX_POSITIONS_MAX = 100
MIN_PROFIT_USDT_MIN = 0.10
MIN_PROFIT_USDT_MAX = 1000.0
MIN_PROFIT_PCT_MIN = 0.0
MIN_PROFIT_PCT_MAX = 100.0

TOOBIT_TAKER_FEE = _env_float("TOOBIT_TAKER_FEE", "TOBIT_TAKER_FEE", default=0.0006)
SPREAD_BUFFER = _env_float("SPREAD_BUFFER", default=0.00025)
SLIPPAGE_BUFFER = _env_float("SLIPPAGE_BUFFER", default=0.00035)
MIN_NET_EDGE = _env_float("MIN_NET_EDGE", default=0.00020)
MIN_RISK_REWARD = _env_float("MIN_RISK_REWARD", default=1.10)

# TP/SL safety for live 5m-15m scalping. Values are price-move percentages, not account PnL.
MIN_SCALP_SL_PCT = _env_float("MIN_SCALP_SL_PCT", default=0.0012)    # 0.12% minimum SL distance
MIN_SCALP_TP_PCT = _env_float("MIN_SCALP_TP_PCT", default=0.0018)    # 0.18% minimum TP distance
MAX_SCALP_SL_PCT = _env_float("MAX_SCALP_SL_PCT", default=0.0200)    # 2.00% maximum SL distance

# Scalping data is heavy; raw learning is short, summaries are weekly.
LEARNING_DAYS = _env_int("LEARNING_DAYS", default=7)
AI_MIN_SAMPLES_SOFT = 8
AI_MIN_SAMPLES_MEDIUM = 20
AI_MIN_SAMPLES_VALID = 35

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
