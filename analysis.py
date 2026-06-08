
async def analyze_pair(update: Update, pair: str):

    price_data = get_latest_price(pair)

    if not price_data["success"]:
        await update.message.reply_text(
            f"❌ خطا در دریافت دیتا\n\n{price_data['error']}"
        )
        return

    current_price = price_data["price"]

    msg = f"""
📊 تحلیل {pair}

💰 قیمت فعلی:
{current_price}

⚙️ وضعیت:
دریافت دیتا موفق

⏳ مراحل بعدی:
✅ قیمت لحظه‌ای
🔄 EMA50
🔄 EMA200
🔄 RSI
🔄 MACD
🔄 ADX
🔄 Prediction Engine
🔄 Entry Engine
🔄 اخبار
"""

    await update.message.reply_text(msg)
