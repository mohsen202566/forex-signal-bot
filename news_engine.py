from datetime import datetime, timezone, timedelta
from typing import Dict, List

from config import NEWS_BLOCK_BEFORE_MINUTES, NEWS_BLOCK_AFTER_MINUTES, IMPORTANT_NEWS_KEYWORDS

# نسخه امن بدون نیاز به API خبر: کرش نمی‌کند و قابل توسعه است.
# بعداً اگر FINNHUB_API_KEY یا منبع تقویم اقتصادی اضافه شود، همین فایل را ارتقا می‌دهیم.

HIGH_IMPACT_EVENTS = [
    {"title": "CPI", "impact": "HIGH", "currency": "USD", "description": "تورم آمریکا؛ تاثیر شدید روی دلار، طلا و جفت‌ارزهای اصلی."},
    {"title": "NFP", "impact": "HIGH", "currency": "USD", "description": "گزارش اشتغال آمریکا؛ معمولا نوسان شدید ایجاد می‌کند."},
    {"title": "FOMC", "impact": "HIGH", "currency": "USD", "description": "تصمیمات و بیانیه فدرال رزرو؛ بسیار مهم برای جهت دلار."},
    {"title": "Interest Rate Decision", "impact": "HIGH", "currency": "USD/EUR/GBP/JPY", "description": "تصمیم نرخ بهره بانک‌های مرکزی."},
    {"title": "Fed Chair Powell Speech", "impact": "HIGH", "currency": "USD", "description": "سخنرانی پاول؛ می‌تواند جهت بازار را ناگهانی تغییر دهد."},
    {"title": "GDP", "impact": "MEDIUM", "currency": "USD/EUR/GBP", "description": "رشد اقتصادی؛ تاثیر متوسط تا زیاد."},
    {"title": "Unemployment Rate", "impact": "MEDIUM", "currency": "USD", "description": "نرخ بیکاری؛ همراه NFP بسیار مهم است."},
]


def affected_currencies(symbol: str) -> List[str]:
    symbol = symbol.upper()
    if symbol == "XAU/USD":
        return ["USD", "XAU"]
    parts = symbol.split("/")
    return parts if len(parts) == 2 else ["USD"]


def get_today_news() -> Dict:
    return {
        "success": True,
        "mode": "STATIC_IMPORTANT_EVENTS",
        "message": "موتور اخبار فعال است، اما تقویم اقتصادی زنده هنوز به API خبر وصل نشده. فیلتر محافظه‌کار اخبار با لیست رویدادهای مهم فعال است.",
        "events": HIGH_IMPACT_EVENTS,
        "keywords": IMPORTANT_NEWS_KEYWORDS,
    }


def get_news_risk_for_symbol(symbol: str) -> Dict:
    # بدون تقویم زنده نمی‌توان زمان دقیق خبر را دانست؛ پس بلاک خودکار انجام نمی‌دهیم.
    # این خروجی طوری طراحی شده که بعداً با تقویم اقتصادی واقعی، blocked=True شود.
    currencies = affected_currencies(symbol)
    return {
        "success": True,
        "blocked": False,
        "risk_level": "LOW",
        "currencies": currencies,
        "block_before_minutes": NEWS_BLOCK_BEFORE_MINUTES,
        "block_after_minutes": NEWS_BLOCK_AFTER_MINUTES,
        "note": "تقویم اقتصادی زنده هنوز وصل نیست؛ برای CPI/NFP/FOMC دستی مراقب زمان خبر باش.",
    }


def format_news_message() -> str:
    data = get_today_news()
    lines = [
        "📰 اخبار و رویدادهای مهم فارکس",
        "",
        "⚠️ نسخه فعلی لیست رویدادهای مهم را نمایش می‌دهد و فیلتر محافظه‌کار آماده است.",
        "برای بلاک خودکار دقیق قبل/بعد خبر، در مرحله بعد باید API تقویم اقتصادی زنده اضافه شود.",
        "",
        "رویدادهای بسیار مهم:",
    ]
    for event in data["events"]:
        icon = "🔴" if event["impact"] == "HIGH" else "🟠"
        lines.append(f"{icon} {event['title']} | ارز: {event['currency']}")
        lines.append(f"   {event['description']}")
    lines.append("")
    lines.append(f"⛔ قانون ربات: {NEWS_BLOCK_BEFORE_MINUTES} دقیقه قبل و {NEWS_BLOCK_AFTER_MINUTES} دقیقه بعد از خبر مهم نباید ورود عجولانه گرفت.")
    return "\n".join(lines)
