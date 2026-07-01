from __future__ import annotations

from storage import BotSettings, StoredSignal
from strategy import Signal
from utils import estimate_pnl_usdt, fmt_num, fmt_pct


def direction_fa(direction: str) -> str:
    return "لانگ 🟢" if direction == "LONG" else "شورت 🔴"


def execution_mode_fa(mode: str) -> str:
    if mode == "real":
        return "واقعی روی Toobit ✅"
    if mode == "paper_trade_off":
        return "نمایشی؛ ترید خاموش ⛔️"
    if mode == "paper_slots_full":
        return "نمایشی؛ اسلات واقعی پر بود 🟠"
    if mode == "paper_order_failed":
        return "نمایشی؛ اجرای Toobit ناموفق بود ⚠️"
    return "نمایشی / تست عملکرد"


def start_message() -> str:
    return (
        "ربات Forex آماده است.\n"
        "بازار واقعی: Crypto Futures\n"
        "تحلیل: OKX\n"
        "اجرا: Toobit\n"
        "دستورات و پنل ترید فارسی هستند."
    )


def trade_panel(settings: BotSettings, real_open: int = 0, paper_open: int = 0) -> str:
    status = "روشن ✅" if settings.trade_enabled else "خاموش ⛔️"
    total_slots = int(settings.max_positions)
    free_slots = max(0, total_slots - int(real_open))
    slot_state = "پر 🔴" if free_slots <= 0 else "باز 🟢"
    return (
        "⚙️ پنل ترید Forex\n\n"
        f"وضعیت ترید: {status}\n"
        f"مبلغ معامله: {fmt_num(settings.margin_usdt, 2)} USDT\n"
        f"لوریج: {settings.leverage}x\n"
        f"حداکثر پوزیشن واقعی: {settings.max_positions}\n"
        f"اسلات واقعی: {real_open}/{total_slots} | خالی: {free_slots} | وضعیت: {slot_state}\n"
        f"سیگنال‌های نمایشی باز: {paper_open}\n\n"
        "نکته: وقتی ترید خاموش باشد یا اسلات واقعی پر باشد، سیگنال‌ها باز هم به صورت نمایشی مانیتور می‌شوند و نتیجه‌شان ثبت می‌شود.\n\n"
        "دستورات:\n"
        "/trade_on روشن کردن ترید\n"
        "/trade_off خاموش کردن ترید\n"
        "/amount 10 تنظیم مبلغ معامله\n"
        "/leverage 10 تنظیم لوریج\n"
        "/max_positions 3 تنظیم حداکثر پوزیشن\n"
        "/stats نمایش آمار\n"
        "/reset_stats ریست آمار\n"
        "/delete_stats حذف آمار"
    )


def signal_message(signal: Signal, margin_usdt: float, leverage: int) -> str:
    possible_profit = estimate_pnl_usdt(margin_usdt, leverage, signal.tp_distance_pct)
    possible_loss = estimate_pnl_usdt(margin_usdt, leverage, signal.sl_distance_pct)
    reasons = "\n".join(f"• {r}" for r in signal.reasons[:6])
    return (
        "🚨 سیگنال Forex\n\n"
        f"ارز: {signal.display_symbol}\n"
        f"جهت: {direction_fa(signal.direction)}\n"
        "تایید جهت: 1D + هم‌جهتی BTC/ETH\n"
        "ورود: 15M / 5M\n"
        "نوع اجرا: بعد از بررسی ترید/اسلات در ریپلای همین سیگنال اعلام می‌شود.\n\n"
        f"ورود: {fmt_num(signal.entry_price, 8)}\n"
        f"🎯 TP: {fmt_num(signal.tp_price, 8)}\n"
        f"🛑 SL: {fmt_num(signal.sl_price, 8)}\n\n"
        f"فاصله TP: {fmt_pct(signal.tp_distance_pct)}\n"
        f"فاصله SL: {fmt_pct(signal.sl_distance_pct)}\n"
        f"ریسک به ریوارد: 1:{signal.rr:.2f}\n"
        f"امتیاز: {signal.score}/100\n\n"
        f"💰 مبلغ: {fmt_num(margin_usdt, 2)} USDT | لوریج: {leverage}x\n"
        f"سود احتمالی: حدود {fmt_num(possible_profit, 3)} USDT\n"
        f"ضرر احتمالی: حدود {fmt_num(possible_loss, 3)} USDT\n\n"
        "دلیل سیگنال:\n"
        f"{reasons}"
    )


