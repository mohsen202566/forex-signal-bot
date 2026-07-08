# HMT-5 Trap Hunt Toobit Scalper

ربات اسکالپ ۵ دقیقه‌ای برای تحلیل با OKX و اجرای Real روی Toobit.

## منطق اصلی

نسخه فعلی با منطق ابداعی `HMT-5 Trap Hunt` کار می‌کند:

```text
1H = جهت اصلی اسکالپ
15M = تأیید فشار جهت
4H = فقط فیلتر خطر، نه خفه‌کننده ربات
5M = محدوده شکار / Context
1M = ورود واقعی
```

قانون اصلی:

```text
ورود مستقیم روی 5M ممنوع است.
ورود فقط وقتی صادر می‌شود که 1M تله/برگشت/پس‌گیری سالم بدهد.
```

## هدف استراتژی

هدف این نسخه شکار حرکت است، نه دنبال‌کردن حرکت:

```text
Trap → Reclaim → Ignition → Entry
```

یعنی بازار اول یک طرف را فریب می‌دهد، نقدینگی را جمع می‌کند، بعد 1M در جهت واقعی برمی‌گردد و ربات همان برگشت را شکار می‌کند.

## ستاپ‌های مجاز

### 1. Trap Reversal

برای LONG:

```text
قیمت low کوتاه‌مدت را می‌زند
پایین نمی‌ماند
1M بالای EMA20/VWAP برمی‌گردد
ورود LONG
SL زیر wick تله
```

برای SHORT برعکس:

```text
قیمت high کوتاه‌مدت را می‌زند
بالا نمی‌ماند
1M زیر EMA20/VWAP برمی‌گردد
ورود SHORT
SL بالای wick تله
```

### 2. Silent Ignition

وقتی 1M بعد از fake-down/fake-up با کندل قوی از محدوده بیرون می‌زند، اما هنوز دیر نشده است.

### 3. Micro Continuation

وقتی 1H و 15M جهت دارند و 5M مرده نیست، ربات روی 5M وارد نمی‌شود؛ فقط اجازه می‌دهد 1M یک اصلاح کوچک، پس‌گیری EMA20/VWAP و تریگر سالم بدهد.

## قوانین سخت

ربات سیگنال صادر نمی‌کند اگر:

```text
1H و 15M همسو نباشند
4H شدیداً خلاف معامله باشد
5M کاملاً مرده باشد؛ ATR و حجم هر دو ضعیف باشند
1M تریگر تله/پس‌گیری ندهد
کندل 1M بدنه قوی نداشته باشد
حجم 1M کم باشد
RSI 1M خسته یا نامناسب باشد
MACD 1M تازه در جهت معامله نباشد
SL بزرگ‌تر از سقف مجاز اسکالپ شود
سود خالص بعد کارمزد کمتر از حداقل پنل باشد
```

## RR و SL

```text
RR عادی: 1.5
RR قوی: 1.8
SL بر اساس wick/trigger یک‌دقیقه‌ای است
حداقل SL: 0.25%
حداکثر SL: 0.90%
```

## تعداد ارزها

لیست پیش‌فرض ۵۰ ارز است. نمادهای خطادار قبلی حذف/جایگزین شدند:

```text
TONUSDT حذف شد
FETUSDT حذف شد
1000PEPEUSDT با PEPEUSDT جایگزین شد
```

## چیزهایی که حفظ شده‌اند

```text
تحلیل OKX
اجرای Real روی Toobit
Normal / Real
پنل ترید
مارجین و لوریج از پنل
حداکثر پوزیشن
حداقل سود خالص
اتو سیگنال
گزارش ردشدن‌ها
آمار
حذف آمار
مانیتورینگ TP/SL
ریپلای نتیجه روی سیگنال اصلی
```

## دستورات تلگرام

```text
ترید
ترید فعال
ترید خاموش
ترید دلار 10
ترید لوریج 10
حداکثر پوزیشن 3
سرمایه ترید 100
حداقل سود خالص 0.01
آمار
آمار 7
حذف آمار
اتو سیگنال
پوزیشن
کوین‌ها
وضعیت
راهنما
```

## اجرای مستقیم روی VPS

پروژه فایل shell ندارد. سرویس باید مستقیم به `main.py` وصل باشد:

```ini
[Service]
WorkingDirectory=/root/forex-signal-bot
EnvironmentFile=/etc/forex-signal-bot.env
ExecStart=/usr/bin/python3 -u /root/forex-signal-bot/main.py
Restart=always
RestartSec=10
```

گیت‌پول و ریستارت:

```bash
cd /root/forex-signal-bot || exit

git pull origin main

python3 -m py_compile *.py

sudo systemctl restart forex-signal-bot.service
sudo systemctl status forex-signal-bot.service --no-pager -l
journalctl -u forex-signal-bot.service -n 80 --no-pager
```

## فایل‌هایی که عمداً وجود ندارند

```text
.env.example
.gitignore
run.sh
start_bot.sh
هر فایل .sh
__pycache__
```
