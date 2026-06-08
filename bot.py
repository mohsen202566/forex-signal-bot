# -*- coding: utf-8 -*-
"""
Forex Signal Bot - safe Persian version
- Text-only Telegram bot
- Persian commands and aliases
- News is warning-only, not signal-blocking
- Market overview reports bullish/bearish/range percentages
"""

import asyncio
import logging
import re
import time
import traceback
from typing import Any, Dict, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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

try:
    from forex_pairs import get_pair_display_name
except Exception:
    def get_pair_display_name(symbol: str) -> str:
        return symbol

from news_engine import format_news_message
from statistics import format_stats, parse_days, reset_stats
from tracker import (
    add_active_signal,
    check_active_signals,
    format_active_signals,
    make_signal_id,
    parse_signal_from_text,
)

try:
    from tracker import parse_signal_from_result
except Exception:
    def parse_signal_from_result(result: Dict[str, Any]):
        if not is_valid_trade_signal(result):
            return None
        signal_id = result.get("signal_id") or make_signal_id(result.get("symbol", "SIGNAL"))
        result["signal_id"] = signal_id
        return {
            "signal_id": signal_id,
            "symbol": result.get("symbol"),
            "direction": result.get("direction"),
            "entry": result.get("entry"),
            "stop_loss": result.get("stop_loss"),
            "tp1": result.get("tp1"),
            "tp2": result.get("tp2"),
        }


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)
LAST_AUTO_SIGNALS: Dict[str, float] = {}


def direction_fa(direction: Optional[str]) -> str:
    return {
        "BUY": "صعودی / خرید",
        "SELL": "نزولی / فروش",
        "NEUTRAL": "رنج / خنثی",
    }.get(direction or "", direction or "نامشخص")


def status_fa(status: Optional[str]) -> str:
    return {
        "SIGNAL": "✅ سیگنال فعال",
        "PREDICTION_ONLY": "🔎 فقط پیش‌بینی؛ ورود هنوز کامل نیست",
        "NO_TRADE": "⏸ بدون معامله",
        "NEWS_BLOCKED": "⚠️ هشدار خبر؛ سیگنال نباید به خاطر خبر بلاک شود",
    }.get(status or "", status or "نامشخص")


def is_valid_trade_signal(result: Dict[str, Any]) -> bool:
    return (
        result.get("status") == "SIGNAL"
        and result.get("entry") is not None
        and result.get("stop_loss") is not None
        and result.get("tp1") is not None
    )


