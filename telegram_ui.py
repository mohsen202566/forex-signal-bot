"""Telegram UI texts for the 15-30m crypto helper bot.

Locked UI rules:
- Persian, simple, exchange-panel feeling.
- Main panel shows Toobit connection, wallet/margin, trading settings and stats.
- Signals are always emitted; REAL trades are titled "سیگنال توبیت".
- Normal signals are titled "سیگنال" and are monitored separately.
- Every signal result is designed to be sent as a reply to the original signal.
- Stats are separated into Toobit REAL and normal signal sections.

This module only renders texts/buttons. It does not send Telegram messages and does
not decide trades.
"""
from __future__ import annotations

from typing import Any


ACTIVE_STATUSES = {"ACTIVE", "PENDING_OPEN", "OPEN"}
REAL_ACTIVE_STATUSES = {"PENDING_OPEN", "OPEN"}


# ---------------------------------------------------------------------------
# Small format helpers
# ---------------------------------------------------------------------------

def _num(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value in (None, "", "نامشخص"):
        return "نامشخص"
    try:
        n = float(value)
        text = f"{n:.{digits}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return f"{text}{suffix}"
    except Exception:
        return f"{value}{suffix}"


def _price(value: Any) -> str:
    if value in (None, ""):
        return "نامشخص"
    try:
        n = float(value)
    except Exception:
        return str(value)
    if n >= 100:
        return f"{n:.3f}".rstrip("0").rstrip(".")
    if n >= 1:
        return f"{n:.5f}".rstrip("0").rstrip(".")
    return f"{n:.8f}".rstrip("0").rstrip(".")


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "نامشخص"


def _side_fa(side: Any) -> str:
    if str(side).upper() == "LONG":
        return "LONG 🟢"
    if str(side).upper() == "SHORT":
        return "SHORT 🔴"
    return str(side or "نامشخص")


def _status_fa(status: Any) -> str:
    mapping = {
        "ACTIVE": "فعال",
        "PENDING_OPEN": "در انتظار تأیید توبیت",
        "OPEN": "باز",
        "TP": "TP خورده",
        "SL": "SL خورده",
        "EXPIRED": "منقضی",
        "REPLACED": "جایگزین‌شده",
        "FAILED_OPEN": "باز نشد",
    }
    return mapping.get(str(status), str(status or "نامشخص"))


def _win_rate(bucket: dict[str, Any]) -> str:
    if "win_rate" in bucket:
        try:
            return f"{float(bucket['win_rate']):.1f}%"
        except Exception:
            pass
    done = int(bucket.get("tp", 0)) + int(bucket.get("sl", 0))
    if done <= 0:
        return "0%"
    return f"{int(bucket.get('tp', 0)) / done * 100:.1f}%"


def _open_real_count(state: dict[str, Any]) -> int:
    return sum(
        1
        for sig in state.get("active_signals", {}).values()
        if sig.get("kind") == "TOBIT" and sig.get("status") in REAL_ACTIVE_STATUSES
    )


def _active_signal_count(state: dict[str, Any], kind: str | None = None) -> int:
    return sum(
        1
        for sig in state.get("active_signals", {}).values()
        if sig.get("status") in ACTIVE_STATUSES and (kind is None or sig.get("kind") == kind)
    )


# ---------------------------------------------------------------------------
# Button layouts as plain data. Telegram adapter can convert them to InlineKeyboard.
# ---------------------------------------------------------------------------

def main_buttons() -> list[list[tuple[str, str]]]:
    return [
        [("▶️ فعال کردن ترید", "trade_on"), ("⏸ خاموش کردن ترید", "trade_off")],
        [("💵 دلار هر پوزیشن", "set_margin"), ("⚡ لوریج", "set_leverage")],
        [("📂 حداکثر پوزیشن", "set_max_positions"), ("🎯 حداقل سود خالص", "set_min_profit")],
        [("📊 آمار", "stats"), ("📈 پوزیشن‌ها", "positions")],
        [("🪙 کوین‌ها", "coins"), ("❓ راهنما", "help")],
    ]


def setting_prompt(setting: str, current: Any = None) -> str:
    prompts = {
        "trade_margin_usdt": ("💵 دلار هر پوزیشن", "عدد جدید را وارد کنید.\nمحدوده مجاز: 1 تا 10000 USDT"),
        "leverage": ("⚡ لوریج", "عدد جدید را وارد کنید.\nمحدوده مجاز: 1 تا 100"),
        "max_open_positions": ("📂 حداکثر پوزیشن", "عدد جدید را وارد کنید.\nمحدوده مجاز: 1 تا 100"),
        "min_net_profit_usdt": ("🎯 حداقل سود خالص", "عدد جدید را وارد کنید.\nمحدوده مجاز: 0.10 تا 10000 USDT"),
    }
    title, body = prompts.get(setting, ("⚙️ تنظیمات", "عدد جدید را وارد کنید."))
    current_line = "" if current is None else f"\nمقدار فعلی: {current}"
    return f"{title}{current_line}\n\n{body}".strip()


# ---------------------------------------------------------------------------
# Main panels
# ---------------------------------------------------------------------------

def panel(state: dict[str, Any], exchange: dict[str, Any] | None = None) -> str:
    """Main trade panel, shown by commands: ترید / وضعیت."""
    s = state.get("settings", {})
    stats = state.get("stats", {})
    signal_stats = stats.get("signal", {})
    tobit_stats = stats.get("tobit", {})
    exchange = exchange or {"connected": False}

    connected = "🟢 متصل" if exchange.get("connected") else "🔴 قطع"
    real_on = "🟢 فعال" if s.get("real_trade_enabled") else "🔴 خاموش"
    engine_health = state.get("engine_health", "نامشخص")

    balance = exchange.get("balance", exchange.get("wallet", exchange.get("available", "نامشخص")))
    margin = exchange.get("margin", exchange.get("used_margin", "نامشخص"))
    free_margin = exchange.get("free_margin", exchange.get("available_margin", "نامشخص"))
    equity = exchange.get("equity", "نامشخص")

    open_real = _open_real_count(state)
    max_positions = s.get("max_open_positions", 1)

    return f"""
══════════════════════
📊 پنل ترید

🤖 وضعیت ترید: {real_on}
🔗 صرافی توبیت: {connected}
🧠 سلامت موتور: {engine_health}

💰 موجودی: {_num(balance, 2, ' USDT')}
💎 Equity: {_num(equity, 2, ' USDT')}
📌 مارجین استفاده‌شده: {_num(margin, 2, ' USDT')}
💵 فری‌مارجین: {_num(free_margin, 2, ' USDT')}

💵 دلار هر پوزیشن: {_num(s.get('trade_margin_usdt'), 2, ' USDT')}
⚡ لوریج: ×{s.get('leverage', 'نامشخص')}
📂 پوزیشن باز: {open_real} / {max_positions}
🎯 حداقل سود خالص: {_num(s.get('min_net_profit_usdt'), 2, ' USDT')}

══════════════════════
📊 خلاصه عملکرد
🔴 توبیت: TP {tobit_stats.get('tp', 0)} | SL {tobit_stats.get('sl', 0)} | باز نشد {tobit_stats.get('failed_open', 0)} | خالص {_num(tobit_stats.get('net_pnl', 0), 2, ' USDT')}
📡 سیگنال: TP {signal_stats.get('tp', 0)} | SL {signal_stats.get('sl', 0)} | منقضی {signal_stats.get('expired', 0)} | جایگزین {signal_stats.get('replaced', 0)}

📌 آخرین اسکن: {state.get('last_scan') or 'نامشخص'}
══════════════════════
""".strip()


def stats_panel(state: dict[str, Any]) -> str:
    st = state.get("stats", {})
    tobit = st.get("tobit", {})
    signal = st.get("signal", {})
    last_result = state.get("last_result", {})
    last_line = ""
    if isinstance(last_result, dict) and last_result:
        last_line = f"\nآخرین نتیجه: {last_result.get('coin', '')} {last_result.get('kind', '')} → {_status_fa(last_result.get('result'))}"

    return f"""
📊 آمار ربات

═══════════════
🔴 توبیت (معاملات واقعی)
تعداد معاملات: {tobit.get('total', 0)}
✅ TP: {tobit.get('tp', 0)}
❌ SL: {tobit.get('sl', 0)}
⚠️ باز نشد: {tobit.get('failed_open', 0)}
⏳ منقضی: {tobit.get('expired', 0)}
📈 وین‌ریت: {_win_rate(tobit)}
💎 سود/ضرر خالص: {_num(tobit.get('net_pnl', 0), 2, ' USDT')}

═══════════════
📡 سیگنال (بدون معامله)
تعداد سیگنال: {signal.get('total', 0)}
✅ TP: {signal.get('tp', 0)}
❌ SL: {signal.get('sl', 0)}
⏳ منقضی: {signal.get('expired', 0)}
🔁 جایگزین: {signal.get('replaced', 0)}
📈 وین‌ریت: {_win_rate(signal)}

═══════════════
⚙️ وضعیت موتور تحلیل
سیگنال‌های فعال: {_active_signal_count(state, 'SIGNAL')}
توبیت فعال/Pending: {_active_signal_count(state, 'TOBIT')}
آخرین اسکن: {state.get('last_scan') or 'نامشخص'}{last_line}
═══════════════
""".strip()


def positions_panel(state: dict[str, Any]) -> str:
    active = [s for s in state.get("active_signals", {}).values() if s.get("status") in ACTIVE_STATUSES]
    if not active:
        return "📈 پوزیشن/سیگنال فعال وجود ندارد."
    lines = ["📈 پوزیشن‌ها و سیگنال‌های فعال", "═══════════════"]
    for sig in active:
        title = "🔴 توبیت" if sig.get("kind") == "TOBIT" else "📡 سیگنال"
        lines.append(
            f"{title} #{sig.get('id')}\n"
            f"🪙 {sig.get('coin')} | {_side_fa(sig.get('side'))}\n"
            f"🎯 ورود: {_price(sig.get('entry'))} | ✅ TP: {_price(sig.get('tp'))} | 🛑 SL: {_price(sig.get('sl'))}\n"
            f"📌 وضعیت: {_status_fa(sig.get('status'))}\n"
            f"⭐ Final: {sig.get('final_score', 'نامشخص')} | اعتبار تا: {sig.get('expires_at', 'نامشخص')}"
        )
        lines.append("──────────────")
    return "\n".join(lines).rstrip("─\n")


def coins_panel(coins: list[str] | tuple[str, ...]) -> str:
    items = "\n".join(f"{i + 1}. {coin}" for i, coin in enumerate(coins))
    return f"""
🪙 کوین‌های ثابت ربات

{items}

تعداد: {len(coins)}
منبع تحلیل: OKX
اجرای REAL: Toobit
""".strip()


# ---------------------------------------------------------------------------
# Signal/result rendering
# ---------------------------------------------------------------------------

def signal_message(sig: dict[str, Any]) -> str:
    title = "🔴 سیگنال توبیت" if sig.get("kind") == "TOBIT" else "📡 سیگنال"
    status_line = ""
    if sig.get("kind") == "TOBIT":
        status_line = "\nوضعیت اجرا: در انتظار تأیید باز شدن پوزیشن از توبیت"

    reasons = sig.get("reasons") or []
    if isinstance(reasons, list) and reasons:
        reason_text = "\n".join(f"• {r}" for r in reasons[:6])
    else:
        reason_text = "• ثبت نشده"

    return f"""
{title} #{sig.get('id')}

🪙 {sig.get('coin')}
📈 جهت: {_side_fa(sig.get('side'))}
🎯 ورود: {_price(sig.get('entry'))}
✅ TP: {_price(sig.get('tp'))} ({_pct(sig.get('tp_percent'))})
🛑 SL: {_price(sig.get('sl'))} ({_pct(sig.get('sl_percent'))})
📐 RR: {_num(sig.get('rr'), 2)}

Entry Score: {_num(sig.get('entry_score'), 2)}
Continuation Score: {_num(sig.get('continuation_score'), 2)}
Confidence Penalty: {_num(sig.get('confidence_penalty'), 2)}
Final Score: {_num(sig.get('final_score'), 2)}
Market State: {sig.get('market_state', 'نامشخص')}

⏱ اعتبار سیگنال: ۳ دقیقه{status_line}

📌 دلایل:
{reason_text}
""".strip()


def result_message(sig: dict[str, Any], result: str, price: float | None = None, net_pnl: float | None = None) -> str:
    result = str(result).upper()
    icon = {
        "TP": "✅",
        "SL": "❌",
        "EXPIRED": "⏳",
        "FAILED_OPEN": "⚠️",
        "REPLACED": "🔁",
        "OPEN": "🟢",
    }.get(result, "ℹ️")
    result_fa = {
        "TP": "TP خورد",
        "SL": "SL خورد",
        "EXPIRED": "منقضی شد",
        "FAILED_OPEN": "پوزیشن توبیت باز نشد و اسلات آزاد شد",
        "REPLACED": "با سیگنال قوی‌تر جایگزین شد",
        "OPEN": "پوزیشن توبیت تأیید و باز شد",
    }.get(result, result)
    kind_title = "سیگنال توبیت" if sig.get("kind") == "TOBIT" else "سیگنال"
    pnl_line = "" if net_pnl is None else f"\n💎 سود/ضرر خالص: {_num(net_pnl, 2, ' USDT')}"
    price_line = "" if price is None else f"\n📍 قیمت نتیجه: {_price(price)}"

    return f"""
{icon} نتیجه {kind_title} #{sig.get('id')}

🪙 {sig.get('coin')}
📈 جهت: {_side_fa(sig.get('side'))}
📌 نتیجه: {result_fa}{price_line}{pnl_line}
""".strip()


# ---------------------------------------------------------------------------
# Help / command map
# ---------------------------------------------------------------------------

def help_text() -> str:
    return """
راهنمای دستورات فارسی

═══════════════
پنل و وضعیت:
ترید
وضعیت
آمار
پوزیشن
کوین‌ها

═══════════════
کنترل ترید واقعی:
ترید فعال
ترید خاموش

═══════════════
تنظیمات:
ترید دلار 7
ترید لوریج 10
حداکثر پوزیشن 1
حداقل سود خالص 0.10

محدوده‌ها:
دلار هر پوزیشن: 1 تا 10000 USDT
لوریج: 1 تا 100
حداکثر پوزیشن: 1 تا 100
حداقل سود خالص: 0.10 تا 10000 USDT

═══════════════
قانون سیگنال:
حتی وقتی ترید خاموش است، سیگنال عادی صادر و مانیتور می‌شود.
وقتی ترید فعال باشد و معامله واقعی باز شود، عنوان پیام «سیگنال توبیت» است.
نتیجه هر دو نوع با Reply روی همان پیام اعلام می‌شود.
""".strip()


__all__ = [
    "main_buttons",
    "setting_prompt",
    "panel",
    "stats_panel",
    "positions_panel",
    "coins_panel",
    "signal_message",
    "result_message",
    "help_text",
]
