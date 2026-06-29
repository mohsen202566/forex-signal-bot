from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSymbol:
    name: str
    okx_inst_id: str
    toobit_symbol: str
    role: str = "main"


MAIN_SYMBOLS: tuple[MarketSymbol, ...] = (
    MarketSymbol("SOL", "SOL-USDT-SWAP", "SOL-SWAP-USDT", "main"),
    MarketSymbol("XRP", "XRP-USDT-SWAP", "XRP-SWAP-USDT", "main"),
    MarketSymbol("DOGE", "DOGE-USDT-SWAP", "DOGE-SWAP-USDT", "main"),
    MarketSymbol("AVAX", "AVAX-USDT-SWAP", "AVAX-SWAP-USDT", "main"),
    MarketSymbol("LINK", "LINK-USDT-SWAP", "LINK-SWAP-USDT", "main"),
)

ALTERNATIVE_SYMBOLS: tuple[MarketSymbol, ...] = (
    MarketSymbol("SUI", "SUI-USDT-SWAP", "SUI-SWAP-USDT", "alternative"),
    MarketSymbol("ADA", "ADA-USDT-SWAP", "ADA-SWAP-USDT", "alternative"),
    MarketSymbol("LTC", "LTC-USDT-SWAP", "LTC-SWAP-USDT", "alternative"),
    MarketSymbol("NEAR", "NEAR-USDT-SWAP", "NEAR-SWAP-USDT", "alternative"),
)

SYMBOLS: tuple[MarketSymbol, ...] = MAIN_SYMBOLS + ALTERNATIVE_SYMBOLS
ACTIVE_SYMBOLS: tuple[MarketSymbol, ...] = MAIN_SYMBOLS
SYMBOL_BY_NAME = {symbol.name: symbol for symbol in SYMBOLS}
