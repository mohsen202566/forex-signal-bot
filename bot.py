# -*- coding: utf-8 -*-
"""
Forex Signal Bot - Diagnostic Safe Persian Version
- Persian text commands
- News is warning-only, not signal-blocking
- Market overview reports bullish/bearish/range percentages
- Built-in health/debug command: عیب یابی / سلامت ربات / /health
"""

import asyncio
import logging
import re
import time
import traceback
from typing import Any, Dict, List, Optional

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
    TWELVE_DATA_API_KEY,
)
from data_provider import get_candles, get_latest_price
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
    list_active_signals,
    make_signal_id,
    parse_signal_from_text,
)

try:
    from tracker import parse_signal_from_result
except Exception:
    def parse_signal_from_result(result: Dict[str, Any]):
        if not is_trade_setup(result):
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
LAST_ERRORS: List[Dict[str, Any]] = []
MAX_ERROR_LOG = 30


def remember_error(area: str, symbol: str = "", error: Any = "", detail: Any = "") -> None:
    """Store recent errors in memory so the bot can report them in Telegram."""
    try:
        item = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "area": str(area),
            "symbol": str(symbol or ""),
            "error": str(error or ""),
            "detail": str(detail or ""),
        }
        LAST_ERRORS.append(item)
        del LAST_ERRORS[:-MAX_ERROR_LOG]
    except Exception:
        pass


def direction_fa(direction: Optional[str]) -> str:
    return {
        "BUY": "صعودی / خرید",
        "SELL": "نزولی / فروش",
        "NEUTRAL": "رنج / خنثی",
    }.get(direction or "", direction or "نامشخص")


def status_fa(status: Optional[str]) -> str:
    return {
        "SIGNAL": "✅ سیگنال ورود فعال",
        "PREDICTION_ONLY": "🔎 فقط پیش‌بینی؛ ورود هنوز کامل نیست",
        "NO_TRADE": "⏸ بدون معامله",
        "NEWS_BLOCKED": "⚠️ هشدار خبر؛ سیگنال نباید به خاطر خبر بلاک شود",
    }.get(status or "", status or "نامشخص")


def is_trade_setup(result: Dict[str, Any]) -> bool:
    # Backward-compatible name; in classic mode only active SIGNAL is tradable.
    return is_valid_trade_signal(result)


def is_initial_setup(result: Dict[str, Any]) -> bool:
    # Setup mode is removed. Keep this helper for older call sites.
    return is_valid_trade_signal(result)


def is_valid_trade_signal(result: Dict[str, Any]) -> bool:
    return (
        result.get("status") == "SIGNAL"
        and result.get("entry") is not None
        and result.get("stop_loss") is not None
        and result.get("tp1") is not None
    )


def _symbol_already_watched(symbol: str) -> bool:
    symbol = str(symbol or "")
    return any(str(s.get("symbol") or "") == symbol for s in list_active_signals())


def can_add_to_watchlist(symbol: str) -> bool:
    """Classic mode has no max-slot limit.

    Duplicate symbols are still avoided to prevent repeated tracking of the same active signal.
    """
    return not _symbol_already_watched(symbol)


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


