from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TpSlResult:
    status: str
    result_source: str
    description: str


class TpSlResultEngine:
    _AI_EXIT_DESCRIPTIONS = {
        "AI_EXIT_PROFIT": "خروج هوشمند AI با سود",
        "AI_EXIT_BREAKEVEN": "خروج هوشمند AI نزدیک سربه‌سر",
        "AI_EXIT_DAMAGE_CONTROL": "خروج هوشمند AI قبل از استاپ",
        "AI_EXIT_REVERSAL": "خروج هوشمند AI با برگشت/ضعف",
        "EXIT": "خروج هوشمند AI",
    }

    def classify(self, *, status: str, signal_type: str, real_status: str, real_pnl_available: bool) -> TpSlResult:
        if status in self._AI_EXIT_DESCRIPTIONS:
            source = "toobit_real" if signal_type == "real" and real_status in {"opened", "closed"} else "normal"
            return TpSlResult(status=status, result_source=source, description=self._AI_EXIT_DESCRIPTIONS[status])
        if signal_type == "real" and real_status in {"opened", "closed"} and real_pnl_available:
            return TpSlResult(status=status, result_source="toobit_real", description="TP/SL واقعی توبیت")
        if signal_type == "real" and real_status in {"opened", "closed"}:
            return TpSlResult(status=status, result_source="normal_on_real", description="TP/SL عادی روی سیگنال واقعی")
        if signal_type == "normal":
            return TpSlResult(status=status, result_source="normal", description="TP/SL عادی ربات")
        return TpSlResult(status=status, result_source="ghost_or_failed", description="نتیجه Ghost/Failed")
