import logging
import traceback
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from config import BOT_TOKEN, MIN_SIGNAL_SCORE, BEST_SIGNAL_COUNT
from forex_pairs import FOREX_PAIRS, normalize_pair, PAIR_DISPLAY_NAMES
from analysis import analyze_pair as run_analysis
from news_engine import format_news_message
from statistics import format_stats, parse_days, reset_stats
from tracker import add_active_signal, parse_signal_from_text, check_active_signals, format_active_signals, make_signal_id

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def direction_fa(direction: str):
    return {"BUY": "صعودی / خرید", "SELL": "نزولی / فروش", "NEUTRAL": "خنثی / نامشخص"}.get(direction, direction)


def status_fa(status: str):
    return {
        "SIGNAL": "✅ سیگنال فعال",
        "PREDICTION_ONLY": "🔎 فقط پیش‌بینی؛ ورود هنوز کامل نیست",
        "NO_TRADE": "⏸ بدون معامله",
        "NEWS_BLOCKED": "⛔ مسدود به خاطر ریسک خبر",
    }.get(status, status)


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
    tf_text = "\n".join(tf_lines)

    signal_id = None
    if result.get("status") == "SIGNAL":
        signal_id = make_signal_id(result["symbol"])

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
        "📰 وضعیت خبر:",
        f"ریسک: {news.get('risk_level', 'LOW')} | بلاک: {'بله' if news.get('blocked') else 'خیر'}",
        news.get("note", ""),
    ])

    if signal_id:
        lines.extend(["", f"شناسه: {signal_id}"])

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
سلام 👋
ربات تحلیل و پیش‌بینی فارکس فعال است.

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
راهنما

نسخه فعلی:
✅ دیتای واقعی Twelve Data
✅ پیش‌بینی چند تایم‌فریم 4H / 1H / 15M / 5M
✅ Entry Engine سریع 5M
✅ Entry / SL / TP
✅ بهترین سیگنال
✅ آمار و حذف آمار
✅ زیر نظر گرفتن سیگنال تا TP1 یا SL
✅ موتور اخبار محافظه‌کار و آماده اتصال به تقویم زنده
"""
    await update.message.reply_text(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


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
    errors = []
    for pair in FOREX_PAIRS:
        r = run_analysis(pair)
        if r.get("success"):
            results.append(r)
        else:
            errors.append(f"{pair}: {r.get('error')}")
    if not results:
        await update.message.reply_text("❌ هیچ تحلیلی دریافت نشد.\n" + "\n".join(errors[:3]))
        return
    results = sorted(results, key=lambda x: (x.get("status") == "SIGNAL", x.get("prediction_score", 0), x.get("entry_score", 0)), reverse=True)
    lines = ["🔥 بهترین فرصت‌های فعلی:", ""]
    for i, r in enumerate(results[:BEST_SIGNAL_COUNT], start=1):
        lines.append(f"{i}. {r['symbol']} | {direction_fa(r['direction'])} | پیش‌بینی {r['prediction_score']}/100 | ورود {r.get('entry_score', 0)}/100 | {status_fa(r['status'])}")
        if r.get("entry") is not None:
            lines.append(f"   Entry: {r['entry']} | SL: {r['stop_loss']} | TP1: {r['tp1']}")
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
    usd_strength = 0
    for r in results:
        sym = r["symbol"]
        d = r["direction"]
        if sym.endswith("/USD") and d == "SELL":
            usd_strength += 1
        if sym.startswith("USD/") and d == "BUY":
            usd_strength += 1
        if sym == "XAU/USD" and d == "SELL":
            usd_strength += 1
    mood = "بازار بیشتر صعودی است" if buy > sell else ("بازار بیشتر نزولی است" if sell > buy else "بازار متعادل/رنج است")
    lines = [
        "🌍 بررسی کلی بازار فارکس",
        "",
        f"🟢 جهت‌های خرید: {buy}",
        f"🔴 جهت‌های فروش: {sell}",
        f"⚪ خنثی: {neutral}",
        f"📌 جمع‌بندی: {mood}",
        f"💵 قدرت تقریبی دلار از روی نمادها: {usd_strength}/9",
        "",
        "نمادهای بررسی‌شده:",
    ]
    for r in results:
        lines.append(f"• {r['symbol']}: {direction_fa(r['direction'])} | امتیاز {r['prediction_score']}/100 | {status_fa(r['status'])}")
    await update.message.reply_text("\n".join(lines))


async def news_today(update: Update):
    await update.message.reply_text(format_news_message())


async def stats_command(update: Update, text: str):
    days = parse_days(text)
    await update.message.reply_text(format_stats(days))


async def reset_stats_command(update: Update):
    reset_stats()
    await update.message.reply_text("🗑 آمار سیگنال‌ها حذف شد.")


async def watch_signal(update: Update):
    reply = update.message.reply_to_message
    if not reply or not reply.text:
        await update.message.reply_text("برای زیر نظر گرفتن، روی پیام سیگنال ریپلای کن و بنویس: زیر نظر بگیر")
        return
    signal = parse_signal_from_text(reply.text)
    if not signal:
        await update.message.reply_text("❌ نتونستم Entry/SL/TP سیگنال رو از پیام ریپلای‌شده بخونم. فقط سیگنال‌هایی که Entry، SL و TP1 دارند قابل پیگیری هستند.")
        return
    added = add_active_signal(signal)
    if added:
        await update.message.reply_text(f"👁 سیگنال {signal['symbol']} زیر نظر گرفته شد تا TP1 یا SL.\nشناسه: {signal['signal_id']}")
    else:
        await update.message.reply_text("این سیگنال قبلاً زیر نظر گرفته شده بود.")


async def check_tracker_events(update: Update):
    try:
        events = check_active_signals()
        for ev in events:
            s = ev["signal"]
            res = "✅ TP1 خورد" if ev["result"] == "TP1" else "❌ SL خورد"
            await update.message.reply_text(f"{res}\n{ s.get('symbol') } | قیمت فعلی: {ev['price']}\nشناسه: {s.get('signal_id')}")
    except Exception as e:
        logger.warning("Tracker check failed: %s", e)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await check_tracker_events(update)
        text = update.message.text.strip()
        text_lower = text.lower()

        if "راهنما" in text_lower:
            await help_command(update, context)
            return
        if "بهترین سیگنال" in text_lower:
            await best_signal(update)
            return
        if "بررسی بازار" in text_lower or "وضعیت بازار" in text_lower:
            await market_overview(update)
            return
        if "اخبار" in text_lower:
            await news_today(update)
            return
        if "حذف آمار" in text_lower or "ریست آمار" in text_lower:
            await reset_stats_command(update)
            return
        if "آمار" in text_lower:
            await stats_command(update, text_lower)
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
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Forex bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
