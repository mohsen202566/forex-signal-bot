# -*- coding: utf-8 -*-
import os
import threading
import time

import telebot

from config import BOT_TOKEN, AUTO_SIGNAL_ENABLED, AUTO_SCAN_INTERVAL_MINUTES, TRACKER_CHECK_INTERVAL_SECONDS, AUTO_TRACK_AUTO_SIGNALS
from coins_fa import COINS_FA
from analysis import analyze_symbol
from scanner import get_best_signals, SCAN_SYMBOLS, should_send_auto_signal
from market_scanner import get_market_status_text
from users import is_user_allowed, is_owner, add_user, remove_user, list_users
from diagnostics import log_exception
from signal_tracker import (
    add_signal_to_tracking,
    check_active_signals,
    get_stats_report,
    parse_days_from_text,
    parse_profit_calc_text,
    parse_days_from_report_text,
    get_profit_for_signal_text,
    get_profit_simulation_report,
    reset_stats,
    can_add_automatic_signal,
)

try:
    from paper_trader import (
        set_trade_enabled,
        emergency_stop,
        set_trade_margin,
        set_leverage,
        set_max_open_positions,
        format_trade_status,
        format_open_positions,
        format_trade_stats,
        format_trade_settings,
        format_empty_slots,
    )
except Exception as e:
    PAPER_ERROR = str(e)

    def _paper_error(*args, **kwargs):
        return "❌ بخش Paper Trade لود نشد. فایل‌های paper_trader.py و auto_trade_config.py را چک کن.\nجزئیات: " + PAPER_ERROR

    def set_trade_enabled(enabled): return _paper_error()
    def emergency_stop(): return _paper_error()
    def set_trade_margin(value): return False, _paper_error()
    def set_leverage(value): return False, _paper_error()
    def set_max_open_positions(value): return False, _paper_error()
    def format_trade_status(): return _paper_error()
    def format_open_positions(): return _paper_error()
    def format_trade_stats(): return _paper_error()
    def format_trade_settings(): return _paper_error()
    def format_empty_slots(): return _paper_error()


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

bot = telebot.TeleBot(BOT_TOKEN)
MESSAGE_RESULTS = {}
TRADE_WAITING_ACTION = {}
TRACK_COMMANDS = ["زیر نظر", "زیرنظر", "زیر نظر بگیر", "نظر"]


def clean_text(text):
    return " ".join((text or "").strip().lower().replace("ي", "ی").replace("ك", "ک").split())


def safe(value, default="نامشخص"):
    return default if value is None else value


def remember_signal_result(sent_message, result):
    try:
        if result and result.get("direction") in ["LONG", "SHORT"]:
            MESSAGE_RESULTS[(int(sent_message.chat.id), int(sent_message.message_id))] = result
    except Exception as e:
        print("REMEMBER SIGNAL ERROR:", str(e))


def get_replied_signal_result(message):
    if not message.reply_to_message:
        return None
    return MESSAGE_RESULTS.get((int(message.reply_to_message.chat.id), int(message.reply_to_message.message_id)))


def is_track_command(text):
    return clean_text(text) in TRACK_COMMANDS


def is_stats_command(text):
    t = clean_text(text)
    return t == "آمار" or t.startswith("آمار ")


def is_reset_stats_command(text):
    return clean_text(text) in ["حذف آمار", "ریست آمار", "پاک کردن آمار", "صفر کردن آمار", "پاکسازی آمار"]


def is_market_status_command(text):
    return clean_text(text) in ["وضعیت بازار", "وضعیت ارزها", "محاسبه وضعیت بازار", "بررسی", "بررسی بازار"]


def find_symbol(text):
    raw = clean_text(text)
    for name, symbol in COINS_FA.items():
        if clean_text(name) in raw:
            return symbol
    cleaned = raw.replace("تحلیل", "").replace("سیگنال", "").strip().upper()
    if cleaned.endswith("USDT"):
        return cleaned
    return None


def fa_direction(direction):
    return {"LONG": "🟢 لانگ", "SHORT": "🔴 شورت", "NO TRADE": "⚪ ورود مناسب نیست"}.get(direction, str(direction))


