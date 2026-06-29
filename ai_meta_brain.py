from __future__ import annotations

from dataclasses import dataclass

from config import WATCH_THRESHOLD


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
    def decide(
        self,
        *,
        total_score: int,
        signal_threshold: int,
        real_threshold: int,
        entry_quality: str,
        risk_ok: bool,
        net_profit_ok: bool,
        range_verdict: str,
        pattern_verdict: str,
        session_state: str,
        market_mode: str,
    ) -> MetaDecision:
        real_qualities = {"EARLY_IGNITION", "GOOD_ENTRY", "POWER_BUILDING", "REVERSAL_BUILDING"}
        clean = entry_quality in real_qualities and risk_ok

        if total_score < WATCH_THRESHOLD:
            return MetaDecision("REJECT", False, False, "رد داخلی", False, "امتیاز کافی نیست", "AI هنوز فرصت تمیز ندیده است.")

        if not clean:
            return MetaDecision("WATCH", False, False, "کاندید داخلی", False, "ورود دقیق یا TP/SL کامل تایید نشد", "AI فرصت را داخلی زیر نظر گرفت؛ تلگرام شلوغ نمی‌شود.")

        memory_negative = range_verdict == "NEGATIVE" or pattern_verdict == "NEGATIVE"
        real_risk_blocked = memory_negative or session_state == "BAD_REAL_ONLY_NORMAL" or market_mode == "CLIMAX_RISK"

        if total_score >= signal_threshold:
            if real_risk_blocked:
                return MetaDecision("SIGNAL", True, False, "سیگنال عادی AI", False, "AI Real را برای این شرایط مناسب نمی‌داند", "سیگنال عادی صادر شد؛ Real به‌خاطر حافظه/ریسک محدود شد.")
            real_allowed = total_score >= real_threshold and net_profit_ok
            if real_allowed:
                return MetaDecision("SIGNAL", True, False, "شکار اسکالپ", True, None, "سیگنال معتبر است؛ Threshold یادگیرنده AI و شرایط Real تایید شد.")
            block = "امتیاز به Threshold یادگیرنده Real نرسید" if total_score < real_threshold else "سود خالص Real کمتر از حداقل است"
            return MetaDecision("SIGNAL", True, False, "سیگنال عادی", False, block, "سیگنال عادی صادر شد؛ Real هنوز توسط AI/Safety تایید نشد.")

        return MetaDecision("WATCH", False, False, "اسکالپ واچ", False, "امتیاز هنوز به Threshold یادگیرنده سیگنال نرسیده", "شکارگاه داخلی فعال است؛ AI منتظر دقت یا امتیاز بهتر می‌ماند.")
