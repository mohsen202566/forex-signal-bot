from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import config
import messages_fa
from stats_manager import StatsManager
from storage import JsonStorage, StoredSignal


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

    def _panel_text(self) -> str:
        real_open = len(self.storage.real_open_signals())
        paper_open = len(self.storage.paper_open_signals())
        return messages_fa.trade_panel(self.storage.state.settings, real_open=real_open, paper_open=paper_open)

    @staticmethod
    def _panel_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("روشن کردن ترید ✅", callback_data="trade_on"), InlineKeyboardButton("خاموش کردن ترید ⛔️", callback_data="trade_off")],
            [InlineKeyboardButton("نمایش آمار 📊", callback_data="stats"), InlineKeyboardButton("پنل ترید ⚙️", callback_data="panel")],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_chat.send_message(messages_fa.start_message())
        await self.panel(update, context)

    async def panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_chat.send_message(self._panel_text(), reply_markup=self._panel_keyboard())

    async def trade_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.storage.update_settings(trade_enabled=True)
        await update.effective_chat.send_message("✅ ترید روشن شد.\n\n" + self._panel_text(), reply_markup=self._panel_keyboard())

    async def trade_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.storage.update_settings(trade_enabled=False)
        await update.effective_chat.send_message("⛔️ ترید خاموش شد.\n\n" + self._panel_text(), reply_markup=self._panel_keyboard())

    async def amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        value = self._first_number(context.args)
        if value is None or not (config.TRADE_AMOUNT_MIN <= value <= config.TRADE_AMOUNT_MAX):
            await update.effective_chat.send_message(f"مبلغ باید بین {config.TRADE_AMOUNT_MIN:g} تا {config.TRADE_AMOUNT_MAX:g} USDT باشد.")
            return
        self.storage.update_settings(margin_usdt=float(value))
        await update.effective_chat.send_message(f"✅ مبلغ معامله روی {value:g} USDT تنظیم شد.\n\n" + self._panel_text(), reply_markup=self._panel_keyboard())

    async def leverage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        value = self._first_int(context.args)
        if value is None or not (config.LEVERAGE_MIN <= value <= config.LEVERAGE_MAX):
            await update.effective_chat.send_message(f"لوریج باید بین {config.LEVERAGE_MIN} تا {config.LEVERAGE_MAX} باشد.")
            return
        self.storage.update_settings(leverage=int(value))
        await update.effective_chat.send_message(f"✅ لوریج روی {value}x تنظیم شد.\n\n" + self._panel_text(), reply_markup=self._panel_keyboard())

    async def max_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        value = self._first_int(context.args)
        if value is None or not (config.MAX_POSITIONS_MIN <= value <= config.MAX_POSITIONS_MAX):
            await update.effective_chat.send_message(f"حداکثر پوزیشن باید بین {config.MAX_POSITIONS_MIN} تا {config.MAX_POSITIONS_MAX} باشد.")
            return
        self.storage.update_settings(max_positions=int(value))
        await update.effective_chat.send_message(f"✅ حداکثر پوزیشن روی {value} تنظیم شد.\n\n" + self._panel_text(), reply_markup=self._panel_keyboard())

    async def stats_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_chat.send_message(self.stats.summary_text())

    async def reset_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.stats.reset()
        await update.effective_chat.send_message("✅ آمار ریست شد.")

    async def delete_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.stats.delete_all()
        await update.effective_chat.send_message("🗑 آمار و وضعیت ذخیره‌شده حذف شد.")

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

    def run_polling(self, post_init=None) -> None:
        if post_init is not None:
            self.app.post_init = post_init
        self.app.run_polling(close_loop=False)

    @staticmethod
    def _first_number(args: list[str]) -> float | None:
        if not args:
            return None
        try:
            return float(args[0])
        except ValueError:
            return None

    @staticmethod
    def _first_int(args: list[str]) -> int | None:
        if not args:
            return None
        try:
            return int(args[0])
        except ValueError:
            return None
