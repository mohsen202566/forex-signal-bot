import json
import os
from datetime import datetime, timedelta
from typing import Dict, List

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
        if "signals" not in data:
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
    for s in data["signals"]:
        if str(s.get("signal_id")) == str(signal_id):
            s["result"] = result
            s["closed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            s["close_reason"] = reason
            updated = True
            break
    save_stats(data)
    return updated


def reset_stats():
    save_stats({"signals": []})


def _filter_by_days(signals: List[Dict], days=None):
    if not days:
        return signals
    cutoff = datetime.utcnow() - timedelta(days=days)
    out = []
    for s in signals:
        created = s.get("created_at", "").replace("Z", "")
        try:
            dt = datetime.fromisoformat(created)
            if dt >= cutoff:
                out.append(s)
        except Exception:
            pass
    return out


def build_stats(days=None) -> Dict:
    data = load_stats()
    signals = _filter_by_days(data.get("signals", []), days)
    total = len(signals)
    tp = sum(1 for s in signals if s.get("result") == "TP1")
    sl = sum(1 for s in signals if s.get("result") == "SL")
    open_count = sum(1 for s in signals if s.get("result") == "OPEN")
    closed = tp + sl
    win_rate = round((tp / closed) * 100, 2) if closed else 0

    by_symbol = {}
    by_direction = {"BUY": {"tp": 0, "sl": 0, "total": 0}, "SELL": {"tp": 0, "sl": 0, "total": 0}}
    for s in signals:
        sym = s.get("symbol", "?")
        by_symbol.setdefault(sym, {"tp": 0, "sl": 0, "open": 0, "total": 0})
        by_symbol[sym]["total"] += 1
        if s.get("result") == "TP1":
            by_symbol[sym]["tp"] += 1
        elif s.get("result") == "SL":
            by_symbol[sym]["sl"] += 1
        else:
            by_symbol[sym]["open"] += 1
        d = s.get("direction")
        if d in by_direction:
            by_direction[d]["total"] += 1
            if s.get("result") == "TP1":
                by_direction[d]["tp"] += 1
            elif s.get("result") == "SL":
                by_direction[d]["sl"] += 1

    return {"total": total, "tp": tp, "sl": sl, "open": open_count, "closed": closed, "win_rate": win_rate, "by_symbol": by_symbol, "by_direction": by_direction}


def parse_days(text: str):
    for n in [3, 7, 14, 30, 60, 90]:
        if str(n) in text:
            return n
    if "讴賱" in text or "賴賲賴" in text:
        return None
    return None


def format_stats(days=None) -> str:
    st = build_stats(days)
    title = "丌賲丕乇 讴賱" if not days else f"丌賲丕乇 {days} 乇賵夭 丕禺蹖乇"
    lines = [
        f"馃搱 {title}",
        "",
        f"讴賱 爻蹖诏賳丕賱鈥屬囏й� 孬亘鬲鈥屫簇�: {st['total']}",
        f"TP1: {st['tp']}",
        f"SL: {st['sl']}",
        f"亘丕夭: {st['open']}",
        f"賵蹖賳鈥屫臂屫� 亘爻鬲賴鈥屫簇団�屬囏�: {st['win_rate']}侏",
        "",
        "毓賲賱讴乇丿 噩賴鬲鈥屬囏�:",
    ]
    for d, name in [("BUY", "禺乇蹖丿"), ("SELL", "賮乇賵卮")]:
        item = st["by_direction"][d]
        lines.append(f"鈥� {name}: 讴賱 {item['total']} | TP {item['tp']} | SL {item['sl']}")
    if st["by_symbol"]:
        lines.append("")
        lines.append("毓賲賱讴乇丿 賳賲丕丿賴丕:")
        for sym, item in st["by_symbol"].items():
            lines.append(f"鈥� {sym}: 讴賱 {item['total']} | TP {item['tp']} | SL {item['sl']} | 亘丕夭 {item['open']}")
    return "\n".join(lines)
