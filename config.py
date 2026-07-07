"""Root config for the simple 5M OKX -> Toobit futures scalper.

Everything is intentionally in the project root because deployment is done by
pushing these files to GitHub and running `git pull` on the VPS.

No .env.example, no .gitignore, no shell launcher, and no generated cache files
are required by this project.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _load_dotenv(path: str = ".env") -> None:
    """Optional local .env loader.

    The project does not ship an .env.example file. If a real .env already exists
    on a server, it can still be used; otherwise environment variables can be set
    in systemd or the shell.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception:
        pass


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(_env(name, str(default))))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name, "1" if default else "0").lower()
    return value in {"1", "true", "yes", "y", "on", "فعال"}


BOT_NAME = _env("BOT_NAME", "Crypto 5M Simple Toobit Scalper")
BOT_DATA_DIR = _env("BOT_DATA_DIR", "data")
BOT_DB_PATH = _env("BOT_DB_PATH", os.path.join(BOT_DATA_DIR, "crypto_5m_simple.sqlite3"))
LOG_LEVEL = _env("LOG_LEVEL", "INFO")

# Telegram
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")
OWNER_ID = _env("OWNER_ID")
TELEGRAM_POLL_TIMEOUT = _env_int("TELEGRAM_POLL_TIMEOUT", 25)

# OKX analysis data only
OKX_BASE_URL = _env("OKX_BASE_URL", "https://www.okx.com")
OKX_CANDLE_LIMIT = _env_int("OKX_CANDLE_LIMIT", 260)
OKX_REQUEST_TIMEOUT = _env_int("OKX_REQUEST_TIMEOUT", 12)

# Toobit execution - the old unchanged toobit_client.py reads these names directly.
TOOBIT_API_KEY = _env("TOOBIT_API_KEY")
TOOBIT_API_SECRET = _env("TOOBIT_API_SECRET", _env("TOOBIT_SECRET_KEY"))
TOOBIT_SECRET_KEY = TOOBIT_API_SECRET
TOOBIT_BASE_URL = _env("TOOBIT_BASE_URL", "https://api.toobit.com")
REQUEST_TIMEOUT = _env_int("TOOBIT_TIMEOUT_SECONDS", 12)
RECV_WINDOW = _env_int("TOOBIT_RECV_WINDOW", 5000)
DEFAULT_MARGIN_TYPE = _env("DEFAULT_MARGIN_TYPE", "ISOLATED").upper()
TOOBIT_VERIFY_AFTER_ERROR_SECONDS = _env_int("TOOBIT_VERIFY_AFTER_ERROR_SECONDS", 70)

# Toobit endpoints are configurable so the unchanged old client remains usable.
TOOBIT_PATH_BALANCE = _env("TOOBIT_PATH_BALANCE", "/api/v1/futures/balance")
TOOBIT_PATH_POSITIONS = _env("TOOBIT_PATH_POSITIONS", "/api/v1/futures/positions")
TOOBIT_PATH_OPEN_ORDERS = _env("TOOBIT_PATH_OPEN_ORDERS", "/api/v1/futures/openOrders")
TOOBIT_PATH_MARGIN_MODE = _env("TOOBIT_PATH_MARGIN_MODE", "/api/v1/futures/marginType")
TOOBIT_PATH_LEVERAGE = _env("TOOBIT_PATH_LEVERAGE", "/api/v1/futures/leverage")
TOOBIT_PATH_POSITION_SETTINGS = _env("TOOBIT_PATH_POSITION_SETTINGS", "/api/v1/futures/accountLeverage")
TOOBIT_PATH_ORDER = _env("TOOBIT_PATH_ORDER", "/api/v1/futures/order")
TOOBIT_PATH_MARK_PRICE = _env("TOOBIT_PATH_MARK_PRICE", "/api/v1/futures/markPrice")
TOOBIT_PATH_EXCHANGE_INFO = _env("TOOBIT_PATH_EXCHANGE_INFO", "/api/v1/futures/exchangeInfo")
TOOBIT_PATH_HISTORY_POSITIONS = _env("TOOBIT_PATH_HISTORY_POSITIONS", "/api/v1/futures/historyPositions")
TOOBIT_PATH_ORDER_HISTORY = _env("TOOBIT_PATH_ORDER_HISTORY", "/api/v1/futures/historyOrders")
TOOBIT_PATH_ORDER_HISTORY_ALT = _env("TOOBIT_PATH_ORDER_HISTORY_ALT", "/api/v1/futures/order/history")
TOOBIT_PATH_TODAY_PNL = _env("TOOBIT_PATH_TODAY_PNL", "/api/v1/futures/todayPnl")
TOOBIT_PATH_CLOSE_ORDER = _env("TOOBIT_PATH_CLOSE_ORDER", TOOBIT_PATH_ORDER)
TOOBIT_PARAM_TP = _env("TOOBIT_PARAM_TP", "takeProfit")
TOOBIT_PARAM_SL = _env("TOOBIT_PARAM_SL", "stopLoss")

