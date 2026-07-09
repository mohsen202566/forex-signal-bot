"""تنظیمات ریشه‌ای ربات DIFT-5M.

همه فایل‌ها در ریشه پروژه قرار می‌گیرند. فایل toobit_client.py ثابت می‌ماند
و فقط از همین مقادیر config استفاده می‌کند.
"""
from __future__ import annotations

import os

# اگر python-dotenv نصب باشد، فایل .env از ریشه پروژه خودکار خوانده می‌شود.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# -----------------------------
# 35 نماد پیش‌فرض: باید هم در OKX SWAP و هم در Toobit Futures قابل اعتبارسنجی باشند.
# اگر یکی از صرافی‌ها نمادی را نداشت، /validate_symbols گزارش می‌دهد و در اسکن رد می‌شود.
# -----------------------------
DEFAULT_SYMBOLS_35 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "DOGEUSDT", "ADAUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT",
    "SUIUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT", "UNIUSDT",
    "AAVEUSDT", "NEARUSDT", "OPUSDT", "ARBUSDT", "INJUSDT",
    "ATOMUSDT", "ETCUSDT", "FILUSDT", "APTUSDT", "WLDUSDT",
    "PEPEUSDT", "SHIBUSDT", "SEIUSDT", "WIFUSDT", "ICPUSDT",
    "HBARUSDT", "ARUSDT", "TIAUSDT", "ORDIUSDT", "JUPUSDT",
]

# -----------------------------
# Telegram
# -----------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_IDS = [int(x.strip()) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# -----------------------------
# حالت اجرا
# NORMAL = سیگنال و مانیتور کاغذی با دیتای OKX
# REAL = سیگنال با OKX، تایید نهایی/اجرا/نتیجه با Toobit
# -----------------------------
BOT_MODE = os.getenv("BOT_MODE", "NORMAL").upper()  # NORMAL / REAL
REAL_TRADING_ENABLED = os.getenv("REAL_TRADING_ENABLED", "false").lower() == "true"
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
RESULT_CHECK_INTERVAL_SECONDS = int(os.getenv("RESULT_CHECK_INTERVAL_SECONDS", "30"))
MONITORING_ENABLED = os.getenv("MONITORING_ENABLED", "true").lower() == "true"
SEND_SIGNAL_MESSAGES = os.getenv("SEND_SIGNAL_MESSAGES", "true").lower() == "true"
SEND_RESULT_MESSAGES = os.getenv("SEND_RESULT_MESSAGES", "true").lower() == "true"

# -----------------------------
# نمادها: داخلی/Toobit = BTCUSDT ، OKX = BTC-USDT-SWAP
# -----------------------------
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", ",".join(DEFAULT_SYMBOLS_35)).split(",") if s.strip()]
REQUIRED_COMMON_SYMBOL_COUNT = int(os.getenv("REQUIRED_COMMON_SYMBOL_COUNT", "35"))
REQUIRE_EXCHANGE_SYMBOL_MATCH = os.getenv("REQUIRE_EXCHANGE_SYMBOL_MATCH", "true").lower() == "true"
VALIDATE_SYMBOLS_ON_START = os.getenv("VALIDATE_SYMBOLS_ON_START", "true").lower() == "true"
# Toobit symbols endpoint may return 404 on some accounts/VPS. Keep this false by default.
# REAL execution still validates symbol on Toobit immediately before order.
CHECK_TOOBIT_SYMBOLS_ON_START = os.getenv("CHECK_TOOBIT_SYMBOLS_ON_START", "false").lower() == "true"
OKX_INST_TYPE = os.getenv("OKX_INST_TYPE", "SWAP")
OKX_BASE_URL = os.getenv("OKX_BASE_URL", "https://www.okx.com")
OKX_CANDLE_LIMIT_5M = int(os.getenv("OKX_CANDLE_LIMIT_5M", "180"))
OKX_CANDLE_LIMIT_15M = int(os.getenv("OKX_CANDLE_LIMIT_15M", "140"))
OKX_CANDLE_LIMIT_1H = int(os.getenv("OKX_CANDLE_LIMIT_1H", "120"))
OKX_ORDERBOOK_DEPTH = int(os.getenv("OKX_ORDERBOOK_DEPTH", "20"))
OKX_TRADE_LIMIT = int(os.getenv("OKX_TRADE_LIMIT", "100"))

