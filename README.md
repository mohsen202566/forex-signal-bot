# DIFT-5M Futures Bot

ربات ۵ دقیقه فیوچرز با منطق ابداعی DIFT-5M:

**Direction Lock → Compression → Impulse Break → Order Flow Confirm → Risk/RR Gate**

- سیستم امتیازی ندارد؛ همه قفل‌ها باید پاس شوند.
- دیتای تحلیل از OKX است.
- در حالت REAL، اجرای سفارش و نتیجه واقعی فقط از Toobit انجام/چک می‌شود.
- فایل‌ها همگی در ریشه پروژه هستند؛ پوشه لازم نیست.
- `toobit_client.py` ثابت می‌ماند.

## نصب

```bash
pip install -r requirements.txt
cp .env.example .env
```

مقادیر `.env` را داخل GitHub Secrets یا محیط سرور تنظیم کن.

## اجرا

```bash
python main.py
```

## دستورات تلگرام

`/start` `/menu` `/help` `/status` `/normal` `/real` `/trade_on` `/trade_off` `/scan` `/active` `/balance` `/pnl` `/positions` `/symbols` `/add` `/remove` `/set_amount` `/set_leverage` `/settings`

## حالت‌ها

- `NORMAL`: سیگنال و مانیتور کاغذی با دیتای OKX.
- `REAL`: سیگنال با OKX، اعتبارسنجی قیمت/نماد روی Toobit، سفارش واقعی با TP/SL روی Toobit، نتیجه با Toobit history.

برای اجرای واقعی، هر دو شرط لازم است:

```env
BOT_MODE=REAL
REAL_TRADING_ENABLED=true
```

و داخل تلگرام هم `/trade_on` زده شود.
