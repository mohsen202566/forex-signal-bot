from __future__ import annotations

import re
from typing import Any

from config import MIN_NET_PROFIT_USDT, OWNER_ID, TELEGRAM_CHAT_ID
from scorer import SignalDecision
from storage import Storage, StoredSignal
from trade_manager import CreatedSignal, PanelData, TradeManager

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_text(text: str) -> str:
    text = text.strip().translate(PERSIAN_DIGITS)
    text = re.sub(r"\s+", " ", text)
    return text


def fmt_price(value: float | None) -> str:
    if value is None:
        return "نامشخص"
    value = float(value)
    if value >= 100:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def fmt_money(value: float | None) -> str:
    if value is None:
        return "خطا در خواندن"
    return f"{value:.2f} USDT"


def fmt_pct(value: float) -> str:
    return f"{value * 100:.3f}%"


class BotUI:
    def __init__(self, storage: Storage, trade_manager: TradeManager) -> None:
        self.storage = storage
        self.trade_manager = trade_manager
        self.app: Any | None = None

    def bind_app(self, app: Any) -> None:
        self.app = app

    def _is_owner(self, chat_id: int | str) -> bool:
        allowed = {str(TELEGRAM_CHAT_ID), str(OWNER_ID)}
        return str(chat_id) in allowed

    async def send_ready_alert(self, *, symbol_name: str, direction: str) -> int | None:
        if self.app is None:
            return None
        direction_fa = "لانگ" if direction == "LONG" else "شورت"
        text = f"🟡 آماده شکار اسکالپ\n{symbol_name} {direction_fa}\nپنجره: 5 تا 15 دقیقه"
        msg = await self.app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
        return int(msg.message_id)

    async def send_signal(self, *, symbol_name: str, decision: SignalDecision, created: CreatedSignal) -> int | None:
        if self.app is None or decision.direction is None:
            return None
        color = "🟢" if decision.direction == "LONG" else "🔴"
        direction_fa = "لانگ" if decision.direction == "LONG" else "شورت"
        text = (
            f"{color} سیگنال اسکالپ {direction_fa}\n\n"
            f"ارز: {symbol_name}\n"
            f"نوع: {created.signal_label}\n"
            f"Score: {decision.score}/{decision.threshold}\n"
            f"کیفیت ورود: {decision.entry_quality}\n"
            f"AI Confidence: {decision.ai_confidence}%\n"
            f"AI Experience: {decision.ai_experience} نمونه\n"
            f"اثر AI: {decision.ai_effect} / adj {decision.ai_adjustment}\n\n"
            f"Entry: {fmt_price(decision.entry)}\n"
            f"TP: {fmt_price(decision.tp)}\n"
            f"SL: {fmt_price(decision.sl)}\n\n"
            f"Pattern: {decision.candle_pattern}\n"
            f"Entry Stage: {decision.entry_stage_pct:.1f}%\n"
            f"RSI 5m/15m: {decision.rsi_5m:.1f} / {decision.rsi_15m:.1f}\n"
            f"ADX 15m: {decision.adx_15m:.1f}\n"
            f"Vol 5m/15m: {decision.volume_ratio_5m:.2f}x / {decision.volume_ratio_15m:.2f}x\n"
            f"Net Edge: {fmt_pct(decision.net_edge)}\n"
            f"سود خالص تخمینی: {fmt_money(decision.estimated_profit_usdt)}\n"
            f"حداقل سود خالص ثابت: {MIN_NET_PROFIT_USDT:.2f} USDT\n"
            f"RR: {decision.risk_reward:.2f}\n\n"
            f"امتیازها: جهت {decision.breakdown.score_direction} | شروع حرکت {decision.breakdown.score_pre_ignition} | "
            f"ورود {decision.breakdown.score_candle_entry} | AI {decision.breakdown.score_ai_memory} | "
            f"سشن {decision.breakdown.score_session} | محدوده {decision.breakdown.score_order_block}\n\n"
            f"دلیل: {decision.reason}\n"
            f"وضعیت اجرا: {created.reason}\n\n"
            f"پروفایل AI:\n{decision.indicator_profile[:700]}"
        )
        message = await self.app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
        self.storage.update_message_id(created.signal_id, int(message.message_id))
        return int(message.message_id)

    async def send_result(self, signal: StoredSignal, status: str, approx_pnl: float, real_pnl: float | None, result_source: str | None = None) -> int | None:
        if self.app is None:
            return None
        direction_fa = "لانگ" if signal.direction == "LONG" else "شورت"
        result_fa = "تیپی خورد" if status == "TP" else "استاپ خورد"
        icon = "🟢" if status == "TP" else "🔴"
        source_fa = {
            "toobit_real": "واقعی توبیت",
            "normal_on_real": "عادی روی سیگنال واقعی",
            "normal": "عادی ربات",
            "ghost_or_failed": "Ghost/Failed",
        }.get(result_source or signal.result_source or "", "عادی ربات")
        text = (
            f"{icon} نتیجه {direction_fa}: {result_fa}\n"
            f"ارز: {signal.symbol_name or signal.toobit_symbol}\n"
            f"نوع نتیجه: {source_fa}\n"
            f"نوع سیگنال: {signal.hunter_type} / {signal.signal_type}\n"
            f"کیفیت ورود: {signal.entry_quality or '-'}\n"
            f"سود/ضرر تقریبی: {fmt_money(approx_pnl)}"
        )
        if signal.signal_type == "real":
            text += f"\nسود/ضرر واقعی Toobit: {fmt_money(real_pnl)}"
        message = await self.app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, reply_to_message_id=signal.message_id)
        return int(message.message_id)

    async def send_panel(self, chat_id: int | str) -> None:
        data = await self.trade_manager.panel_data()
        await self._send_text(chat_id, self.panel_text(data))

    def panel_text(self, data: PanelData) -> str:
        status = "فعال ✅" if data.trade_enabled else "خاموش ⛔️"
        wallet_line = fmt_money(data.wallet_margin_usdt)
        if data.wallet_error:
            wallet_line = f"خطا در خواندن ({data.wallet_error[:80]})"
        pos_line = "نامشخص" if data.exchange_open_positions is None else str(data.exchange_open_positions)
        ord_line = "نامشخص" if data.exchange_open_orders is None else str(data.exchange_open_orders)
        exch_note = f"\nخطای وضعیت Toobit: {data.exchange_error[:90]}" if data.exchange_error else ""
        long_stats = data.today_stats.get("long", {})
        short_stats = data.today_stats.get("short", {})
        hunter_stats = data.today_stats.get("hunter", {})
        real_tpsl = data.today_stats.get("toobit_real_tp_sl", {})
        normal_tpsl = data.today_stats.get("normal_tp_sl", {})
        return (
            "📌 پنل ترید Forex Scalper\n\n"
            f"وضعیت ترید واقعی: {status}\n"
            "بازار واقعی: Toobit Futures | دیتا: OKX\n"
            "تحلیل: اسکالپ 5 تا 15 دقیقه\n\n"
            "💰 Toobit:\n"
            f"موجودی قابل استفاده: {wallet_line}\n"
            f"پوزیشن‌های باز واقعی: {pos_line}\n"
            f"سفارش‌های باز واقعی: {ord_line}{exch_note}\n\n"
            "⚙️ تنظیمات ربات:\n"
            f"دلار هر پوزیشن: {data.margin_usdt:.2f} USDT\n"
            f"لوریج: {data.leverage}x\n"
            f"حداکثر پوزیشن: {data.max_positions}\n"
            f"حداقل سود خالص ثابت: {MIN_NET_PROFIT_USDT:.2f} USDT\n"
            f"اسلات پر/رزرو: {data.filled_slots}\n"
            f"اسلات خالی: {data.empty_slots}\n"
            f"در انتظار تایید 70 ثانیه‌ای: {data.pending_slots}\n"
            f"نماد OKX خطادار: {data.symbol_health.get('okx_disabled', 0)}\n"
            f"نماد Toobit real غیرفعال: {data.symbol_health.get('toobit_real_disabled', 0)}\n\n"
            "📈 امروز:\n"
            f"PnL واقعی Toobit/ربات: {fmt_money(data.today_real_pnl)}\n"
            f"PnL تقریبی عادی: {fmt_money(data.today_approx_pnl)}\n"
            f"TP/SL واقعی Toobit: TP {real_tpsl.get('tp', 0)} / SL {real_tpsl.get('sl', 0)} / WR {real_tpsl.get('win_rate', 0):.1f}%\n"
            f"TP/SL عادی ربات: TP {normal_tpsl.get('tp', 0)} / SL {normal_tpsl.get('sl', 0)} / WR {normal_tpsl.get('win_rate', 0):.1f}%\n"
            f"لانگ: TP {long_stats.get('tp', 0)} / SL {long_stats.get('sl', 0)} / WR {long_stats.get('win_rate', 0):.1f}%\n"
            f"شورت: TP {short_stats.get('tp', 0)} / SL {short_stats.get('sl', 0)} / WR {short_stats.get('win_rate', 0):.1f}%\n"
            f"شکار: TP {hunter_stats.get('tp', 0)} / SL {hunter_stats.get('sl', 0)} / WR {hunter_stats.get('win_rate', 0):.1f}%"
        )

    async def handle_text(self, update: Any, context: Any) -> None:
        if update.message is None or update.message.text is None:
            return
        chat_id = update.message.chat_id
        text = normalize_text(update.message.text)
        if not self._is_owner(chat_id):
            return
        try:
            if text in {"/start", "start", "راهنما", "/راهنما", "کمک"}:
                await self._send_text(chat_id, self.help_text())
            elif text in {"/پنل", "پنل", "ترید", "/ترید", "وضعیت", "/وضعیت"}:
                await self.send_panel(chat_id)
            elif text.lower() in {"ai", "هوش", "مصنوعی", "هوش مصنوعی", "پنل هوش", "پنل هوش مصنوعی"}:
                await self._send_text(chat_id, self.ai_text())
            elif text in {"/ترید_فعال", "ترید فعال", "ترید روشن"}:
                self.storage.set_trade_enabled(True)
                await self._send_text(chat_id, "✅ ترید واقعی فعال شد.")
            elif text in {"/ترید_خاموش", "ترید خاموش", "ترید غیر فعال", "ترید غیرفعال"}:
                self.storage.set_trade_enabled(False)
                await self._send_text(chat_id, "✅ ترید واقعی خاموش شد. سیگنال‌ها عادی ثبت می‌شوند.")
            elif text.startswith("ترید دلار") or text.startswith("/ترید_دلار"):
                value = self._last_number(text)
                self.storage.set_margin_usdt(value)
                await self._send_text(chat_id, f"✅ دلار هر پوزیشن روی {value:.2f} USDT تنظیم شد.")
            elif text.startswith("ترید لوریج") or text.startswith("/ترید_لوریج"):
                value = int(self._last_number(text))
                self.storage.set_leverage(value)
                await self._send_text(chat_id, f"✅ لوریج روی {value}x تنظیم شد.")
            elif text.startswith("حداکثر پوزیشن") or text.startswith("/حداکثر_پوزیشن"):
                value = int(self._last_number(text))
                self.storage.set_max_positions(value)
                await self._send_text(chat_id, f"✅ حداکثر پوزیشن روی {value} تنظیم شد.")
            elif text.startswith("حداقل سود") or text.startswith("درصد سود"):
                await self._send_text(chat_id, "❌ این نسخه دستور حداقل سود و درصد سود ندارد. حداقل سود خالص ثابت داخل ربات 0.10 USDT است.")
            elif text == "حذف آمار":
                await self._send_text(chat_id, "⚠️ برای صفر کردن آمار بنویس: حذف آمار تایید")
            elif text == "حذف آمار تایید":
                self.storage.reset_stats()
                await self._send_text(chat_id, "✅ آمار و سیگنال‌ها صفر شد.")
            elif text == "ریست یادگیری":
                await self._send_text(chat_id, "⚠️ برای ریست حافظه AI بنویس: ریست یادگیری تایید")
            elif text == "ریست یادگیری تایید":
                self.storage.reset_learning()
                await self._send_text(chat_id, "✅ حافظه AI ریست شد.")
            elif text.startswith("/آمار") or text.startswith("آمار") or text.startswith("امار"):
                parts = text.split()
                days = 7
                if len(parts) > 1:
                    try:
                        days = int(float(parts[-1]))
                    except ValueError:
                        days = 7
                await self._send_text(chat_id, self.stats_text(days))
            else:
                await self._send_text(chat_id, "دستور نامعتبر است. راهنما را بزن.")
        except Exception as exc:
            await self._send_text(chat_id, f"❌ خطا: {exc}")

    def ai_text(self) -> str:
        data = self.storage.ai_panel_stats()
        return (
            "🤖 پنل هوش مصنوعی اسکالپ\n\n"
            f"حافظه فعال: {data['learning_days']} روز\n"
            f"الگوهای ذخیره‌شده: {data['stored_patterns']}\n"
            f"الگوهای فعال هفته اخیر: {data['active_patterns']}\n\n"
            f"شکارهای درست: {data['hunter_tp']}\n"
            f"شکارهای SL شده: {data['hunter_sl']}\n\n"
            f"تحلیل‌های درست: {data['analysis_right']}\n"
            f"تحلیل‌های غلط: {data['analysis_wrong']}\n"
            f"میانگین AI Confidence: {data['avg_ai_confidence']:.1f}%\n\n"
            f"بهترین ارز/جهت: {data['best_symbol_side']}\n"
            f"بدترین ارز/جهت: {data['worst_symbol_side']}\n\n"
            f"ساعت‌های خوب: {data['good_sessions']}\n"
            f"ساعت‌های بد فقط عادی: {data['bad_sessions']}\n\n"
            f"بهترین الگوهای کندلی:\n{data['best_indicator_patterns']}\n\n"
            f"بهترین بازه‌های AI/اندیکاتور:\n{data['best_indicator_ranges']}"
        )

    def stats_text(self, days: int) -> str:
        stats = self.storage.stats(days)
        def line(title: str, key: str) -> str:
            item = stats.get(key, {})
            return f"{title}: کل {item.get('total', 0)} | TP {item.get('tp', 0)} | SL {item.get('sl', 0)} | WR {item.get('win_rate', 0):.1f}% | PnL {item.get('pnl', 0):.2f}"
        return "📊 آمار " + str(days) + " روز\n\n" + "\n".join([
            line("همه", "all"), line("عادی", "normal"), line("واقعی", "real"), line("شکار", "hunter"),
            line("TP/SL واقعی Toobit", "toobit_real_tp_sl"), line("TP/SL عادی", "normal_tp_sl"),
            line("لانگ", "long"), line("شورت", "short"), line("Real Failed", "real_failed"),
        ])

    def help_text(self) -> str:
        return (
            "دستورات فارسی ربات:\n"
            "پنل / وضعیت / ترید\n"
            "آمار یا آمار 7\n"
            "هوش مصنوعی / Ai / هوش / مصنوعی\n"
            "ترید فعال / ترید خاموش\n"
            "ترید دلار 20\n"
            "ترید لوریج 10\n"
            "حداکثر پوزیشن 3\n"
            "حذف آمار / حذف آمار تایید\n"
            "ریست یادگیری / ریست یادگیری تایید\n\n"
            "این نسخه دستور حداقل سود و درصد سود ندارد؛ حداقل سود خالص ثابت 0.10 USDT است."
        )

    async def _send_text(self, chat_id: int | str, text: str) -> None:
        if self.app is not None:
            await self.app.bot.send_message(chat_id=chat_id, text=text)

    def _last_number(self, text: str) -> float:
        matches = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
        if not matches:
            raise ValueError("عدد پیدا نشد.")
        return float(matches[-1])