# کنترل فشار روی OKX: جلوگیری از 429 و حذف نمادهای نامعتبر از چرخه اسکن
OKX_REQUEST_DELAY_SECONDS = float(os.getenv("OKX_REQUEST_DELAY_SECONDS", "0.30"))
OKX_BAD_SYMBOL_COOLDOWN_SECONDS = int(os.getenv("OKX_BAD_SYMBOL_COOLDOWN_SECONDS", "3600"))
OKX_FETCH_FUNDING_EVERY_SCAN = os.getenv("OKX_FETCH_FUNDING_EVERY_SCAN", "false").lower() == "true"
OKX_MAX_RETRIES = int(os.getenv("OKX_MAX_RETRIES", "2"))

# -----------------------------
# Toobit - فایل toobit_client.py همین‌ها را می‌خواند
# -----------------------------
TOOBIT_BASE_URL = os.getenv("TOOBIT_BASE_URL", "https://api.toobit.com")
TOOBIT_API_KEY = os.getenv("TOOBIT_API_KEY", "")
TOOBIT_API_SECRET = os.getenv("TOOBIT_API_SECRET", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))
RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))
DEFAULT_MARGIN_TYPE = os.getenv("DEFAULT_MARGIN_TYPE", "ISOLATED").upper()
TOOBIT_VERIFY_AFTER_ERROR_SECONDS = int(os.getenv("TOOBIT_VERIFY_AFTER_ERROR_SECONDS", "70"))

# مسیرهای قابل تغییر Toobit؛ با فایل ثابت سازگار است.
TOOBIT_PATH_BALANCE = os.getenv("TOOBIT_PATH_BALANCE", "/api/v1/futures/balance")
TOOBIT_PATH_POSITIONS = os.getenv("TOOBIT_PATH_POSITIONS", "/api/v1/futures/positions")
TOOBIT_PATH_OPEN_ORDERS = os.getenv("TOOBIT_PATH_OPEN_ORDERS", "/api/v1/futures/openOrders")
TOOBIT_PATH_MARGIN_MODE = os.getenv("TOOBIT_PATH_MARGIN_MODE", "/api/v1/futures/marginType")
TOOBIT_PATH_LEVERAGE = os.getenv("TOOBIT_PATH_LEVERAGE", "/api/v1/futures/leverage")
TOOBIT_PATH_POSITION_SETTINGS = os.getenv("TOOBIT_PATH_POSITION_SETTINGS", "/api/v1/futures/accountLeverage")
TOOBIT_PATH_ORDER = os.getenv("TOOBIT_PATH_ORDER", "/api/v1/futures/order")
TOOBIT_PATH_MARK_PRICE = os.getenv("TOOBIT_PATH_MARK_PRICE", "/api/v1/futures/markPrice")
TOOBIT_PATH_EXCHANGE_INFO = os.getenv("TOOBIT_PATH_EXCHANGE_INFO", "/api/v1/futures/exchangeInfo")
TOOBIT_PATH_HISTORY_POSITIONS = os.getenv("TOOBIT_PATH_HISTORY_POSITIONS", "/api/v1/futures/historyPositions")
TOOBIT_PATH_ORDER_HISTORY = os.getenv("TOOBIT_PATH_ORDER_HISTORY", "/api/v1/futures/historyOrders")
TOOBIT_PATH_ORDER_HISTORY_ALT = os.getenv("TOOBIT_PATH_ORDER_HISTORY_ALT", "/api/v1/futures/order/history")
TOOBIT_PATH_TODAY_PNL = os.getenv("TOOBIT_PATH_TODAY_PNL", "/api/v1/futures/todayPnl")
TOOBIT_PARAM_TP = os.getenv("TOOBIT_PARAM_TP", "takeProfit")
TOOBIT_PARAM_SL = os.getenv("TOOBIT_PARAM_SL", "stopLoss")
MAX_TOOBIT_OKX_PRICE_DEVIATION_PCT = float(os.getenv("MAX_TOOBIT_OKX_PRICE_DEVIATION_PCT", "0.25"))

# -----------------------------
# سرمایه/ریسک
# -----------------------------
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "6"))
LEVERAGE = int(os.getenv("LEVERAGE", "10"))
MAX_ACTIVE_TRADES = int(os.getenv("MAX_ACTIVE_TRADES", "1"))
MAX_ACTIVE_PER_SYMBOL = int(os.getenv("MAX_ACTIVE_PER_SYMBOL", "1"))
COOLDOWN_AFTER_SIGNAL_SECONDS = int(os.getenv("COOLDOWN_AFTER_SIGNAL_SECONDS", "1800"))
COOLDOWN_AFTER_LOSS_SECONDS = int(os.getenv("COOLDOWN_AFTER_LOSS_SECONDS", "3600"))
DAILY_MAX_REAL_LOSS_USDT = float(os.getenv("DAILY_MAX_REAL_LOSS_USDT", "0"))  # 0 یعنی غیرفعال