def _short_error(value: Any, max_len: int = 140) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


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

    reasons = "\n".join([f"• {r}" for r in result.get("reasons", [])]) or "• دلیل خاصی ثبت نشد."
    entry_reasons = "\n".join([f"• {r}" for r in result.get("entry_reasons", [])]) or "• تریگر ورود هنوز کامل نیست."

    tf = result.get("tf_summary", {}) or {}
    tf_lines = []
    for name in ["4H", "1H", "30M", "15M", "5M"]:
        item = tf.get(name, {})
        if item:
            tf_lines.append(
                f"{name}: RSI {item.get('rsi')} | ADX {item.get('adx')} | "
                f"EMA50 {item.get('ema50')} | EMA200 {item.get('ema200')}"
            )
    tf_text = "\n".join(tf_lines) if tf_lines else "داده تایم‌فریم‌ها کامل نیست."

    signal_id = None
    if is_trade_setup(result):
        signal_id = result.get("signal_id") or make_signal_id(symbol)
        result["signal_id"] = signal_id

    if result.get("status") == "SIGNAL":
        title = "🚨 سیگنال ورود فارکس"
        mode = "CLASSIC_DIRECT_SIGNAL"
    else:
        title = f"📊 تحلیل {display} ({symbol})"
        mode = "PREDICTION_ONLY"

    lines = [
        title,
        f"وضعیت: {status_fa(result.get('status'))}",
        f"نماد: {display} ({symbol})",
        f"جهت: {direction_fa(result.get('direction'))}",
        f"حالت ورود: {mode}",
        "",
        f"💰 قیمت فعلی: {result.get('price')}",
        f"⭐ قدرت پیش‌بینی: {result.get('prediction_score')} / 100",
        f"⚡ آمادگی ورود سریع: {result.get('entry_score', 0)} / 100",
        f"🟢 قدرت خرید: {result.get('buy_score')}",
        f"🔴 قدرت فروش: {result.get('sell_score')}",
        "",
        "🧭 جهت کلی تایم‌فریم‌ها:",
        tf_text,
        "",
        "🧠 دلایل پیش‌بینی:",
        reasons,
        "",
        "⚡ وضعیت ورود 5M/15M:",
        entry_reasons,
    ]

    if is_trade_setup(result):
        lines.extend([
            "",
            "🎯 سطوح معامله:",
            f"Entry: {result.get('entry')}",
            f"SL: {result.get('stop_loss')}",
            f"TP1: {result.get('tp1')}",
            f"TP2: {result.get('tp2', '')}",
            "",
            f"شناسه: {signal_id}",
        ])
        lines.append("مانیتورینگ خودکار فعال است تا TP1 / TP2 / SL بررسی شود.")
    else:
        lines.extend([
            "",
            "❌ این تحلیل هنوز سیگنال ورود کامل نیست.",
            "Entry / SL / TP فعال نیست.",
        ])

    lines.extend(["", _format_news_warning(result.get("news", {}) or {})])
    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3800] + "\n\n... پیام کوتاه شد."
    return text


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
عیب یابی
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
حداقل امتیاز اتو سیگنال: {AUTO_SIGNAL_SCORE}\nمحدودیت تعداد سیگنال فعال: حذف شده
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
        remember_error("send_analysis/run_analysis", pair, e, traceback.format_exc())
        logger.error("Analysis crashed for %s: %s\n%s", pair, e, traceback.format_exc())
        await update.message.reply_text(f"❌ خطای داخلی هنگام تحلیل {display} ({pair}) رخ داد.\nبرای بررسی دقیق بنویس: عیب یابی")
        return

    if not result.get("success"):
        remember_error("send_analysis/analyze_pair", pair, result.get("error"), result.get("raw"))
        await update.message.reply_text(f"❌ خطا در تحلیل {display} ({pair})\n\n{result.get('error')}")
        return

    sent = await update.message.reply_text(format_analysis(result))
    if is_valid_trade_signal(result):
        signal = parse_signal_from_result(result)
        if signal:
            signal["message_id"] = sent.message_id
            signal["chat_id"] = update.effective_chat.id
            add_active_signal(signal)


async def best_signal(update: Update):
    await update.message.reply_text("⏳ در حال بررسی بهترین سیگنال‌ها...")

    results = []
    failed_items = []

    for pair in FOREX_PAIRS:
        try:
            r = run_analysis(pair)
            if r.get("success"):
                results.append(r)
            else:
                failed_items.append((pair, r.get("error", "خطای نامشخص")))
                remember_error("best_signal/analyze_pair", pair, r.get("error"), r.get("raw"))
        except Exception as e:
            failed_items.append((pair, str(e)))
            remember_error("best_signal/crash", pair, e, traceback.format_exc())
            logger.warning("Best signal analysis failed for %s: %s", pair, e)

    if not results:
        lines = ["❌ هیچ تحلیلی دریافت نشد.", "", "نمونه خطاها:"]
        for pair, err in failed_items[:8]:
            lines.append(f"• {pair}: {_short_error(err)}")
        lines.append("")
        lines.append("برای گزارش کامل‌تر بنویس: عیب یابی")
        await update.message.reply_text("\n".join(lines))
        return

    valid_signals = [r for r in results if is_initial_setup(r)]
    valid_signals = sorted(
        valid_signals,
        key=lambda x: (_safe_float(x.get("prediction_score")), _safe_float(x.get("entry_score"))),
        reverse=True,
    )

    if not valid_signals:
        msg = "❌ فعلاً سیگنال ورود کامل وجود ندارد."
        if failed_items:
            msg += f"\nنمادهای بدون دیتای موفق: {len(failed_items)}"
        await update.message.reply_text(msg)
        return

    for i, r in enumerate(valid_signals[:BEST_SIGNAL_COUNT], start=1):
        symbol = r.get("symbol")
        display = get_pair_display_name(symbol)
        signal_id = r.get("signal_id") or make_signal_id(symbol)
        r["signal_id"] = signal_id

        prefix = f"🔥 بهترین سیگنال #{i}\n\n"
        sent = await update.message.reply_text(prefix + format_analysis(r))
        signal = parse_signal_from_result(r)
        if signal:
            signal["message_id"] = sent.message_id
            signal["chat_id"] = update.effective_chat.id
            add_active_signal(signal)


