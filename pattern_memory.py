from __future__ import annotations

from dataclasses import dataclass

from config import WEIGHTS
from scorer import Direction, PatternLabel


@dataclass(frozen=True)
class MemoryResult:
    score: int
    confidence: int
    experience: int
    adjustment: int
    expected_move_pct: float | None
    reasons: tuple[str, ...]


class PatternMemory:
    def analyze(self, storage, symbol_name: str, direction: Direction, pattern: PatternLabel, rsi: float, adx: float, volume_ratio: float) -> MemoryResult:
        stats = storage.pattern_stats(symbol_name, direction, pattern, rsi, adx, volume_ratio)
        samples = int(stats.get("samples", 0))
        wr = float(stats.get("win_rate", 0.0))
        avg_mfe = float(stats.get("avg_mfe", 0.0))
        adjustment = 0
        if samples >= 35:
            adjustment = max(-6, min(6, int((wr - 50.0) / 6.0)))
        elif samples >= 12:
            adjustment = max(-3, min(3, int((wr - 50.0) / 10.0)))
        confidence = 45
        if samples >= 8:
            confidence = int(max(30, min(99, wr + min(15, samples // 5) + adjustment)))
        base = 6 if samples < 8 else 8
        score = max(0, min(WEIGHTS.ai_memory, base + adjustment))
        expected = avg_mfe if samples >= 8 and avg_mfe > 0 else None
        reasons = [f"AI Pattern={samples} نمونه، WR={wr:.1f}%"]
        if samples < 8:
            reasons.append("نمونه کافی نیست؛ اثر Pattern Memory کم است.")
        else:
            reasons.append("Pattern Memory روی تصمیم اسکالپ اثر واقعی داد.")
        return MemoryResult(score, confidence, samples, adjustment, expected, tuple(reasons))