def execution_status(signal: StoredSignal, message: str) -> str:
    return (
        "📌 وضعیت اجرای سیگنال\n\n"
        f"ارز: {signal.base_symbol}/USDT\n"
        f"جهت: {direction_fa(signal.direction)}\n"
        f"نوع: {execution_mode_fa(signal.execution_mode)}\n"
        f"شناسه سیگنال: {signal.signal_id}\n\n"
        f"توضیح: {message}\n\n"
        "این سیگنال تا رسیدن به TP، SL یا خروج هوشمند مانیتور می‌شود و نتیجه به همین پیام ریپلای می‌شود."
    )


def result_tp(signal: StoredSignal, exit_price: float, pnl_pct: float, pnl_usdt: float) -> str:
    return (
        "✅ نتیجه سیگنال Forex\n\n"
        f"ارز: {signal.base_symbol}/USDT\n"
        f"جهت: {direction_fa(signal.direction)}\n"
        f"نوع اجرا: {execution_mode_fa(signal.execution_mode)}\n"
        "نتیجه: حد سود خورد\n\n"
        f"ورود: {fmt_num(signal.entry_price, 8)}\n"
        f"خروج: {fmt_num(exit_price, 8)}\n"
        f"سود تقریبی: +{fmt_pct(abs(pnl_pct))}\n"
        f"سود دلاری تقریبی: +{fmt_num(abs(pnl_usdt), 3)} USDT\n\n"
        "دلیل نتیجه:\n"
        "قیمت طبق جهت روزانه حرکت کرد و تارگت اصلی لمس شد."
    )


def result_sl(signal: StoredSignal, exit_price: float, pnl_pct: float, pnl_usdt: float, stop_reason: str) -> str:
    return (
        "❌ نتیجه سیگنال Forex\n\n"
        f"ارز: {signal.base_symbol}/USDT\n"
        f"جهت: {direction_fa(signal.direction)}\n"
        f"نوع اجرا: {execution_mode_fa(signal.execution_mode)}\n"
        "نتیجه: حد ضرر خورد\n\n"
        f"ورود: {fmt_num(signal.entry_price, 8)}\n"
        f"خروج: {fmt_num(exit_price, 8)}\n"
        f"ضرر تقریبی: -{fmt_pct(abs(pnl_pct))}\n"
        f"ضرر دلاری تقریبی: -{fmt_num(abs(pnl_usdt), 3)} USDT\n\n"
        "دلیل استاپ:\n"
        f"{stop_reason}"
    )


def result_smart_exit(signal: StoredSignal, exit_price: float, pnl_pct: float, pnl_usdt: float, reason: str) -> str:
    status = "خروج در سود" if pnl_pct >= 0 else "خروج نزدیک سر به سر / ضرر کم"
    sign = "+" if pnl_usdt >= 0 else "-"
    return (
        "🟡 خروج هوشمند Forex\n\n"
        f"ارز: {signal.base_symbol}/USDT\n"
        f"جهت: {direction_fa(signal.direction)}\n"
        f"نوع اجرا: {execution_mode_fa(signal.execution_mode)}\n"
        f"نتیجه: {status}\n\n"
        f"ورود: {fmt_num(signal.entry_price, 8)}\n"
        f"خروج: {fmt_num(exit_price, 8)}\n"
        f"نتیجه تقریبی: {sign}{fmt_pct(abs(pnl_pct))}\n"
        f"نتیجه دلاری تقریبی: {sign}{fmt_num(abs(pnl_usdt), 3)} USDT\n\n"
        "دلیل خروج:\n"
        f"{reason}"
    )


def error_message(text: str) -> str:
    return f"⚠️ {text}"
