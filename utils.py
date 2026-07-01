from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pct_change(entry: float, target: float, direction: str = "LONG") -> float:
    if entry <= 0:
        return 0.0
    if direction.upper() == "SHORT":
        return (entry - target) / entry * 100.0
    return (target - entry) / entry * 100.0


def pct_distance(a: float, b: float) -> float:
    if a <= 0:
        return 0.0
    return abs(b - a) / a * 100.0


def risk_reward(entry: float, tp: float, sl: float, direction: str) -> float:
    reward = pct_change(entry, tp, direction)
    risk = pct_change(entry, sl, "SHORT" if direction.upper() == "LONG" else "LONG")
    if risk <= 0:
        return 0.0
    return reward / risk


def estimate_pnl_usdt(margin_usdt: float, leverage: int, move_pct: float) -> float:
    return float(margin_usdt) * int(leverage) * (float(move_pct) / 100.0)


def okx_symbol(base: str) -> str:
    base = normalize_base_symbol(base)
    return f"{base}-USDT-SWAP"


def toobit_symbol(base: str) -> str:
    base = normalize_base_symbol(base)
    return f"{base}-SWAP-USDT"


def display_symbol(base_or_symbol: str) -> str:
    base = normalize_base_symbol(base_or_symbol)
    return f"{base}/USDT"


def normalize_base_symbol(symbol: str) -> str:
    s = str(symbol).upper().strip()
    for suffix in ("-USDT-SWAP", "-SWAP-USDT", "USDT", "/USDT"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    s = s.replace("-", "").replace("/", "")
    # OKX renamed MATIC to POL on some venues; keep user whitelist flexible.
    if s == "RENDER":
        return "RENDER"
    return s


def parse_bool_fa(text: str) -> bool | None:
    t = str(text).strip().lower()
    if t in {"روشن", "فعال", "on", "true", "1", "yes"}:
        return True
    if t in {"خاموش", "غیرفعال", "off", "false", "0", "no"}:
        return False
    return None


def round_price(value: float, decimals: int = 8) -> float:
    if not math.isfinite(value):
        return 0.0
    q = Decimal("1") if decimals <= 0 else Decimal("1") / (Decimal("10") ** decimals)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def fmt_num(value: Any, decimals: int = 4) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(f) >= 100:
        decimals = min(decimals, 2)
    return f"{f:,.{decimals}f}".rstrip("0").rstrip(".")


def fmt_pct(value: Any, decimals: int = 2) -> str:
    try:
        return f"{float(value):.{decimals}f}%"
    except (TypeError, ValueError):
        return str(value)


def now_ms() -> int:
    import time
    return int(time.time() * 1000)
