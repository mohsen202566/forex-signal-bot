# -*- coding: utf-8 -*-
"""Two-stage signal tracker for Forex Signal Bot.

Tracks SETUP -> ACTIVATED -> TP1/TP2/SL.
UTF-8/Persian safe and VPS-safe.
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


def _text_is_activated_signal(text: str) -> bool:
    """Detect whether a pasted/replied signal text is already an active entry signal.

    This is important because reply-based tracking may be used on either:
    - setup messages waiting for activation
    - already activated signal messages

    If an already activated message is stored as SETUP, check_active_signals() will
    intentionally skip it and TP/SL will never be recorded.
    """
    cleaned = _clean_text(text)
    upper_text = cleaned.upper()

    activated_markers = (
        "ورود فعال شد",
        "ورود فعال",
        "وضعیت: ✅ ورود فعال",
        "وضعیت: ورود فعال",
        "ENTRY ACTIVATED",
        "STATUS: SIGNAL",
        "SIGNAL",
    )
    waiting_markers = (
        "منتظر فعال سازی",
        "منتظر فعال‌سازی",
        "منتظر فعالسازی",
        "WAITING",
        "SETUP",
    )

    if any(marker in cleaned for marker in waiting_markers) or any(marker in upper_text for marker in waiting_markers):
        return False
    return any(marker in cleaned for marker in activated_markers) or any(marker in upper_text for marker in activated_markers)


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
    """Add a setup/active signal and record SETUP_CREATED once."""
    data = load_active()
    existing_ids = {str(s.get("signal_id")) for s in data["active"]}
    if str(signal.get("signal_id")) in existing_ids:
        return False

    signal = dict(signal)
    signal.setdefault("created_at", _utc_now())
    signal.setdefault("stage", "SETUP")
    signal.setdefault("result", "SETUP_CREATED")
    signal.setdefault("tp1_hit", False)

    data["active"].append(signal)
    save_active(data)
    record_signal(signal)
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
    """Build tracker signal from analysis result dict.

    Accepts both SETUP and SIGNAL so auto-monitoring can start before activation.
    """
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

    if not symbol or direction not in ("BUY", "SELL") or entry is None or sl is None or tp1 is None:
        return None

    stage = "ACTIVATED" if status == "SIGNAL" else "SETUP"
    result_name = "ACTIVATED" if stage == "ACTIVATED" else "SETUP_CREATED"
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

    stage = "ACTIVATED" if _text_is_activated_signal(text) else "SETUP"
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
        "stage": stage,
        "created_at": now,
        "activated_at": now if stage == "ACTIVATED" else "",
        "result": "ACTIVATED" if stage == "ACTIVATED" else "SETUP_CREATED",
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
                value = result.get(source_key)
                updates[key] = _to_float(value) if key in ("entry", "stop_loss", "tp1", "tp2", "entry_score", "score") else value

    updated = update_active_signal(signal_id, **updates)
    if updated:
        update_signal_result(signal_id, "ACTIVATED", "entry activated")
    return updated


def check_active_signals():
    """Check ACTIVATED signals for TP1/TP2/SL.

    SETUP signals are intentionally kept active but are not checked for TP/SL
    until bot.py or reply parsing marks them as ACTIVATED.

    Important fixes:
    - Already activated reply-tracked messages can now be checked.
    - TP2 hit before TP1 records TP1 first, then TP2, so stats do not miss wins.
    - SL is recorded only before TP1, keeping win rate based on TP1 vs SL.
    - Bad/missing data does not remove the signal from tracking.
    """
    data = load_active()
    active = data.get("active", [])
    remaining = []
    events = []

    for s in active:
        try:
            # Backward compatibility: older records may have result=ACTIVATED but no stage.
            if s.get("stage") != "ACTIVATED" and s.get("result") == "ACTIVATED":
                s["stage"] = "ACTIVATED"

            if s.get("stage") != "ACTIVATED":
                remaining.append(s)
                continue

            symbol = s.get("symbol")
            price_data = get_latest_price(symbol)
            if not isinstance(price_data, dict) or not price_data.get("success"):
                remaining.append(s)
                continue

            price = _to_float(price_data.get("price"))
            direction = s.get("direction")
            tp1 = _to_float(s.get("tp1"))
            sl = _to_float(s.get("stop_loss"))
            tp2 = _to_float(s.get("tp2"))
            tp1_hit = bool(s.get("tp1_hit"))

            if price is None or direction not in ("BUY", "SELL") or tp1 is None or sl is None:
                remaining.append(s)
                continue

            hit_tp1 = False
            hit_tp2 = False
            hit_sl = False

            if direction == "BUY":
                hit_tp1 = price >= tp1
                hit_tp2 = tp2 is not None and price >= tp2
                hit_sl = price <= sl
            elif direction == "SELL":
                hit_tp1 = price <= tp1
                hit_tp2 = tp2 is not None and price <= tp2
                hit_sl = price >= sl

            # If TP2 is reached before TP1 was recorded, record TP1 first for win-rate stats.
            if hit_tp2 and not tp1_hit:
                s["tp1_hit"] = True
                s["tp1_hit_at"] = _utc_now()
                update_signal_result(s.get("signal_id"), "TP1", f"price={price}; auto-recorded before TP2")
                events.append({"signal": dict(s), "result": "TP1", "price": price})
                tp1_hit = True

            if hit_tp2:
                s["result"] = "TP2"
                s["closed_at"] = _utc_now()
                update_signal_result(s.get("signal_id"), "TP2", f"price={price}")
                events.append({"signal": dict(s), "result": "TP2", "price": price})
                continue

            if hit_tp1 and not tp1_hit:
                s["tp1_hit"] = True
                s["tp1_hit_at"] = _utc_now()
                s["result"] = "TP1"
                update_signal_result(s.get("signal_id"), "TP1", f"price={price}")
                events.append({"signal": dict(s), "result": "TP1", "price": price})
                remaining.append(s)
                continue

            # SL before TP1 closes the signal as a loss. After TP1, SL is not counted as loss.
            if hit_sl and not tp1_hit:
                s["result"] = "SL"
                s["closed_at"] = _utc_now()
                update_signal_result(s.get("signal_id"), "SL", f"price={price}")
                events.append({"signal": dict(s), "result": "SL", "price": price})
                continue

            remaining.append(s)
        except Exception as exc:
            s["last_tracker_error"] = str(exc)
            s["last_tracker_error_at"] = _utc_now()
            remaining.append(s)

    data["active"] = remaining
    save_active(data)
    return events

def format_active_signals():
    active = list_active_signals()
    if not active:
        return "👁 هیچ سیگنال فعالی زیر نظر نیست."

    lines = ["👁 سیگنال‌های زیر نظر", ""]
    for s in active:
        direction_text = "خرید" if s.get("direction") == "BUY" else "فروش"
        stage_text = "✅ ورود فعال" if s.get("stage") == "ACTIVATED" else "👀 منتظر فعال‌سازی ورود"
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
