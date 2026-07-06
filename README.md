# Crypto 5M Simple Toobit Scalper

ربات اسکالپ ۵ دقیقه‌ای ساده برای تحلیل با OKX و اجرای واقعی روی Toobit.

## قوانین اصلی

- تحلیل فقط از OKX انجام می‌شود.
- اجرای واقعی فقط روی Toobit انجام می‌شود.
- پنل ترید، دستورات، مارجین، لوریج، آمار، سیگنال عادی/Real، اسلات‌ها و ثبت نتایج مثل نسخه قبلی حفظ شده‌اند.
- تایم‌فریم جهت: `4H + 1H` باید همسو باشند.
- تایم‌فریم ورود: `5m`.
- بدون تأیید کندلی؛ چون در اسکالپ ۵ دقیقه‌ای همان کندل می‌تواند کل سود باشد.
- بدون حمایت/مقاومت.
- بدون AI، DCA، Martingale و trailing.
- امتیاز از ۱۰۰؛ حداقل صدور سیگنال `70`.
- RR پیش‌فرض `1.5`.
- TP و SL فقط مخصوص ۵ دقیقه هستند.
- حداقل سود خالص بعد از کارمزد باید حداقل مقدار پنل باشد؛ پیش‌فرض `0.01 USDT`.

## امتیازدهی

| بخش | امتیاز |
|---|---:|
| جهت 4H | 20 |
| جهت 1H | 20 |
| EMA در 5M | 20 |
| RSI در 5M | 15 |
| MACD در 5M | 15 |
| VWAP در 5M | 5 |
| ATR / کیفیت SL در 5M | 5 |
| جمع | 100 |

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
پوزیشن
کوین‌ها
وضعیت
راهنما
```

## اجرای مستقیم روی VPS

پروژه فایل shell ندارد. اجرای سرویس باید مستقیم به `main.py` وصل باشد:

```ini
[Service]
WorkingDirectory=/root/crypto-ai-helper
ExecStart=/usr/bin/python3 /root/crypto-ai-helper/main.py
Restart=always
RestartSec=5
```

بعد از `git pull`:

```bash
cd /root/crypto-ai-helper || exit
git fetch --all --prune
git reset --hard @{u}
rm -f run.sh .env.example .gitignore
find . -type d -name "__pycache__" -exec rm -rf {} +
python3 -m py_compile *.py
systemctl restart crypto-bot.service
systemctl status crypto-bot.service --no-pager -l
journalctl -u crypto-bot.service -n 100 --no-pager
```

## فایل‌هایی که عمداً وجود ندارند

این فایل‌ها عمداً داخل پروژه نیستند تا برای Git pull و VPS دردسر نسازند:

- `.env.example`
- `.gitignore`
- `run.sh`
- هر فایل `.sh`
- `__pycache__`
