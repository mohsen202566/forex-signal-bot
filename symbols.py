from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSymbol:
    name: str
    okx_inst_id: str
    toobit_symbol: str
    role: str = "main"


_SYMBOL_NAMES = (
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "TRX",
    "DOT", "NEAR", "APT", "ARB", "OP", "SUI", "SEI", "INJ", "LTC", "BCH",
    "ETC", "FIL", "ATOM", "AAVE", "UNI", "WIF", "ORDI", "PEPE", "SHIB", "FLOKI",
    "BONK", "WLD", "ICP", "XLM", "HBAR", "ALGO", "GALA", "APE", "SAND", "MANA",
    "LDO", "ENS", "DYDX", "CHZ", "CRV", "COMP", "SNX", "MKR", "ZEC", "DASH",
)

MAIN_SYMBOLS: tuple[MarketSymbol, ...] = tuple(
    MarketSymbol(name, f"{name}-USDT-SWAP", f"{name}USDT") for name in _SYMBOL_NAMES
)

CONTEXT_SYMBOLS: tuple[MarketSymbol, ...] = ()

ACTIVE_SYMBOLS = MAIN_SYMBOLS
SYMBOLS = MAIN_SYMBOLS + CONTEXT_SYMBOLS
SYMBOL_BY_NAME = {symbol.name: symbol for symbol in SYMBOLS}