def fa_general(value):
    data = {
        "above_vwap": "بالای VWAP",
        "below_vwap": "پایین VWAP",
        "near_vwap": "نزدیک VWAP",
        "bullish": "صعودی",
        "bearish": "نزولی",
        "weak_bullish": "تمایل صعودی",
        "weak_bearish": "تمایل نزولی",
        "range": "رنج",
    }
    return data.get(value, value)


def build_trade_levels(result):
    if result.get("stop_loss") is None:
        return "برای این وضعیت ورود مستقیم پیشنهاد نمی‌شود."
    return (
        f"ورود: {result.get('entry') or result.get('price')}\n"
        f"حد ضرر: {result.get('stop_loss')}\n"
        f"حد سود 1: {result.get('tp1')}\n"
        f"حد سود 2: {result.get('tp2')}"
    )


def build_analysis_text(result):
    reasons = result.get("reasons", [])[:10]
    reasons_text = "\n".join([f"✅ {r}" for r in reasons]) if reasons else "ندارد"
    return f"""
📊 تحلیل تکنیکال {result.get('symbol')}

وضعیت ورود: {'✅ فعال' if result.get('entry_confirmed') else '⛔ بدون ورود'}
قیمت فعلی: {safe(result.get('price'))}

جهت نهایی: {fa_direction(result.get('direction'))}
حالت ورود: {safe(result.get('entry_mode'))}
امتیاز: {safe(result.get('score'))}
تاییدیه‌ها: {safe(result.get('confirmations'))}
تازگی حرکت: {safe(result.get('freshness'))}
ریسک: {safe(result.get('risk_level'))}
ریسک به ریوارد: {safe(result.get('risk_reward'))}

قدرت خرید 2 کندلی: {safe(result.get('power2_buy'))}٪
قدرت فروش 2 کندلی: {safe(result.get('power2_sell'))}٪
قدرت خرید 3 کندلی: {safe(result.get('power3_buy'))}٪
قدرت فروش 3 کندلی: {safe(result.get('power3_sell'))}٪

RSI: {safe(result.get('rsi'))}
MACD Hist: {safe(result.get('macd_hist'))}
ADX: {safe(result.get('adx'))}
VWAP: {fa_general(result.get('vwap_status'))}

حمایت: {safe(result.get('support'))}
مقاومت: {safe(result.get('resistance'))}

🎯 سطوح معامله:
{build_trade_levels(result)}

⏱ تایم‌فریم: {safe(result.get('signal_timeframe'))}
⏰ اعتبار: {safe(result.get('validity'))}

دلایل اصلی:
{reasons_text}

⚠️ مدیریت ریسک فراموش نشود.
"""


def send_analysis(message, symbol):
    bot.reply_to(message, f"⏳ در حال تحلیل {symbol} ...")
    result = analyze_symbol(symbol)
    sent = bot.reply_to(message, build_analysis_text(result))
    remember_signal_result(sent, result)


def send_best_signals(message, very_safe_only=False):
    bot.reply_to(message, "⏳ در حال اسکن تکنیکال بازار...")
    try:
        results = get_best_signals(limit=5, very_safe_only=very_safe_only)
    except Exception as e:
        bot.reply_to(message, f"❌ خطا در اسکن بازار:\n{e}")
        return
    if not results:
        bot.reply_to(message, "فعلاً سیگنال تکنیکال مناسبی پیدا نشد.")
        return
    msg = "🏆 بهترین سیگنال‌های تکنیکال الان:\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, r in enumerate(results):
        msg += (
            f"{medals[i]} {r.get('symbol')}\n"
            f"جهت: {'لانگ' if r.get('direction') == 'LONG' else 'شورت'}\n"
            f"امتیاز: {r.get('score')}\n"
            f"تاییدیه‌ها: {r.get('confirmations')}\n"
            f"ریسک: {r.get('risk_level')}\n"
            f"ورود: {r.get('entry') or r.get('price')}\n"
            f"TP1: {r.get('tp1')} | SL: {r.get('stop_loss')}\n\n"
        )
    bot.reply_to(message, msg)


