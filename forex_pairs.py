FOREX_PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "NZD/USD",
    "USD/CAD",
    "EUR/JPY",
    "XAU/USD",
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
    "XAU/USD": "طلا / دلار",
}

PAIR_ALIASES = {
    "یورو دلار": "EUR/USD",
    "eurusd": "EUR/USD",
    "eur/usd": "EUR/USD",

    "پوند دلار": "GBP/USD",
    "gbpusd": "GBP/USD",
    "gbp/usd": "GBP/USD",

    "دلار ین": "USD/JPY",
    "ین": "USD/JPY",
    "usdjpy": "USD/JPY",
    "usd/jpy": "USD/JPY",

    "دلار فرانک": "USD/CHF",
    "فرانک": "USD/CHF",
    "usdchf": "USD/CHF",
    "usd/chf": "USD/CHF",

    "دلار استرالیا": "AUD/USD",
    "استرالیا دلار": "AUD/USD",
    "audusd": "AUD/USD",
    "aud/usd": "AUD/USD",

    "دلار نیوزیلند": "NZD/USD",
    "نیوزیلند دلار": "NZD/USD",
    "nzdusd": "NZD/USD",
    "nzd/usd": "NZD/USD",

    "دلار کانادا": "USD/CAD",
    "کانادا": "USD/CAD",
    "usdcad": "USD/CAD",
    "usd/cad": "USD/CAD",

    "یورو ین": "EUR/JPY",
    "eurjpy": "EUR/JPY",
    "eur/jpy": "EUR/JPY",

    "طلا": "XAU/USD",
    "انس": "XAU/USD",
    "اونس": "XAU/USD",
    "gold": "XAU/USD",
    "xauusd": "XAU/USD",
    "xau/usd": "XAU/USD",
}


def normalize_pair(text: str):
    if not text:
        return None

    text_clean = text.lower().strip()

    for alias, symbol in PAIR_ALIASES.items():
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
