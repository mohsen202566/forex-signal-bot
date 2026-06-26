# Crypto Helper 15m/30m Bot - نسخه کم‌فایل

## هدف قفل‌شده
- پوزیشن ۱۵ تا ۳۰ دقیقه‌ای
- ۱۰ کوین ثابت
- تحلیل و سیگنال عادی از OKX
- REAL، باز شدن پوزیشن و نتیجه REAL از Toobit
- سیگنال عادی حتی وقتی ترید خاموش است صادر و مانیتور می‌شود
- آمار دو بخش جدا دارد: `توبیت` و `سیگنال`

## فایل‌های اصلی
```text
bot.py              حلقه اصلی، اسکن، ارسال سیگنال، REAL
config.py           تنظیمات و وزن‌ها و بازه‌ها
strategy_engine.py  تکنیکال، Entry/Continuation/Confidence، TP/SL، سود خالص
state_store.py      حافظه، آمار جدا، اسلات‌ها، سیگنال‌ها
exchange_clients.py OKX + Adapter برای فایل Toobit قبلی
position_monitor.py مانیتور همه سیگنال‌ها و ریپلای نتیجه
command_router.py   دستورات فارسی
telegram_ui.py      متن پنل، سیگنال، آمار و نتیجه
```

## دستورات فارسی
```text
ترید
وضعیت
ترید فعال
ترید خاموش
ترید دلار 7
ترید لوریج 10
حداکثر پوزیشن 1
حداقل سود خالص 0.10
آمار
پوزیشن
کوین‌ها
استراتژی لول 4
```

## تنظیمات عددی
```text
ترید دلار: 1 تا 10000 USDT
ترید لوریج: 1 تا 100
حداکثر پوزیشن: 1 تا 100
حداقل سود خالص: 0.10 تا 10000 USDT
```

## منطق سیگنال
- اعتبار سیگنال: ۳ دقیقه
- اگر همان کوین و همان جهت سیگنال قوی‌تر بدهد، سیگنال عادی قبلی `REPLACED` می‌شود
- برای هر کوین فقط یک REAL فعال یا Pending مجاز است
- بعد از ارسال سفارش Toobit، اسلات فوراً `PENDING_OPEN` می‌شود
- ۷۰ ثانیه بعد اگر پوزیشن باز نشده بود، `FAILED_OPEN` و اسلات آزاد می‌شود

## منطق تکنیکال
ربات دنبال مقدار خام اندیکاتورها نیست؛ دنبال شتاب تغییرات است:
- RSI Slope
- ATR Expansion
- ADX Rising
- Volume Growth
- Open Interest Growth
- Market Structure / EMA50 فقط برای جهت و بایاس

### Entry Score
```text
RSI Slope Direction        25
ATR Expansion              20
Market Structure Bias      15
EMA50 Direction            10
Volume Growth              15
Open Interest Direction    10
ADX Rising                  5
```

### Continuation Score
```text
ATR Acceleration           25
RSI Slope Continuation     20
Volume Stability           15
OI Growth With Price       15
ADX Rising                 15
Candle Not Exhausted       10
```

### Confidence Penalty
Confidence سیگنال‌ساز نیست؛ فقط جریمه می‌کند:
- اختلاف سنسورها
- بازار رنج/خواب
- کندل بیش از حد کشیده
- Volume Spike غیرطبیعی
- دیر شدن ورود

## TP/SL و سود خالص
- TP/SL باید همراه با خود پوزیشن در Toobit ثبت شود، نه جدا جدا
- TP و SL بر اساس ATR و کیفیت سیگنال پویاست
- قبل از REAL، سود خالص تخمینی محاسبه می‌شود:
```text
سود ناخالص تارگت - کارمزد باز - کارمزد بسته - بافر اسلیپیج
```
اگر کمتر از `حداقل سود خالص` باشد، REAL باز نمی‌شود.

## اتصال Toobit
فایل سالم ربات قبلی را با نام `tobit_client.py` کنار این فایل‌ها بگذار.
`exchange_clients.py` به صورت Adapter به آن وصل می‌شود.
اگر نام متدهای فایل قبلی متفاوت بود، فقط Adapter را هماهنگ کن.

## اجرای تست
```bash
cd /root/forex-bot
python3 -m py_compile *.py
python3 bot.py
```
