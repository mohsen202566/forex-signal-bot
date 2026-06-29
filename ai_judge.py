from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Judgement:
    entry_quality: str
    tp_quality: str
    sl_quality: str
    failure_reason: str
    score_delta: int
    reasons: tuple[str, ...]


class AIJudge:
    _WIN_STATUSES = {"TP", "AI_EXIT_PROFIT"}
    _PROTECT_STATUSES = {"AI_EXIT_BREAKEVEN"}
    _LOSS_STATUSES = {"SL", "AI_EXIT_DAMAGE_CONTROL", "AI_EXIT_REVERSAL"}

    def judge_closed_signal(self, signal: dict) -> Judgement:
        status = str(signal.get("status") or "")
        mfe = float(signal.get("mfe_pct") or 0.0)
        mae = float(signal.get("mae_pct") or 0.0)
        pnl = float(signal.get("approx_pnl") or 0.0)
        expected = abs(float(signal.get("tp") or 0.0) - float(signal.get("entry") or 0.0)) / max(float(signal.get("entry") or 1.0), 1e-9)
        risk = abs(float(signal.get("entry") or 0.0) - float(signal.get("sl") or 0.0)) / max(float(signal.get("entry") or 1.0), 1e-9)
        reasons: list[str] = []

        win_like = status in self._WIN_STATUSES or (status == "AI_EXIT_BREAKEVEN" and pnl >= 0)
        loss_like = status in self._LOSS_STATUSES or (status == "AI_EXIT_BREAKEVEN" and pnl < 0)
        entry_quality = "good" if win_like or mae <= risk * 0.55 else "needs_precision"
        tp_quality = "ai_managed" if status.startswith("AI_EXIT") else "good" if status == "TP" else "review"
        sl_quality = "protected" if status in {"AI_EXIT_BREAKEVEN", "AI_EXIT_DAMAGE_CONTROL"} else "good" if status == "SL" and mae >= risk * 0.90 else "review"
        failure_reason = "none"
        delta = 2 if status in self._WIN_STATUSES else 1 if status == "AI_EXIT_BREAKEVEN" and pnl >= 0 else -1 if status == "AI_EXIT_DAMAGE_CONTROL" else -2 if loss_like else 0

        if status == "TP":
            reasons.append("جهت و TP ثابت برای این الگو تایید شد.")
            if mfe > expected * 1.5:
                reasons.append("Shadow: احتمالاً TP می‌توانست بازتر باشد یا AI Exit نگه‌داری بهتری بدهد.")
        elif status == "AI_EXIT_PROFIT":
            reasons.append("AI موج را تا دیدن ضعف نگه داشت و با سود خارج شد.")
            if mfe > expected * 1.25:
                reasons.append("نگه‌داری بعد از Target Zone ارزشمند بوده؛ TP ذهنی نباید خروج اجباری باشد.")
        elif status == "AI_EXIT_BREAKEVEN":
            failure_reason = "profit_saved_or_exit_tight"
            reasons.append("AI بعد از برگشت سود شناور نزدیک سربه‌سر خارج شد؛ باید بررسی شود زود بوده یا ضرر را نجات داده.")
        elif status == "AI_EXIT_DAMAGE_CONTROL":
            failure_reason = "damage_control_before_sl"
            reasons.append("AI قبل از خوردن SL کامل خروج زد؛ برای کاهش ضرر ثبت شد.")
        elif status == "AI_EXIT_REVERSAL":
            failure_reason = "reversal_after_entry"
            reasons.append("برگشت/ضعف واقعی بعد از ورود دیده شد؛ کیفیت ورود یا نگه‌داری نیاز به تنظیم دارد.")
        elif status == "SL":
            if mfe >= expected * 0.55:
                failure_reason = "tp_too_far_or_exit_missed"
                reasons.append("قیمت بخشی از مسیر سود را رفت اما TP یا خروج AI بهینه نبود.")
            elif mae < risk * 0.75:
                failure_reason = "noise_or_bad_price_tracking"
                reasons.append("SL کامل با حرکت طبیعی پر نشده؛ بررسی نویز/قیمت لازم است.")
            else:
                failure_reason = "direction_or_entry_precision"
                reasons.append("جهت یا دقت ورود برای این الگو نیاز به اصلاح دارد.")
        else:
            failure_reason = "early_exit_or_failed"
            reasons.append("نتیجه غیر استاندارد برای یادگیری جدا ثبت شد.")
        return Judgement(entry_quality, tp_quality, sl_quality, failure_reason, delta, tuple(reasons))
