# -*- coding: utf-8 -*-
"""Classic direct-signal tracker for Forex Signal Bot.

Tracks active SIGNAL -> TP1/TP2/SL. Pending SETUP mode is removed.
UTF-8/Persian safe and VPS-safe.
"""

import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config import DATA_DIR, TRACKER_FILE
from data_provider import get_latest_price
from statistics import record_signal, update_signal_result

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
SYMBOL_RE = r"(?:[A-Z]{2,10}/[A-Z]{2,10}|[A-Z]{2,10})"


def _utc_now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


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
        value = str(value).translate(PERSIAN_DIGITS).strip().replace(",", "")
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
    """Add an already-active classic signal and record ACTIVATED once."""
    data = load_active()
    existing_ids = {str(s.get("signal_id")) for s in data["active"]}
    if str(signal.get("signal_id")) in existing_ids:
        return False

    signal = dict(signal)
    now = _utc_now()
    signal.setdefault("created_at", now)
    signal.setdefault("activated_at", now)
    signal["stage"] = "ACTIVATED"
    signal["result"] = "ACTIVATED"
    signal.setdefault("tp1_hit", False)

    data["active"].append(signal)
    save_active(data)
    record_signal(signal)
    update_signal_result(signal.get("signal_id"), "ACTIVATED", "classic direct signal")
    return True


def update_active_signal(signal_id: str, **updates):
    data = load_active()
    updated = False
    for item in data.get("active", []):
        if str(item.get("signal_id")) == str(signal_id):
            item.update(updates)
            updated = True
            break
    if updated:
        save_active(data)
    return updated


def remove_active_signal(signal_id: str):
    data = load_active()
    before = len(data["active"])
    data["active"] = [s for s in data["active"] if str(s.get("signal_id")) != str(signal_id)]
    save_active(data)
    return len(data["active"]) < before


def list_active_signals() -> List[Dict]:
    return load_active().get("active", [])


def parse_signal_from_result(result: Dict):
    """Build tracker signal from an active SIGNAL analysis result dict."""
    if not result or result.get("entry") is None:
        return None

    symbol = result.get("symbol")
    direction = result.get("direction")
    entry = _to_float(result.get("entry"))
    sl = _to_float(result.get("stop_loss"))
    tp1 = _to_float(result.get("tp1"))
    tp2 = _to_float(result.get("tp2"))
    score = _to_float(result.get("prediction_score")) or 0
    entry_score = _to_float(result.get("entry_score")) or 0
    status = result.get("status")

    if status != "SIGNAL" or not symbol or direction not in ("BUY", "SELL") or entry is None or sl is None or tp1 is None:
        return None

    stage = "ACTIVATED"
    result_name = "ACTIVATED"
    now = _utc_now()

    return {
        "signal_id": result.get("signal_id") or make_signal_id(symbol),
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "score": score,
        "entry_score": entry_score,
        "stage": stage,
        "result": result_name,
        "created_at": now,
        "activated_at": now if stage == "ACTIVATED" else "",
        "tp1_hit": False,
    }


def parse_signal_from_text(text: str):
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
    tp2 = _search(r"(?:TP2|TP\s*2|تی\s*پی\s*2|تارگت\s*2)\s*[:：]\s*" + number, text)
    score = _search(r"(?:امتیاز\s*پیش\s*بینی|پیش\s*بینی|امتیاز)\s*[:：]?\s*" + number, text)
    signal_id = _search(r"شناسه\s*[:：]\s*([A-Z0-9\-/]+)", text)

    entry_f = _to_float(entry)
    sl_f = _to_float(sl)
    tp1_f = _to_float(tp1)
    tp2_f = _to_float(tp2)
    score_f = _to_float(score) or 0

    if not symbol or direction not in ("BUY", "SELL") or entry_f is None or sl_f is None or tp1_f is None:
        return None

    now = _utc_now()
    return {
        "signal_id": signal_id or make_signal_id(symbol),
        "symbol": symbol,
        "direction": direction,
        "entry": entry_f,
        "stop_loss": sl_f,
        "tp1": tp1_f,
        "tp2": tp2_f,
        "score": score_f,
        "entry_score": 0,
        "stage": "ACTIVATED",
        "created_at": now,
        "activated_at": now,
        "result": "ACTIVATED",
        "tp1_hit": False,
    }


