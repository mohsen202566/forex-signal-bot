"""ابزارهای مشترک ریشه‌ای؛ با toobit_client.py ثابت سازگار است."""
from __future__ import annotations

import json
import logging
import math
import os
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger("dift5m")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    try:
        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass


def now_ms() -> int:
    return int(time.time() * 1000)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def decimal_round_down(value: float | str | Decimal, step: str | float | Decimal | None = None, digits: int = 8) -> str:
    dec = Decimal(str(value))
    if step not in (None, "", 0, "0"):
        step_dec = Decimal(str(step))
        if step_dec > 0:
            dec = (dec / step_dec).to_integral_value(rounding=ROUND_DOWN) * step_dec
            return format(dec.normalize(), "f")
    quant = Decimal("1") / (Decimal("10") ** int(digits))
    return format(dec.quantize(quant, rounding=ROUND_DOWN).normalize(), "f")


def pct_change(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return (a - b) / b * 100.0


def pct_distance(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return abs(a - b) / b * 100.0


def extract_filter(info: dict[str, Any], filter_type: str) -> dict[str, Any]:
    filters = info.get("filters") or info.get("filter") or []
    if isinstance(filters, dict):
        return filters.get(filter_type) or filters.get(filter_type.lower()) or {}
    if isinstance(filters, list):
        for f in filters:
            if not isinstance(f, dict):
                continue
            if str(f.get("filterType") or f.get("type") or "").upper() == filter_type.upper():
                return f
    return {}


def side_to_toobit_position(side: str | None) -> str:
    s = str(side or "").upper()
    if s in {"BUY", "LONG", "BUY_OPEN"}:
        return "LONG"
    if s in {"SELL", "SHORT", "SELL_OPEN"}:
        return "SHORT"
    return s


def side_to_toobit_open(side: str | None) -> str:
    s = str(side or "").upper()
    if s in {"BUY", "LONG", "BUY_OPEN"}:
        return "BUY_OPEN"
    if s in {"SELL", "SHORT", "SELL_OPEN"}:
        return "SELL_OPEN"
    return s


def opposite_side(side: str) -> str:
    return "SELL" if side.upper() == "BUY" else "BUY"


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").replace("-", "").replace("_", "").replace("/", "").upper()


def to_okx_inst_id(symbol: str) -> str:
    s = normalize_symbol(symbol)
    if s.endswith("USDT"):
        base = s[:-4]
        return f"{base}-USDT-{config.OKX_INST_TYPE}"
    return s


def toobit_symbol_candidates(internal_symbol: str) -> list[str]:
    s = normalize_symbol(internal_symbol)
    candidates = [s]
    if s.endswith("USDT"):
        base = s[:-4]
        candidates += [f"{base}USDT", f"{base}-USDT", f"{base}_USDT"]
    out: list[str] = []
    for c in candidates:
        if c and c not in out:
            out.append(c)
    return out


def load_json(path: str, default: Any) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("خواندن JSON ناموفق بود %s: %s", path, exc)
        return default


def save_json(path: str, data: Any) -> None:
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def append_jsonl(path: str, item: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def human_price(x: float) -> str:
    if x >= 100:
        return f"{x:.2f}"
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.8f}"


def is_admin(user_id: int | None) -> bool:
    if not config.TELEGRAM_ADMIN_IDS:
        return True
    return int(user_id or 0) in config.TELEGRAM_ADMIN_IDS
