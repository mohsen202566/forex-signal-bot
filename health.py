"""Health Manager.
دستور سلامت/هلس/Health نشان می‌دهد چه چیزی ربات را خوابانده یا جلوی کارش را گرفته است.
"""
from __future__ import annotations

import time

from storage import Storage

class HealthManager:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.last_okx_ts = 0
        self.last_toobit_ts = 0
        self.last_signal_loop_ts = 0
        self.last_monitor_loop_ts = 0
        self.last_telegram_ts = 0
        self.last_profile_update_ts = 0

    def mark(self, name: str) -> None:
        now = int(time.time())
        if name == "okx":
            self.last_okx_ts = now
        elif name == "toobit":
            self.last_toobit_ts = now
        elif name == "signal":
            self.last_signal_loop_ts = now
        elif name == "monitor":
            self.last_monitor_loop_ts = now
        elif name == "telegram":
            self.last_telegram_ts = now
        elif name == "profiles":
            self.last_profile_update_ts = now

    @staticmethod
    def age(ts: int) -> str:
        if not ts:
            return "هنوز ثبت نشده"
        sec = int(time.time()) - int(ts)
        if sec < 60:
            return f"{sec} ثانیه قبل"
        return f"{sec//60} دقیقه قبل"

    def report(self) -> str:
        events = self.storage.active_health_events()
        black = self.storage.blacklist_rows()
        status = "✅ سالم" if not events else "⚠️ هشدار"
        critical = [e for e in events if str(e.get("severity", "")).lower() in ("critical", "error", "❌")]
        if critical:
            status = "❌ مشکل جدی"
        lines = [
            "🩺 سلامت ربات 5M",
            "",
            f"وضعیت کلی: {status}",
            "",
            f"OKX Data: آخرین موفقیت {self.age(self.last_okx_ts)}",
            f"Toobit Trade: آخرین موفقیت {self.age(self.last_toobit_ts)}",
            f"Signal Engine: آخرین تحلیل {self.age(self.last_signal_loop_ts)}",
            f"Monitoring: آخرین چک {self.age(self.last_monitor_loop_ts)}",
            f"Profiles: آخرین آپدیت {self.age(self.last_profile_update_ts)}",
            "",
            f"ارزهای blacklist موقت: {len(black)}",
        ]
        if black:
            for b in black[:8]:
                left = max(0, int(b["until_ts"]) - int(time.time()))
                lines.append(f"- {b['symbol_id']}: {b['reason']} | {left//60} دقیقه باقی‌مانده")
        lines.append("")
        if not events:
            lines.append("🚨 مشکلات فعال: ندارد")
        else:
            lines.append("🚨 مشکلات فعال:")
            for e in events[:10]:
                lines.append(f"- {e['severity']} | {e['component']} | {e['symbol_id'] or '-'} | {e['message']}")
        return "\n".join(lines)
