import os

# =========================
# Telegram / API Keys
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")  # optional, only for future real economic calendar

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
MIN_SIGNAL_SCORE = int(os.getenv("MIN_SIGNAL_SCORE", "75"))
BEST_SIGNAL_COUNT = int(os.getenv("BEST_SIGNAL_COUNT", "5"))

# =========================
# News Filter
# =========================
NEWS_BLOCK_BEFORE_MINUTES = int(os.getenv("NEWS_BLOCK_BEFORE_MINUTES", "30"))
NEWS_BLOCK_AFTER_MINUTES = int(os.getenv("NEWS_BLOCK_AFTER_MINUTES", "30"))

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
DEFAULT_RISK_PERCENT = float(os.getenv("DEFAULT_RISK_PERCENT", "1.0"))
MAX_RISK_PERCENT = float(os.getenv("MAX_RISK_PERCENT", "2.0"))

# =========================
# File Storage
# =========================
DATA_DIR = os.getenv("FOREX_BOT_DATA_DIR", "/root/forex-signal-bot/data")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
TRACKER_FILE = os.path.join(DATA_DIR, "active_signals.json")

# =========================
# Bot Settings
# =========================
BOT_LANGUAGE = "fa"
PYTHONUNBUFFERED = "1"
