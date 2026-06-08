import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from config import BOT_TOKEN
from forex_pairs import FOREX_PAIRS
from analysis import analyze_pair as run_analysis


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)


PAIR_NAMES = {
    "یورو دلار": "EUR/USD",
    "eurusd": "EUR/USD",
    "eur/usd": "EUR/USD",
    "EUR/USD": "EUR/USD",

    "پوند دلار": "GBP/USD",
    "gbpusd": "GBP/USD",
    "gbp/usd": "GBP/USD",
    "GBP/USD": "GBP/USD",

    "دلار ین": "USD/JPY",
    "usdjpy": "USD/JPY",
    "usd/jpy": "USD/JPY",
    "USD/JPY": "USD/JPY",

    "دلار فرانک": "USD/CHF",
    "usdchf": "USD/CHF",
    "usd/chf": "USD/CHF",
    "USD/CHF": "USD/CHF",

    "استرالیا دلار": "AUD/USD",
    "دلار استرالیا": "AUD/USD",
    "audusd": "AUD/USD",
    "aud/usd": "AUD/USD",
    "AUD/USD": "AUD/USD",

    "نیوزیلند دلار": "NZD/USD",
    "دلار نیوزیلند": "NZD/USD",
    "nzdusd": "NZD/USD",
    "nzd/usd": "NZD/USD",
    "NZD/USD": "NZD/USD",

    "دلار کانادا": "USD/CAD",
    "usdcad": "USD/CAD",
    "usd/cad": "USD/CAD",
    "USD/CAD": "USD/CAD",

    "یورو ین": "EUR/JPY",
    "eurjpy": "EUR/JPY",
    "eur/jpy": "EUR/JPY",
    "EUR/JPY": "EUR/JPY",

    "طلا": "XAU/USD",
    "انس": "XAU/USD",
    "gold": "XAU/USD",
    "xauusd": "XAU/USD",
    "xau/usd": "XAU/USD",
    "XAU/USD": "XAU/USD",
}


def normalize_pair(text: str):
    text_lower = text.lower().strip()

    for name, pair in PAIR_NAMES.items():
        if name.lower() in text_lower:
            return pair

    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
سلام 👋
ربات تحلیل فارکس فعال شد.

دستورهای اصلی:

تحلیل یورو دلار
تحلیل پوند دلار
سیگنال طلا
بهترین سیگنال
بررسی بازار
اخبار امروز
آمار
حذف آمار
راهنما

نسخه فعلی:
✅ اتصال به VPS
✅ اجرای سیستمی با systemd
✅ دریافت دیتا از Twelve Data
✅ تحلیل اولیه جهت بازار با EMA / RSI / MACD

مرحله بعد:
اضافه کردن Entry Engine سریع 5M برای ورود، SL و TP.
"""
    await update.message.reply_text(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
راهنمای ربات فارکس:

برای تحلیل:
تحلیل یورو دلار
تحلیل پوند دلار
تحلیل دلار ین
سیگنال طلا

برای بررسی کلی:
بهترین سیگنال
بررسی بازار
اخبار امروز

برای آمار:
آمار
حذف آمار

برای زیر نظر گرفتن:
بعداً با ریپلای روی سیگنال و نوشتن «زیر نظر بگیر» فعال می‌شود.
"""
    await update.message.reply_text(msg)


async def analyze_pair(update: Update, pair: str):
    result = run_analysis(pair)

    if not result["success"]:
        await update.message.reply_text(
            f"❌ خطا در تحلیل {pair}\n\n{result['error']}"
        )
        return

    direction_fa = {
        "BUY": "صعودی / خرید",
        "SELL": "نزولی / فروش",
        "NEUTRAL": "خنثی / نامشخص"
    }.get(result["direction"], result["direction"])

    reasons_text = "\n".join([f"• {r}" for r in result["reasons"]])

    msg = f"""
📊 تحلیل واقعی {result['symbol']}

💰 قیمت فعلی:
{result['price']}

📍 جهت پیش‌بینی:
{direction_fa}

⭐ امتیاز پیش‌بینی:
{result['score']} / 100

📈 RSI:
{result['rsi']}

📊 EMA50:
{result['ema50']}

📊 EMA200:
{result['ema200']}

📉 MACD:
{result['macd']}

📉 MACD Signal:
{result['macd_signal']}

🧠 دلایل تحلیل:
{reasons_text}

⚠️ هنوز Entry / SL / TP فعال نشده.
مرحله بعدی: اضافه کردن Entry Engine سریع با 5M.
"""
    await update.message.reply_text(msg)


