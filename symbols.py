from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class SymbolMap:
    id:str; okx:str; toobit:str; base:str; quote:str='USDT'; group:str='ALT'; active:bool=True
SYMBOLS=[
SymbolMap('BTC','BTC-USDT-SWAP','BTCUSDT','BTC',group='MAJOR'),SymbolMap('ETH','ETH-USDT-SWAP','ETHUSDT','ETH',group='MAJOR'),
SymbolMap('SOL','SOL-USDT-SWAP','SOLUSDT','SOL',group='LIQUID_VOL'),SymbolMap('XRP','XRP-USDT-SWAP','XRPUSDT','XRP',group='LIQUID_VOL'),
SymbolMap('BNB','BNB-USDT-SWAP','BNBUSDT','BNB',group='MAJOR'),SymbolMap('LINK','LINK-USDT-SWAP','LINKUSDT','LINK'),
SymbolMap('ADA','ADA-USDT-SWAP','ADAUSDT','ADA'),SymbolMap('AVAX','AVAX-USDT-SWAP','AVAXUSDT','AVAX',group='LIQUID_VOL'),
SymbolMap('DOGE','DOGE-USDT-SWAP','DOGEUSDT','DOGE',group='LIQUID_VOL'),SymbolMap('SUI','SUI-USDT-SWAP','SUIUSDT','SUI',group='LIQUID_VOL'),
SymbolMap('LTC','LTC-USDT-SWAP','LTCUSDT','LTC'),SymbolMap('BCH','BCH-USDT-SWAP','BCHUSDT','BCH'),
SymbolMap('DOT','DOT-USDT-SWAP','DOTUSDT','DOT'),SymbolMap('NEAR','NEAR-USDT-SWAP','NEARUSDT','NEAR',group='HIGH_VOL'),
SymbolMap('APT','APT-USDT-SWAP','APTUSDT','APT',group='HIGH_VOL'),SymbolMap('ATOM','ATOM-USDT-SWAP','ATOMUSDT','ATOM'),
SymbolMap('INJ','INJ-USDT-SWAP','INJUSDT','INJ',group='HIGH_VOL'),SymbolMap('ARB','ARB-USDT-SWAP','ARBUSDT','ARB',group='HIGH_VOL'),
SymbolMap('OP','OP-USDT-SWAP','OPUSDT','OP',group='HIGH_VOL'),SymbolMap('FIL','FIL-USDT-SWAP','FILUSDT','FIL',group='HIGH_VOL')]
BY_ID={s.id:s for s in SYMBOLS}; BY_OKX={s.okx:s for s in SYMBOLS}; BY_TOOBIT={s.toobit:s for s in SYMBOLS}
def get_symbol(symbol_id:str): return BY_ID.get(symbol_id.upper())