# Compatibility aliases for old unchanged toobit_client.py variants.
TOOBIT_PLACE_REAL_TP = _env_bool("TOOBIT_PLACE_REAL_TP", True)
TOOBIT_PLACE_REAL_SL = _env_bool("TOOBIT_PLACE_REAL_SL", True)
TOOBIT_TP_PARAM = TOOBIT_PARAM_TP
TOOBIT_SL_PARAM = TOOBIT_PARAM_SL
TOOBIT_PANEL_CACHE_SECONDS = _env_int("TOOBIT_PANEL_CACHE_SECONDS", 20)

# Main runtime laws.
MAX_WATCH_SYMBOLS = _env_int("MAX_WATCH_SYMBOLS", 30)
FULL_SCAN_SECONDS = _env_int("FULL_SCAN_SECONDS", 55)
MONITOR_INTERVAL_SECONDS = _env_int("MONITOR_INTERVAL_SECONDS", 5)
SLOT_RECHECK_SECONDS = _env_int("SLOT_RECHECK_SECONDS", 70)
COIN_ERROR_COOLDOWN_SECONDS = _env_int("COIN_ERROR_COOLDOWN_SECONDS", 70)

# Trade panel defaults - user can change them from Telegram.
DEFAULT_TRADE_ENABLED = _env_bool("DEFAULT_TRADE_ENABLED", False)
DEFAULT_TRADE_DOLLAR = _env_float("DEFAULT_TRADE_DOLLAR", _env_float("DEFAULT_MARGIN_USDT", 10.0))
DEFAULT_TRADE_CAPITAL = _env_float("DEFAULT_TRADE_CAPITAL", 100.0)
DEFAULT_LEVERAGE = _env_int("DEFAULT_LEVERAGE", 10)
DEFAULT_MAX_POSITIONS = _env_int("DEFAULT_MAX_POSITIONS", 3)
DEFAULT_MIN_NET_PROFIT_USDT = _env_float("DEFAULT_MIN_NET_PROFIT_USDT", 0.01)

# Simple 5M strategy laws.
SIGNAL_SCORE_THRESHOLD = _env_float("SIGNAL_SCORE_THRESHOLD", 70.0)
STRONG_SCORE_THRESHOLD = _env_float("STRONG_SCORE_THRESHOLD", 85.0)
RR_NORMAL = _env_float("RR_NORMAL", 1.5)
RR_STRONG = _env_float("RR_STRONG", 1.5)
ROUND_TRIP_FEE_USDT = _env_float("ROUND_TRIP_FEE_USDT", 0.05)
MIN_5M_SL_PCT = _env_float("MIN_5M_SL_PCT", 0.0025)   # 0.25%
MAX_5M_SL_PCT = _env_float("MAX_5M_SL_PCT", 0.0120)   # 1.20%
ATR_SL_MULT = _env_float("ATR_SL_MULT", 1.20)
SWING_LOOKBACK_5M = _env_int("SWING_LOOKBACK_5M", 12)
VWAP_LOOKBACK_5M = _env_int("VWAP_LOOKBACK_5M", 48)
VOLUME_LOOKBACK_5M = _env_int("VOLUME_LOOKBACK_5M", 20)

