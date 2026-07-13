"""مدل‌های داده مشترک پروژه."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class MarketCandidate:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    side: str
    detected_at: int
    structure_level: float
    invalidation_price: float
    atr_pct: float
    expected_move_pct: float
    direction_reason: str
    source: str = "1H"

@dataclass
class WatchState:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    started_at: float
    candidate: MarketCandidate
    last_reanalysis_at: float = 0.0
    last_scenario_change_at: float = 0.0
    prices: list[float] = field(default_factory=list)
    trade_values: list[float] = field(default_factory=list)
    book_values: list[float] = field(default_factory=list)
    micro_values: list[float] = field(default_factory=list)
    opposite_pressure_count: int = 0
    aligned_pressure_count: int = 0
    break_seen_count: int = 0

    def append_snapshot(self, price: float, trade: float, book: float, micro: float, maxlen: int = 12) -> None:
        self.prices.append(float(price))
        self.trade_values.append(float(trade))
        self.book_values.append(float(book))
        self.micro_values.append(float(micro))
        for seq in (self.prices, self.trade_values, self.book_values, self.micro_values):
            if len(seq) > maxlen:
                del seq[:-maxlen]

@dataclass(frozen=True)
class MarketSignal:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    side: str
    entry: float
    invalidation_price: float
    atr_pct: float
    expected_move_pct: float
    strength: str
    direction_reason: str
    strength_reason: str
    entry_reason: str
    spread_pct: float
    trade_imbalance: float
    book_imbalance: float
    microprice_bias_pct: float

@dataclass(frozen=True)
class RiskPlan:
    entry: float
    tp: float
    sl: float
    rr_net: float
    sl_pct: float
    tp_pct: float
    notional: float
    quantity_estimate: float
    estimated_tp_gross: float
    estimated_tp_fees: float
    estimated_tp_net: float
    estimated_sl_gross_loss: float
    estimated_sl_fees: float
    estimated_sl_net_loss: float
    min_net_profit_ok: bool
    reason: str

@dataclass(frozen=True)
class MicroSnapshot:
    last: float
    bid: float
    ask: float
    spread_pct: float
    trade_imbalance: float
    book_imbalance: float
    microprice: float
    microprice_bias_pct: float
    trade_count: int
    raw: dict[str, Any]