def activate_signal(signal_id: str, result: Optional[Dict] = None, message_id: Optional[int] = None):
    updates = {"stage": "ACTIVATED", "result": "ACTIVATED", "activated_at": _utc_now()}
    if message_id is not None:
        updates["activation_message_id"] = message_id
    if result:
        for key in ("entry", "stop_loss", "tp1", "tp2", "entry_score", "score"):
            source_key = "prediction_score" if key == "score" else key
            if result.get(source_key) is not None:
                updates[key] = result.get(source_key)
    update_active_signal(signal_id, **updates)
    update_signal_result(signal_id, "ACTIVATED", "entry activated")


def check_active_signals():
    """Check active classic signals for TP1/TP2/SL.

    TP1 is recorded once and signal remains active for possible TP2.
    Win rate is still based on first TP1 versus SL.
    """
    data = load_active()
    active = data.get("active", [])
    remaining = []
    events = []

    for s in active:
        try:
            if s.get("stage") != "ACTIVATED":
                remaining.append(s)
                continue

            symbol = s.get("symbol")
            price_data = get_latest_price(symbol)
            if not price_data.get("success"):
                remaining.append(s)
                continue

            price = float(price_data["price"])
            direction = s.get("direction")
            tp1 = float(s.get("tp1"))
            sl = float(s.get("stop_loss"))
            tp2 = _to_float(s.get("tp2"))
            tp1_hit = bool(s.get("tp1_hit"))

            hit = None
            if direction == "BUY":
                if tp2 is not None and price >= tp2:
                    hit = "TP2"
                elif not tp1_hit and price >= tp1:
                    hit = "TP1"
                elif not tp1_hit and price <= sl:
                    hit = "SL"
            elif direction == "SELL":
                if tp2 is not None and price <= tp2:
                    hit = "TP2"
                elif not tp1_hit and price <= tp1:
                    hit = "TP1"
                elif not tp1_hit and price >= sl:
                    hit = "SL"

            if hit == "TP1":
                s["tp1_hit"] = True
                s["tp1_hit_at"] = _utc_now()
                s["result"] = "TP1"
                update_signal_result(s.get("signal_id"), "TP1", f"price={price}")
                events.append({"signal": s, "result": "TP1", "price": price})
                remaining.append(s)
            elif hit in ("TP2", "SL"):
                s["result"] = hit
                s["closed_at"] = _utc_now()
                update_signal_result(s.get("signal_id"), hit, f"price={price}")
                events.append({"signal": s, "result": hit, "price": price})
            else:
                remaining.append(s)
        except Exception:
            remaining.append(s)

    data["active"] = remaining
    save_active(data)
    return events




def _parse_utc(value: str):
    try:
        text = str(value or "").replace("Z", "")
        if not text:
            return None
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _update_stats_result(signal: Dict, result: str, reason: str = ""):
    return update_signal_result(signal.get("signal_id"), result, reason)

def format_active_signals():
    active = list_active_signals()
    if not active:
        return "👁 هیچ سیگنال فعالی زیر نظر نیست."

    lines = ["👁 سیگنال‌های زیر نظر", ""]
    for s in active:
        direction_text = "خرید" if s.get("direction") == "BUY" else "فروش"
        stage_text = "✅ ورود فعال"
        lines.extend([
            f"• {s.get('symbol')} | {direction_text}",
            f"وضعیت: {stage_text}",
            f"Entry: {s.get('entry')}",
            f"SL: {s.get('stop_loss')}",
            f"TP1: {s.get('tp1')}",
            f"TP2: {s.get('tp2')}",
            f"شناسه: {s.get('signal_id')}",
            "────────────",
        ])
    return "\n".join(lines)