# Simple anti-chase guard: prevents entering after the 5M move is already tired.
# These are hard reject filters, not support/resistance.
ANTI_CHASE_ENABLED = _env_bool("ANTI_CHASE_ENABLED", True)
ANTI_CHASE_MAX_EMA50_DISTANCE_PCT = _env_float("ANTI_CHASE_MAX_EMA50_DISTANCE_PCT", 0.0045)  # 0.45%
ANTI_CHASE_MAX_VWAP_DISTANCE_PCT = _env_float("ANTI_CHASE_MAX_VWAP_DISTANCE_PCT", 0.0035)   # 0.35%
ANTI_CHASE_MAX_3CANDLE_MOVE_PCT = _env_float("ANTI_CHASE_MAX_3CANDLE_MOVE_PCT", 0.0090)     # 0.90%
ANTI_CHASE_LONG_MAX_RSI = _env_float("ANTI_CHASE_LONG_MAX_RSI", 68.0)
ANTI_CHASE_SHORT_MIN_RSI = _env_float("ANTI_CHASE_SHORT_MIN_RSI", 32.0)

# Pullback Re-Entry: enter early on a healthy pullback, not after the move is tired.
# Not support/resistance. This only checks distance from EMA50/VWAP, RSI freshness, MACD histogram and range.
PULLBACK_REENTRY_ENABLED = _env_bool("PULLBACK_REENTRY_ENABLED", True)
PULLBACK_MIN_RECLAIM_DISTANCE_PCT = _env_float("PULLBACK_MIN_RECLAIM_DISTANCE_PCT", 0.0005)  # 0.05%, avoids pure noise around EMA/VWAP
PULLBACK_MAX_ENTRY_DISTANCE_PCT = _env_float("PULLBACK_MAX_ENTRY_DISTANCE_PCT", 0.0035)    # 0.35%, avoids late/chase entries
PULLBACK_LONG_RSI_MIN = _env_float("PULLBACK_LONG_RSI_MIN", 48.0)
PULLBACK_LONG_RSI_MAX = _env_float("PULLBACK_LONG_RSI_MAX", 62.0)
PULLBACK_SHORT_RSI_MIN = _env_float("PULLBACK_SHORT_RSI_MIN", 38.0)
PULLBACK_SHORT_RSI_MAX = _env_float("PULLBACK_SHORT_RSI_MAX", 52.0)
PULLBACK_REQUIRED_TRIGGERS = _env_int("PULLBACK_REQUIRED_TRIGGERS", 2)

# Range guard: avoid 5M chop where EMA/RSI give fake signals.
RANGE_FILTER_ENABLED = _env_bool("RANGE_FILTER_ENABLED", True)
RANGE_MAX_EMA_SPREAD_PCT = _env_float("RANGE_MAX_EMA_SPREAD_PCT", 0.0020)       # 0.20%
RANGE_MAX_EMA50_SLOPE_10_PCT = _env_float("RANGE_MAX_EMA50_SLOPE_10_PCT", 0.0010)  # 0.10% over 10 candles
RANGE_MIN_20CANDLE_RANGE_PCT = _env_float("RANGE_MIN_20CANDLE_RANGE_PCT", 0.0060)   # 0.60%
RANGE_MIN_FLAGS = _env_int("RANGE_MIN_FLAGS", 2)

# Hard rule: no support/resistance filter for this scalper.
ENABLE_SUPPORT_RESISTANCE_FILTER = False
ENABLE_AI = False
ENABLE_DCA = False
ENABLE_MARTINGALE = False
ENABLE_TRAILING_STOP = False

# 30 symbols. Keep internal name USDT style. OKX and Toobit mapping happens in utils.py.
WATCHLIST = tuple(
    s.strip().upper()
    for s in _env(
        "WATCHLIST",
        "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,TRXUSDT,"
        "TONUSDT,DOTUSDT,NEARUSDT,APTUSDT,ARBUSDT,OPUSDT,SUIUSDT,SEIUSDT,FETUSDT,INJUSDT,"
        "LTCUSDT,BCHUSDT,ETCUSDT,FILUSDT,ATOMUSDT,AAVEUSDT,UNIUSDT,1000PEPEUSDT,WIFUSDT,ORDIUSDT",
    ).split(",")
    if s.strip()
)[:MAX_WATCH_SYMBOLS]


@dataclass(frozen=True)
class RuntimeDefaults:
    trade_enabled: bool = DEFAULT_TRADE_ENABLED
    trade_dollar_usdt: float = DEFAULT_TRADE_DOLLAR
    trade_capital_usdt: float = DEFAULT_TRADE_CAPITAL
    leverage: int = DEFAULT_LEVERAGE
    max_positions: int = DEFAULT_MAX_POSITIONS
    min_net_profit_usdt: float = DEFAULT_MIN_NET_PROFIT_USDT
