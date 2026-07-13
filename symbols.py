"""پنجاه نماد ثابت و نگاشت OKX/Toobit؛ همه فایل‌ها در ریشه پروژه باقی می‌مانند."""
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
    SymbolMap("LINK", "LINK-USDT-SWAP", "LINKUSDT", "LINK"),
    SymbolMap("AVAX", "AVAX-USDT-SWAP", "AVAXUSDT", "AVAX"),
    SymbolMap("SUI", "SUI-USDT-SWAP", "SUIUSDT", "SUI"),
    SymbolMap("ADA", "ADA-USDT-SWAP", "ADAUSDT", "ADA"),
    SymbolMap("DOT", "DOT-USDT-SWAP", "DOTUSDT", "DOT"),
    SymbolMap("LTC", "LTC-USDT-SWAP", "LTCUSDT", "LTC"),
    SymbolMap("BCH", "BCH-USDT-SWAP", "BCHUSDT", "BCH"),
    SymbolMap("TRX", "TRX-USDT-SWAP", "TRXUSDT", "TRX"),
    SymbolMap("TON", "TON-USDT-SWAP", "TONUSDT", "TON"),
    SymbolMap("NEAR", "NEAR-USDT-SWAP", "NEARUSDT", "NEAR"),
    SymbolMap("APT", "APT-USDT-SWAP", "APTUSDT", "APT"),
    SymbolMap("ARB", "ARB-USDT-SWAP", "ARBUSDT", "ARB"),
    SymbolMap("OP", "OP-USDT-SWAP", "OPUSDT", "OP"),
    SymbolMap("PEPE", "PEPE-USDT-SWAP", "PEPEUSDT", "PEPE"),
    SymbolMap("SHIB", "SHIB-USDT-SWAP", "SHIBUSDT", "SHIB"),
    SymbolMap("WIF", "WIF-USDT-SWAP", "WIFUSDT", "WIF"),
    SymbolMap("BONK", "BONK-USDT-SWAP", "BONKUSDT", "BONK"),
    SymbolMap("FLOKI", "FLOKI-USDT-SWAP", "FLOKIUSDT", "FLOKI"),
    SymbolMap("AAVE", "AAVE-USDT-SWAP", "AAVEUSDT", "AAVE"),
    SymbolMap("UNI", "UNI-USDT-SWAP", "UNIUSDT", "UNI"),
    SymbolMap("ATOM", "ATOM-USDT-SWAP", "ATOMUSDT", "ATOM"),
    SymbolMap("FIL", "FIL-USDT-SWAP", "FILUSDT", "FIL"),
    SymbolMap("ETC", "ETC-USDT-SWAP", "ETCUSDT", "ETC"),
    SymbolMap("XLM", "XLM-USDT-SWAP", "XLMUSDT", "XLM"),
    SymbolMap("HBAR", "HBAR-USDT-SWAP", "HBARUSDT", "HBAR"),
    SymbolMap("ICP", "ICP-USDT-SWAP", "ICPUSDT", "ICP"),
    SymbolMap("INJ", "INJ-USDT-SWAP", "INJUSDT", "INJ"),
    SymbolMap("SEI", "SEI-USDT-SWAP", "SEIUSDT", "SEI"),
    SymbolMap("TIA", "TIA-USDT-SWAP", "TIAUSDT", "TIA"),
    SymbolMap("JUP", "JUP-USDT-SWAP", "JUPUSDT", "JUP"),
    SymbolMap("GALA", "GALA-USDT-SWAP", "GALAUSDT", "GALA"),
    SymbolMap("SAND", "SAND-USDT-SWAP", "SANDUSDT", "SAND"),
    SymbolMap("MANA", "MANA-USDT-SWAP", "MANAUSDT", "MANA"),
    SymbolMap("APE", "APE-USDT-SWAP", "APEUSDT", "APE"),
    SymbolMap("CRV", "CRV-USDT-SWAP", "CRVUSDT", "CRV"),
    SymbolMap("LDO", "LDO-USDT-SWAP", "LDOUSDT", "LDO"),
    SymbolMap("WLD", "WLD-USDT-SWAP", "WLDUSDT", "WLD"),
    SymbolMap("RUNE", "RUNE-USDT-SWAP", "RUNEUSDT", "RUNE"),
    SymbolMap("ALGO", "ALGO-USDT-SWAP", "ALGOUSDT", "ALGO"),
    SymbolMap("EOS", "EOS-USDT-SWAP", "EOSUSDT", "EOS"),
    SymbolMap("MKR", "MKR-USDT-SWAP", "MKRUSDT", "MKR"),
    SymbolMap("COMP", "COMP-USDT-SWAP", "COMPUSDT", "COMP"),
    SymbolMap("ZEC", "ZEC-USDT-SWAP", "ZECUSDT", "ZEC"),
    SymbolMap("DYDX", "DYDX-USDT-SWAP", "DYDXUSDT", "DYDX"),
]

if len(SYMBOLS) != 50:
    raise RuntimeError(f"فهرست نمادها باید دقیقاً 50 مورد باشد، فعلاً {len(SYMBOLS)} است")

BY_ID = {s.id: s for s in SYMBOLS}


def get_symbol(symbol_id: str) -> SymbolMap | None:
    return BY_ID.get(symbol_id.upper())
