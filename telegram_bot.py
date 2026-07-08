"""پنل تلگرام ریشه‌ای؛ دستورات و آپشن‌های اصلی حفظ شده‌اند."""
from __future__ import annotations

import asyncio
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import config
from engine import BotEngine
from state import BotState
from toobit_client import ToobitClient
from trade_manager import TradeManager
from okx_client import OKXClient
from utils import is_admin, logger

engine: BotEngine | None = None
admin_chat_ids: set[int] = set()


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Status", callback_data="status"), InlineKeyboardButton("🔎 Scan", callback_data="scan")],
        [InlineKeyboardButton("🟢 Normal", callback_data="mode_normal"), InlineKeyboardButton("🔴 Real", callback_data="mode_real")],
        [InlineKeyboardButton("▶️ Trade ON", callback_data="trade_on"), InlineKeyboardButton("⏸ Trade OFF", callback_data="trade_off")],
        [InlineKeyboardButton("📌 Active", callback_data="active"), InlineKeyboardButton("💰 Balance", callback_data="balance")],
    ])


async def notify_admins(text: str) -> None:
    app = getattr(notify_admins, "app", None)
    if not app:
        return
    targets = admin_chat_ids or set(config.TELEGRAM_ADMIN_IDS)
    for chat_id in targets:
        try:
            await app.bot.send_message(chat_id=chat_id, text=text)
        except Exception as exc:
            logger.warning("ارسال پیام تلگرام ناموفق بود: %s", exc)


