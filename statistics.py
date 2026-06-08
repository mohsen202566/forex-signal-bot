# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config import DATA_DIR, STATS_FILE


def fa(text: str) -> str:
    return text.encode("utf-8").decode("unicode_escape")


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
    signal.setdefault("result", "OPEN")
    data["signals"].append(signal)
    save_stats(data)


def update_signal_result(signal_id: str, result: str, reason: str = ""):
    data = load_stats()
    updated = False

    for signal in data["signals"]:
        if str(signal.get("signal_id")) == str(signal_id):
            signal["result"] = result
            signal["closed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            signal["close_reason"] = reason
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
            created_at = datetime.fromisoformat(created)
            if created_at >= cutoff:
                filtered.append(signal)
        except Exception:
            continue

    return filtered


def build_stats(days: Optional[int] = None) -> Dict:
    data = load_stats()
    signals = _filter_by_days(data.get("signals", []), days)

    total = len(signals)
    tp = sum(1 for signal in signals if signal.get("result") == "TP1")
    sl = sum(1 for signal in signals if signal.get("result") == "SL")
    open_count = sum(1 for signal in signals if signal.get("result") == "OPEN")
    closed = tp + sl
    win_rate = round((tp / closed) * 100, 2) if closed else 0

    by_symbol = {}
    by_direction = {
        "BUY": {"tp": 0, "sl": 0, "open": 0, "total": 0},
        "SELL": {"tp": 0, "sl": 0, "open": 0, "total": 0},
    }

    for signal in signals:
        symbol = signal.get("symbol", "UNKNOWN")
        direction = signal.get("direction")
        result = signal.get("result")

        by_symbol.setdefault(symbol, {"tp": 0, "sl": 0, "open": 0, "total": 0})
        by_symbol[symbol]["total"] += 1

        if result == "TP1":
            by_symbol[symbol]["tp"] += 1
        elif result == "SL":
            by_symbol[symbol]["sl"] += 1
        else:
            by_symbol[symbol]["open"] += 1

        if direction in by_direction:
            by_direction[direction]["total"] += 1
            if result == "TP1":
                by_direction[direction]["tp"] += 1
            elif result == "SL":
                by_direction[direction]["sl"] += 1
            else:
                by_direction[direction]["open"] += 1

    return {
        "total": total,
        "tp": tp,
        "sl": sl,
        "open": open_count,
        "closed": closed,
        "win_rate": win_rate,
        "by_symbol": by_symbol,
        "by_direction": by_direction,
    }


def parse_days(text: str):
    text = str(text)

    for days in [3, 7, 14, 30, 60, 90]:
        if str(days) in text:
            return days

    if "\u06a9\u0644" in text or "\u0647\u0645\u0647" in text:
        return None

    return None


def format_stats(days: Optional[int] = None) -> str:
    stats = build_stats(days)
    title = "\u0622\u0645\u0627\u0631 \u06a9\u0644" if not days else f"\u0622\u0645\u0627\u0631 {days} \u0631\u0648\u0632 \u0627\u062e\u06cc\u0631"

    lines = [
        f"\U0001f4c8 {title}",
        "",
        f"\u06a9\u0644 \u0633\u06cc\u06af\u0646\u0627\u0644\u200c\u0647\u0627\u06cc \u062b\u0628\u062a\u200c\u0634\u062f\u0647: {stats['total']}",
        f"\u062a\u0639\u062f\u0627\u062f TP1: {stats['tp']}",
        f"\u062a\u0639\u062f\u0627\u062f SL: {stats['sl']}",
        f"\u0633\u06cc\u06af\u0646\u0627\u0644\u200c\u0647\u0627\u06cc \u0628\u0627\u0632: {stats['open']}",
        f"\u0648\u06cc\u0646\u200c\u0631\u06cc\u062a \u0633\u06cc\u06af\u0646\u0627\u0644\u200c\u0647\u0627\u06cc \u0628\u0633\u062a\u0647\u200c\u0634\u062f\u0647: {stats['win_rate']}\u066a",
        "",
        "\U0001f4ca \u0639\u0645\u0644\u06a9\u0631\u062f \u0628\u0631 \u0627\u0633\u0627\u0633 \u062c\u0647\u062a:",
    ]

    direction_names = {
        "BUY": "\u062e\u0631\u06cc\u062f",
        "SELL": "\u0641\u0631\u0648\u0634",
    }

    for direction in ["BUY", "SELL"]:
        item = stats["by_direction"][direction]
        name = direction_names[direction]
        lines.append(
            f"\u2022 {name}: \u06a9\u0644 {item['total']} | TP1 {item['tp']} | SL {item['sl']} | \u0628\u0627\u0632 {item['open']}"
        )

    if stats["by_symbol"]:
        lines.append("")
        lines.append("\U0001f4cc \u0639\u0645\u0644\u06a9\u0631\u062f \u0628\u0631 \u0627\u0633\u0627\u0633 \u0646\u0645\u0627\u062f:")
        for symbol, item in stats["by_symbol"].items():
            lines.append(
                f"\u2022 {symbol}: \u06a9\u0644 {item['total']} | TP1 {item['tp']} | SL {item['sl']} | \u0628\u0627\u0632 {item['open']}"
            )

    if stats["total"] == 0:
        lines.append("")
        lines.append("\u0647\u0646\u0648\u0632 \u0647\u06cc\u0686 \u0633\u06cc\u06af\u0646\u0627\u0644\u06cc \u0628\u0631\u0627\u06cc \u0622\u0645\u0627\u0631 \u062b\u0628\u062a \u0646\u0634\u062f\u0647 \u0627\u0633\u062a.")

    return "\n".join(lines)
