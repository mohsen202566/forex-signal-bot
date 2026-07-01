from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return str(value).strip() if value is not None and str(value).strip() else default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name, "true" if default else "false").lower()
    return value in {"1", "true", "yes", "y", "on", "فعال", "روشن"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return float(default)


BOT_NAME = "Forex"
BOT_DISPLAY_NAME = "Forex"
PROJECT_ROOT = Path(__file__).resolve().parent
BOT_DATA_DIR = Path(_env("BOT_DATA_DIR", str(PROJECT_ROOT / "data")))
BOT_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Telegram
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")
OWNER_ID = _env("OWNER_ID")

# OKX public-data only
OKX_BASE_URL = _env("OKX_BASE_URL", "https://www.okx.com").rstrip("/")
OKX_TIMEOUT_SECONDS = _env_int("OKX_TIMEOUT_SECONDS", 12)

# Toobit behavior. The uploaded toobit_client.py imports this name.
TOOBIT_PLACE_REAL_TP = _env_bool("TOOBIT_PLACE_REAL_TP", True)
TOOBIT_CLOSE_CONFIRM_REQUIRED = _env_bool("TOOBIT_CLOSE_CONFIRM_REQUIRED", True)
TOOBIT_CLOSE_CONFIRM_DELAY_SECONDS = _env_float("TOOBIT_CLOSE_CONFIRM_DELAY_SECONDS", 3.0)
TOOBIT_CLOSE_CONFIRM_RETRY = _env_int("TOOBIT_CLOSE_CONFIRM_RETRY", 2)
# Keep endpoint configurable because Toobit confirmation paths can differ by account/API version.
TOOBIT_PATH_CLOSE_CONFIRM = _env("TOOBIT_PATH_CLOSE_CONFIRM", "")

# Trading panel limits
TRADE_AMOUNT_MIN = 1.0
TRADE_AMOUNT_MAX = 10000.0
LEVERAGE_MIN = 1
LEVERAGE_MAX = 100
MAX_POSITIONS_MIN = 1
MAX_POSITIONS_MAX = 100

DEFAULT_TRADE_ENABLED = _env_bool("DEFAULT_TRADE_ENABLED", False)
DEFAULT_MARGIN_USDT = _env_float("DEFAULT_MARGIN_USDT", 10.0)
DEFAULT_LEVERAGE = _env_int("DEFAULT_LEVERAGE", 5)
DEFAULT_MAX_POSITIONS = _env_int("DEFAULT_MAX_POSITIONS", 3)

# Strategy: simple strange 1D scalper
MAIN_TIMEFRAME = "1D"
ENTRY_TIMEFRAMES = ("15m", "5m")
MIN_SYMBOLS_COUNT = _env_int("MIN_SYMBOLS_COUNT", 50)
MIN_DAILY_TP_ROOM_PCT = _env_float("MIN_DAILY_TP_ROOM_PCT", 3.0)
RISK_REWARD = _env_float("RISK_REWARD", 2.0)
SIGNAL_THRESHOLD = _env_int("SIGNAL_THRESHOLD", 80)

# Scan cadence
FULL_SCAN_SECONDS = _env_float("FULL_SCAN_SECONDS", 30.0)
MONITOR_INTERVAL_SECONDS = _env_float("MONITOR_INTERVAL_SECONDS", 2.0)
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()

# Smart exit
SMART_EXIT_ENABLED = _env_bool("SMART_EXIT_ENABLED", True)
SMART_EXIT_MIN_PROFIT_PCT = _env_float("SMART_EXIT_MIN_PROFIT_PCT", 0.8)
SMART_EXIT_DEFENSE_MAX_LOSS_PCT = _env_float("SMART_EXIT_DEFENSE_MAX_LOSS_PCT", 0.4)
SMART_EXIT_CONFIRMATIONS_REQUIRED = _env_int("SMART_EXIT_CONFIRMATIONS_REQUIRED", 3)

# Symbol universe. Final list is this whitelist ∩ OKX swap symbols ∩ Toobit futures symbols.
BASE_SYMBOL_WHITELIST = [
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC",
    "BCH", "DOT", "UNI", "AAVE", "ETC", "FIL", "ATOM", "NEAR", "ARB", "OP",
    "SUI", "APT", "INJ", "TIA", "SEI", "WLD", "ORDI", "TRX", "TON", "MATIC",
    "POL", "ALGO", "SAND", "MANA", "AXS", "APE", "GALA", "LDO", "CRV", "MKR",
    "COMP", "SNX", "DYDX", "RUNE", "IMX", "ICP", "HBAR", "XLM", "VET", "EGLD",
    "FLOW", "KAS", "FET", "RENDER", "RNDR", "JUP", "PYTH", "STRK", "ENA", "WIF",
    "PEPE", "SHIB", "AR", "STX", "GMT", "MASK", "MINA", "CHZ", "ZIL", "ROSE",
    "GMX", "BLUR", "ENS", "ZK", "NOT", "ONDO", "W", "JTO", "PIXEL", "PORTAL",
]
