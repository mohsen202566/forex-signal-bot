# -*- coding: utf-8 -*-

# نمادهای اصلی قابل اسکن و تحلیل
# نکته: اگر بعضی نمادها توسط پلن Twelve Data جواب ندهند، ربات کرش نمی‌کند و آن نماد را رد می‌کند.
FOREX_PAIRS = [
    # Major Forex
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "NZD/USD",
    "USD/CAD",

    # Cross Forex
    "EUR/JPY",
    "EUR/GBP",
    "EUR/CHF",
    "EUR/AUD",
    "EUR/CAD",
    "GBP/JPY",
    "GBP/CHF",
    "AUD/JPY",
    "CAD/JPY",
    "CHF/JPY",
    "NZD/JPY",

    # Metals
    "XAU/USD",
    "XAG/USD",

    # Energy
    "WTI/USD",
    "BRENT/USD",

    # Indices / Dollar Index
    "DXY",
    "US30",
    "NAS100",
    "SPX500",
    "DAX40",

    # Crypto majors
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
]

PAIR_DISPLAY_NAMES = {
    "EUR/USD": "یورو / دلار",
    "GBP/USD": "پوند / دلار",
    "USD/JPY": "دلار / ین",
    "USD/CHF": "دلار / فرانک",
    "AUD/USD": "دلار استرالیا / دلار",
    "NZD/USD": "دلار نیوزیلند / دلار",
    "USD/CAD": "دلار / دلار کانادا",

    "EUR/JPY": "یورو / ین",
    "EUR/GBP": "یورو / پوند",
    "EUR/CHF": "یورو / فرانک",
    "EUR/AUD": "یورو / دلار استرالیا",
    "EUR/CAD": "یورو / دلار کانادا",
    "GBP/JPY": "پوند / ین",
    "GBP/CHF": "پوند / فرانک",
    "AUD/JPY": "دلار استرالیا / ین",
    "CAD/JPY": "دلار کانادا / ین",
    "CHF/JPY": "فرانک / ین",
    "NZD/JPY": "دلار نیوزیلند / ین",

    "XAU/USD": "طلا / دلار",
    "XAG/USD": "نقره / دلار",

    "WTI/USD": "نفت آمریکا / دلار",
    "BRENT/USD": "نفت برنت / دلار",

    "DXY": "شاخص دلار",
    "US30": "داوجونز",
    "NAS100": "نزدک",
    "SPX500": "اس اند پی 500",
    "DAX40": "دکس آلمان",

    "BTC/USD": "بیتکوین / دلار",
    "ETH/USD": "اتریوم / دلار",
    "SOL/USD": "سولانا / دلار",
}

