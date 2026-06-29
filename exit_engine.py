from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from config import (
    AI_EXIT_BREAKEVEN_BUFFER_PCT,
    AI_EXIT_DAMAGE_CONTROL_ADVERSE_RATIO,
    AI_EXIT_ENABLED,
    AI_EXIT_GIVEBACK_RATIO,
    AI_EXIT_MIN_ACTIVE_SECONDS,
    AI_EXIT_MIN_GIVEBACK_PCT,
    AI_EXIT_MIN_PROFIT_PCT,
    AI_EXIT_REVERSAL_TICKS,
    AI_EXIT_RISKY_GIVEBACK_RATIO,
    AI_EXIT_TARGET_ZONE_RATIO,
)
from storage import StoredSignal


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str
    status: str | None = None
    exit_price: float | None = None
    exit_score: int = 0
    giveback_pct: float = 0.0
    target_zone_reached: bool = False


class ExitEngine:
    """Second-by-second AI exit brain.

    TP is treated as a mental target zone, not as a forced close. The position is
    held while the wave is healthy, even after the target zone is crossed. The
    engine exits only when live price action shows weakness, a reversal, heavy
    giveback, or damage-control conditions before the hard SL.
    """

    _RISKY_ENTRY_QUALITIES = {"PRECISION_WAIT", "EXHAUSTION_RISK", "NOISE_RISK", "WEAK_MOVEMENT", "NO_ENTRY"}
    _RISKY_MARKET_MODES = {"CLIMAX_RISK", "NOISY"}

    def analyze(
        self,
        signal: StoredSignal,
        price: float,
        *,
        mfe_pct: float | None = None,
        mae_pct: float | None = None,
        recent_prices: tuple[float, ...] = (),
    ) -> ExitDecision:
        if not AI_EXIT_ENABLED:
            return ExitDecision(False, "")
        if signal.entry <= 0 or price <= 0:
            return ExitDecision(False, "")
        if self._age_seconds(signal.created_at) < AI_EXIT_MIN_ACTIVE_SECONDS:
            return ExitDecision(False, "")

        entry = float(signal.entry)
        reward_abs = abs(float(signal.tp) - entry)
        risk_abs = abs(entry - float(signal.sl))
        if reward_abs <= 0 or risk_abs <= 0:
            return ExitDecision(False, "")

        signed_profit_pct = self._signed_profit_pct(signal.direction, entry, price)
        current_profit_pct = max(0.0, signed_profit_pct)
        current_loss_pct = max(0.0, -signed_profit_pct)
        mfe = max(float(signal.mfe_pct or 0.0), float(mfe_pct or 0.0), current_profit_pct)
        mae = max(float(signal.mae_pct or 0.0), float(mae_pct or 0.0), current_loss_pct)

        progress = self._progress_to_target(signal.direction, entry, price, reward_abs)
        adverse = self._adverse_to_sl(signal.direction, entry, price, risk_abs)
        target_zone = progress >= AI_EXIT_TARGET_ZONE_RATIO
        target_crossed = progress >= 1.0
        risky_context = (signal.entry_quality or "") in self._RISKY_ENTRY_QUALITIES or (signal.market_mode or "") in self._RISKY_MARKET_MODES
        giveback_ratio_limit = AI_EXIT_RISKY_GIVEBACK_RATIO if risky_context else AI_EXIT_GIVEBACK_RATIO
        giveback_pct = max(0.0, (mfe - current_profit_pct) / max(mfe, 1e-9)) if mfe > 0 else 0.0
        from_peak_pct = max(0.0, mfe - current_profit_pct)

        recent = tuple(float(x) for x in recent_prices if float(x) > 0)
        if not recent or abs(recent[-1] - price) > max(entry * 0.000001, 1e-12):
            recent = (*recent, price)
        pulse = self._pulse(signal.direction, entry, recent)

        weakness_score = 0
        reasons: list[str] = []
        min_profit_activation = max(AI_EXIT_MIN_PROFIT_PCT, (reward_abs / entry) * 0.18)
        giveback_abs_limit = max(AI_EXIT_MIN_GIVEBACK_PCT, mfe * giveback_ratio_limit)

        if target_zone:
            weakness_score += 1
            reasons.append("قیمت وارد Target Zone ذهنی شده است؛ AI حساس‌تر موج را تماشا می‌کند.")
        if target_crossed:
            weakness_score += 1
            reasons.append("TP ذهنی رد شده اما تا دیدن ضعف اجباری برای خروج نیست.")
        if mfe >= min_profit_activation and giveback_pct >= giveback_ratio_limit and from_peak_pct >= giveback_abs_limit:
            weakness_score += 3
            reasons.append(f"سود از سقف موج {giveback_pct * 100:.1f}% پس داده شد.")
        if pulse["adverse_ticks"] >= AI_EXIT_REVERSAL_TICKS:
            weakness_score += 2
            reasons.append("چند تیک پشت‌سرهم خلاف جهت پوزیشن دیده شد.")
        if pulse["recent_move_pct"] <= -max(AI_EXIT_MIN_GIVEBACK_PCT * 0.55, mfe * 0.12, 0.00020):
            weakness_score += 2
            reasons.append("شیب چند ثانیه اخیر خلاف موج شده است.")
        if pulse["from_local_peak_pct"] >= max(AI_EXIT_MIN_GIVEBACK_PCT, mfe * 0.16) and mfe >= min_profit_activation:
            weakness_score += 2
            reasons.append("از سقف/کف محلی موج برگشت قابل توجه دیده شد.")
        if risky_context and mfe >= min_profit_activation and weakness_score >= 2:
            weakness_score += 1
            reasons.append("Context ورود/بازار ریسکی است؛ AI زودتر سود شناور را محافظت می‌کند.")

        trend_alive = self._trend_alive(pulse, current_profit_pct, mfe, giveback_pct, giveback_ratio_limit)
        if trend_alive and weakness_score < 4:
            return ExitDecision(False, "")

        if mfe >= min_profit_activation and weakness_score >= (3 if target_zone else 4):
            if signed_profit_pct > AI_EXIT_BREAKEVEN_BUFFER_PCT:
                return ExitDecision(
                    True,
                    " | ".join(reasons) or "ضعف موج بعد از ورود به سود دیده شد.",
                    "AI_EXIT_PROFIT",
                    price,
                    weakness_score,
                    giveback_pct,
                    target_zone,
                )
            return ExitDecision(
                True,
                " | ".join(reasons) or "سود شناور برگشت؛ AI نزدیک سربه‌سر خارج شد.",
                "AI_EXIT_BREAKEVEN",
                price,
                weakness_score,
                giveback_pct,
                target_zone,
            )

        reversal_score = weakness_score
        if pulse["adverse_ticks"] >= AI_EXIT_REVERSAL_TICKS + 1:
            reversal_score += 1
        if pulse["recent_move_pct"] <= -0.00035:
            reversal_score += 1
        if adverse >= AI_EXIT_DAMAGE_CONTROL_ADVERSE_RATIO and reversal_score >= 4:
            return ExitDecision(
                True,
                " | ".join(reasons) or "جهت سریع برگشت و AI قبل از استاپ کامل خروج زد.",
                "AI_EXIT_DAMAGE_CONTROL",
                price,
                reversal_score,
                giveback_pct,
                target_zone,
            )

        if reversal_score >= 5 and (mfe >= min_profit_activation or adverse >= 0.25):
            status = "AI_EXIT_PROFIT" if signed_profit_pct > AI_EXIT_BREAKEVEN_BUFFER_PCT else "AI_EXIT_REVERSAL"
            return ExitDecision(
                True,
                " | ".join(reasons) or "کندل/حرکت برگشتی معتبر در موج دیده شد.",
                status,
                price,
                reversal_score,
                giveback_pct,
                target_zone,
            )

        return ExitDecision(False, "")

    @staticmethod
    def _age_seconds(created_at: str) -> float:
        try:
            created = datetime.fromisoformat(created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - created).total_seconds())
        except Exception:
            return float(AI_EXIT_MIN_ACTIVE_SECONDS)

    @staticmethod
    def _signed_profit_pct(direction: str, entry: float, price: float) -> float:
        if direction == "LONG":
            return (price - entry) / entry
        return (entry - price) / entry

    @staticmethod
    def _progress_to_target(direction: str, entry: float, price: float, reward_abs: float) -> float:
        move = price - entry if direction == "LONG" else entry - price
        return move / max(reward_abs, 1e-9)

    @staticmethod
    def _adverse_to_sl(direction: str, entry: float, price: float, risk_abs: float) -> float:
        adverse = entry - price if direction == "LONG" else price - entry
        return max(0.0, adverse / max(risk_abs, 1e-9))

    @staticmethod
    def _pulse(direction: str, entry: float, prices: tuple[float, ...]) -> dict[str, float | int]:
        if len(prices) < 2:
            return {"recent_move_pct": 0.0, "adverse_ticks": 0, "favorable_ticks": 0, "from_local_peak_pct": 0.0}
        tail = prices[-12:]
        signed_steps: list[float] = []
        for prev, cur in zip(tail, tail[1:]):
            move = (cur - prev) / entry if direction == "LONG" else (prev - cur) / entry
            signed_steps.append(move)
        adverse_ticks = 0
        for move in reversed(signed_steps):
            if move < 0:
                adverse_ticks += 1
            else:
                break
        favorable_ticks = 0
        for move in reversed(signed_steps):
            if move > 0:
                favorable_ticks += 1
            else:
                break
        recent_move_pct = (tail[-1] - tail[0]) / entry if direction == "LONG" else (tail[0] - tail[-1]) / entry
        if direction == "LONG":
            local_peak = max(tail)
            from_local_peak_pct = max(0.0, (local_peak - tail[-1]) / entry)
        else:
            local_peak = min(tail)
            from_local_peak_pct = max(0.0, (tail[-1] - local_peak) / entry)
        return {
            "recent_move_pct": float(recent_move_pct),
            "adverse_ticks": int(adverse_ticks),
            "favorable_ticks": int(favorable_ticks),
            "from_local_peak_pct": float(from_local_peak_pct),
        }

    @staticmethod
    def _trend_alive(pulse: dict[str, float | int], current_profit_pct: float, mfe_pct: float, giveback_pct: float, giveback_limit: float) -> bool:
        if current_profit_pct <= 0:
            return False
        favorable_ticks = int(pulse["favorable_ticks"])
        adverse_ticks = int(pulse["adverse_ticks"])
        recent_move_pct = float(pulse["recent_move_pct"])
        if favorable_ticks >= adverse_ticks and recent_move_pct >= 0:
            return True
        if mfe_pct > 0 and giveback_pct < max(0.16, giveback_limit * 0.55) and recent_move_pct > -0.00018:
            return True
        return False
