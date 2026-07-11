"""۱۰ نماد پایه با مپ یکسان OKX/Toobit.
انتخاب نهایی عملکردی فقط پس از بک‌تست معتبر است؛ این فهرست universe اولیه نقدشونده است.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class SymbolMap:
    id: str
    okx: str
    toobit: str
    base: str
    quote: str = "USDT"

SYMBOLS: list[SymbolMap] = [
    SymbolMap("BTC", "BTC-USDT-SWAP", "BTCUSDT", "BTC"),
    SymbolMap("ETH", "ETH-USDT-SWAP", "ETHUSDT", "ETH"),
    SymbolMap("SOL", "SOL-USDT-SWAP", "SOLUSDT", "SOL"),
    SymbolMap("BNB", "BNB-USDT-SWAP", "BNBUSDT", "BNB"),
    SymbolMap("XRP", "XRP-USDT-SWAP", "XRPUSDT", "XRP"),
    SymbolMap("DOGE", "DOGE-USDT-SWAP", "DOGEUSDT", "DOGE"),
    SymbolMap("ADA", "ADA-USDT-SWAP", "ADAUSDT", "ADA"),
    SymbolMap("LINK", "LINK-USDT-SWAP", "LINKUSDT", "LINK"),
    SymbolMap("AVAX", "AVAX-USDT-SWAP", "AVAXUSDT", "AVAX"),
    SymbolMap("SUI", "SUI-USDT-SWAP", "SUIUSDT", "SUI"),
]
BY_ID = {s.id: s for s in SYMBOLS}
BY_OKX = {s.okx: s for s in SYMBOLS}
BY_TOOBIT = {s.toobit: s for s in SYMBOLS}
def get_symbol(symbol_id: str) -> SymbolMap | None:
    return BY_ID.get(symbol_id.upper())
