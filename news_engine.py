# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from config import IMPORTANT_NEWS_KEYWORDS

HIGH_IMPACT_WEEKDAYS = {
    0: "دوشنبه: شروع هفته؛ احتمال گپ و نوسان بعد از باز شدن بازار.",
    2: "چهارشنبه: معمولاً روز مهمی برای داده‌های اقتصادی و سخنرانی‌هاست.",
    4: "جمعه: ریسک اخبار اشتغال، NFP یا بستن پوزیشن‌های هفتگی بیشتر است.",
}

def get_news_risk(symbol: str = ""):
    """
    سیستم خبر در این نسخه فقط هشدار می‌دهد و هیچ سیگنالی را بلاک نمی‌کند.
    blocked همیشه False است تا با کدهای قبلی سازگار بماند.
    """
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour

    risk = "LOW"
    notes = []

    if weekday in HIGH_IMPACT_WEEKDAYS:
        risk = "MEDIUM"
        notes.append(HIGH_IMPACT_WEEKDAYS[weekday])

    if 12 <= hour <= 16:
        if risk == "LOW":
            risk = "MEDIUM"
        notes.append("ساعت فعلی نزدیک بازه انتشار بسیاری از اخبار آمریکا/لندن است؛ احتمال نوسان بیشتر است.")

    if weekday == 4 and 12 <= hour <= 15:
        risk = "HIGH"
        notes.append("جمعه و بازه پرریسک اخبار آمریکا؛ نوسان شدید محتمل است.")

    if symbol:
        if "USD" in symbol or symbol in ("DXY", "XAU/USD", "XAG/USD", "BTC/USD", "ETH/USD", "SOL/USD"):
            notes.append("این نماد به دلار یا ریسک‌پذیری بازار وابسته است؛ اخبار آمریکا می‌تواند جهت را سریع تغییر دهد.")
        if symbol in ("WTI/USD", "BRENT/USD"):
            notes.append("این نماد به اخبار انرژی، ذخایر نفت، جنگ و تنش‌های ژئوپلیتیک حساس است.")
        if symbol in ("US30", "NAS100", "SPX500", "DAX40"):
            notes.append("شاخص‌ها به نرخ بهره، سخنرانی بانک‌های مرکزی و ریسک بازار حساس هستند.")

    if not notes:
        notes.append("خبر مهم زنده متصل نیست؛ این بخش فعلاً هشدار زمانی و ریسک عمومی را نمایش می‌دهد.")

    return {
        "risk_level": risk,
        "blocked": False,
        "warning_only": True,
        "note": " ".join(notes),
        "keywords": IMPORTANT_NEWS_KEYWORDS,
    }

def format_news_message():
    risk = get_news_risk("")
    lines = [
        "📰 هشدار اخبار و ریسک بازار",
        "",
        f"سطح ریسک فعلی: {risk['risk_level']}",
        "اثر روی سیگنال: فقط هشدار؛ سیگنال تکنیکال بلاک نمی‌شود.",
        "",
        risk["note"],
        "",
        "رویدادهایی که باید جدی گرفته شوند:",
    ]
    for k in risk["keywords"]:
        lines.append(f"• {k}")
    lines.append("")
    lines.append("نکته: تقویم اقتصادی زنده هنوز وصل نیست؛ این بخش فعلاً ریسک زمانی و عمومی را هشدار می‌دهد.")
    return "\n".join(lines)
