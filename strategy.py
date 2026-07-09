"""اصل ۱ و ۲ ربات: شکار حرکت و تشخیص جهت.
این فایل باید سریع‌ترین مسیر تحلیلی باشد و هیچ کار سنگین روزانه داخل آن انجام نشود.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

import config

@dataclass
class StrategySignal:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    side: str
    entry: float
    strength: str
    strength_score: float
    compression_score: float
    flow_bias: float
    absorption_score: float
    reason: str

def pct_range(c: dict[str, float]) -> float:
    close = float(c["close"])
    return (float(c["high"]) - float(c["low"])) / close * 100.0 if close > 0 else 0.0

def signed_body(c: dict[str, float]) -> float:
    close = float(c["close"])
    if close <= 0:
        return 0.0
    return (float(c["close"]) - float(c["open"])) / close * 100.0

def detect_compression(candles: list[dict[str, float]]) -> tuple[bool, float, str]:
    if len(candles) < config.COMPRESSION_LOOKBACK + 5:
        return False, 0.0, "candles_too_few"
    recent = candles[-config.COMPRESSION_RECENT:]
    lookback = candles[-config.COMPRESSION_LOOKBACK:]
    recent_ranges = [pct_range(c) for c in recent]
    all_ranges = [pct_range(c) for c in lookback]
    med_recent = median(recent_ranges)
    med_all = median(all_ranges) or 1e-9
    ratio = med_recent / med_all
    body_move = abs((recent[-1]["close"] - recent[0]["open"]) / recent[0]["open"] * 100.0)
    ok = ratio <= config.COMPRESSION_RATIO_MAX and body_move <= config.PREMOVE_PRICE_MOVE_MAX_PCT
    score = max(0.0, min(1.0, 1.0 - ratio))
    return ok, score, f"compression_ratio={ratio:.3f};body_move={body_move:.3f}%"

def pre_move_flow_bias(candles: list[dict[str, float]]) -> float:
    """نسخه سبک Taker Flow Proxy.
    اگر دیتای واقعی taker buy/sell اضافه شود، فقط همین تابع عوض می‌شود.
    فعلاً از بدنه کندل و حجم نسبی برای تخمین فشار داخل فشردگی استفاده می‌کند.
    """
    recent = candles[-config.FLOW_BIAS_LOOKBACK:]
    total_vol = sum(max(float(c.get("vol_quote") or c.get("volume") or 0.0), 0.0) for c in recent) or 1e-9
    s = 0.0
    for c in recent:
        vol = max(float(c.get("vol_quote") or c.get("volume") or 0.0), 0.0)
        rng = max(float(c["high"]) - float(c["low"]), 1e-12)
        body_pos = (float(c["close"]) - float(c["open"])) / rng
        s += max(-1.0, min(1.0, body_pos)) * (vol / total_vol)
    return max(-1.0, min(1.0, s))

def absorption_score(candles: list[dict[str, float]], side: str) -> float:
    recent = candles[-config.FLOW_BIAS_LOOKBACK:]
    lows = [float(c["low"]) for c in recent]
    highs = [float(c["high"]) for c in recent]
    closes = [float(c["close"]) for c in recent]
    if side == "LONG":
        # فروش/فشار پایین هست ولی کف‌ها نمی‌شکنند و کلوزها به نیمه بالایی می‌آیند.
        low_stability = 1.0 - (max(lows) - min(lows)) / max(median(closes), 1e-9) * 100.0
        close_pos = sum((float(c["close"]) - float(c["low"])) / max(float(c["high"]) - float(c["low"]), 1e-9) for c in recent) / len(recent)
    else:
        high_stability = 1.0 - (max(highs) - min(highs)) / max(median(closes), 1e-9) * 100.0
        low_stability = high_stability
        close_pos = sum((float(c["high"]) - float(c["close"])) / max(float(c["high"]) - float(c["low"]), 1e-9) for c in recent) / len(recent)
    return max(0.0, min(1.0, 0.5 * max(0.0, low_stability) + 0.5 * close_pos))

def estimate_strength(candles: list[dict[str, float]], compression_score: float, flow_bias: float, absorption: float) -> tuple[str, float]:
    score = 0.40 * compression_score + 0.35 * abs(flow_bias) + 0.25 * absorption
    if score >= 0.72:
        label = "خیلی قوی"
    elif score >= 0.58:
        label = "قوی"
    elif score >= 0.45:
        label = "متوسط"
    else:
        label = "ضعیف"
    return label, round(score * 100.0, 2)

def analyze_symbol(symbol_id: str, okx_symbol: str, toobit_symbol: str, candles: list[dict[str, float]]) -> StrategySignal | None:
    comp_ok, comp_score, comp_reason = detect_compression(candles)
    if not comp_ok:
        return None
    bias = pre_move_flow_bias(candles)
    if abs(bias) < config.FLOW_BIAS_MIN_ABS:
        return None
    side = "LONG" if bias > 0 else "SHORT"
    absorb = absorption_score(candles, side)
    if absorb < config.ABSORPTION_MIN_SCORE:
        return None
    entry = float(candles[-1]["close"])
    strength, strength_score = estimate_strength(candles, comp_score, bias, absorb)

    # Gate کیفیت سیگنال: سیگنال ضعیف یا مرزی باعث استاپ سریع می‌شود.
    # اینجا قدرت روند را شرط نمی‌کنیم؛ فقط قفل جهت/کیفیت حداقلی سیگنال را چک می‌کنیم.
    if (not getattr(config, "ALLOW_WEAK_SIGNALS", False)) and strength == "ضعیف":
        return None
    if strength_score < float(getattr(config, "MIN_SIGNAL_STRENGTH_SCORE", 55.0)):
        return None

    return StrategySignal(
        symbol_id=symbol_id,
        okx_symbol=okx_symbol,
        toobit_symbol=toobit_symbol,
        side=side,
        entry=entry,
        strength=strength,
        strength_score=strength_score,
        compression_score=round(comp_score * 100.0, 2),
        flow_bias=round(bias, 4),
        absorption_score=round(absorb * 100.0, 2),
        reason=f"Compression + FlowBias + Absorption | {comp_reason}",
    )
