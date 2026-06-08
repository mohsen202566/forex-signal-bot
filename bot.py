# -*- coding: utf-8 -*-
import asyncio
import logging
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
from forex_pairs import PAIR_DISPLAY_NAMES, normalize_pair
from news_engine import format_news_message
from statistics import format_stats, parse_days, reset_stats
from tracker import (
    add_active_signal,
    check_active_signals,
    format_active_signals,
    make_signal_id,
    parse_signal_from_result,
    parse_signal_from_text,
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
LAST_AUTO_SIGNALS = {}

def direction_fa(direction: str):
    return {"BUY": "صعودی / خرید", "SELL": "نزولی / فروش", "NEUTRAL": "خنثی / نامشخص"}.get(direction, direction)

def status_fa(status: str):
    return {
        "SIGNAL": "✅ سیگنال فعال",
        "PREDICTION_ONLY": "🔎 فقط پیش‌بینی؛ ورود هنوز کامل نیست",
        "NO_TRADE": "⏸ بدون معامله",
        "NEWS_BLOCKED": "⛔ مسدود به خاطر ریسک خبر",
    }.get(status, status)

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
            tf_lines.append(f"{name}: RSI {item.get('rsi')} | ADX {item.get('adx')} | EMA50 {item.get('ema50')} | EMA200 {item.get('ema200')}")
    tf_text = "\n".join(tf_lines) if tf_lines else "داده تایم‌فریم‌ها کامل نیست."

    signal_id = None
    if result.get("status") == "SIGNAL":
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

    if result.get("entry") is not None:
        lines.extend([
            "",
            "🎯 سطوح معامله:",
            f"Entry: {result['entry']}",
            f"SL: {result['stop_loss']}",
            f"TP1: {result['tp1']}",
            f"TP2: {result['tp2']}",
        ])
    else:
        lines.extend(["", "🎯 Entry / SL / TP فعال نیست چون جهت یا ورود هنوز کامل نیست."])

    lines.extend([
        "",
        "📰 هشدار خبر:",
        f"ریسک: {news.get('risk_level', 'LOW')} | اثر: فقط هشدار، سیگنال بلاک نمی‌شود",
        news.get("note", ""),
    ])

    if signal_id:
        lines.extend(["", f"شناسه: {signal_id}", "برای زیر نظر گرفتن، روی همین پیام ریپلای کن و بنویس: زیر نظر بگیر"])

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
طلا
نقره
نفت
نفت برنت
یورو دلار
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

async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await deny(update)
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("مثال:\n/adduser 123456789")
        return
    add_user(int(context.args[0]))
    await update.message.reply_text("✅ کاربر اضافه شد.")

async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await deny(update)
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("مثال:\n/removeuser 123456789")
        return
    remove_user(int(context.args[0]))
    await update.message.reply_text("✅ کاربر حذف شد.")

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
    results = sorted(results, key=lambda x: (x.get("status") == "SIGNAL", x.get("prediction_score", 0), x.get("entry_score", 0)), reverse=True)
    lines = ["🔥 بهترین فرصت‌های فعلی:", ""]
    for i, r in enumerate(results[:BEST_SIGNAL_COUNT], start=1):
        lines.append(f"{i}. {r['symbol']} | {direction_fa(r['direction'])} | پیش‌بینی {r['prediction_score']}/100 | ورود {r.get('entry_score', 0)}/100 | {status_fa(r['status'])}")
        if r.get("entry") is not None:
            lines.append(f"   Entry: {r['entry']} | SL: {r['stop_loss']} | TP1: {r['tp1']}")
    await update.message.reply_text("\n".join(lines))

async def market_overview(update: Update):
    await update.message.reply_text("⏳ در حال بررسی سریع بازار...")

    results = []
    failed = 0

    for pair in FOREX_PAIRS:
        try:
            r = run_analysis(pair)
            if r.get("success"):
                results.append(r)
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.warning("Market overview failed for %s: %s", pair, e)

    if not results:
        await update.message.reply_text("❌ بررسی بازار ناموفق بود.")
        return

    total = len(results)
    bullish = sum(1 for r in results if r.get("direction") == "BUY")
    bearish = sum(1 for r in results if r.get("direction") == "SELL")
    neutral = sum(1 for r in results if r.get("direction") == "NEUTRAL")

    bullish_pct = round((bullish / total) * 100)
    bearish_pct = round((bearish / total) * 100)
    neutral_pct = round((neutral / total) * 100)

    if neutral_pct >= 50:
        if bearish > bullish:
            mood = "بازار بیشتر رنج است، اما تمایل نزولی دارد."
            advice = "سیگنال‌های فروش اعتبار بیشتری دارند، ولی چون بازار رنج است باید با احتیاط وارد شد."
        elif bullish > bearish:
            mood = "بازار بیشتر رنج است، اما تمایل صعودی دارد."
            advice = "سیگنال‌های خرید اعتبار بیشتری دارند، ولی چون بازار رنج است باید با احتیاط وارد شد."
        else:
            mood = "بازار عمدتاً رنج و بدون جهت قوی است."
            advice = "فعلاً بهتر است فقط سیگنال‌های خیلی قوی بررسی شوند."
    elif bearish > bullish:
        mood = "قدرت نزولی بازار بیشتر است."
        advice = "سیگنال‌های فروش اعتبار بیشتری دارند."
    elif bullish > bearish:
        mood = "قدرت صعودی بازار بیشتر است."
        advice = "سیگنال‌های خرید اعتبار بیشتری دارند."
    else:
        mood = "بازار متعادل و بدون برتری واضح است."
        advice = "بهتر است تا شکل‌گیری جهت واضح‌تر صبر شود."

    lines = [
        "🌍 بررسی سریع بازار",
        "",
        f"تعداد نمادهای بررسی‌شده: {total}",
    ]

    if failed:
        lines.append(f"نمادهای بدون دیتای موفق: {failed}")

    lines.extend([
        "",
        f"🟢 صعودی: {bullish} نماد / {bullish_pct}٪",
        f"🔴 نزولی: {bearish} نماد / {bearish_pct}٪",
        f"⚪ رنج/خنثی: {neutral} نماد / {neutral_pct}٪",
        "",
        f"📌 جمع‌بندی: {mood}",
        f"⚠️ نتیجه: {advice}",
        "",
        "نمادهای قوی‌تر:",
    ])

    sorted_results = sorted(
        results,
        key=lambda r: r.get("prediction_score", 0),
        reverse=True,
    )

    for r in sorted_results[:10]:
        symbol = r.get("symbol")
        display = get_pair_display_name(symbol)
        lines.append(
            f"• {display} ({symbol}): {direction_fa(r.get('direction'))} | امتیاز {r.get('prediction_score')}/100"
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
    await update.message.reply_text(f"👁 سیگنال {signal['symbol']} زیر نظر گرفته شد.\nشناسه: {signal['signal_id']}" if added else "این سیگنال قبلاً زیر نظر گرفته شده بود.")

async def check_tracker_events(app: Application):
    try:
        if not OWNER_ID:
            return
        events = check_active_signals()
        for ev in events:
            s = ev["signal"]
            res = "✅ TP1 خورد" if ev["result"] == "TP1" else "❌ SL خورد"
            await app.bot.send_message(chat_id=OWNER_ID, text=f"{res}\n{s.get('symbol')} | قیمت فعلی: {ev['price']}\nشناسه: {s.get('signal_id')}")
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
                    if r.get("status") == "SIGNAL" and r.get("prediction_score", 0) >= AUTO_SIGNAL_SCORE:
                        signal = parse_signal_from_result(r)
                        if signal:
                            r["signal_id"] = signal["signal_id"]
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

        if "راهنما" in text_lower:
            await start(update, context)
            return
        if "بهترین سیگنال" in text_lower:
            await best_signal(update)
            return
        if text_lower in ("بررسی", "بررسی بازار", "وضعیت بازار", "وضعیت"):
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

        await update.message.reply_text("متوجه نشدم. بنویس مثلا:\nتحلیل یورو دلار\nسیگنال طلا\nبهترین سیگنال\nبررسی بازار\nاخبار امروز\nآمار")
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
