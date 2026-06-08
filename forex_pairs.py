PAIR_ALIASES = {
    "یورو دلار": "EUR/USD",
    "eurusd": "EUR/USD",
    "eur/usd": "EUR/USD",

    "پوند دلار": "GBP/USD",
    "gbpusd": "GBP/USD",
    "gbp/usd": "GBP/USD",

    "دلار ین": "USD/JPY",
    "usdjpy": "USD/JPY",
    "usd/jpy": "USD/JPY",

    "دلار فرانک": "USD/CHF",
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
    "usdcad": "USD/CAD",
    "usd/cad": "USD/CAD",

    "یورو ین": "EUR/JPY",
    "eurjpy": "EUR/JPY",
    "eur/jpy": "EUR/JPY",

    "طلا": "XAU/USD",
    "انس": "XAU/USD",
    "gold": "XAU/USD",
    "xauusd": "XAU/USD",
    "xau/usd": "XAU/USD",
}


def normalize_pair(text: str):
    text = text.lower().strip()

    for alias, symbol in PAIR_ALIASES.items():
        if alias.lower() in text:
            return symbol

    for symbol in FOREX_PAIRS:
        if symbol.lower() in text or symbol.replace("/", "").lower() in text:
            return symbol

    return None
