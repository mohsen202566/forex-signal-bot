# اصلاح تمیز دستورات متنی Forex

این نسخه دکمه‌ها را کامل حذف می‌کند. همه پیام‌های ربات با `ReplyKeyboardRemove` ارسال می‌شوند تا دکمه‌های قدیمی تلگرام هم از چت پاک شوند.

## فایل‌های اصلاح‌شده

- `telegram_bot.py`: فقط دستورات متنی، بدون دکمه، با پشتیبانی از متن فارسی روان.
- `messages_fa.py`: پنل و راهنما بدون دکمه و بدون اشاره به BTC/ETH.
- `strategy.py`: شرط هم‌جهتی BTC/ETH حذف شده و فقط جهت روزانه خود ارز بررسی می‌شود.
- `main.py`: دیگر BTC/ETH را برای قانون هم‌جهتی نمی‌گیرد.

## دستورات اصلی

- `ترید`
- `ترید فعال`
- `ترید خاموش`
- `آمار`
- `تنظیم مبلغ 10`
- `تنظیم لوریج 10`
- `تنظیم حداکثر پوزیشن 3`
- `ریست آمار`
- `حذف آمار`

## نصب روی سرور

```bash
cd /root/forex-signal-bot
systemctl stop forex-signal-bot

cp telegram_bot.py telegram_bot.py.bak_text_clean
cp messages_fa.py messages_fa.py.bak_text_clean
cp strategy.py strategy.py.bak_text_clean
cp main.py main.py.bak_text_clean

unzip -o forex_text_only_clean_v2.zip
cp forex_text_only_clean_v2/telegram_bot.py .
cp forex_text_only_clean_v2/messages_fa.py .
cp forex_text_only_clean_v2/strategy.py .
cp forex_text_only_clean_v2/main.py .

source venv/bin/activate
python -m py_compile main.py telegram_bot.py messages_fa.py strategy.py

systemctl restart forex-signal-bot
sleep 8
tail -n 160 forex.log
```

بعد در تلگرام یک بار بزنید: `ترید` تا دکمه‌های قدیمی حذف شوند.