def send_auto_signal_to_all_users(result):
    direction_fa = "لانگ" if result.get("direction") == "LONG" else "شورت"
    text = f"""
🚨 سیگنال خودکار تکنیکال

وضعیت: ✅ ورود فعال
ارز: {result.get('symbol')}
جهت: {direction_fa}
امتیاز: {result.get('score')}
تاییدیه‌ها: {result.get('confirmations')}
ریسک: {result.get('risk_level')}
ریسک به ریوارد: {result.get('risk_reward')}

قیمت/ورود: {result.get('entry') or result.get('price')}
حد ضرر: {result.get('stop_loss')}
حد سود 1: {result.get('tp1')}
حد سود 2: {result.get('tp2')}

RSI: {result.get('rsi')}
ADX: {result.get('adx')}
قدرت خرید 2 کندلی: {result.get('power2_buy')}٪
قدرت فروش 2 کندلی: {result.get('power2_sell')}٪

⚠️ مدیریت ریسک فراموش نشود.
"""
    for user_id in list_users():
        try:
            can_add, reason = can_add_automatic_signal(user_id, result.get("symbol"))
            if not can_add:
                print("AUTO SIGNAL SKIPPED:", result.get("symbol"), reason)
                continue
            sent = bot.send_message(user_id, text)
            remember_signal_result(sent, result)
            if AUTO_TRACK_AUTO_SIGNALS:
                ok, msg = add_signal_to_tracking(user_id=user_id, chat_id=user_id, message_id=sent.message_id, result=result)
                if not ok:
                    print("AUTO TRACK SKIPPED:", result.get("symbol"), msg)
        except Exception as e:
            log_exception("ارسال سیگنال خودکار", e, "bot.py", "send_auto_signal_to_all_users", result.get("symbol"))


def auto_signal_loop():
    print("AUTO SIGNAL LOOP STARTED")
    time.sleep(30)
    while True:
        try:
            print("AUTO SIGNAL SCAN START", len(SCAN_SYMBOLS))
            sent_count = 0
            for symbol in SCAN_SYMBOLS:
                try:
                    result = analyze_symbol(symbol)
                    if should_send_auto_signal(result):
                        print("AUTO SIGNAL SEND:", symbol, result.get("direction"), result.get("score"))
                        send_auto_signal_to_all_users(result)
                        sent_count += 1
                except Exception as e:
                    msg = str(e)
                    if not any(x in msg for x in ["does not have market symbol", "Too Many Requests", "429", "داده کافی", "timeout"]):
                        print("AUTO SIGNAL ERROR:", symbol, msg[:200])
            print("AUTO SIGNAL SCAN END. SENT:", sent_count)
        except Exception as e:
            print("AUTO SIGNAL LOOP ERROR:", str(e))
        time.sleep(AUTO_SCAN_INTERVAL_MINUTES * 60)


def signal_tracking_loop():
    time.sleep(20)
    while True:
        try:
            messages = check_active_signals()
            for item in messages:
                try:
                    bot.send_message(item["chat_id"], item["message"], reply_to_message_id=item.get("reply_to_message_id"))
                except Exception:
                    bot.send_message(item["chat_id"], item["message"])
        except Exception as e:
            print("SIGNAL TRACKING LOOP ERROR:", str(e))
        time.sleep(TRACKER_CHECK_INTERVAL_SECONDS)


def handle_trade_waiting_input(message, text):
    user_id = int(message.from_user.id)
    if user_id not in TRADE_WAITING_ACTION:
        return False
    action = TRADE_WAITING_ACTION.pop(user_id)
    if not is_owner(user_id):
        bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند تنظیمات ترید را تغییر دهد.")
        return True
    try:
        value = clean_text(text)
        if action == "trade_margin":
            ok, reply = set_trade_margin(value)
        elif action == "leverage":
            ok, reply = set_leverage(value)
        elif action == "max_positions":
            ok, reply = set_max_open_positions(value)
        else:
            reply = "❌ دستور تنظیم نامشخص بود."
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, f"❌ خطا در ثبت تنظیم:\n{e}")
    return True


