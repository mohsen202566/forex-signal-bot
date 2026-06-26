"""متن‌های فارسی تلگرام؛ پنل و سیگنال مثل ربات قبلی، ولی با آمار جدا."""
from __future__ import annotations

from typing import Any


def panel(state: dict[str, Any], exchange: dict[str, Any] | None = None) -> str:
    s = state["settings"]
    stats = state["stats"]
    exchange = exchange or {"connected": False}
    connected = "🟢 متصل" if exchange.get("connected") else "🔴 قطع"
    bal = exchange.get("balance", "نامشخص")
    margin = exchange.get("margin", "نامشخص")
    free_margin = exchange.get("free_margin", "نامشخص")
    real_on = "🟢 فعال" if s.get("real_trade_enabled") else "🔴 خاموش"
    open_real = sum(1 for x in state["active_signals"].values() if x.get("kind") == "TOBIT" and x.get("status") in {"PENDING_OPEN", "OPEN"})
    return f"""
══════════════════════
📊 پنل ترید

🤖 وضعیت ترید: {real_on}
🔗 صرافی توبیت: {connected}
💰 موجودی: {bal} USDT
📌 مارجین استفاده‌شده: {margin}
💵 فری‌مارجین: {free_margin}

💵 دلار هر پوزیشن: {s.get('trade_margin_usdt')} USDT
⚡ لوریج: ×{s.get('leverage')}
📂 پوزیشن باز: {open_real} / {s.get('max_open_positions')}
🎯 حداقل سود خالص: {s.get('min_net_profit_usdt')} USDT

══════════════════════
📊 خلاصه امروز/کل
🔴 توبیت: TP {stats['tobit']['tp']} | SL {stats['tobit']['sl']} | Failed {stats['tobit']['failed_open']}
📡 سیگنال: TP {stats['signal']['tp']} | SL {stats['signal']['sl']} | Exp {stats['signal']['expired']}
══════════════════════
""".strip()


def stats_panel(state: dict[str, Any]) -> str:
    st = state["stats"]
    def wr(bucket: dict[str, Any]) -> str:
        done = bucket.get("tp", 0) + bucket.get("sl", 0)
        return "0%" if done == 0 else f"{bucket.get('tp', 0) / done * 100:.1f}%"
    return f"""
📊 آمار ربات

═══════════════
🔴 توبیت (معاملات واقعی)
تعداد: {st['tobit']['total']}
✅ TP: {st['tobit']['tp']}
❌ SL: {st['tobit']['sl']}
⚠️ باز نشد: {st['tobit']['failed_open']}
📈 وین‌ریت: {wr(st['tobit'])}
💎 سود/ضرر خالص: {st['tobit']['net_pnl']:.2f} USDT

═══════════════
📡 سیگنال (بدون معامله)
تعداد: {st['signal']['total']}
✅ TP: {st['signal']['tp']}
❌ SL: {st['signal']['sl']}
⏳ منقضی: {st['signal']['expired']}
🔁 جایگزین: {st['signal']['replaced']}
📈 وین‌ریت: {wr(st['signal'])}
═══════════════
""".strip()


def signal_message(sig: dict[str, Any]) -> str:
    title = "🔴 سیگنال توبیت" if sig.get("kind") == "TOBIT" else "📡 سیگنال"
    return f"""
{title} #{sig.get('id')}

🪙 {sig['coin']}
📈 جهت: {sig['side']}
🎯 ورود: {sig['entry']:.6g}
✅ TP: {sig['tp']:.6g}
🛑 SL: {sig['sl']:.6g}

Entry Score: {sig.get('entry_score')}
Continuation Score: {sig.get('continuation_score')}
Confidence Penalty: {sig.get('confidence_penalty')}
Final Score: {sig.get('final_score')}
اعتبار سیگنال: ۳ دقیقه
""".strip()


def result_message(sig: dict[str, Any], result: str, price: float | None = None, net_pnl: float | None = None) -> str:
    icon = {"TP": "✅", "SL": "❌", "EXPIRED": "⏳", "FAILED_OPEN": "⚠️", "REPLACED": "🔁"}.get(result, "ℹ️")
    result_fa = {"TP": "TP خورد", "SL": "SL خورد", "EXPIRED": "منقضی شد", "FAILED_OPEN": "پوزیشن باز نشد", "REPLACED": "با سیگنال قوی‌تر جایگزین شد"}.get(result, result)
    pnl_line = "" if net_pnl is None else f"\n💎 سود/ضرر خالص: {net_pnl:.2f} USDT"
    price_line = "" if price is None else f"\n📍 قیمت نتیجه: {price:.6g}"
    return f"""
{icon} نتیجه سیگنال #{sig.get('id')}

🪙 {sig.get('coin')}
📈 جهت: {sig.get('side')}
📌 نتیجه: {result_fa}{price_line}{pnl_line}
""".strip()


def help_text() -> str:
    return """
دستورات:
ترید
وضعیت
ترید فعال
ترید خاموش
ترید دلار 7
ترید لوریج 10
حداکثر پوزیشن 1
حداقل سود خالص 0.10
آمار
پوزیشن
کوین‌ها
استراتژی لول 4
""".strip()
