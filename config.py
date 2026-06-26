"""تنظیمات قفل‌شده ربات ۱۵ تا ۳۰ دقیقه‌ای.

فلسفه: فایل کم، تنظیمات متمرکز، تحلیل بر اساس شتاب تغییرات نه فقط مقدار اندیکاتورها.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final


WATCHLIST: Final[list[str]] = [
    "SOLUSDT", "DOGEUSDT", "XRPUSDT", "SUIUSDT", "LINKUSDT",
    "AVAXUSDT", "ADAUSDT", "APTUSDT", "NEARUSDT", "LTCUSDT",
]

# زمان‌بندی‌ها
PRICE_MONITOR_SECONDS: Final[int] = 3          # مانیتور سریع TP/SL و پوزیشن‌ها
COIN_SCAN_SECONDS: Final[int] = 25             # اسکن ۱۰ کوین
SIGNAL_VALID_SECONDS: Final[int] = 180         # اعتبار سیگنال: ۳ دقیقه
TOBIT_OPEN_CONFIRM_SECONDS: Final[int] = 70    # بعد از سفارش REAL، تایید پوزیشن
POSITION_MAX_MINUTES: Final[int] = 30          # خروج/انقضای تحلیلی سیگنال عادی
POSITION_MIN_MINUTES: Final[int] = 15

# امتیازهای ورود
MIN_ENTRY_SCORE: Final[float] = 70.0
MIN_CONTINUATION_SCORE: Final[float] = 62.0
MIN_FINAL_SCORE: Final[float] = 68.0
REPLACE_SIGNAL_MIN_IMPROVEMENT: Final[float] = 5.0

# رنج‌های تنظیمات کاربر
TRADE_MARGIN_MIN: Final[float] = 1.0
TRADE_MARGIN_MAX: Final[float] = 10000.0
LEVERAGE_MIN: Final[int] = 1
LEVERAGE_MAX: Final[int] = 100
MAX_POSITIONS_MIN: Final[int] = 1
MAX_POSITIONS_MAX: Final[int] = 100
MIN_NET_PROFIT_MIN: Final[float] = 0.10
MIN_NET_PROFIT_MAX: Final[float] = 10000.0

# کارمزد و بافر. عدد واقعی را با Toobit خودت تنظیم کن.
DEFAULT_FEE_RATE: Final[float] = float(os.getenv("TOBIT_FEE_RATE", "0.0006"))
SLIPPAGE_BUFFER_RATE: Final[float] = float(os.getenv("SLIPPAGE_BUFFER_RATE", "0.0002"))

# Risk/Reward پویا ولی کنترل‌شده برای تایم ۱۵ تا ۳۰ دقیقه
MIN_RR: Final[float] = 1.25
BASE_RR: Final[float] = 1.50
MAX_RR: Final[float] = 2.00
ATR_SL_MULT_MIN: Final[float] = 0.75
ATR_SL_MULT_BASE: Final[float] = 1.00
ATR_SL_MULT_MAX: Final[float] = 1.35


@dataclass
class RuntimeSettings:
    real_trade_enabled: bool = False
    trade_margin_usdt: float = 7.0
    leverage: int = 10
    max_open_positions: int = 1
    min_net_profit_usdt: float = 0.10

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls(
            real_trade_enabled=os.getenv("REAL_TRADE_ENABLED", "false").lower() == "true",
            trade_margin_usdt=float(os.getenv("TRADE_MARGIN_USDT", "7")),
            leverage=int(os.getenv("TRADE_LEVERAGE", "10")),
            max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "1")),
            min_net_profit_usdt=float(os.getenv("MIN_NET_PROFIT_USDT", "0.10")),
        )


def clamp_float(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))
