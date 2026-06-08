# -*- coding: utf-8 -*-
import asyncio
import logging
import re
import time
import traceback

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from access_control import add_user, is_allowed, is_owner, list_users_text, remove_user
from analysis import analyze_pair as run_analysis
from config import (
    AUTO_SCAN_INTERVAL_MINUTES,
    AUTO_SIGNAL_COOLDOWN_MINUTES,
    AUTO_SIGNAL_ENABLED,
    AUTO_SIGNAL_SCORE,
    BEST_SIGNAL_COUNT,
    BOT_TOKEN,
    FOREX_PAIRS,
    OWNER_ID,
)
from forex_pairs import normalize_pair
from news_engine import format_news_message
from statistics import format_stats, parse_days, reset_stats
from tracker import (
    add_active_signal,
    check_active_signals,
    format_active_signals,
    make_signal_id,
    parse_signal_from_text,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

LAST_AUTO_SIGNALS = {}


def direction_fa(direction: str):
    return {
        "BUY": "صعودی / خرید",
        "SELL": "نزولی / فروش",
        "NEUTRAL": "خنثی / نامشخص",
    }.get(direction, direction)


def status_fa(status: str):
    return {
        "SIGNAL": "✅ سیگنال فعال",
        "PREDICTION_ONLY": "🔎 فقط پیش‌بینی",
        "NO_TRADE": "⏸ بدون معامله",
        "NEWS_BLOCKED": "⛔ مسدود به خاطر خبر",
    }.get(status, status)


def is_valid_trade_signal(result: dict) -> bool:
    return (
        result.get("status") == "SIGNAL"
        and result.get("entry") is not None
        and result.get("stop_loss") is not None
        and result.get("tp1") is not None
    )


def ensure_access(update: Update):
    user = update.effective_user
    if not user:
        return False
    return is_allowed(user.id)


def format_analysis(result: dict) -> str:
    reasons = "\n".join([f"• {r}" for r in result.get("reasons", [])]) or "• دلیل خاصی ثبت نشد."
    entry_reasons = "\n".join([f"• {r}" for r in result.get("entry_reasons", [])]) or "• تریگر ورود هنوز کامل نیست."

    news = result.get("news", {})
    tf = result.get("tf_summary", {})

    tf_lines = []
    for name in ["4H", "1H", "15M", "5M"]:
        item = tf.get(name, {})
        if item:
            tf_lines.append(
                f"{name}: RSI {item.get('rsi')} | ADX {item.get('adx')} | "
                f"EMA50 {item.get('ema50')} | EMA200 {item.get('ema200')}"
            )

    tf_text = "\n".join(tf_lines) if tf_lines else "داده تایم‌فریم‌ها کامل نیست."

    signal_id = None
    if is_valid_trade_signal(result):
        signal_id = make_signal_id(result["symbol"])
        result["signal_id"] = signal_id

    lines = [
        f"📊 تحلیل {result['symbol']}",
        "",
        f"💰 قیمت فعلی: {result['price']}",
        f"📍 جهت پیش‌بینی: {direction_fa(result['direction'])}",
        f"⭐ امتیاز پیش‌بینی: {result['prediction_score']} / 100",
        f"🟢 امتیاز خرید: {result['buy_score']}",
        f"🔴 امتیاز فروش: {result['sell_score']}",
        f"⚙️ وضعیت: {status_fa(result['status'])}",
        "",
        "🧭 خلاصه تایم‌فریم‌ها:",
        tf_text,
        "",
        "🧠 دلایل پیش‌بینی:",
        reasons,
        "",
        "⚡ وضعیت ورود سریع 5M:",
        f"امتیاز ورود: {result.get('entry_score', 0)} / 100",
        entry_reasons,
    ]

    if is_valid_trade_signal(result):
        lines.extend([
            "",
            "🎯 سطوح معامله:",
            f"Entry: {result['entry']}",
            f"SL: {result['stop_loss']}",
            f"TP1: {result['tp1']}",
            f"TP2: {result.get('tp2', '')}",
            "",
            f"شناسه: {signal_id}",
            "برای زیر نظر گرفتن، روی همین پیام ریپلای کن و بنویس: زیر نظر بگیر",
        ])
    else:
        lines.extend([
            "",
            "❌ این تحلیل هنوز سیگنال قابل ورود نیست.",
            "Entry / SL / TP فعال نیست.",
        ])

    lines.extend([
        "",
        "📰 وضعیت خبر:",
        f"ریسک: {news.get('risk_level', 'LOW')} | بلاک: {'بله' if news.get('blocked') else 'خیر'}",
        news.get("note", ""),
    ])

    return "\n".join(lines)


async def deny(update: Update):
    user_id = update.effective_user.id if update.effective_user else "نامشخص"
    await update.message.reply_text(
        f"⛔ دسترسی شما مجاز نیست.\nآیدی شما: {user_id}\nمالک ربات باید این آیدی را اضافه کند."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not OWNER_ID:
        await update.message.reply_text(f"⚠️ OWNER_ID روی VPS تنظیم نشده است.\nآیدی شما: {user_id}")
        return

    if not ensure_access(update):
        await deny(update)
        return

    msg = f"""
سلام 👋
ربات تحلیل و پیش‌بینی فارکس فعال است.

آیدی شما: {user_id}

دستورها:
تحلیل یورو دلار
سیگنال طلا
بهترین سیگنال
بررسی بازار
اخبار امروز
آمار
آمار 7 روز
حذف آمار
سیگنال‌های فعال
زیر نظر بگیر  ← با ریپلای روی سیگنال
/id

دستورات مالک:
/adduser USER_ID
/removeuser USER_ID
/listusers

اتو سیگنال: {'فعال' if AUTO_SIGNAL_ENABLED else 'غیرفعال'}
حداقل امتیاز اتو سیگنال: {AUTO_SIGNAL_SCORE}
"""
    await update.message.reply_text(msg)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"آیدی تلگرام شما:\n{update.effective_user.id}")


def extract_user_id_from_text(text: str):
    match = re.search(r"\b\d{5,15}\b", text or "")
    return int(match.group(0)) if match else None


async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await deny(update)
        return

    user_id = extract_user_id_from_text(update.message.text)

    if not user_id:
        await update.message.reply_text("مثال:\n/adduser 123456789")
        return

    add_user(user_id)
    await update.message.reply_text(f"✅ کاربر اضافه شد.\nآیدی: {user_id}\n\n{list_users_text()}")


async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await deny(update)
        return

    user_id = extract_user_id_from_text(update.message.text)

    if not user_id:
        await update.message.reply_text("مثال:\n/removeuser 123456789")
        return

    if int(user_id) == int(OWNER_ID):
        await update.message.reply_text("⛔ مالک ربات قابل حذف نیست.")
        return

    remove_user(user_id)
    await update.message.reply_text(f"✅ کاربر حذف شد.\nآیدی: {user_id}\n\n{list_users_text()}")


async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await deny(update)
        return

    await update.message.reply_text(list_users_text())


async def send_analysis(update: Update, pair: str):
    await update.message.reply_text(f"⏳ در حال تحلیل {pair}...")

    result = run_analysis(pair)

    if not result.get("success"):
        await update.message.reply_text(f"❌ خطا در تحلیل {pair}\n\n{result.get('error')}")
        return

    await update.message.reply_text(format_analysis(result))


async def best_signal(update: Update):
    await update.message.reply_text("⏳ در حال بررسی بهترین سیگنال‌ها...")

    results = []

    for pair in FOREX_PAIRS:
        r = run_analysis(pair)
        if r.get("success"):
            results.append(r)

    if not results:
        await update.message.reply_text("❌ هیچ تحلیلی دریافت نشد.")
        return

    valid_signals = [r for r in results if is_valid_trade_signal(r)]

    valid_signals = sorted(
        valid_signals,
        key=lambda x: (
            x.get("prediction_score", 0),
            x.get("entry_score", 0),
        ),
        reverse=True,
    )

    if not valid_signals:
        await update.message.reply_text("❌ فعلاً سیگنالی نیست.")
        return

    for i, r in enumerate(valid_signals[:BEST_SIGNAL_COUNT], start=1):
        signal_id = make_signal_id(r["symbol"])
        r["signal_id"] = signal_id

        lines = [
            f"🔥 سیگنال قابل ورود #{i}",
            "",
            f"نماد: {r['symbol']}",
            f"📍 جهت: {direction_fa(r['direction'])}",
            f"⭐ پیش‌بینی: {r['prediction_score']} / 100",
            f"⚡ ورود: {r.get('entry_score', 0)} / 100",
            f"⚙️ وضعیت: {status_fa(r['status'])}",
            "",
            "🎯 سطوح معامله:",
            f"Entry: {r['entry']}",
            f"SL: {r['stop_loss']}",
            f"TP1: {r['tp1']}",
            f"TP2: {r.get('tp2', '')}",
            "",
            f"شناسه: {signal_id}",
            "برای زیر نظر گرفتن، روی همین پیام ریپلای کن و بنویس: زیر نظر بگیر",
        ]

        await update.message.reply_text("\n".join(lines))


async def market_overview(update: Update):
    await update.message.reply_text("⏳ در حال بررسی بازار...")

    results = []

    for pair in FOREX_PAIRS:
        r = run_analysis(pair)
        if r.get("success"):
            results.append(r)

    if not results:
        await update.message.reply_text("❌ بررسی بازار ناموفق بود.")
        return

    buy = sum(1 for r in results if r["direction"] == "BUY")
    sell = sum(1 for r in results if r["direction"] == "SELL")
    neutral = sum(1 for r in results if r["direction"] == "NEUTRAL")

    mood = "بازار بیشتر صعودی است" if buy > sell else (
        "بازار بیشتر نزولی است" if sell > buy else "بازار متعادل/رنج است"
    )

    lines = [
        "🌍 بررسی کلی بازار فارکس",
        "",
        f"🟢 خرید: {buy}",
        f"🔴 فروش: {sell}",
        f"⚪ خنثی: {neutral}",
        f"📌 جمع‌بندی: {mood}",
        "",
    ]

    for r in results:
        lines.append(
            f"• {r['symbol']}: {direction_fa(r['direction'])} | "
            f"امتیاز {r['prediction_score']}/100 | {status_fa(r['status'])}"
        )

    await update.message.reply_text("\n".join(lines))


async def watch_signal(update: Update):
    reply = update.message.reply_to_message

    if not reply or not reply.text:
        await update.message.reply_text("برای زیر نظر گرفتن، روی پیام سیگنال ریپلای کن و بنویس: زیر نظر بگیر")
        return

    signal = parse_signal_from_text(reply.text)

    if not signal:
        await update.message.reply_text("❌ نتونستم Entry/SL/TP سیگنال رو بخونم.")
        return

    added = add_active_signal(signal)

    if added:
        await update.message.reply_text(
            f"👁 سیگنال {signal['symbol']} زیر نظر گرفته شد.\nشناسه: {signal['signal_id']}"
        )
    else:
        await update.message.reply_text("این سیگنال قبلاً زیر نظر گرفته شده بود.")


async def check_tracker_events(app: Application):
    try:
        if not OWNER_ID:
            return

        events = check_active_signals()

        for ev in events:
            s = ev["signal"]
            res = "✅ TP1 خورد" if ev["result"] == "TP1" else "❌ SL خورد"

            await app.bot.send_message(
                chat_id=OWNER_ID,
                text=f"{res}\n{s.get('symbol')} | قیمت فعلی: {ev['price']}\nشناسه: {s.get('signal_id')}",
            )

    except Exception as e:
        logger.warning("Tracker check failed: %s", e)


async def auto_signal_loop(app: Application):
    await asyncio.sleep(10)

    while True:
        try:
            await check_tracker_events(app)

            if AUTO_SIGNAL_ENABLED and OWNER_ID:
                now = time.time()

                for pair in FOREX_PAIRS:
                    last_ts = LAST_AUTO_SIGNALS.get(pair, 0)

                    if now - last_ts < AUTO_SIGNAL_COOLDOWN_MINUTES * 60:
                        continue

                    r = run_analysis(pair)

                    if not r.get("success"):
                        continue

                    if is_valid_trade_signal(r) and r.get("prediction_score", 0) >= AUTO_SIGNAL_SCORE:
                        text = "🚨 اتو سیگنال فارکس\n\n" + format_analysis(r)

                        await app.bot.send_message(chat_id=OWNER_ID, text=text)

                        LAST_AUTO_SIGNALS[pair] = now

            await asyncio.sleep(max(60, AUTO_SCAN_INTERVAL_MINUTES * 60))

        except Exception as e:
            logger.error("Auto signal loop error: %s\n%s", e, traceback.format_exc())
            await asyncio.sleep(60)


async def post_init(app: Application):
    app.create_task(auto_signal_loop(app))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not ensure_access(update):
            await deny(update)
            return

        text = update.message.text.strip()
        text_lower = text.lower()

        if (
            text_lower.startswith(("adduser", "add user"))
            or "افزودن کاربر" in text_lower
            or "اضافه کردن کاربر" in text_lower
            or "اد کردن کاربر" in text_lower
        ):
            await add_user_command(update, context)
            return

        if (
            text_lower.startswith(("removeuser", "remove user"))
            or "حذف کاربر" in text_lower
            or "پاک کردن کاربر" in text_lower
        ):
            await remove_user_command(update, context)
            return

        if "لیست کاربران" in text_lower or "کاربران مجاز" in text_lower:
            await list_users_command(update, context)
            return

        if "راهنما" in text_lower:
            await start(update, context)
            return

        if "بهترین سیگنال" in text_lower:
            await best_signal(update)
            return

        if "بررسی بازار" in text_lower or "وضعیت بازار" in text_lower:
            await market_overview(update)
            return

        if "اخبار" in text_lower:
            await update.message.reply_text(format_news_message())
            return

        if "حذف آمار" in text_lower or "ریست آمار" in text_lower:
            reset_stats()
            await update.message.reply_text("🗑 آمار سیگنال‌ها حذف شد.")
            return

        if "آمار" in text_lower:
            await update.message.reply_text(format_stats(parse_days(text_lower)))
            return

        if "سیگنال‌های فعال" in text_lower or "سیگنال های فعال" in text_lower:
            await update.message.reply_text(format_active_signals())
            return

        if "زیر نظر" in text_lower or text_lower == "نظر":
            await watch_signal(update)
            return

        pair = normalize_pair(text)

        if pair:
            await send_analysis(update, pair)
            return

        await update.message.reply_text(
            "متوجه نشدم. بنویس مثلا:\n"
            "تحلیل یورو دلار\n"
            "سیگنال طلا\n"
            "بهترین سیگنال\n"
            "بررسی بازار\n"
            "اخبار امروز\n"
            "آمار"
        )

    except Exception as e:
        logger.error("Unhandled error: %s\n%s", e, traceback.format_exc())
        await update.message.reply_text(f"❌ خطای داخلی ربات رخ داد:\n{e}")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN تنظیم نشده است.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("adduser", add_user_command))
    app.add_handler(CommandHandler("removeuser", remove_user_command))
    app.add_handler(CommandHandler("listusers", list_users_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Forex bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
