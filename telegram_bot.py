from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import messages_fa
from stats_manager import StatsManager
from storage import JsonStorage, StoredSignal


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _norm_text(text: str | None) -> str:
    text = (text or "").translate(_FA_DIGITS)
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text.strip())
    return text


def _first_number_from_text(text: str) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", _norm_text(text))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _first_int_from_text(text: str) -> int | None:
    value = _first_number_from_text(text)
    if value is None:
        return None
    return int(value)


class TelegramBot:
    def __init__(self, storage: JsonStorage, stats: StatsManager) -> None:
        self.storage = storage
        self.stats = stats
        if not config.TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")
        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self._register()

    def _register(self) -> None:
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("panel", self.panel))
        self.app.add_handler(CommandHandler("trade_on", self.trade_on))
        self.app.add_handler(CommandHandler("trade_off", self.trade_off))
        self.app.add_handler(CommandHandler("amount", self.amount))
        self.app.add_handler(CommandHandler("leverage", self.leverage))
        self.app.add_handler(CommandHandler("max_positions", self.max_positions))
        self.app.add_handler(CommandHandler("stats", self.stats_cmd))
        self.app.add_handler(CommandHandler("reset_stats", self.reset_stats))
        self.app.add_handler(CommandHandler("delete_stats", self.delete_stats))
        self.app.add_handler(CallbackQueryHandler(self.callback))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_message))

    def _panel_text(self) -> str:
        real_open = len(self.storage.real_open_signals())
        paper_open = len(self.storage.paper_open_signals())
        return messages_fa.trade_panel(self.storage.state.settings, real_open=real_open, paper_open=paper_open)

    @staticmethod
    def _panel_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("ترید فعال ✅", callback_data="trade_on"),
                InlineKeyboardButton("ترید خاموش ⛔️", callback_data="trade_off"),
            ],
            [
                InlineKeyboardButton("آمار 📊", callback_data="stats"),
                InlineKeyboardButton("پنل ترید ⚙️", callback_data="panel"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def _send_panel(self, update: Update, prefix: str | None = None) -> None:
        text = self._panel_text()
        if prefix:
            text = prefix + "\n\n" + text
        await update.effective_chat.send_message(text, reply_markup=self._panel_keyboard())

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_chat.send_message(messages_fa.start_message())
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
        value = self._first_number(context.args)
        await self._set_amount(update, value)

    async def leverage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        value = self._first_int(context.args)
        await self._set_leverage(update, value)

    async def max_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        value = self._first_int(context.args)
        await self._set_max_positions(update, value)

    async def _set_amount(self, update: Update, value: float | None) -> None:
        if value is None or not (config.TRADE_AMOUNT_MIN <= value <= config.TRADE_AMOUNT_MAX):
            await update.effective_chat.send_message(
                f"مبلغ باید بین {config.TRADE_AMOUNT_MIN:g} تا {config.TRADE_AMOUNT_MAX:g} USDT باشد.\nمثال: تنظیم مبلغ 10"
            )
            return
        self.storage.update_settings(margin_usdt=float(value))
        await self._send_panel(update, f"✅ مبلغ معامله روی {value:g} USDT تنظیم شد.")

    async def _set_leverage(self, update: Update, value: int | None) -> None:
        if value is None or not (config.LEVERAGE_MIN <= value <= config.LEVERAGE_MAX):
            await update.effective_chat.send_message(
                f"لوریج باید بین {config.LEVERAGE_MIN} تا {config.LEVERAGE_MAX} باشد.\nمثال: تنظیم لوریج 10"
            )
            return
        self.storage.update_settings(leverage=int(value))
        await self._send_panel(update, f"✅ لوریج روی {value}x تنظیم شد.")

    async def _set_max_positions(self, update: Update, value: int | None) -> None:
        if value is None or not (config.MAX_POSITIONS_MIN <= value <= config.MAX_POSITIONS_MAX):
            await update.effective_chat.send_message(
                f"حداکثر پوزیشن باید بین {config.MAX_POSITIONS_MIN} تا {config.MAX_POSITIONS_MAX} باشد.\nمثال: تنظیم حداکثر پوزیشن 3"
            )
            return
        self.storage.update_settings(max_positions=int(value))
        await self._send_panel(update, f"✅ حداکثر پوزیشن واقعی روی {value} تنظیم شد.")

    async def stats_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_chat.send_message(self.stats.summary_text())

    async def reset_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.stats.reset()
        await update.effective_chat.send_message("✅ آمار ریست شد.")

    async def delete_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.stats.delete_all()
        await update.effective_chat.send_message("🗑 آمار و وضعیت ذخیره‌شده حذف شد.")

    async def text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = _norm_text(update.message.text if update.message else "")
        t = text.lower()

        panel_words = {"ترید", "پنل", "پنل ترید", "وضعیت", "وضعیت ترید"}
        stats_words = {"آمار", "امار", "گزارش", "استات", "stats"}
        on_words = {"ترید فعال", "ترید روشن", "روشن کردن ترید", "فعال کردن ترید", "ترید رو روشن کن", "فعال"}
        off_words = {"ترید خاموش", "خاموش کردن ترید", "غیرفعال کردن ترید", "ترید رو خاموش کن", "خاموش", "غیرفعال"}
        reset_words = {"ریست آمار", "ریست امار", "صفر کردن آمار", "صفر کردن امار"}
        delete_words = {"حذف آمار", "حذف امار", "پاک کردن آمار", "پاک کردن امار"}

        if t in panel_words:
            await self._send_panel(update)
            return
        if t in stats_words:
            await update.effective_chat.send_message(self.stats.summary_text())
            return
        if t in on_words:
            self.storage.update_settings(trade_enabled=True)
            await self._send_panel(update, "✅ ترید فعال شد.")
            return
        if t in off_words:
            self.storage.update_settings(trade_enabled=False)
            await self._send_panel(update, "⛔️ ترید خاموش شد.")
            return
        if t in reset_words:
            self.stats.reset()
            await update.effective_chat.send_message("✅ آمار ریست شد.")
            return
        if t in delete_words:
            self.stats.delete_all()
            await update.effective_chat.send_message("🗑 آمار و وضعیت ذخیره‌شده حذف شد.")
            return

        if t.startswith(("تنظیم مبلغ", "مبلغ", "سرمایه", "حجم معامله")):
            await self._set_amount(update, _first_number_from_text(text))
            return
        if t.startswith(("تنظیم لوریج", "لوریج", "اهرم")):
            await self._set_leverage(update, _first_int_from_text(text))
            return
        if t.startswith(("تنظیم حداکثر پوزیشن", "حداکثر پوزیشن", "حداکثر پوزیشن ها", "اسلات", "اسلات ها")):
            await self._set_max_positions(update, _first_int_from_text(text))
            return

        await update.effective_chat.send_message(
            "دستور نامشخص است.\n\n"
            "دستورهای اصلی:\n"
            "ترید\n"
            "ترید فعال\n"
            "ترید خاموش\n"
            "آمار\n"
            "تنظیم مبلغ 10\n"
            "تنظیم لوریج 10\n"
            "تنظیم حداکثر پوزیشن 3"
        )

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return
        await query.answer()
        data = query.data
        if data == "trade_on":
            self.storage.update_settings(trade_enabled=True)
            await query.edit_message_text(self._panel_text(), reply_markup=self._panel_keyboard())
        elif data == "trade_off":
            self.storage.update_settings(trade_enabled=False)
            await query.edit_message_text(self._panel_text(), reply_markup=self._panel_keyboard())
        elif data == "panel":
            await query.edit_message_text(self._panel_text(), reply_markup=self._panel_keyboard())
        elif data == "stats" and query.message:
            await query.message.reply_text(self.stats.summary_text())

    async def send_signal(self, text: str) -> int | None:
        if not config.TELEGRAM_CHAT_ID:
            return None
        msg = await self.app.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text)
        return msg.message_id

    async def reply_to_signal(self, sig: StoredSignal, text: str) -> None:
        if not config.TELEGRAM_CHAT_ID:
            return
        kwargs = {"chat_id": config.TELEGRAM_CHAT_ID, "text": text}
        if sig.telegram_message_id:
            kwargs["reply_to_message_id"] = sig.telegram_message_id
        await self.app.bot.send_message(**kwargs)

    def run_polling(self, post_init=None) -> None:  # noqa: ANN001
        if post_init is not None:
            self.app.post_init = post_init
        self.app.run_polling(close_loop=False)

    @staticmethod
    def _first_number(args: list[str]) -> float | None:
        if not args:
            return None
        try:
            return float(str(args[0]).translate(_FA_DIGITS))
        except ValueError:
            return None

    @staticmethod
    def _first_int(args: list[str]) -> int | None:
        value = TelegramBot._first_number(args)
        return int(value) if value is not None else None
