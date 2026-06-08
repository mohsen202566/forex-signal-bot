# -*- coding: utf-8 -*-
"""Signal tracker for Forex Signal Bot.

UTF-8/Persian safe. Parses both full analysis messages and single best-signal messages.
"""

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from config import DATA_DIR, TRACKER_FILE
from data_provider import get_latest_price
from statistics import record_signal, update_signal_result


PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
SYMBOL_RE = r"(?:[A-Z]{3}/[A-Z]{3}|XAU/USD|XAG/USD)"


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).translate(PERSIAN_DIGITS)
    text = text.replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    text = text.replace("｜", "|").replace("–", "-").replace("—", "-")
    return text


def _to_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        value = str(value).translate(PERSIAN_DIGITS).strip()
        value = value.replace(",", "")
        return float(value)
    except Exception:
        return None


def _search(pattern: str, text: str):
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def ensure_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump({"active": []}, f, ensure_ascii=False, indent=2)


def load_active() -> Dict:
    ensure_storage()
    try:
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {"active": []}
        if "active" not in data or not isinstance(data.get("active"), list):
            data["active"] = []
        return data
    except Exception:
        return {"active": []}


def save_active(data: Dict):
    ensure_storage()
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_signal_id(symbol: str) -> str:
    clean_symbol = str(symbol or "SIGNAL").replace("/", "").upper()
    return clean_symbol + "-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")


def add_active_signal(signal: Dict):
    data = load_active()
    existing_ids = {str(s.get("signal_id")) for s in data["active"]}
    if str(signal.get("signal_id")) in existing_ids:
        return False
    data["active"].append(signal)
    save_active(data)
    record_signal(signal)
    return True


def remove_active_signal(signal_id: str):
    data = load_active()
    before = len(data["active"])
    data["active"] = [s for s in data["active"] if str(s.get("signal_id")) != str(signal_id)]
    save_active(data)
    return len(data["active"]) < before


def list_active_signals() -> List[Dict]:
    return load_active().get("active", [])


def parse_signal_from_result(result: Dict):
    """Build a tracker signal directly from analysis result dict.

    Kept for compatibility with older bot.py versions.
    """
    if not result or result.get("entry") is None:
        return None

    symbol = result.get("symbol")
    direction = result.get("direction")
    entry = _to_float(result.get("entry"))
    sl = _to_float(result.get("stop_loss"))
    tp1 = _to_float(result.get("tp1"))
    score = _to_float(result.get("prediction_score")) or 0

    if not symbol or direction not in ("BUY", "SELL") or entry is None or sl is None or tp1 is None:
        return None

    return {
        "signal_id": result.get("signal_id") or make_signal_id(symbol),
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop_loss": sl,
        "tp1": tp1,
        "score": score,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "result": "OPEN",
    }


def parse_signal_from_text(text: str):
    """Parse Entry/SL/TP from a Telegram signal message.

    Supported formats:
    - Full analysis: "تحلیل EUR/USD ... Entry: ..."
    - Best signal item: "#1 - EUR/USD ... Entry: ..."
    - Compact format: "EUR/USD | فروش | Entry: ... | SL: ... | TP1: ..."
    """
    text = _clean_text(text)
    if not text:
        return None

    symbol = (
        _search(r"نماد\s*[:：]\s*(" + SYMBOL_RE + r")", text)
        or _search(r"تحلیل\s+(" + SYMBOL_RE + r")", text)
        or _search(r"#\s*\d+\s*-\s*(" + SYMBOL_RE + r")", text)
        or _search(r"\b(" + SYMBOL_RE + r")\b\s*\|", text)
        or _search(r"\b(" + SYMBOL_RE + r")\b", text)
    )

    upper_text = text.upper()
    if "BUY" in upper_text or "خرید" in text or "صعودی" in text:
        direction = "BUY"
    elif "SELL" in upper_text or "فروش" in text or "نزولی" in text:
        direction = "SELL"
    else:
        direction = None

    number = r"([0-9]+(?:\.[0-9]+)?)"
    entry = _search(r"(?:Entry|ENTRY|ورود)\s*[:：]\s*" + number, text)
    sl = _search(r"(?:SL|Stop\s*Loss|STOP\s*LOSS|استاپ|حد\s*ضرر)\s*[:：]\s*" + number, text)
    tp1 = _search(r"(?:TP1|TP\s*1|تی\s*پی\s*1|تارگت\s*1)\s*[:：]\s*" + number, text)
    score = _search(r"(?:امتیاز\s*پیش\s*بینی|پیش\s*بینی|امتیاز)\s*[:：]?\s*" + number, text)
    signal_id = _search(r"شناسه\s*[:：]\s*([A-Z0-9\-/]+)", text)

    entry_f = _to_float(entry)
    sl_f = _to_float(sl)
    tp1_f = _to_float(tp1)
    score_f = _to_float(score) or 0

    if not symbol or direction not in ("BUY", "SELL") or entry_f is None or sl_f is None or tp1_f is None:
        return None

    return {
        "signal_id": signal_id or make_signal_id(symbol),
        "symbol": symbol,
        "direction": direction,
        "entry": entry_f,
        "stop_loss": sl_f,
        "tp1": tp1_f,
        "score": score_f,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "result": "OPEN",
    }


def check_active_signals():
    data = load_active()
    active = data.get("active", [])
    remaining = []
    events = []

    for s in active:
        try:
            symbol = s.get("symbol")
            price_data = get_latest_price(symbol)
            if not price_data.get("success"):
                remaining.append(s)
                continue

            price = float(price_data["price"])
            direction = s.get("direction")
            tp1 = float(s.get("tp1"))
            sl = float(s.get("stop_loss"))
            hit = None

            if direction == "BUY":
                if price >= tp1:
                    hit = "TP1"
                elif price <= sl:
                    hit = "SL"
            elif direction == "SELL":
                if price <= tp1:
                    hit = "TP1"
                elif price >= sl:
                    hit = "SL"

            if hit:
                update_signal_result(s.get("signal_id"), hit, f"price={price}")
                events.append({"signal": s, "result": hit, "price": price})
            else:
                remaining.append(s)
        except Exception:
            remaining.append(s)

    data["active"] = remaining
    save_active(data)
    return events


def format_active_signals():
    active = list_active_signals()
    if not active:
        return "👁 هیچ سیگنال فعالی زیر نظر نیست."

    lines = ["👁 سیگنال‌های فعال زیر نظر", ""]
    for s in active:
        direction_text = "خرید" if s.get("direction") == "BUY" else "فروش"
        lines.extend([
            f"• {s.get('symbol')} | {direction_text}",
            f"Entry: {s.get('entry')}",
            f"SL: {s.get('stop_loss')}",
            f"TP1: {s.get('tp1')}",
            f"شناسه: {s.get('signal_id')}",
            "────────────",
        ])
    return "\n".join(lines)
