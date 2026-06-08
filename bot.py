from data_provider import get_latest_price
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from config import BOT_TOKEN, FOREX_PAIRS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

PAIR_NAMES = {
    "یورو دلار": "EUR/USD",
    "eurusd": "EUR/USD",
    "eur/usd": "EUR/USD",

    "پوند دلار": "GBP/USD",
    "gbpusd": "GBP/USD",
    "gbp/usd": "GBP/USD",

    "دلار ین": "USD/JPY",
    "usdjpy": "USD/JPY",
    "usd/jpy": "USD/JPY",

    "دلار فرانک": "USD/CHF",
    "usdchf": "USD/CHF",
    "usd/chf": "USD/CHF",

    "استرالیا دلار": "AUD/USD",
    "audusd": "AUD/USD",
    "aud/usd": "AUD/USD",

    "نیوزیلند دلار": "NZD/USD",
    "nzdusd": "NZD/USD",
    "nzd/usd": "NZD/USD",

    "دلار کانادا": "USD/CAD",
    "usdcad": "USD/CAD",
    "usd/cad": "USD/CAD",

    "یورو ین": "EUR/JPY",
    "eurjpy": "EUR/JPY",
    "eur/jpy": "EUR/JPY",

    "طلا": "XAU/USD",
    "gold": "XAU/USD",
    "xauusd": "XAU/USD",
    "xau/usd": "XAU/USD",
}


def normalize_pair(text: str):
    text = text.lower().strip()
    for name, pair in PAIR_NAMES.items():
        if name in text:
            return pair
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
سلام 👋
ربات تحلیل فارکس فعال شد.

دستورهای فعلی:

تحلیل یورو دلار
سیگنال طلا
بهترین سیگنال
بررسی بازار
اخبار امروز
آمار
حذف آمار
راهنما

نسخه فعلی پایه است؛ بعداً موتور تحلیل، اخبار، آمار و زیرنظر گرفتن را مرحله‌به‌مرحله اضافه می‌کنیم.
"""
    await update.message.reply_text(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
راهنمای ربات فارکس:

برای تحلیل:
تحلیل یورو دلار
تحلیل پوند دلار
سیگنال طلا

برای بررسی کلی:
بهترین سیگنال
بررسی بازار
اخبار امروز

برای عملکرد:
آمار
حذف آمار

برای زیر نظر گرفتن:
بعداً با ریپلای روی سیگنال و نوشتن «زیر نظر بگیر» فعال می‌شود.
"""
    await update.message.reply_text(msg)


async def analyze_pair(update: Update, pair: str):
    msg = f"""
📊 تحلیل اولیه {pair}

وضعیت: آماده تحلیل تکنیکال

در نسخه بعدی اضافه می‌کنیم:
- پیش‌بینی جهت با 4H و 1H
- بررسی ستاپ با 15M
- تریگر ورود با 5M
- EMA50/200
- MACD
- RSI Slope
- ADX
- Support/Resistance
- ATR برای SL و TP
- فیلتر اخبار مهم

فعلاً این دستور درست کار می‌کند و آماده اتصال به موتور تحلیل است.
"""
    await update.message.reply_text(msg)


async def best_signal(update: Update):
    msg = """
🔥 بهترین سیگنال‌ها

فعلاً موتور تحلیل هنوز وصل نشده.

در نسخه بعدی این بخش جفت‌ارزهای زیر را بررسی می‌کند:
EUR/USD
GBP/USD
USD/JPY
USD/CHF
AUD/USD
NZD/USD
USD/CAD
EUR/JPY
XAU/USD

و بهترین 3 تا 5 سیگنال را بر اساس امتیاز نمایش می‌دهد.
"""
    await update.message.reply_text(msg)


async def market_overview(update: Update):
    msg = """
🌍 بررسی بازار فارکس

فعلاً نسخه پایه است.

در نسخه بعدی بررسی می‌کند:
- قدرت دلار
- روند کلی EUR/USD و GBP/USD و USD/JPY
- اخبار مهم امروز
- وضعیت بازار: رونددار / رنج / پرریسک
- مناسب بودن بازار برای ترید
"""
    await update.message.reply_text(msg)


async def news_today(update: Update):
    msg = """
📰 اخبار امروز

فعلاً موتور اخبار وصل نشده.

در نسخه بعدی اضافه می‌کنیم:
- CPI
- NFP
- FOMC
- نرخ بهره
- سخنرانی‌های مهم فدرال رزرو
- هشدار قبل از خبر
- تحلیل اثر خبر بعد از انتشار
"""
    await update.message.reply_text(msg)


async def stats(update: Update):
    msg = """
📈 آمار سیگنال‌ها

فعلاً آمار ثبت نشده.

در نسخه بعدی:
- تعداد سیگنال‌ها
- TP
- SL
- Win Rate
- عملکرد هر جفت‌ارز
- آمار 3 / 7 / 30 روز / کل
اضافه می‌شود.
"""
    await update.message.reply_text(msg)


async def reset_stats(update: Update):
    msg = """
🗑 حذف آمار

فعلاً سیستم آمار هنوز فعال نشده.
بعداً این دستور آمار ذخیره‌شده را پاک می‌کند.
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

    if "زیر نظر" in text_lower or "نظر" == text_lower:
        await update.message.reply_text(
            "قابلیت زیر نظر گرفتن در مرحله بعدی اضافه می‌شود. بعداً با ریپلای روی سیگنال فعال خواهد شد."
        )
        return

    pair = normalize_pair(text_lower)

    if pair and ("تحلیل" in text_lower or "سیگنال" in text_lower or pair):
        await analyze_pair(update, pair)
        return

    await update.message.reply_text(
        "متوجه نشدم. بنویس مثلا:\nتحلیل یورو دلار\nبهترین سیگنال\nبررسی بازار\nاخبار امروز"
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Forex bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