async def best_signal(update: Update):
    results = []

    for pair in FOREX_PAIRS:
        result = run_analysis(pair)
        if result["success"]:
            results.append(result)

    if not results:
        await update.message.reply_text("❌ فعلاً هیچ تحلیلی دریافت نشد.")
        return

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    top_results = results[:5]

    lines = ["🔥 بهترین سیگنال‌های فعلی:\n"]

    for i, r in enumerate(top_results, start=1):
        direction_fa = {
            "BUY": "خرید",
            "SELL": "فروش",
            "NEUTRAL": "خنثی"
        }.get(r["direction"], r["direction"])

        lines.append(
            f"{i}. {r['symbol']} | {direction_fa} | امتیاز: {r['score']}/100 | قیمت: {r['price']}"
        )

    lines.append("\n⚠️ هنوز Entry / SL / TP فعال نشده.")
    await update.message.reply_text("\n".join(lines))


async def market_overview(update: Update):
    msg = """
🌍 بررسی بازار فارکس

در نسخه فعلی:
- تحلیل جهت جفت‌ارزها فعال شده
- موتور اخبار هنوز فعال نشده
- بررسی قدرت دلار هنوز کامل نشده

نسخه بعدی:
- روند کلی دلار
- اخبار مهم امروز
- بازار رنج / رونددار
- مناسب بودن بازار برای ترید
"""
    await update.message.reply_text(msg)


async def news_today(update: Update):
    msg = """
📰 اخبار امروز

موتور اخبار هنوز وصل نشده.

در نسخه بعدی اضافه می‌کنیم:
- CPI
- NFP
- FOMC
- نرخ بهره
- سخنرانی‌های فدرال رزرو
- هشدار قبل از خبر
- تحلیل اثر خبر بعد از انتشار
"""
    await update.message.reply_text(msg)


async def stats(update: Update):
    msg = """
📈 آمار سیگنال‌ها

فعلاً سیستم آمار فعال نشده.

بعداً اضافه می‌شود:
- تعداد سیگنال‌ها
- TP
- SL
- Win Rate
- عملکرد هر جفت‌ارز
- آمار 3 / 7 / 30 روز / کل
"""
    await update.message.reply_text(msg)


async def reset_stats(update: Update):
    msg = """
🗑 حذف آمار

فعلاً سیستم آمار هنوز فعال نشده.
بعداً این دستور آمار ذخیره‌شده را پاک می‌کند.
"""
    await update.message.reply_text(msg)


async def watch_signal(update: Update):
    msg = """
👁 زیر نظر گرفتن سیگنال

این قابلیت در مرحله بعدی اضافه می‌شود.
بعداً با ریپلای روی سیگنال و نوشتن «زیر نظر بگیر» فعال خواهد شد.
"""
    await update.message.reply_text(msg)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    text_lower = text.lower()

    if "راهنما" in text_lower:
        await help_command(update, context)
        return

    if "بهترین سیگنال" in text_lower:
        await best_signal(update)
        return

    if "بررسی بازار" in text_lower:
        await market_overview(update)
        return

    if "اخبار" in text_lower:
        await news_today(update)
        return

    if "حذف آمار" in text_lower or "ریست آمار" in text_lower:
        await reset_stats(update)
        return

    if "آمار" in text_lower:
        await stats(update)
        return

    if "زیر نظر" in text_lower or text_lower == "نظر":
        await watch_signal(update)
        return

    pair = normalize_pair(text)

    if pair:
        await analyze_pair(update, pair)
        return

    await update.message.reply_text(
        "متوجه نشدم. یکی از این‌ها رو بنویس:\n\nتحلیل یورو دلار\nسیگنال طلا\nبهترین سیگنال\nبررسی بازار\nاخبار امروز"
    )


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
