from __future__ import annotations

from storage import JsonStorage
from utils import fmt_num


class StatsManager:
    def __init__(self, storage: JsonStorage) -> None:
        self.storage = storage

    def summary_text(self) -> str:
        stats = self.storage.state.stats
        signals = int(stats.get("signals", 0))
        real_signals = int(stats.get("real_signals", 0))
        paper_signals = int(stats.get("paper_signals", 0))
        trade_off_signals = int(stats.get("trade_off_signals", 0))
        blocked_slot_signals = int(stats.get("blocked_slot_signals", 0))
        order_failed_signals = int(stats.get("order_failed_signals", 0))
        tp = int(stats.get("tp", 0))
        sl = int(stats.get("sl", 0))
        smart = int(stats.get("smart_exit", 0))
        wins = tp + smart
        closed = tp + sl + smart
        win_rate = (wins / closed * 100.0) if closed else 0.0
        pnl = float(stats.get("estimated_pnl_usdt", 0.0))
        real_open, total_slots, free_slots = self.storage.slot_status()
        paper_open = len(self.storage.paper_open_signals())
        open_all = len(self.storage.open_signals())
        return (
            "📊 آمار ربات Forex\n\n"
            f"کل سیگنال‌ها: {signals}\n"
            f"سیگنال واقعی اجراشده: {real_signals}\n"
            f"سیگنال نمایشی/بدون اجرا: {paper_signals}\n"
            f"نمایشی به خاطر ترید خاموش: {trade_off_signals}\n"
            f"نمایشی به خاطر اسلات پر: {blocked_slot_signals}\n"
            f"نمایشی به خاطر خطای اجرا: {order_failed_signals}\n\n"
            f"سیگنال‌های باز کل: {open_all}\n"
            f"پوزیشن واقعی باز: {real_open}/{total_slots}\n"
            f"اسلات خالی واقعی: {free_slots}\n"
            f"سیگنال نمایشی باز: {paper_open}\n\n"
            f"TP: {tp}\n"
            f"SL: {sl}\n"
            f"خروج هوشمند: {smart}\n"
            f"وین‌ریت تقریبی: {win_rate:.1f}%\n"
            f"سود/ضرر تقریبی: {fmt_num(pnl, 3)} USDT"
        )

    def reset(self) -> None:
        self.storage.reset_stats()

    def delete_all(self) -> None:
        self.storage.delete_all()
