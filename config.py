import os

# =========================
# Telegram
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# =========================
# Data API
# =========================
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

# =========================
# Forex Pairs
# =========================
FOREX_PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "NZD/USD",
    "USD/CAD",
    "EUR/JPY",
    "XAU/USD",
]

# =========================
# Timeframes
# =========================
TREND_TF = "4h"       # جهت کلی
CONFIRM_TF = "1h"     # تایید جهت
SETUP_TF = "15min"    # آماده بودن ستاپ
ENTRY_TF = "5min"     # تریگر ورود سریع

# =========================
# Signal Settings
# =========================
MIN_SIGNAL_SCORE = 75
BEST_SIGNAL_COUNT = 5

# =========================
# News Filter
# =========================
NEWS_BLOCK_BEFORE_MINUTES = 30
NEWS_BLOCK_AFTER_MINUTES = 30

IMPORTANT_NEWS_KEYWORDS = [
    "CPI",
    "NFP",
    "Nonfarm Payrolls",
    "FOMC",
    "Interest Rate",
    "Rate Decision",
    "Fed Chair",
    "Powell",
    "Unemployment Rate",
    "GDP",
]

# =========================
# Risk Settings
# =========================
DEFAULT_RISK_PERCENT = 1.0
MAX_RISK_PERCENT = 2.0

# =========================
# Bot Settings
# =========================
BOT_LANGUAGE = "fa"
