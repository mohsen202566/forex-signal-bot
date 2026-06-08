# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from config import IMPORTANT_NEWS_KEYWORDS

HIGH_IMPACT_WEEKDAYS = {
    0: "دوشنبه: شروع هفته؛ احتمال گپ و نوسان بعد از باز شدن بازار.",
    2: "چهارشنبه: معمولاً روز مهمی برای داده‌های اقتصادی و سخنرانی‌هاست.",
    4: "جمعه: ریسک اخبار اشتغال، NFP یا بستن پوزیشن‌های هفتگی بیشتر است.",
}

def get_news_risk(symbol: str = ""):
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour

    risk = "LOW"
    blocked = False
    notes = []

    if weekday in HIGH_IMPACT_WEEKDAYS:
        risk = "MEDIUM"
        notes.append(HIGH_IMPACT_WEEKDAYS[weekday])

    if 12 <= hour <= 16:
        risk = "MEDIUM" if risk == "LOW" else risk
        notes.append("ساعت فعلی نزدیک بازه انتشار بسیاری از اخبار آمریکا/لندن است؛ با احتیاط معامله کن.")

    if weekday == 4 and 12 <= hour <= 15:
        risk = "HIGH"
        blocked = True
        notes.append("جمعه و بازه پرریسک اخبار آمریکا؛ سیگنال جدید بهتر است با احتیاط شدید بررسی شود.")

    if symbol and "USD" in symbol:
        notes.append("این نماد به دلار وابسته است؛ اخبار آمریکا می‌تواند جهت را سریع تغییر دهد.")

    return {
        "risk_level": risk,
        "blocked": blocked,
        "note": " ".join(notes) if notes else "خبر مهم زنده متصل نیست؛ فیلتر فعلی محافظه‌کار است.",
        "keywords": IMPORTANT_NEWS_KEYWORDS,
    }

def format_news_message():
    risk = get_news_risk("")
    lines = [
        "📰 اخبار و ریسک امروز",
        "",
        f"سطح ریسک فعلی: {risk['risk_level']}",
        f"بلاک معامله: {'بله' if risk['blocked'] else 'خیر'}",
        "",
        risk["note"],
        "",
        "اخبار مهمی که ربات در فاز زنده باید جدی بگیرد:",
    ]
    for k in risk["keywords"]:
        lines.append(f"• {k}")
    lines.append("")
    lines.append("فعلاً تقویم اقتصادی زنده وصل نیست؛ این بخش به صورت محافظه‌کار ریسک زمانی را بررسی می‌کند.")
    return "\n".join(lines)
