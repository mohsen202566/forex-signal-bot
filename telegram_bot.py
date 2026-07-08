"""پنل تلگرام ریشه‌ای؛ دستورات و آپشن‌های اصلی حفظ شده‌اند."""
from __future__ import annotations

import asyncio
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import config
from engine import BotEngine
from state import BotState
from toobit_client import ToobitClient
from trade_manager import TradeManager
from okx_client import OKXClient
from symbol_registry import default_symbols_text
from utils import is_admin, logger

engine: BotEngine | None = None
admin_chat_ids: set[int] = set()


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 وضعیت", callback_data="status"), InlineKeyboardButton("🔎 اسکن", callback_data="scan")],
        [InlineKeyboardButton("🟢 نرمال", callback_data="mode_normal"), InlineKeyboardButton("🔴 واقعی", callback_data="mode_real")],
        [InlineKeyboardButton("▶️ ترید روشن", callback_data="trade_on"), InlineKeyboardButton("⏸ ترید خاموش", callback_data="trade_off")],
        [InlineKeyboardButton("📌 فعال‌ها", callback_data="active"), InlineKeyboardButton("✅ آمار", callback_data="results")],
        [InlineKeyboardButton("💰 موجودی", callback_data="balance"), InlineKeyboardButton("🔗 چک ارزها", callback_data="validate_symbols")],
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
        "دستورات فارسی روان:\n"
        "منو | راهنما | وضعیت\n"
        "نرمال | واقعی\n"
        "ترید روشن | ترید خاموش | ترید\n"
        "اسکن\n"
        "فعال | موجودی | سود | پوزیشن\n"
        "آمار یا آمار 30 | حذف آمار\n"
        "ارزها | کوین‌ها | چک ارزها | ریست ارزها\n"
        "افزودن BTCUSDT | حذف BTCUSDT\n"
        "ترید دلار 6\n"
        "ترید لوریج 10\n"
        "حداکثر پوزیشن 3\n\n"
        "دستورات انگلیسی قبلی هم برای سازگاری فعال هستند: /start /menu /status /scan /results"
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
    real_on = state.mode == "REAL" and state.trading_enabled and bool(config.REAL_TRADING_ENABLED)
    real_text = "روشن ✅" if real_on else "خاموش ⛔"
    signal_text = "فعال ✅" if config.SEND_SIGNAL_MESSAGES else "خاموش ⛔"
    free_slots = max(0, int(state.max_active_trades) - (engine.manager.active_count() if engine else 0))
    active_real = 0
    try:
        from state import load_active_trades
        active_real = sum(1 for t in load_active_trades() if str(t.get("mode")) == "REAL")
    except Exception:
        active_real = 0
    return (
        "⚙️ وضعیت ربات 5M اسکلپ\n\n"
        f"💹 ترید واقعی: {real_text}\n"
        f"📡 اتو سیگنال: {signal_text}\n"
        f"💰 مارجین توبیت: نامشخص\n"
        f"💵 دلار هر پوزیشن: USDT {float(state.trade_amount_usdt):.2f}\n"
        f"📈 لوریج: {int(state.leverage)}x\n"
        f"🎯 حداکثر پوزیشن: {int(state.max_active_trades)}\n"
        f"📌 پوزیشن Real فعال: {active_real}\n"
        f"🟢 اسلات آزاد: {free_slots}\n"
        f"💵 سرمایه مجاز ربات: USDT {float(state.trade_amount_usdt) * int(state.max_active_trades):.2f}\n"
        f"🧾 کارمزد رفت‌وبرگشت ثابت: USDT {float(getattr(config, 'FIXED_ROUNDTRIP_FEE_USDT', 0.05)):.2f}\n"
        f"✅ حداقل سود خالص: USDT {float(getattr(config, 'MIN_NET_PROFIT_USDT', 0.01)):.2f}\n"
        f"📐 RR اسکالپ: {float(state.default_rr):.1f}\n"
        "🎯 ورود: DIFT-5M Trap Hunt ✅\n\n"
        "دستورات:\n"
        "ترید فعال | ترید خاموش\n"
        "ترید دلار 10 | ترید لوریج 10 | حداکثر پوزیشن 3\n"
        "سرمایه ترید 100 | حداقل سود خالص 0.01\n"
        "آمار | حذف آمار | سیگنال | پوزیشن | کوین‌ها | وضعیت"
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


async def results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    limit = 30
    if context.args:
        try:
            limit = max(1, min(30, int(context.args[0])))
        except Exception:
            pass
    tm = TradeManager(OKXClient())
    await update.message.reply_text(tm.format_recent_results(limit))


async def validate_symbols_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    assert engine is not None
    report = await engine.validate_symbols_once(force=True)
    if report is None:
        await update.message.reply_text("اعتبارسنجی انجام نشد؛ لاگ را چک کن.")
        return
    await update.message.reply_text(report.short_text())


async def reset_symbols(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    state = BotState.load()
    state.symbols = list(config.DEFAULT_SYMBOLS_35)
    state.save()
    if engine is not None:
        engine.symbol_report = None
        engine.valid_symbols = set()
    await update.message.reply_text(
        f"لیست نمادها به ۳۵ ارز پیش‌فرض برگشت:\n{default_symbols_text()}",
        reply_markup=menu_keyboard(),
    )


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


def _text_number(parts: list[str]) -> str | None:
    for part in reversed(parts):
        t = part.strip().replace("٬", "").replace(",", "")
        if t.replace(".", "", 1).isdigit():
            return t
    return None


async def set_max_positions_text(update: Update, context: ContextTypes.DEFAULT_TYPE, value: int | None = None) -> None:
    if not guard(update):
        return
    state = BotState.load()
    if value is None:
        await update.message.reply_text(f"حداکثر پوزیشن فعلی: {state.max_active_trades}", reply_markup=menu_keyboard())
        return
    state.max_active_trades = max(1, min(20, int(value)))
    state.save()
    await update.message.reply_text(f"حداکثر پوزیشن تنظیم شد: {state.max_active_trades}", reply_markup=menu_keyboard())




async def clear_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    from pathlib import Path
    for name in (config.SIGNALS_FILE, config.RESULTS_FILE, config.TRADE_HISTORY_FILE):
        try:
            Path(name).unlink(missing_ok=True)
        except Exception:
            pass
    await update.message.reply_text("✅ آمار و نتایج قبلی حذف شد؛ سود/ضرر کل و امروز از این لحظه دوباره محاسبه می‌شود.", reply_markup=menu_keyboard())

async def persian_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not guard(update):
        return
    raw = (update.message.text or "").strip()
    text = " ".join(raw.replace("/", " ").split()).lower()
    parts = text.split()

    if text in {"منو", "پنل"}:
        await menu(update, context); return
    if text in {"راهنما", "کمک", "دستورات"}:
        await help_cmd(update, context); return
    if text in {"وضعیت", "تنظیمات"}:
        await status(update, context); return
    if text in {"نرمال", "حالت نرمال", "normal"}:
        await set_normal(update, context); return
    if text in {"واقعی", "حالت واقعی", "ریل", "real"}:
        await set_real(update, context); return

    if text in {"ترید روشن", "ترید فعال", "روشن کردن ترید", "اجرای روشن", "trade on"}:
        await trade_on(update, context); return
    if text in {"ترید خاموش", "ترید غیرفعال", "خاموش کردن ترید", "اجرای خاموش", "trade off"}:
        await trade_off(update, context); return
    if text == "ترید":
        await status(update, context); return

    if text in {"اسکن", "سیگنال", "اسکن دستی"}:
        await scan(update, context); return
    if text in {"حذف آمار", "پاک کردن آمار", "ریست آمار", "آمار حذف"}:
        await clear_stats(update, context); return
    if text in {"فعال", "معاملات فعال", "پوزیشن فعال"}:
        await active(update, context); return
    if text in {"موجودی", "بالانس"}:
        await balance(update, context); return
    if text in {"سود", "پی ان ال", "pnl"}:
        await pnl(update, context); return
    if text in {"پوزیشن", "پوزیشن ها", "پوزیشن‌ها"}:
        await positions(update, context); return
    if text in {"ارزها", "کوین ها", "کوین‌ها", "لیست ارزها", "نمادها"}:
        await symbols(update, context); return
    if text in {"چک ارزها", "اعتبارسنجی", "اعتبارسنجی ارزها"}:
        await validate_symbols_cmd(update, context); return
    if text in {"ریست ارزها", "ریست نمادها"}:
        await reset_symbols(update, context); return

    if parts and parts[0] == "آمار":
        n = _text_number(parts)
        context.args = [n] if n else []
        await results(update, context); return

    if text.startswith("ترید دلار") or text.startswith("دلار "):
        n = _text_number(parts)
        if not n:
            await update.message.reply_text("مثال درست: ترید دلار 6")
            return
        context.args = [n]
        await set_amount(update, context); return

    if text.startswith("ترید لوریج") or text.startswith("لوریج ") or text.startswith("اهرم "):
        n = _text_number(parts)
        if not n:
            await update.message.reply_text("مثال درست: ترید لوریج 10")
            return
        context.args = [n]
        await set_leverage(update, context); return

    if text.startswith("حداکثر پوزیشن") or text.startswith("حداکثر معامله"):
        n = _text_number(parts)
        await set_max_positions_text(update, context, int(float(n)) if n else None)
        return

    if text.startswith("افزودن ") or text.startswith("اضافه "):
        sym = parts[-1].upper()
        context.args = [sym]
        await add_symbol(update, context); return
    if text.startswith("حذف "):
        sym = parts[-1].upper()
        context.args = [sym]
        await remove_symbol(update, context); return

    await update.message.reply_text("دستور شناخته نشد. برای لیست دستورها بنویس: راهنما", reply_markup=menu_keyboard())


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
    elif data == "results": await results(dummy, context)  # type: ignore[arg-type]
    elif data == "balance": await balance(dummy, context)  # type: ignore[arg-type]
    elif data == "validate_symbols": await validate_symbols_cmd(dummy, context)  # type: ignore[arg-type]


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
    app.add_handler(CommandHandler("results", results))
    app.add_handler(CommandHandler("validate_symbols", validate_symbols_cmd))
    app.add_handler(CommandHandler("reset_symbols", reset_symbols))
    app.add_handler(CommandHandler("symbols", symbols))
    app.add_handler(CommandHandler("add", add_symbol))
    app.add_handler(CommandHandler("remove", remove_symbol))
    app.add_handler(CommandHandler("set_amount", set_amount))
    app.add_handler(CommandHandler("set_leverage", set_leverage))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("clear_stats", clear_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, persian_text))
    app.add_handler(CallbackQueryHandler(callback))
    return app


async def post_init(app: Application) -> None:
    global engine
    engine = BotEngine(notify=notify_admins)
    if config.VALIDATE_SYMBOLS_ON_START:
        asyncio.create_task(engine.validate_symbols_once(force=True))
    asyncio.create_task(engine.scan_loop(config.SCAN_INTERVAL_SECONDS))
    asyncio.create_task(engine.monitor_loop(config.RESULT_CHECK_INTERVAL_SECONDS))


def run() -> None:
    app = build_application()
    app.post_init = post_init
    app.run_polling(close_loop=False)
