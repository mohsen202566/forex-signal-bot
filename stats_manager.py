from __future__ import annotations

from storage import JsonStorage
from utils import fmt_num


class StatsManager:
    def __init__(self, storage: JsonStorage) -> None:
        self.storage = storage

    def summary_text(self) -> str:
        stats = self.storage.state.stats
        signals = int(stats.get("signals", 0))
        tp = int(stats.get("tp", 0))
        sl = int(stats.get("sl", 0))
        smart = int(stats.get("smart_exit", 0))
        wins = tp + smart
        closed = tp + sl + smart
        win_rate = (wins / closed * 100.0) if closed else 0.0
        pnl = float(stats.get("estimated_pnl_usdt", 0.0))
        return (
            "📊 آمار ربات Forex\n\n"
            f"کل سیگنال‌ها: {signals}\n"
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