def handle_trade_command(message, text):
    clean = clean_text(text)
    user_id = int(message.from_user.id)

    if clean in ["ترید", "وضعیت ترید", "داشبورد", "داشبورد ترید"]:
        bot.reply_to(message, format_trade_status()); return True
    if clean in ["آمار ترید", "امار ترید", "آمار معاملات", "امار معاملات"]:
        bot.reply_to(message, format_trade_stats()); return True
    if clean in ["پوزیشن ها", "پوزیشن‌ها", "پوزیشنهای باز", "پوزیشن های باز", "پوزیشن فعال", "معاملات فعال", "تریدهای فعال"]:
        bot.reply_to(message, format_open_positions()); return True
    if clean in ["تنظیمات ترید", "تنظیم ترید", "ستینگ ترید"]:
        bot.reply_to(message, format_trade_settings()); return True
    if clean in ["اسلات خالی", "اسلات ترید", "ظرفیت ترید"]:
        bot.reply_to(message, format_empty_slots()); return True

    owner_commands = [
        "ترید فعال", "فعال کردن ترید", "ترید روشن", "روشن کردن ترید",
        "ترید غیرفعال", "ترید غیر فعال", "غیرفعال کردن ترید", "ترید خاموش", "خاموش کردن ترید",
        "توقف اضطراری", "استاپ ترید", "توقف ترید",
        "ترید دلار", "دلار ترید", "حجم ترید", "مارجین ترید",
        "ترید لوریج", "لوریج ترید", "اهرم ترید",
        "حداکثر پوزیشن", "حد اکثر پوزیشن", "حداکثر معاملات",
    ]
    if clean in owner_commands and not is_owner(user_id):
        bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند دستورهای ترید را اجرا کند."); return True

    if clean in ["ترید فعال", "فعال کردن ترید", "ترید روشن", "روشن کردن ترید"]:
        bot.reply_to(message, set_trade_enabled(True)); return True
    if clean in ["ترید غیرفعال", "ترید غیر فعال", "غیرفعال کردن ترید", "ترید خاموش", "خاموش کردن ترید"]:
        bot.reply_to(message, set_trade_enabled(False)); return True
    if clean in ["توقف اضطراری", "استاپ ترید", "توقف ترید"]:
        bot.reply_to(message, emergency_stop()); return True
    if clean in ["ترید دلار", "دلار ترید", "حجم ترید", "مارجین ترید"]:
        TRADE_WAITING_ACTION[user_id] = "trade_margin"
        bot.reply_to(message, "مقدار دلاری هر پوزیشن را وارد کن:\nمثلاً: 5"); return True
    if clean in ["ترید لوریج", "لوریج ترید", "اهرم ترید"]:
        TRADE_WAITING_ACTION[user_id] = "leverage"
        bot.reply_to(message, "لوریج معاملات بعدی را وارد کن:\nمثلاً: 10"); return True
    if clean in ["حداکثر پوزیشن", "حد اکثر پوزیشن", "حداکثر معاملات"]:
        TRADE_WAITING_ACTION[user_id] = "max_positions"
        bot.reply_to(message, "حداکثر تعداد پوزیشن همزمان را وارد کن:\nمثلاً: 5"); return True

    if clean.startswith("مارجین ") or clean.startswith("دلار "):
        if not is_owner(user_id):
            bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند مارجین را تغییر دهد."); return True
        ok, reply = set_trade_margin(clean.split()[-1]); bot.reply_to(message, reply); return True
    if clean.startswith("لوریج ") or clean.startswith("اهرم "):
        if not is_owner(user_id):
            bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند لوریج را تغییر دهد."); return True
        ok, reply = set_leverage(clean.split()[-1]); bot.reply_to(message, reply); return True
    if clean.startswith("حداکثر پوزیشن ") or clean.startswith("حد اکثر پوزیشن "):
        if not is_owner(user_id):
            bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند حداکثر پوزیشن را تغییر دهد."); return True
        ok, reply = set_max_open_positions(clean.split()[-1]); bot.reply_to(message, reply); return True

    return False


