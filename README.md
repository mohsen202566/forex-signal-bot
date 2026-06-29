# Forex Scalper AI Helper

اسم/ID ربات «Forex» است، اما منطق واقعی آن Crypto Futures روی Toobit است.

## قفل‌های اصلی

- Data Source: OKX
- Execution: فقط Toobit Futures
- Strategy: شکار شروع حرکت پامپ/دامپ و برگشت مصرف‌شده در بازه 5 تا 15 دقیقه
- 1H و 4H فقط context هستند و قفل ورود نیستند
- سنسورها نرم هستند؛ هیچ سنسور تحلیلی به‌تنهایی ورود را ممنوع نمی‌کند
- Entry فقط زیر نظر AI است؛ اگر ورود دقیق تایید نشود، سیگنال صادر نمی‌شود
- AI مسئول کامل Entry است: یا ورود دقیق می‌زند، یا سیگنال نمی‌دهد و فقط یاد می‌گیرد
- امتیاز 100تایی نرم است؛ Real فقط وقتی کیفیت، اسلات، Toobit، قیمت و سود خالص تأیید شوند
- حداقل سود خالص برای Real: 0.01 USDT بعد از fee/slippage
- حجم پوزیشن با امتیاز تغییر نمی‌کند؛ فقط از تنظیمات کاربر می‌آید
- TP/SL هوشمند، قابل یادگیری و جدا برای هر ارز/جهت است
- نتیجه TP/SL دو نوع دارد: واقعی Toobit و عادی ربات
- نتیجه‌ها روی پیام سیگنال اصلی reply می‌شوند
- AI از Pattern Memory، Range Memory، Judge، Shadow Test، Market Mode، Sensitivity و Meta Brain تشکیل شده است

## ارزها

اصلی: SOL, XRP, DOGE, AVAX, LINK

جایگزین برای پیشنهاد/فعال‌سازی بعد از یادگیری کافی: SUI, ADA, LTC, NEAR

## دستورات فارسی

```text
پنل
وضعیت
آمار
آمار 7
هوش
یادگیری
پیشنهاد
ارزها
ترید فعال
ترید خاموش
ترید دلار 20
ترید لوریج 10
حداکثر پوزیشن 3
حذف آمار
حذف آمار تایید
ریست یادگیری
ریست یادگیری تایید
راهنما
```

## نصب روی VPS

```bash
cd /root/forex-signal-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 -m py_compile *.py
./start_bot.sh
```

`.env` را عمومی نکن. توکن تلگرام و کلیدهای Toobit نباید داخل گیت یا فایل ارسالی باشند.
