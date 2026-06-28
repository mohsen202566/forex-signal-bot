from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScalpWindowResult:
    result_5m: str = "pending"
    result_10m: str = "pending"
    result_15m: str = "pending"


class ScalpLearningEngine:
    """Placeholder-safe learning layer for 5m/10m/15m summaries.

    The monitor stores final TP/SL and indicator ranges immediately; this class exists so future
    expansion can add timed snapshots without changing imports or storage contracts.
    """

    def empty(self) -> ScalpWindowResult:
        return ScalpWindowResult()