def guard(update: Update) -> bool:
    user = update.effective_user
    return is_admin(user.id if user else None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    if update.effective_chat:
        admin_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text(
        "ربات DIFT-5M آماده است.\n"
        "دیتا و سیگنال از OKX است؛ اجرای واقعی و نتیجه واقعی فقط با Toobit انجام می‌شود.\n"
        "سیستم امتیازی نیست؛ همه قفل‌ها باید پاس شوند.",
        reply_markup=menu_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    text = (
        "دستورات:\n"
        "/start /menu /help\n"
        "/status وضعیت ربات\n"
        "/normal حالت نرمال\n"
        "/real حالت واقعی\n"
        "/trade_on روشن کردن اجرای حالت فعلی\n"
        "/trade_off خاموش کردن اجرا، فقط ثبت سیگنال\n"
        "/scan اسکن دستی\n"
        "/active معاملات فعال\n"
        "/balance موجودی Toobit\n"
        "/pnl PnL امروز Toobit\n"
        "/positions پوزیشن‌های Toobit\n"
        "/symbols لیست نمادها\n"
        "/add BTCUSDT افزودن نماد\n"
        "/remove BTCUSDT حذف نماد\n"
        "/set_amount 6 تنظیم مارجین هر معامله\n"
        "/set_leverage 10 تنظیم لوریج\n"
        "/settings تنظیمات اصلی"
    )
    await update.message.reply_text(text, reply_markup=menu_keyboard())


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    await update.message.reply_text("پنل:", reply_markup=menu_keyboard())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    state = BotState.load()
    msg = format_status(state)
    await update.message.reply_text(msg, reply_markup=menu_keyboard())


def format_status(state: BotState) -> str:
    return (
        f"Mode: {state.mode}\n"
        f"Trading: {'ON' if state.trading_enabled else 'OFF'}\n"
        f"Symbols: {', '.join(state.symbols)}\n"
        f"Amount: {state.trade_amount_usdt} USDT\n"
        f"Leverage: {state.leverage}x\n"
        f"RR min/default: {state.min_rr}/{state.default_rr}\n"
        f"REAL_TRADING_ENABLED: {config.REAL_TRADING_ENABLED}"
    )


async def set_normal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    state = BotState.load(); state.set_mode("NORMAL")
    await update.message.reply_text("حالت روی NORMAL تنظیم شد.", reply_markup=menu_keyboard())


async def set_real(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    state = BotState.load(); state.set_mode("REAL")
    await update.message.reply_text("حالت روی REAL تنظیم شد. اجرای واقعی فقط وقتی انجام می‌شود که REAL_TRADING_ENABLED=true و /trade_on باشد.", reply_markup=menu_keyboard())


async def trade_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    state = BotState.load(); state.set_trading(True)
    await update.message.reply_text("Trade ON شد.", reply_markup=menu_keyboard())


async def trade_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    state = BotState.load(); state.set_trading(False)
    await update.message.reply_text("Trade OFF شد؛ فقط سیگنال ثبت می‌شود.", reply_markup=menu_keyboard())


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    assert engine is not None
    signals = await engine.scan_once()
    if signals:
        await update.message.reply_text(f"{len(signals)} سیگنال معتبر پیدا شد.")
    else:
        details = "\n".join(f"{s}: {r}" for s, r in list(engine.last_rejections.items())[-10:])
        await update.message.reply_text("سیگنال معتبری نبود.\n" + details)


async def active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    tm = TradeManager(OKXClient())
    await update.message.reply_text(tm.format_active())


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    try:
        b = ToobitClient().get_usdt_balance_summary()
        await update.message.reply_text("Toobit Balance:\n" + "\n".join(f"{k}: {v}" for k, v in b.items()))
    except Exception as exc:
        await update.message.reply_text(f"خطا در خواندن بالانس Toobit: {exc}")


async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    try:
        value = ToobitClient().get_today_pnl()
        await update.message.reply_text(f"Today PnL Toobit: {value}")
    except Exception as exc:
        await update.message.reply_text(f"خطا در خواندن PnL: {exc}")


async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    try:
        rows = ToobitClient().get_positions()
        if not rows:
            await update.message.reply_text("پوزیشن بازی در Toobit پیدا نشد.")
            return
        text = "\n\n".join(str(x)[:900] for x in rows[:10])
        await update.message.reply_text(text)
    except Exception as exc:
        await update.message.reply_text(f"خطا در خواندن پوزیشن‌ها: {exc}")


async def symbols(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    state = BotState.load()
    await update.message.reply_text("Symbols:\n" + ", ".join(state.symbols))


async def add_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    if not context.args:
        await update.message.reply_text("مثال: /add BTCUSDT")
        return
    state = BotState.load(); state.add_symbol(context.args[0])
    await update.message.reply_text("نماد اضافه شد: " + context.args[0].upper())


async def remove_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    if not context.args:
        await update.message.reply_text("مثال: /remove BTCUSDT")
        return
    state = BotState.load(); state.remove_symbol(context.args[0])
    await update.message.reply_text("نماد حذف شد: " + context.args[0].upper())


async def set_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    if not context.args:
        await update.message.reply_text("مثال: /set_amount 6")
        return
    state = BotState.load(); state.trade_amount_usdt = float(context.args[0]); state.save()
    await update.message.reply_text(f"Amount شد: {state.trade_amount_usdt} USDT")


async def set_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    if not context.args:
        await update.message.reply_text("مثال: /set_leverage 10")
        return
    state = BotState.load(); state.leverage = int(context.args[0]); state.save()
    await update.message.reply_text(f"Leverage شد: {state.leverage}x")


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    await update.message.reply_text(format_status(BotState.load()))


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    q = update.callback_query
    await q.answer()
    data = q.data
    fake_msg = q.message
    class Dummy:
        message = fake_msg
        effective_user = update.effective_user
        effective_chat = update.effective_chat
    dummy = Dummy()
    if data == "status": await status(dummy, context)  # type: ignore[arg-type]
    elif data == "scan": await scan(dummy, context)  # type: ignore[arg-type]
    elif data == "mode_normal": await set_normal(dummy, context)  # type: ignore[arg-type]
    elif data == "mode_real": await set_real(dummy, context)  # type: ignore[arg-type]
    elif data == "trade_on": await trade_on(dummy, context)  # type: ignore[arg-type]
    elif data == "trade_off": await trade_off(dummy, context)  # type: ignore[arg-type]
    elif data == "active": await active(dummy, context)  # type: ignore[arg-type]
    elif data == "balance": await balance(dummy, context)  # type: ignore[arg-type]


def build_application() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    setattr(notify_admins, "app", app)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("normal", set_normal))
    app.add_handler(CommandHandler("real", set_real))
    app.add_handler(CommandHandler("trade_on", trade_on))
    app.add_handler(CommandHandler("trade_off", trade_off))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("active", active))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("pnl", pnl))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("symbols", symbols))
    app.add_handler(CommandHandler("add", add_symbol))
    app.add_handler(CommandHandler("remove", remove_symbol))
    app.add_handler(CommandHandler("set_amount", set_amount))
    app.add_handler(CommandHandler("set_leverage", set_leverage))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CallbackQueryHandler(callback))
    return app


async def post_init(app: Application) -> None:
    global engine
    engine = BotEngine(notify=notify_admins)
    asyncio.create_task(engine.loop(config.SCAN_INTERVAL_SECONDS))


def run() -> None:
    app = build_application()
    app.post_init = post_init
    app.run_polling(close_loop=False)
