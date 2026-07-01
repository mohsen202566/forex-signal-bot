from __future__ import annotations

import re
from collections.abc import Iterable

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import config
import messages_fa
from stats_manager import StatsManager
from storage import JsonStorage, StoredSignal

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _norm_text(text: str | None) -> str:
    """Normalize Persian/Arabic text so natural commands work reliably."""
    value = (text or "").translate(_FA_DIGITS)
    value = value.replace("ي", "ی").replace("ك", "ک")
    value = value.replace("‌", " ")
    value = re.sub(r"[\t\r\n]+", " ", value)
    value = re.sub(r"\s+", " ", value.strip())
    return value


def _norm_key(text: str | None) -> str:
    value = _norm_text(text).lower()
    value = value.replace("/", " ")
    value = value.replace("_", " ")
    value = re.sub(r"[!؟?،,:;؛()\[\]{}]+", " ", value)
    value = re.sub(r"\s+", " ", value.strip())
    return value


def _first_number_from_text(text: str | None) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", _norm_text(text))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _first_int_from_text(text: str | None) -> int | None:
    value = _first_number_from_text(text)
    if value is None:
        return None
    return int(value)


def _contains_all(text: str, words: Iterable[str]) -> bool:
    return all(word in text for word in words)


class TelegramBot:
    """Pure text Telegram interface.

    این کلاس هیچ ReplyKeyboardMarkup یا InlineKeyboardMarkup نمی‌سازد.
    برای پاک شدن دکمه‌های قدیمی، همه پیام‌ها با ReplyKeyboardRemove ارسال می‌شوند.
    """

    def __init__(self, storage: JsonStorage, stats: StatsManager) -> None:
        self.storage = storage
        self.stats = stats
        if not config.TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")
        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("panel", self.panel))
        self.app.add_handler(CommandHandler("trade", self.panel))
        self.app.add_handler(CommandHandler("trade_on", self.trade_on))
        self.app.add_handler(CommandHandler("trade_off", self.trade_off))
        self.app.add_handler(CommandHandler("amount", self.amount))
        self.app.add_handler(CommandHandler("leverage", self.leverage))
        self.app.add_handler(CommandHandler("max_positions", self.max_positions))
        self.app.add_handler(CommandHandler("stats", self.stats_cmd))
        self.app.add_handler(CommandHandler("reset_stats", self.reset_stats))
        self.app.add_handler(CommandHandler("delete_stats", self.delete_stats))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_message))

    async def _send_text(self, update: Update, text: str) -> None:
        if update.effective_chat is None:
            return
        await update.effective_chat.send_message(text, reply_markup=ReplyKeyboardRemove(remove_keyboard=True))

    async def _send_direct(self, text: str, *, reply_to_message_id: int | None = None) -> int | None:
        if not config.TELEGRAM_CHAT_ID:
            return None
        kwargs = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "reply_markup": ReplyKeyboardRemove(remove_keyboard=True),
        }
        if reply_to_message_id:
            kwargs["reply_to_message_id"] = reply_to_message_id
        msg = await self.app.bot.send_message(**kwargs)
        return msg.message_id

    def _panel_text(self) -> str:
        real_open = len(self.storage.real_open_signals())
        paper_open = len(self.storage.paper_open_signals())
        return messages_fa.trade_panel(self.storage.state.settings, real_open=real_open, paper_open=paper_open)

    async def _send_panel(self, update: Update, prefix: str | None = None) -> None:
        text = self._panel_text()
        if prefix:
            text = f"{prefix}\n\n{text}"
        await self._send_text(update, text)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._send_text(update, messages_fa.start_message())
        await self._send_panel(update)

    async def panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._send_panel(update)

    async def trade_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.storage.update_settings(trade_enabled=True)
        await self._send_panel(update, "✅ ترید فعال شد.")

    async def trade_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.storage.update_settings(trade_enabled=False)
        await self._send_panel(update, "⛔️ ترید خاموش شد.")

    async def amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._set_amount(update, self._first_number(context.args))

    async def leverage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._set_leverage(update, self._first_int(context.args))

    async def max_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._set_max_positions(update, self._first_int(context.args))

    async def stats_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._send_text(update, self.stats.summary_text())

    async def reset_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.stats.reset()
        await self._send_text(update, "✅ آمار ریست شد.")

    async def delete_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.stats.delete_all()
        await self._send_text(update, "🗑 آمار و وضعیت ذخیره‌شده حذف شد.")

    async def _set_amount(self, update: Update, value: float | None) -> None:
        if value is None or not (config.TRADE_AMOUNT_MIN <= value <= config.TRADE_AMOUNT_MAX):
            await self._send_text(
                update,
                f"مبلغ باید بین {config.TRADE_AMOUNT_MIN:g} تا {config.TRADE_AMOUNT_MAX:g} USDT باشد.\n"
                "مثال: تنظیم مبلغ 10",
            )
            return
        self.storage.update_settings(margin_usdt=float(value))
        await self._send_panel(update, f"✅ مبلغ معامله روی {value:g} USDT تنظیم شد.")

    async def _set_leverage(self, update: Update, value: int | None) -> None:
        if value is None or not (config.LEVERAGE_MIN <= value <= config.LEVERAGE_MAX):
            await self._send_text(
                update,
                f"لوریج باید بین {config.LEVERAGE_MIN} تا {config.LEVERAGE_MAX} باشد.\n"
                "مثال: تنظیم لوریج 10",
            )
            return
        self.storage.update_settings(leverage=int(value))
        await self._send_panel(update, f"✅ لوریج روی {value}x تنظیم شد.")

    async def _set_max_positions(self, update: Update, value: int | None) -> None:
        if value is None or not (config.MAX_POSITIONS_MIN <= value <= config.MAX_POSITIONS_MAX):
            await self._send_text(
                update,
                f"حداکثر پوزیشن باید بین {config.MAX_POSITIONS_MIN} تا {config.MAX_POSITIONS_MAX} باشد.\n"
                "مثال: تنظیم حداکثر پوزیشن 3",
            )
            return
        self.storage.update_settings(max_positions=int(value))
        await self._send_panel(update, f"✅ حداکثر پوزیشن واقعی روی {value} تنظیم شد.")

    async def text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        raw = update.message.text if update.message else ""
        text = _norm_text(raw)
        key = _norm_key(raw)

        # Exact/natural panel commands. فقط نمایش پنل، بدون تغییر تنظیمات.
        if key in {"ترید", "پنل", "پنل ترید", "وضعیت", "وضعیت ترید", "trade", "panel", "start"}:
            await self._send_panel(update)
            return

        # Trade on/off. ترتیب مهم است؛ «ترید خاموش» نباید با «ترید» اشتباه شود.
        if (
            key in {"ترید فعال", "ترید روشن", "روشن کردن ترید", "فعال کردن ترید", "trade on"}
            or _contains_all(key, ("ترید", "روشن"))
            or _contains_all(key, ("ترید", "فعال"))
        ):
            self.storage.update_settings(trade_enabled=True)
            await self._send_panel(update, "✅ ترید فعال شد.")
            return

        if (
            key in {"ترید خاموش", "خاموش کردن ترید", "غیر فعال کردن ترید", "غیرفعال کردن ترید", "trade off"}
            or _contains_all(key, ("ترید", "خاموش"))
            or _contains_all(key, ("ترید", "غیر فعال"))
            or _contains_all(key, ("ترید", "غیرفعال"))
        ):
            self.storage.update_settings(trade_enabled=False)
            await self._send_panel(update, "⛔️ ترید خاموش شد.")
            return

        if key in {"آمار", "امار", "گزارش", "استات", "stats", "آمار ربات", "امار ربات"}:
            await self._send_text(update, self.stats.summary_text())
            return

        if key in {"ریست آمار", "ریست امار", "صفر کردن آمار", "صفر کردن امار", "reset stats"}:
            self.stats.reset()
            await self._send_text(update, "✅ آمار ریست شد.")
            return

        if key in {"حذف آمار", "حذف امار", "پاک کردن آمار", "پاک کردن امار", "delete stats"}:
            self.stats.delete_all()
            await self._send_text(update, "🗑 آمار و وضعیت ذخیره‌شده حذف شد.")
            return

        if key.startswith(("تنظیم مبلغ", "مبلغ", "سرمایه", "حجم معامله", "amount")):
            await self._set_amount(update, _first_number_from_text(text))
            return

        if key.startswith(("تنظیم لوریج", "لوریج", "اهرم", "leverage")):
            await self._set_leverage(update, _first_int_from_text(text))
            return

        if key.startswith(("تنظیم حداکثر پوزیشن", "حداکثر پوزیشن", "حداکثر پوزیشن ها", "حداکثر پوزیشنها", "اسلات", "اسلات ها", "اسلاتها", "max positions")):
            await self._set_max_positions(update, _first_int_from_text(text))
            return

        await self._send_text(update, messages_fa.commands_help())

    async def send_signal(self, text: str) -> int | None:
        return await self._send_direct(text)

    async def reply_to_signal(self, sig: StoredSignal, text: str) -> None:
        await self._send_direct(text, reply_to_message_id=sig.telegram_message_id)

    def run_polling(self, post_init=None) -> None:  # noqa: ANN001
        if post_init is not None:
            self.app.post_init = post_init
        self.app.run_polling(close_loop=False)

    @staticmethod
    def _first_number(args: list[str]) -> float | None:
        if not args:
            return None
        return _first_number_from_text(" ".join(args))

    @staticmethod
    def _first_int(args: list[str]) -> int | None:
        return _first_int_from_text(" ".join(args or []))
