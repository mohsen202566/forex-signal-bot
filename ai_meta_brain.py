from __future__ import annotations

from dataclasses import dataclass

from config import GHOST_THRESHOLD, SIGNAL_THRESHOLD, WATCH_THRESHOLD
from scorer import SignalDecision


@dataclass(frozen=True)
class MetaDecision:
    action: str
    accepted: bool
    ready_alert: bool
    signal_label: str
    real_allowed: bool
    real_block_reason: str | None
    reason: str


class AIMetaBrain:
    def decide(self, *, total_score: int, entry_quality: str, risk_ok: bool, net_profit_ok: bool, range_verdict: str, pattern_verdict: str, session_state: str, market_mode: str) -> MetaDecision:
        real_qualities = {"EARLY_IGNITION", "GOOD_ENTRY", "POWER_BUILDING", "REVERSAL_BUILDING"}
        clean = entry_quality in real_qualities and risk_ok
        if total_score < WATCH_THRESHOLD:
            return MetaDecision("REJECT", False, False, "رد داخلی", False, "امتیاز کافی نیست", "AI هنوز فرصت تمیز ندیده است.")
        if not clean:
            return MetaDecision("WATCH", False, total_score >= WATCH_THRESHOLD, "کاندید یادگیری", False, "ورود دقیق یا TP/SL کامل تایید نشد", "AI فرصت را برای یادگیری زیر نظر گرفت.")
        if range_verdict == "NEGATIVE" or pattern_verdict == "NEGATIVE" or session_state == "BAD_REAL_ONLY_NORMAL" or market_mode == "CLIMAX_RISK":
            if total_score >= GHOST_THRESHOLD:
                return MetaDecision("SIGNAL", True, False, "سیگنال عادی هوشمند", False, "AI Real را برای این شرایط مناسب نمی‌داند", "سیگنال عادی صادر شد؛ Real به‌خاطر حافظه/ریسک محدود شد.")
            return MetaDecision("WATCH", False, True, "واچ هوشمند", False, "AI Real را برای این شرایط مناسب نمی‌داند", "AI فقط واچ/یادگیری را تایید کرد.")
        if total_score >= SIGNAL_THRESHOLD:
            real_allowed = net_profit_ok
            return MetaDecision("SIGNAL", True, False, "شکار اسکالپ", real_allowed, None if real_allowed else "سود خالص Real کمتر از حداقل است", "سیگنال اسکالپ معتبر است؛ ورود دقیق و TP/SL تایید شد.")
        if total_score >= GHOST_THRESHOLD:
            return MetaDecision("SIGNAL", True, False, "سیگنال عادی", False, "امتیاز برای Real کافی نیست", "سیگنال عادی برای یادگیری و پایش صادر شد.")
        return MetaDecision("WATCH", False, True, "اسکالپ واچ", False, "امتیاز هنوز برای سیگنال کامل نیست", "شکارگاه فعال است؛ AI منتظر دقت بیشتر می‌ماند.")
