import json
import os
import re
from datetime import datetime
from typing import Dict, List

from config import DATA_DIR, TRACKER_FILE
from data_provider import get_latest_price
from statistics import record_signal, update_signal_result


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
        if "active" not in data:
            data["active"] = []
        return data
    except Exception:
        return {"active": []}


def save_active(data: Dict):
    ensure_storage()
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_signal_id(symbol: str) -> str:
    return symbol.replace("/", "") + "-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")


def add_active_signal(signal: Dict):
    data = load_active()
    existing_ids = {s.get("signal_id") for s in data["active"]}
    if signal.get("signal_id") in existing_ids:
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


def parse_signal_from_text(text: str):
    if not text:
        return None
    def get(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    symbol = get(r"نماد:\s*([A-Z]{3}/[A-Z]{3}|XAU/USD)") or get(r"تحلیل\s+([A-Z]{3}/[A-Z]{3}|XAU/USD)")
    direction_fa = "BUY" if ("خرید" in text or "BUY" in text.upper()) else ("SELL" if ("فروش" in text or "SELL" in text.upper()) else None)
    entry = get(r"Entry:\s*([0-9.]+)") or get(r"ورود:\s*([0-9.]+)")
    sl = get(r"SL:\s*([0-9.]+)") or get(r"استاپ:\s*([0-9.]+)")
    tp1 = get(r"TP1:\s*([0-9.]+)") or get(r"تی‌پی 1:\s*([0-9.]+)")
    score = get(r"امتیاز(?: پیش‌بینی)?:\s*([0-9.]+)")

    if not symbol or not direction_fa or not entry or not sl or not tp1:
        return None
    signal_id = get(r"شناسه:\s*([A-Z0-9\-]+)") or make_signal_id(symbol)
    try:
        return {
            "signal_id": signal_id,
            "symbol": symbol,
            "direction": direction_fa,
            "entry": float(entry),
            "stop_loss": float(sl),
            "tp1": float(tp1),
            "score": float(score) if score else 0,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "result": "OPEN",
        }
    except Exception:
        return None


def check_active_signals():
    data = load_active()
    active = data.get("active", [])
    remaining = []
    events = []

    for s in active:
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
    data["active"] = remaining
    save_active(data)
    return events


def format_active_signals():
    active = list_active_signals()
    if not active:
        return "👁 هیچ سیگنال فعالی زیر نظر نیست."
    lines = ["👁 سیگنال‌های فعال زیر نظر:", ""]
    for s in active:
        d = "خرید" if s.get("direction") == "BUY" else "فروش"
        lines.append(f"• {s.get('symbol')} | {d} | Entry: {s.get('entry')} | TP1: {s.get('tp1')} | SL: {s.get('stop_loss')} | شناسه: {s.get('signal_id')}")
    return "\n".join(lines)