@bot.message_handler(commands=["start"])
def start(message):
    if not is_user_allowed(message.from_user.id):
        bot.reply_to(message, "⛔ شما مجاز به استفاده از این ربات نیستید.")
        return
    bot.reply_to(message, """
سلام 👋

ربات کلاسیک تحلیل تکنیکال فعال است.

دستورات:
بیتکوین / اتریوم / تحلیل دوج
بهترین سیگنال
بررسی بازار
آمار / آمار 7 روز / حذف آمار

زیر نظر:
روی پیام سیگنال ریپلای کن و بنویس: زیر نظر

ترید:
ترید
ترید فعال / ترید غیرفعال
ترید دلار / ترید لوریج
حداکثر پوزیشن
آمار ترید / پوزیشن ها / تنظیمات ترید
""")


@bot.message_handler(commands=["adduser"])
def add_user_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند کاربر اضافه کند."); return
    try:
        user_id = int(message.text.split()[1])
        add_user(user_id)
        bot.reply_to(message, f"✅ کاربر {user_id} اضافه شد.")
    except Exception:
        bot.reply_to(message, "فرمت درست:\n/adduser 123456789")


@bot.message_handler(commands=["removeuser"])
def remove_user_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند کاربر حذف کند."); return
    try:
        user_id = int(message.text.split()[1])
        ok = remove_user(user_id)
        bot.reply_to(message, f"✅ کاربر {user_id} حذف شد." if ok else "❌ حذف انجام نشد.")
    except Exception:
        bot.reply_to(message, "فرمت درست:\n/removeuser 123456789")


@bot.message_handler(commands=["listusers"])
def list_users_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند لیست کاربران را ببیند."); return
    bot.reply_to(message, "👥 کاربران مجاز:\n" + "\n".join([str(u) for u in list_users()]))


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if not is_user_allowed(message.from_user.id):
        bot.reply_to(message, "⛔ شما مجاز به استفاده از این ربات نیستید.")
        return
    if not message.text:
        return
    text = message.text.strip()

    if handle_trade_waiting_input(message, text): return
    if handle_trade_command(message, text): return

    if is_market_status_command(text):
        bot.reply_to(message, "⏳ در حال محاسبه وضعیت بازار...")
        try:
            bot.reply_to(message, get_market_status_text())
        except Exception as e:
            bot.reply_to(message, f"❌ خطا در محاسبه وضعیت بازار:\n{e}")
        return

    if is_reset_stats_command(text):
        if not is_owner(message.from_user.id):
            bot.reply_to(message, "⛔ فقط مالک ربات می‌تواند آمار را پاک کند."); return
        bot.reply_to(message, "✅ آمار سیگنال‌ها صفر شد." if reset_stats() else "❌ خطا در پاک کردن آمار.")
        return

    profit_calc = parse_profit_calc_text(text)
    if profit_calc:
        margin, leverage = profit_calc
        reply_text = message.reply_to_message.text if message.reply_to_message and message.reply_to_message.text else None
        single = get_profit_for_signal_text(reply_text, margin, leverage)
        bot.reply_to(message, single or get_profit_simulation_report(margin, leverage, parse_days_from_report_text(reply_text) if reply_text else 7))
        return

    if is_track_command(text):
        result = get_replied_signal_result(message)
        if not result:
            bot.reply_to(message, "❌ برای زیر نظر گرفتن، روی پیام تحلیل یا سیگنال خودکار ریپلای کن و بنویس: زیر نظر")
            return
        ok, msg = add_signal_to_tracking(message.from_user.id, message.chat.id, message.reply_to_message.message_id, result)
        bot.reply_to(message, msg)
        return

    if is_stats_command(text):
        bot.reply_to(message, get_stats_report(parse_days_from_text(text)))
        return

    if "خیلی امن" in text or "very safe" in text.lower():
        send_best_signals(message, very_safe_only=True)
        return

    if "بهترین سیگنال" in text or "بهترین فرصت" in text:
        send_best_signals(message)
        return

    symbol = find_symbol(text)
    if not symbol:
        bot.reply_to(message, "ارز رو متوجه نشدم. مثلا بنویس: بیتکوین یا اتریوم")
        return
    send_analysis(message, symbol)


if AUTO_SIGNAL_ENABLED:
    threading.Thread(target=auto_signal_loop, daemon=True).start()
threading.Thread(target=signal_tracking_loop, daemon=True).start()

print("Bot is running...")
bot.infinity_polling(timeout=60, long_polling_timeout=50)
