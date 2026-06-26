"""Router دستورات فارسی ربات.

قفل‌های UI/Command:
- همه کنترل‌ها از تلگرام و با فارسی ساده انجام می‌شود.
- دستور «ترید» مثل پنل صرافی وضعیت کامل را نشان می‌دهد.
- ترید خاموش فقط اجرای REAL را خاموش می‌کند؛ سیگنال عادی همچنان صادر، مانیتور و آمارگیری می‌شود.
- بازه تنظیمات دقیق است و مقدار خارج از بازه Clamp نمی‌شود؛ خطای واضح فارسی برمی‌گردد.
- آمار، پوزیشن‌ها و کوین‌ها با تفکیک SIGNAL / TOBIT نمایش داده می‌شوند.
"""
from __future__ import annotations

from typing import Any

import config
from state_store import StateStore, now_ts
from telegram_ui import (
    coins_panel,
    help_text,
    main_buttons,
    panel,
    positions_panel,
    setting_prompt,
    stats_panel,
)


PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٫٬", "0123456789..")


class CommandRouter:
    def __init__(self, state: StateStore, tobit_client: Any):
        self.state = state
        self.tobit = tobit_client

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    def handle(self, text: str) -> str:
        """Handle normal Telegram text commands."""
        t = self._normalize_text(text)
        if not t:
            return help_text()

        if t in {"/start", "start", "راهنما", "کمک", "help"}:
            return help_text()

        if t in {"ترید", "وضعیت", "پنل"}:
            return self.trade_panel()

        if t == "آمار":
            return stats_panel(self._view_state())

        if t in {"پوزیشن", "پوزیشن‌ها", "پوزیشن ها"}:
            return positions_panel(self._view_state())

        if t in {"کوین‌ها", "کوین ها", "کوین"}:
            return self.coins_status_panel()

        if t in {"استراتژی", "استراتژی لول 4", "استراتژی لول۴", "لول 4", "لول۴"}:
            return self.strategy_text()

        if t == "ترید فعال":
            self.state.update_setting("real_trade_enabled", True)
            return "✅ ترید واقعی فعال شد.\nاز این لحظه اگر قوانین REAL پاس شوند، پیام با عنوان «🔴 سیگنال توبیت» ارسال می‌شود."

        if t == "ترید خاموش":
            self.state.update_setting("real_trade_enabled", False)
            return "⏸ ترید واقعی خاموش شد.\n📡 سیگنال‌های عادی همچنان صادر، مانیتور و در آمار ثبت می‌شوند."

        if t.startswith("ترید دلار "):
            return self._set_float(
                text=t,
                prefix="ترید دلار ",
                key="trade_margin_usdt",
                label="دلار هر پوزیشن",
                lo=config.TRADE_MARGIN_MIN,
                hi=config.TRADE_MARGIN_MAX,
                suffix="USDT",
            )

        if t.startswith("ترید لوریج "):
            return self._set_int(
                text=t,
                prefix="ترید لوریج ",
                key="leverage",
                label="لوریج",
                lo=config.LEVERAGE_MIN,
                hi=config.LEVERAGE_MAX,
                suffix="x",
            )

        if t.startswith("حداکثر پوزیشن "):
            return self._set_int(
                text=t,
                prefix="حداکثر پوزیشن ",
                key="max_open_positions",
                label="حداکثر پوزیشن",
                lo=config.MAX_POSITIONS_MIN,
                hi=config.MAX_POSITIONS_MAX,
                suffix="",
            )

        if t.startswith("حداقل سود خالص "):
            return self._set_float(
                text=t,
                prefix="حداقل سود خالص ",
                key="min_net_profit_usdt",
                label="حداقل سود خالص",
                lo=config.MIN_NET_PROFIT_MIN,
                hi=config.MIN_NET_PROFIT_MAX,
                suffix="USDT",
            )

        return "دستور نامعتبر است.\n\n" + help_text()

    def handle_callback(self, data: str) -> str:
        """Handle inline-button callback data.

        The actual Telegram adapter can call this and send the returned text.
        """
        d = str(data or "").strip()
        settings = self.state.settings()

        if d == "trade_on":
            return self.handle("ترید فعال")
        if d == "trade_off":
            return self.handle("ترید خاموش")
        if d == "stats":
            return self.handle("آمار")
        if d == "positions":
            return self.handle("پوزیشن")
        if d == "coins":
            return self.handle("کوین‌ها")
        if d == "help":
            return help_text()
        if d == "set_margin":
            return setting_prompt("trade_margin_usdt", settings.get("trade_margin_usdt")) + "\n\nنمونه: ترید دلار 7"
        if d == "set_leverage":
            return setting_prompt("leverage", settings.get("leverage")) + "\n\nنمونه: ترید لوریج 10"
        if d == "set_max_positions":
            return setting_prompt("max_open_positions", settings.get("max_open_positions")) + "\n\nنمونه: حداکثر پوزیشن 1"
        if d == "set_min_profit":
            return setting_prompt("min_net_profit_usdt", settings.get("min_net_profit_usdt")) + "\n\nنمونه: حداقل سود خالص 0.10"

        return help_text()

    # ------------------------------------------------------------------
    # Panels
    # ------------------------------------------------------------------
    def trade_panel(self) -> str:
        exchange = self._safe_account_panel()
        body = panel(self._view_state(), exchange)
        buttons = self._button_hint()
        return f"{body}\n\n{buttons}".strip()

    def coins_status_panel(self) -> str:
        base = coins_panel(config.WATCHLIST)
        lines = [base, "", "وضعیت لحظه‌ای کوین‌ها:"]
        for coin in config.WATCHLIST:
            active = self.state.active_by_coin(coin)
            real_active = [s for s in active if s.get("kind") == "TOBIT"]
            normal_active = [s for s in active if s.get("kind") == "SIGNAL"]
            if real_active:
                status = "🔴 توبیت فعال/Pending"
            elif normal_active:
                status = "📡 سیگنال فعال"
            else:
                status = "🟢 آزاد"
            lines.append(f"{coin}: {status}")
        return "\n".join(lines)

    def strategy_text(self) -> str:
        return """
استراتژی قفل‌شده نسخه ۱۵ تا ۳۰ دقیقه

- تایم معامله: ۱۵ تا ۳۰ دقیقه
- واچ‌لیست: ۱۰ کوین ثابت
- منبع تحلیل و سیگنال عادی: OKX
- اجرای REAL و نتیجه واقعی: Toobit
- سیگنال عادی حتی در حالت ترید خاموش هم صادر و مانیتور می‌شود.
- سیگنال عادی ۳ دقیقه معتبر است.
- اگر همان کوین/همان جهت با امتیاز قوی‌تر بیاید، سیگنال قبلی REPLACED می‌شود.
- برای هر کوین فقط یک REAL فعال یا Pending مجاز است.
- Entry Score + Continuation Score + Confidence Penalty
- Confidence فقط جریمه‌کننده است، نه سیگنال‌ساز.
- محور تصمیم: شتاب RSI / ATR / ADX / Volume / OI
- بازار رنج جریمه سنگین دارد، مگر شتاب حرکت واقعاً قوی باشد.
- TP و SL همزمان با پوزیشن توبیت ارسال می‌شوند.
- حداقل سود خالص بعد از کارمزد و اسلیپیج قبل از REAL چک می‌شود.
- آمار جداست: 🔴 توبیت و 📡 سیگنال.
""".strip()

    # ------------------------------------------------------------------
    # Setting helpers
    # ------------------------------------------------------------------
    def _set_float(self, *, text: str, prefix: str, key: str, label: str, lo: float, hi: float, suffix: str) -> str:
        raw = text.replace(prefix, "", 1).strip()
        try:
            value = self._parse_float(raw)
        except ValueError:
            return f"❌ مقدار {label} نامعتبر است.\nبازه مجاز: {lo:g} تا {hi:g} {suffix}".strip()

        if value < lo or value > hi:
            return f"❌ مقدار {label} خارج از بازه است.\nبازه مجاز: {lo:g} تا {hi:g} {suffix}\nمقدار واردشده: {value:g}"

        self.state.update_setting(key, round(value, 8))
        return f"✅ {label} تنظیم شد: {value:g} {suffix}".strip()

    def _set_int(self, *, text: str, prefix: str, key: str, label: str, lo: int, hi: int, suffix: str) -> str:
        raw = text.replace(prefix, "", 1).strip()
        try:
            value_float = self._parse_float(raw)
        except ValueError:
            return f"❌ مقدار {label} نامعتبر است.\nبازه مجاز: {lo} تا {hi} {suffix}".strip()

        if not value_float.is_integer():
            return f"❌ مقدار {label} باید عدد صحیح باشد.\nنمونه درست: {int(lo)}"

        value = int(value_float)
        if value < lo or value > hi:
            return f"❌ مقدار {label} خارج از بازه است.\nبازه مجاز: {lo} تا {hi} {suffix}\nمقدار واردشده: {value}"

        self.state.update_setting(key, value)
        suffix_text = f"{suffix}" if suffix else ""
        return f"✅ {label} تنظیم شد: {value}{suffix_text}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _view_state(self) -> dict[str, Any]:
        """Flatten runtime keys so telegram_ui can render both old/new state shapes."""
        view = dict(self.state.data)
        runtime = view.get("runtime", {})
        if isinstance(runtime, dict):
            for key in ("last_scan", "last_signal_id", "last_result", "engine_health"):
                if key in runtime:
                    view[key] = runtime[key]
        return view

    def _safe_account_panel(self) -> dict[str, Any]:
        try:
            out = self.tobit.account_panel()
            return out if isinstance(out, dict) else {"connected": True, "raw": out}
        except Exception as exc:
            return {"connected": False, "error": str(exc)}

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text or "").translate(PERSIAN_DIGITS).strip().split())

    @staticmethod
    def _parse_float(raw: str) -> float:
        cleaned = raw.translate(PERSIAN_DIGITS).replace(",", ".").strip()
        if not cleaned:
            raise ValueError("empty")
        return float(cleaned)

    @staticmethod
    def _button_hint() -> str:
        rows = []
        for row in main_buttons():
            rows.append(" | ".join(label for label, _callback in row))
        return "دکمه‌های پنل:\n" + "\n".join(rows)


__all__ = ["CommandRouter"]