# حداقل RR حتماً 1 است. کمتر از 1 اجازه ورود ندارد.
MIN_RR = max(1.0, float(os.getenv("MIN_RR", "1.0")))
DEFAULT_RR = max(MIN_RR, float(os.getenv("DEFAULT_RR", "1.5")))
STRONG_FLOW_RR = max(DEFAULT_RR, float(os.getenv("STRONG_FLOW_RR", "2.0")))
USE_DYNAMIC_RR = os.getenv("USE_DYNAMIC_RR", "true").lower() == "true"

# -----------------------------
# DIFT-5M Gate System - بدون امتیاز
# -----------------------------
EMA_FAST = int(os.getenv("EMA_FAST", "21"))
EMA_SLOW = int(os.getenv("EMA_SLOW", "55"))
VWAP_LENGTH = int(os.getenv("VWAP_LENGTH", "48"))
ATR_LENGTH = int(os.getenv("ATR_LENGTH", "14"))
ADX_LENGTH = int(os.getenv("ADX_LENGTH", "14"))
MIN_ADX_15M = float(os.getenv("MIN_ADX_15M", "16"))
MIN_ADX_1H = float(os.getenv("MIN_ADX_1H", "14"))

COMPRESSION_LOOKBACK = int(os.getenv("COMPRESSION_LOOKBACK", "10"))
MIN_PRE_RANGE_PCT = float(os.getenv("MIN_PRE_RANGE_PCT", "0.18"))
MAX_PRE_RANGE_PCT = float(os.getenv("MAX_PRE_RANGE_PCT", "1.80"))
MAX_PRE_RANGE_ATR_MULT = float(os.getenv("MAX_PRE_RANGE_ATR_MULT", "3.2"))

MIN_BODY_RATIO = float(os.getenv("MIN_BODY_RATIO", "0.55"))
MIN_CLOSE_POSITION_LONG = float(os.getenv("MIN_CLOSE_POSITION_LONG", "0.68"))
MAX_CLOSE_POSITION_SHORT = float(os.getenv("MAX_CLOSE_POSITION_SHORT", "0.32"))
MIN_VOLUME_RATIO = float(os.getenv("MIN_VOLUME_RATIO", "1.30"))
MAX_IMPULSE_ATR_MULT = float(os.getenv("MAX_IMPULSE_ATR_MULT", "2.60"))

REQUIRE_ORDER_FLOW = os.getenv("REQUIRE_ORDER_FLOW", "true").lower() == "true"
MIN_TAKER_RATIO_LONG = float(os.getenv("MIN_TAKER_RATIO_LONG", "1.06"))
MIN_TAKER_RATIO_SHORT = float(os.getenv("MIN_TAKER_RATIO_SHORT", "1.06"))
MIN_BOOK_BID_RATIO_LONG = float(os.getenv("MIN_BOOK_BID_RATIO_LONG", "0.48"))
MAX_BOOK_BID_RATIO_SHORT = float(os.getenv("MAX_BOOK_BID_RATIO_SHORT", "0.52"))
STRONG_TAKER_RATIO = float(os.getenv("STRONG_TAKER_RATIO", "1.35"))
STRONG_BOOK_EDGE = float(os.getenv("STRONG_BOOK_EDGE", "0.56"))

MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.08"))
MAX_ABS_FUNDING_RATE = float(os.getenv("MAX_ABS_FUNDING_RATE", "0.0012"))
MAX_DIRECTIONAL_FUNDING_RATE = float(os.getenv("MAX_DIRECTIONAL_FUNDING_RATE", "0.0008"))

MIN_SL_DISTANCE_PCT = float(os.getenv("MIN_SL_DISTANCE_PCT", "0.20"))
MAX_SL_DISTANCE_PCT = float(os.getenv("MAX_SL_DISTANCE_PCT", "1.80"))
SL_ATR_BUFFER = float(os.getenv("SL_ATR_BUFFER", "0.10"))
MIN_TARGET_ROOM_R_MULT = float(os.getenv("MIN_TARGET_ROOM_R_MULT", "1.0"))

# -----------------------------
# فایل‌های ریشه‌ای runtime
# -----------------------------
STATE_FILE = os.getenv("STATE_FILE", "runtime_state.json")
SIGNALS_FILE = os.getenv("SIGNALS_FILE", "signals.jsonl")
RESULTS_FILE = os.getenv("RESULTS_FILE", "results.jsonl")
ACTIVE_TRADES_FILE = os.getenv("ACTIVE_TRADES_FILE", "active_trades.json")
TRADE_HISTORY_FILE = os.getenv("TRADE_HISTORY_FILE", "trade_history.csv")
LOG_FILE = os.getenv("LOG_FILE", "bot.log")