PAIR_ALIASES = {
    # EUR/USD
    "یورو دلار": "EUR/USD",
    "یورو/دلار": "EUR/USD",
    "یورو": "EUR/USD",
    "eurusd": "EUR/USD",
    "eur/usd": "EUR/USD",

    # GBP/USD
    "پوند دلار": "GBP/USD",
    "پوند/دلار": "GBP/USD",
    "پوند": "GBP/USD",
    "gbpusd": "GBP/USD",
    "gbp/usd": "GBP/USD",

    # USD/JPY
    "دلار ین": "USD/JPY",
    "دلار/ین": "USD/JPY",
    "ین": "USD/JPY",
    "usdjpy": "USD/JPY",
    "usd/jpy": "USD/JPY",

    # USD/CHF
    "دلار فرانک": "USD/CHF",
    "دلار/فرانک": "USD/CHF",
    "فرانک": "USD/CHF",
    "usdchf": "USD/CHF",
    "usd/chf": "USD/CHF",

    # AUD/USD
    "دلار استرالیا": "AUD/USD",
    "استرالیا دلار": "AUD/USD",
    "استرالیا": "AUD/USD",
    "audusd": "AUD/USD",
    "aud/usd": "AUD/USD",

    # NZD/USD
    "دلار نیوزیلند": "NZD/USD",
    "نیوزیلند دلار": "NZD/USD",
    "نیوزیلند": "NZD/USD",
    "nzdusd": "NZD/USD",
    "nzd/usd": "NZD/USD",

    # USD/CAD
    "دلار کانادا": "USD/CAD",
    "کانادا دلار": "USD/CAD",
    "کانادا": "USD/CAD",
    "usdcad": "USD/CAD",
    "usd/cad": "USD/CAD",

    # Crosses
    "یورو ین": "EUR/JPY",
    "یورو/ین": "EUR/JPY",
    "eurjpy": "EUR/JPY",
    "eur/jpy": "EUR/JPY",

    "یورو پوند": "EUR/GBP",
    "یورو/پوند": "EUR/GBP",
    "eurgbp": "EUR/GBP",
    "eur/gbp": "EUR/GBP",

    "یورو فرانک": "EUR/CHF",
    "یورو/فرانک": "EUR/CHF",
    "eurchf": "EUR/CHF",
    "eur/chf": "EUR/CHF",

    "یورو استرالیا": "EUR/AUD",
    "یورو/استرالیا": "EUR/AUD",
    "euraud": "EUR/AUD",
    "eur/aud": "EUR/AUD",

    "یورو کانادا": "EUR/CAD",
    "یورو/کانادا": "EUR/CAD",
    "eurcad": "EUR/CAD",
    "eur/cad": "EUR/CAD",

    "پوند ین": "GBP/JPY",
    "پوند/ین": "GBP/JPY",
    "gbpjpy": "GBP/JPY",
    "gbp/jpy": "GBP/JPY",

    "پوند فرانک": "GBP/CHF",
    "پوند/فرانک": "GBP/CHF",
    "gbpchf": "GBP/CHF",
    "gbp/chf": "GBP/CHF",

    "استرالیا ین": "AUD/JPY",
    "استرالیا/ین": "AUD/JPY",
    "audjpy": "AUD/JPY",
    "aud/jpy": "AUD/JPY",

    "کانادا ین": "CAD/JPY",
    "کانادا/ین": "CAD/JPY",
    "cadjpy": "CAD/JPY",
    "cad/jpy": "CAD/JPY",

    "فرانک ین": "CHF/JPY",
    "فرانک/ین": "CHF/JPY",
    "chfjpy": "CHF/JPY",
    "chf/jpy": "CHF/JPY",

    "نیوزیلند ین": "NZD/JPY",
    "نیوزیلند/ین": "NZD/JPY",
    "nzdjpy": "NZD/JPY",
    "nzd/jpy": "NZD/JPY",

    # Metals
    "طلا": "XAU/USD",
    "انس": "XAU/USD",
    "اونس": "XAU/USD",
    "گلد": "XAU/USD",
    "gold": "XAU/USD",
    "xauusd": "XAU/USD",
    "xau/usd": "XAU/USD",

    "نقره": "XAG/USD",
    "سیلور": "XAG/USD",
    "silver": "XAG/USD",
    "xagusd": "XAG/USD",
    "xag/usd": "XAG/USD",

    # Energy
    "نفت برنت": "BRENT/USD",
    "برنت": "BRENT/USD",
    "brent": "BRENT/USD",
    "brentusd": "BRENT/USD",
    "brent/usd": "BRENT/USD",

    "نفت آمریکا": "WTI/USD",
    "نفت": "WTI/USD",
    "wti": "WTI/USD",
    "wtiusd": "WTI/USD",
    "wti/usd": "WTI/USD",
    "oil": "WTI/USD",

    # Indices
    "شاخص دلار": "DXY",
    "دلار": "DXY",
    "dxy": "DXY",

    "داوجونز": "US30",
    "داو جونز": "US30",
    "dow": "US30",
    "us30": "US30",

    "نزدک": "NAS100",
    "ناسداک": "NAS100",
    "nasdaq": "NAS100",
    "nas100": "NAS100",

    "اس اند پی": "SPX500",
    "اس‌اندپی": "SPX500",
    "s&p": "SPX500",
    "spx500": "SPX500",

    "دکس": "DAX40",
    "دکس آلمان": "DAX40",
    "dax": "DAX40",
    "dax40": "DAX40",

    # Crypto
    "بیتکوین": "BTC/USD",
    "بیت کوین": "BTC/USD",
    "btc": "BTC/USD",
    "btcusd": "BTC/USD",
    "btc/usd": "BTC/USD",

    "اتریوم": "ETH/USD",
    "اتر": "ETH/USD",
    "eth": "ETH/USD",
    "ethusd": "ETH/USD",
    "eth/usd": "ETH/USD",

    "سولانا": "SOL/USD",
    "sol": "SOL/USD",
    "solusd": "SOL/USD",
    "sol/usd": "SOL/USD",
}

def normalize_pair(text: str):
    if not text:
        return None

    text_clean = text.lower().strip()

    # اولویت با عبارت‌های طولانی‌تر است تا مثلاً «نفت برنت» قبل از «نفت» تشخیص داده شود.
    for alias, symbol in sorted(PAIR_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if alias.lower() in text_clean:
            return symbol

    for symbol in FOREX_PAIRS:
        symbol_lower = symbol.lower()
        symbol_no_slash = symbol.replace("/", "").lower()
        if symbol_lower in text_clean or symbol_no_slash in text_clean:
            return symbol

    return None

def get_pair_display_name(symbol: str):
    return PAIR_DISPLAY_NAMES.get(symbol, symbol)