def ensure_access(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    return is_allowed(user.id)


def extract_user_id_from_text(text: str) -> Optional[int]:
    match = re.search(r"\b\d{5,15}\b", text or "")
    return int(match.group(0)) if match else None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _format_news_warning(news: Dict[str, Any]) -> str:
    risk = news.get("risk_level", "LOW")
    note = news.get("note", "")

    if risk == "HIGH":
        icon = "🚨"
    elif risk == "MEDIUM":
        icon = "⚠️"
    else:
        icon = "🟡"

    lines = [
        "📰 هشدار خبر:",
        f"{icon} سطح ریسک: {risk}",
        "اثر خبر: فقط هشدار است و سیگنال را بلاک نمی‌کند.",
    ]

    if note:
        lines.append(note)

    return "\n".join(lines)


def format_analysis(result: Dict[str, Any]) -> str:
    symbol = result.get("symbol", "UNKNOWN")
    display = get_pair_display_name(symbol)

    reasons = "\n".join([f"• {r}" for r in result.get("reasons", [])])
    if not reasons:
        reasons = "• دلیل خاصی ثبت نشد."

    entry_reasons = "\n".join([f"• {r}" for r in result.get("entry_reasons", [])])
    if not entry_reasons:
        entry_reasons = "• تریگر ورود هنوز کامل نیست."

    tf = result.get("tf_summary", {}) or {}
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
        signal_id = result.get("signal_id") or make_signal_id(symbol)
        result["signal_id"] = signal_id

    lines = [
        f"📊 تحلیل {display} ({symbol})",
        "",
        f"💰 قیمت فعلی: {result.get('price')}",
        f"📍 جهت پیش‌بینی: {direction_fa(result.get('direction'))}",
        f"⭐ امتیاز پیش‌بینی: {result.get('prediction_score')} / 100",
        f"🟢 امتیاز خرید: {result.get('buy_score')}",
        f"🔴 امتیاز فروش: {result.get('sell_score')}",
        f"⚙️ وضعیت: {status_fa(result.get('status'))}",
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
            f"Entry: {result.get('entry')}",
            f"SL: {result.get('stop_loss')}",
            f"TP1: {result.get('tp1')}",
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

    lines.extend(["", _format_news_warning(result.get("news", {}) or {})])

    return "\n".join(lines)


async def deny(update: Update):
    user_id = update.effective_user.id if update.effective_user else "نامشخص"
    await update.message.reply_text(
        f"⛔ دسترسی شما مجاز نیست.\n"
        f"آیدی شما: {user_id}\n"
        "مالک ربات باید این آیدی را اضافه کند."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else "نامشخص"

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

دستورهای اصلی:
طلا
نقره
نفت
نفت برنت
بیتکوین
یورو دلار
پوند دلار
بهترین سیگنال
بررسی بازار
اخبار امروز
آمار
آمار 7 روز
حذف آمار
سیگنال‌های فعال
زیر نظر بگیر  ← با ریپلای روی پیام سیگنال
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

    user_id = None
    if context.args and context.args[0].isdigit():
        user_id = int(context.args[0])
    else:
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

    user_id = None
    if context.args and context.args[0].isdigit():
        user_id = int(context.args[0])
    else:
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
    display = get_pair_display_name(pair)
    await update.message.reply_text(f"⏳ در حال تحلیل {display} ({pair})...")

    try:
        result = run_analysis(pair)
    except Exception as e:
        logger.error("Analysis crashed for %s: %s\n%s", pair, e, traceback.format_exc())
        await update.message.reply_text(f"❌ خطای داخلی هنگام تحلیل {pair} رخ داد.")
        return

    if not result.get("success"):
        await update.message.reply_text(f"❌ خطا در تحلیل {display} ({pair})\n\n{result.get('error')}")
        return

    await update.message.reply_text(format_analysis(result))


async def best_signal(update: Update):
    await update.message.reply_text("⏳ در حال بررسی بهترین سیگنال‌ها...")

    results = []
    failed = 0

    for pair in FOREX_PAIRS:
        try:
            r = run_analysis(pair)
            if r.get("success"):
                results.append(r)
            else:
                failed += 1
                logger.info("Best signal skipped %s: %s", pair, r.get("error"))
        except Exception as e:
            failed += 1
            logger.warning("Best signal analysis failed for %s: %s", pair, e)

    if not results:
        await update.message.reply_text("❌ هیچ تحلیلی دریافت نشد.")
        return

    valid_signals = [r for r in results if is_valid_trade_signal(r)]
    valid_signals = sorted(
        valid_signals,
        key=lambda x: (_safe_float(x.get("prediction_score")), _safe_float(x.get("entry_score"))),
        reverse=True,
    )

    if not valid_signals:
        msg = "❌ فعلاً سیگنال قابل ورود وجود ندارد."
        if failed:
            msg += f"\nنمادهای بدون دیتای موفق: {failed}"
        await update.message.reply_text(msg)
        return

    for i, r in enumerate(valid_signals[:BEST_SIGNAL_COUNT], start=1):
        symbol = r.get("symbol")
        display = get_pair_display_name(symbol)
        signal_id = r.get("signal_id") or make_signal_id(symbol)
        r["signal_id"] = signal_id

        lines = [
            f"🔥 سیگنال قابل ورود #{i}",
            "",
            f"نماد: {display} ({symbol})",
            f"📍 جهت: {direction_fa(r.get('direction'))}",
            f"⭐ پیش‌بینی: {r.get('prediction_score')} / 100",
            f"⚡ ورود: {r.get('entry_score', 0)} / 100",
            f"⚙️ وضعیت: {status_fa(r.get('status'))}",
            "",
            "🎯 سطوح معامله:",
            f"Entry: {r.get('entry')}",
            f"SL: {r.get('stop_loss')}",
            f"TP1: {r.get('tp1')}",
            f"TP2: {r.get('tp2', '')}",
            "",
            _format_news_warning(r.get("news", {}) or {}),
            "",
            f"شناسه: {signal_id}",
            "برای زیر نظر گرفتن، روی همین پیام ریپلای کن و بنویس: زیر نظر بگیر",
        ]

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
                logger.info("Market overview skipped %s: %s", pair, r.get("error"))
        except Exception as e:
            failed += 1
            logger.warning("Market overview failed for %s: %s", pair, e)

    if not results:
        await update.message.reply_text("❌ بررسی بازار ناموفق بود.\nهیچ نمادی دیتای قابل تحلیل نداد.")
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
            advice = "سیگنال‌های فروش اعتبار بیشتری دارند، ولی چون بازار رنج است با احتیاط وارد شو."
        elif bullish > bearish:
            mood = "بازار بیشتر رنج است، اما تمایل صعودی دارد."
            advice = "سیگنال‌های خرید اعتبار بیشتری دارند، ولی چون بازار رنج است با احتیاط وارد شو."
        else:
            mood = "بازار عمدتاً رنج و بدون جهت قوی است."
            advice = "فعلاً فقط سیگنال‌های خیلی قوی ارزش بررسی دارند."
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

    sorted_results = sorted(results, key=lambda r: _safe_float(r.get("prediction_score")), reverse=True)

    for r in sorted_results[:10]:
        symbol = r.get("symbol", "")
        display = get_pair_display_name(symbol)
        lines.append(
            f"• {display} ({symbol}): {direction_fa(r.get('direction'))} | "
            f"امتیاز {r.get('prediction_score')}/100"
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
        await update.message.reply_text(f"👁 سیگنال {signal['symbol']} زیر نظر گرفته شد.\nشناسه: {signal['signal_id']}")
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

                    try:
                        r = run_analysis(pair)
                    except Exception as e:
                        logger.warning("Auto analysis failed for %s: %s", pair, e)
                        continue

                    if not r.get("success"):
                        continue

                    if is_valid_trade_signal(r) and _safe_float(r.get("prediction_score")) >= AUTO_SIGNAL_SCORE:
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

        text = (update.message.text or "").strip()
        text_lower = text.lower()

        if not text_lower:
            return

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

        await update.message.reply_text(
            "متوجه نشدم. بنویس مثلا:\n"
            "طلا\n"
            "نقره\n"
            "نفت\n"
            "یورو دلار\n"
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
