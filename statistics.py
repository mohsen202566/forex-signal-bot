# -*- coding: utf-8 -*-
"""Compact futures-like statistics for Forex bot.

Win rate is based only on TP1 vs SL. TP2 is tracked separately.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config import DATA_DIR, STATS_FILE


def ensure_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(STATS_FILE):
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump({"signals": []}, f, ensure_ascii=False, indent=2)


def load_stats() -> Dict:
    ensure_storage()
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"signals": []}
        if "signals" not in data or not isinstance(data["signals"], list):
            data["signals"] = []
        return data
    except Exception:
        return {"signals": []}


def save_stats(data: Dict):
    ensure_storage()
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_signal(signal: Dict):
    data = load_stats()
    signal = dict(signal)
    signal.setdefault("created_at", datetime.utcnow().isoformat(timespec="seconds") + "Z")
    signal.setdefault("result", "ACTIVATED")
    signal.setdefault("stage", "ACTIVATED")
    signal.setdefault("tp1_hit", False)
    data["signals"].append(signal)
    save_stats(data)


def update_signal_result(signal_id: str, result: str, reason: str = ""):
    data = load_stats()
    updated = False
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    for signal in data["signals"]:
        if str(signal.get("signal_id")) == str(signal_id):
            signal["result"] = result
            signal["close_reason"] = reason
            if result == "ACTIVATED":
                signal["stage"] = "ACTIVATED"
                signal["activated_at"] = now
            elif result == "TP1":
                signal["tp1_hit"] = True
                signal["tp1_hit_at"] = now
            elif result in ("TP2", "SL", "CANCELLED"):
                signal["closed_at"] = now
                if result == "TP2":
                    signal["tp2_hit"] = True
                if result == "SL":
                    signal["sl_hit"] = True
            updated = True
            break

    save_stats(data)
    return updated


def reset_stats():
    save_stats({"signals": []})


def _filter_by_days(signals: List[Dict], days: Optional[int] = None):
    if not days:
        return signals

    cutoff = datetime.utcnow() - timedelta(days=days)
    filtered = []
    for signal in signals:
        created = str(signal.get("created_at", "")).replace("Z", "")
        try:
            if datetime.fromisoformat(created) >= cutoff:
                filtered.append(signal)
        except Exception:
            continue
    return filtered


def _is_tp1(signal: Dict) -> bool:
    return bool(signal.get("tp1_hit")) or signal.get("result") in ("TP1", "TP2")


def _is_tp2(signal: Dict) -> bool:
    return bool(signal.get("tp2_hit")) or signal.get("result") == "TP2"


def _is_sl(signal: Dict) -> bool:
    return bool(signal.get("sl_hit")) or signal.get("result") == "SL"


def build_stats(days: Optional[int] = None) -> Dict:
    data = load_stats()
    signals = _filter_by_days(data.get("signals", []), days)

    total_signals = len(signals)
    activated = sum(1 for s in signals if s.get("stage") == "ACTIVATED" or s.get("result") in ("ACTIVATED", "TP1", "TP2", "SL"))
    cancelled = sum(1 for s in signals if s.get("result") == "CANCELLED")
    tp1 = sum(1 for s in signals if _is_tp1(s))
    tp2 = sum(1 for s in signals if _is_tp2(s))
    sl = sum(1 for s in signals if _is_sl(s))
    open_count = sum(1 for s in signals if s.get("result") in ("SETUP_CREATED", "ACTIVATED", "TP1"))

    closed_for_wr = tp1 + sl
    win_rate = round((tp1 / closed_for_wr) * 100, 2) if closed_for_wr else 0
    tp2_rate = round((tp2 / tp1) * 100, 2) if tp1 else 0

    by_direction = {
        "BUY": {"signals": 0, "activated": 0, "tp1": 0, "tp2": 0, "sl": 0},
        "SELL": {"signals": 0, "activated": 0, "tp1": 0, "tp2": 0, "sl": 0},
    }
    by_symbol = {}

    for s in signals:
        symbol = s.get("symbol", "UNKNOWN")
        direction = s.get("direction")
        by_symbol.setdefault(symbol, {"signals": 0, "activated": 0, "tp1": 0, "tp2": 0, "sl": 0})
        by_symbol[symbol]["signals"] += 1
        if s.get("stage") == "ACTIVATED" or s.get("result") in ("ACTIVATED", "TP1", "TP2", "SL"):
            by_symbol[symbol]["activated"] += 1
        if _is_tp1(s):
            by_symbol[symbol]["tp1"] += 1
        if _is_tp2(s):
            by_symbol[symbol]["tp2"] += 1
        if _is_sl(s):
            by_symbol[symbol]["sl"] += 1

        if direction in by_direction:
            by_direction[direction]["signals"] += 1
            if s.get("stage") == "ACTIVATED" or s.get("result") in ("ACTIVATED", "TP1", "TP2", "SL"):
                by_direction[direction]["activated"] += 1
            if _is_tp1(s):
                by_direction[direction]["tp1"] += 1
            if _is_tp2(s):
                by_direction[direction]["tp2"] += 1
            if _is_sl(s):
                by_direction[direction]["sl"] += 1

    return {
        "total_signals": total_signals,
        "activated": activated,
        "cancelled": cancelled,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "open": open_count,
        "closed_for_wr": closed_for_wr,
        "win_rate": win_rate,
        "tp2_rate": tp2_rate,
        "by_symbol": by_symbol,
        "by_direction": by_direction,
    }


def parse_days(text: str):
    text = str(text)
    for days in [3, 7, 14, 30, 60, 90]:
        if str(days) in text:
            return days
    if "کل" in text or "همه" in text:
        return None
    return None


def format_stats(days: Optional[int] = None) -> str:
    stats = build_stats(days)
    title = "آمار کل" if not days else f"آمار {days} روز اخیر"

    lines = [
        f"📈 {title}",
        "",
        f"سیگنال‌های صادرشده: {stats['total_signals']}",
        f"سیگنال‌های فعال: {stats['activated']}",
        f"لغوشده/قدیمی: {stats['cancelled']}",
        f"TP1: {stats['tp1']}",
        f"TP2: {stats['tp2']}  | نرخ TP2 بعد از TP1: {stats['tp2_rate']}٪",
        f"SL: {stats['sl']}",
        f"باز/درحال پیگیری: {stats['open']}",
        f"وین‌ریت: {stats['win_rate']}٪",
        "",
        "نکته: وین‌ریت فقط با TP1 و SL حساب شده؛ TP2 جداگانه است.",
        "",
        "📊 عملکرد جهت‌ها:",
    ]

    direction_names = {"BUY": "خرید", "SELL": "فروش"}
    for direction in ["BUY", "SELL"]:
        item = stats["by_direction"][direction]
        lines.append(
            f"• {direction_names[direction]}: سیگنال {item['signals']} | فعال {item['activated']} | TP1 {item['tp1']} | TP2 {item['tp2']} | SL {item['sl']}"
        )

    if stats["by_symbol"]:
        lines.append("")
        lines.append("📌 عملکرد نمادها:")
        sorted_symbols = sorted(
            stats["by_symbol"].items(),
            key=lambda kv: (kv[1].get("tp1", 0), kv[1].get("activated", 0)),
            reverse=True,
        )
        for symbol, item in sorted_symbols[:12]:
            lines.append(
                f"• {symbol}: سیگنال {item['signals']} | فعال {item['activated']} | TP1 {item['tp1']} | TP2 {item['tp2']} | SL {item['sl']}"
            )

    if stats["total_setups"] == 0:
        lines.append("")
        lines.append("هنوز هیچ سیگنالی برای آمار ثبت نشده است.")

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3700] + "\n\n... گزارش کوتاه شد."
    return text
