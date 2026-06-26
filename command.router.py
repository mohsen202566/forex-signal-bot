"""دستورات فارسی ربات."""
from __future__ import annotations

from typing import Any

import config
from state_store import StateStore
from telegram_ui import panel, stats_panel, help_text


class CommandRouter:
    def __init__(self, state: StateStore, tobit_client: Any):
        self.state = state
        self.tobit = tobit_client

    def handle(self, text: str) -> str:
        t = " ".join(text.strip().split())
        if not t:
            return help_text()
        if t in {"ترید", "وضعیت"}:
            return panel(self.state.data, self.tobit.account_panel())
        if t == "آمار":
            return stats_panel(self.state.data)
        if t == "کوین‌ها":
            return "🪙 کوین‌های فعال:\n" + "\n".join(config.WATCHLIST)
        if t == "پوزیشن":
            active = self.state.all_active()
            if not active:
                return "پوزیشن یا سیگنال فعال نداریم."
            return "\n\n".join(f"{x.get('id')} | {x.get('kind')} | {x.get('coin')} | {x.get('side')} | {x.get('status')}" for x in active)
        if t == "استراتژی لول 4":
            return self.strategy_text()
        if t == "ترید فعال":
            self.state.update_setting("real_trade_enabled", True)
            return "✅ ترید واقعی فعال شد."
        if t == "ترید خاموش":
            self.state.update_setting("real_trade_enabled", False)
            return "⏸ ترید واقعی خاموش شد. سیگنال‌ها همچنان صادر و مانیتور می‌شوند."
        if t.startswith("ترید دلار "):
            return self._set_float(t, "ترید دلار ", "trade_margin_usdt", config.TRADE_MARGIN_MIN, config.TRADE_MARGIN_MAX, "USDT")
        if t.startswith("ترید لوریج "):
            return self._set_int(t, "ترید لوریج ", "leverage", config.LEVERAGE_MIN, config.LEVERAGE_MAX, "x")
        if t.startswith("حداکثر پوزیشن "):
            return self._set_int(t, "حداکثر پوزیشن ", "max_open_positions", config.MAX_POSITIONS_MIN, config.MAX_POSITIONS_MAX, "")
        if t.startswith("حداقل سود خالص "):
            return self._set_float(t, "حداقل سود خالص ", "min_net_profit_usdt", config.MIN_NET_PROFIT_MIN, config.MIN_NET_PROFIT_MAX, "USDT")
        return help_text()

    def _set_float(self, text: str, prefix: str, key: str, lo: float, hi: float, suffix: str) -> str:
        try:
            value = config.clamp_float(float(text.replace(prefix, "", 1)), lo, hi)
        except ValueError:
            return f"عدد نامعتبر است. بازه مجاز: {lo} تا {hi}"
        self.state.update_setting(key, value)
        return f"✅ تنظیم شد: {value} {suffix}".strip()

    def _set_int(self, text: str, prefix: str, key: str, lo: int, hi: int, suffix: str) -> str:
        try:
            value = config.clamp_int(int(float(text.replace(prefix, "", 1))), lo, hi)
        except ValueError:
            return f"عدد نامعتبر است. بازه مجاز: {lo} تا {hi}"
        self.state.update_setting(key, value)
        return f"✅ تنظیم شد: {value}{suffix}"

    def strategy_text(self) -> str:
        return """
استراتژی قفل‌شده:
- پوزیشن ۱۵ تا ۳۰ دقیقه
- ۱۰ کوین ثابت
- تحلیل از OKX
- REAL از Toobit
- سیگنال ۳ دقیقه معتبر
- Entry + Continuation + Confidence Penalty
- محور تصمیم: شتاب RSI/ATR/ADX/Volume/OI
- TP/SL همزمان با پوزیشن
- آمار جدا: توبیت و سیگنال
""".strip()