async def market_overview(update: Update):
    await update.message.reply_text("⏳ در حال بررسی سریع بازار...")

    results = []
    failed_items = []

    for pair in FOREX_PAIRS:
        try:
            r = run_analysis(pair)
            if r.get("success"):
                results.append(r)
            else:
                failed_items.append((pair, r.get("error", "خطای نامشخص")))
                remember_error("market_overview/analyze_pair", pair, r.get("error"), r.get("raw"))
                logger.info("Market overview skipped %s: %s", pair, r.get("error"))
        except Exception as e:
            failed_items.append((pair, str(e)))
            remember_error("market_overview/crash", pair, e, traceback.format_exc())
            logger.warning("Market overview failed for %s: %s", pair, e)

    if not results:
        lines = [
            "❌ بررسی بازار ناموفق بود.",
            "هیچ نمادی دیتای قابل تحلیل نداد.",
            "",
            "نمونه خطاها:",
        ]
        for pair, err in failed_items[:10]:
            lines.append(f"• {pair}: {_short_error(err)}")
        lines.extend(["", "برای تست کامل‌تر بنویس: عیب یابی"])
        await update.message.reply_text("\n".join(lines))
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

    if failed_items:
        lines.append(f"نمادهای بدون دیتای موفق: {len(failed_items)}")

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

    if failed_items:
        lines.extend(["", "نمونه نمادهای ناموفق:"])
        for pair, err in failed_items[:5]:
            lines.append(f"• {pair}: {_short_error(err, 80)}")

    await update.message.reply_text("\n".join(lines))


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram-side diagnostic report for API/symbol/analysis problems."""
    await update.message.reply_text("🧪 در حال عیب‌یابی ربات...")

    lines = [
        "🧪 گزارش سلامت ربات",
        "",
        f"BOT_TOKEN: {'✅ تنظیم شده' if BOT_TOKEN else '❌ تنظیم نشده'}",
        f"OWNER_ID: {'✅ تنظیم شده' if OWNER_ID else '❌ تنظیم نشده'}",
        f"TWELVE_DATA_API_KEY: {'✅ تنظیم شده' if TWELVE_DATA_API_KEY else '❌ تنظیم نشده'}",
        f"اتو سیگنال: {'✅ فعال' if AUTO_SIGNAL_ENABLED else '⏸ غیرفعال'}",
        f"حداقل امتیاز اتو سیگنال: {AUTO_SIGNAL_SCORE}\nمحدودیت تعداد سیگنال فعال: حذف شده",
        f"تعداد نمادها: {len(FOREX_PAIRS)}",
        "",
    ]

    if not TWELVE_DATA_API_KEY:
        lines.append("❌ مشکل اصلی: TWELVE_DATA_API_KEY تنظیم نشده است.")
        await update.message.reply_text("\n".join(lines))
        return

    # Test all symbols but keep output short.
    ok_price = 0
    ok_candle = 0
    ok_analysis = 0
    failed = []

    for pair in FOREX_PAIRS:
        display = get_pair_display_name(pair)
        try:
            price = get_latest_price(pair)
            if not price.get("success"):
                failed.append((pair, display, "price", price.get("error", "خطا در دریافت قیمت")))
                continue
            ok_price += 1

            candles = get_candles(pair, interval="5min", outputsize=80)
            if not candles.get("success"):
                failed.append((pair, display, "candles 5min", candles.get("error", "خطا در دریافت کندل")))
                continue
            ok_candle += 1

            analysis = run_analysis(pair)
            if not analysis.get("success"):
                failed.append((pair, display, "analysis", analysis.get("error", "تحلیل ناموفق")))
                continue
            ok_analysis += 1
        except Exception as e:
            failed.append((pair, display, "exception", str(e)))
            remember_error("health_check", pair, e, traceback.format_exc())

    lines.extend([
        "نتیجه تست نمادها:",
        f"✅ قیمت موفق: {ok_price} از {len(FOREX_PAIRS)}",
        f"✅ کندل 5M موفق: {ok_candle} از {len(FOREX_PAIRS)}",
        f"✅ تحلیل کامل موفق: {ok_analysis} از {len(FOREX_PAIRS)}",
        f"❌ ناموفق: {len(failed)}",
        "",
    ])

    if failed:
        lines.append("نمونه خطاهای مهم:")
        for pair, display, stage, err in failed[:12]:
            lines.append(f"• {display} ({pair}) | {stage}: {_short_error(err, 90)}")
        lines.extend([
            "",
            "تشخیص احتمالی:",
            "اگر بیشتر نمادها خطا دارند، API Key یا محدودیت Twelve Data مشکل دارد.",
            "اگر فقط چند نماد مثل نفت/شاخص‌ها خطا دارند، آن نماد توسط پلن فعلی API پشتیبانی نمی‌شود.",
        ])
    else:
        lines.append("✅ همه نمادها در تست سریع سالم بودند.")

    if LAST_ERRORS:
        lines.extend(["", "آخرین خطاهای ذخیره‌شده:"])
        for item in LAST_ERRORS[-5:]:
            sym = f" | {item.get('symbol')}" if item.get("symbol") else ""
            lines.append(f"• {item.get('area')}{sym}: {_short_error(item.get('error'), 80)}")

    # Telegram max message is 4096 chars; keep it safe.
    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3700] + "\n\n... گزارش کوتاه شد."
    await update.message.reply_text(text)


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
            if ev["result"] == "TP1":
                res = "✅ TP1 خورد"
            elif ev["result"] == "TP2":
                res = "🎯 TP2 خورد"
            elif ev["result"] == "SL":
                res = "❌ SL خورد"
            else:
                res = str(ev.get("result") or "رویداد")
            await app.bot.send_message(
                chat_id=s.get("chat_id") or OWNER_ID,
                text=f"{res}\n{s.get('symbol')} | قیمت فعلی: {ev['price']}\nشناسه: {s.get('signal_id')}",
                reply_to_message_id=s.get("activation_message_id") or s.get("message_id"),
                allow_sending_without_reply=True,
            )
    except Exception as e:
        remember_error("check_tracker_events", "", e, traceback.format_exc())
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
                        remember_error("auto_signal_loop/run_analysis", pair, e, traceback.format_exc())
                        logger.warning("Auto analysis failed for %s: %s", pair, e)
                        continue
                    if not r.get("success"):
                        continue
                    if is_valid_trade_signal(r) and _safe_float(r.get("prediction_score")) >= AUTO_SIGNAL_SCORE and can_add_to_watchlist(r.get("symbol")):
                        signal = parse_signal_from_result(r)
                        if signal:
                            r["signal_id"] = signal["signal_id"]
                        text = "🚨 اتو سیگنال فارکس\n\n" + format_analysis(r)
                        sent = await app.bot.send_message(chat_id=OWNER_ID, text=text)
                        if signal:
                            signal["message_id"] = sent.message_id
                            signal["chat_id"] = OWNER_ID
                            add_active_signal(signal)
                        LAST_AUTO_SIGNALS[pair] = now
            await asyncio.sleep(max(60, AUTO_SCAN_INTERVAL_MINUTES * 60))
        except Exception as e:
            remember_error("auto_signal_loop", "", e, traceback.format_exc())
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

        if "عیب" in text_lower or "دیباگ" in text_lower or "سلامت" in text_lower or text_lower in ("health", "debug"):
            await health_check(update, context)
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
            "عیب یابی\n"
            "اخبار امروز\n"
            "آمار"
        )
    except Exception as e:
        remember_error("handle_message", "", e, traceback.format_exc())
        logger.error("Unhandled error: %s\n%s", e, traceback.format_exc())
        await update.message.reply_text(f"❌ خطای داخلی ربات رخ داد:\n{e}\n\nبرای بررسی دقیق بنویس: عیب یابی")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN تنظیم نشده است.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("health", health_check))
    app.add_handler(CommandHandler("debug", health_check))
    app.add_handler(CommandHandler("adduser", add_user_command))
    app.add_handler(CommandHandler("removeuser", remove_user_command))
    app.add_handler(CommandHandler("listusers", list_users_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Forex bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
