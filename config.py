# -*- coding: utf-8 -*-
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

def _parse_ids(raw: str):
    ids = set()
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            ids.add(int(part))
    return ids

ALLOWED_USER_IDS = _parse_ids(os.getenv("ALLOWED_USER_IDS", ""))
if OWNER_ID:
    ALLOWED_USER_IDS.add(OWNER_ID)

DATA_DIR = os.getenv("DATA_DIR", "data")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
TRACKER_FILE = os.path.join(DATA_DIR, "active_signals.json")
USERS_FILE = os.path.join(DATA_DIR, "allowed_users.json")

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

TREND_TF = "4h"
CONFIRM_TF = "1h"
SETUP_TF = "15min"
ENTRY_TF = "5min"

MIN_SIGNAL_SCORE = int(os.getenv("MIN_SIGNAL_SCORE", "75"))
BEST_SIGNAL_COUNT = int(os.getenv("BEST_SIGNAL_COUNT", "5"))

AUTO_SIGNAL_ENABLED = os.getenv("AUTO_SIGNAL_ENABLED", "true").lower() in ("1", "true", "yes", "on")
AUTO_SIGNAL_SCORE = int(os.getenv("AUTO_SIGNAL_SCORE", "80"))
AUTO_SCAN_INTERVAL_MINUTES = int(os.getenv("AUTO_SCAN_INTERVAL_MINUTES", "5"))
AUTO_SIGNAL_COOLDOWN_MINUTES = int(os.getenv("AUTO_SIGNAL_COOLDOWN_MINUTES", "120"))

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

DEFAULT_RISK_PERCENT = 1.0
MAX_RISK_PERCENT = 2.0
BOT_LANGUAGE = "fa"
