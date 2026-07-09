# DIFT-5M v7 - OKX Fix / Fast Panel

این نسخه خطاهای OKX را اصلاح می‌کند:

- تبدیل نماد داخلی مثل `BTCUSDT` به instId صحیح `BTC-USDT-SWAP`
- کش کردن لیست Instrumentهای OKX
- حذف نماد نامعتبر از چرخه اسکن برای جلوگیری از اسپم `51001`
- کنترل سرعت درخواست‌ها برای جلوگیری از `HTTP 429`
- اگر endpoint نمادهای Toobit خطای 404 بدهد، اسکن NORMAL متوقف نمی‌شود؛ در REAL قبل از سفارش Toobit دوباره اعتبارسنجی می‌شود.
- `TONUSDT` با `WIFUSDT` جایگزین شد، چون در لاگ OKX برای TON خطای Instrument می‌داد.

دستور آپدیت روی VPS:

```bash
cd /root/forex-signal-bot || exit
git pull origin main
python3 -m py_compile *.py
sudo systemctl restart forex-signal-bot.service
journalctl -u forex-signal-bot.service -n 120 --no-pager
```

تنظیمات اختیاری در `.env`:

```env
OKX_REQUEST_DELAY_SECONDS=0.18
OKX_BAD_SYMBOL_COOLDOWN_SECONDS=3600
OKX_FETCH_FUNDING_EVERY_SCAN=false
```

# DIFT-5M Futures Bot — Root Clean Version

ربات ۵ دقیقه فیوچرز با منطق ابداعی:

**Direction Lock → Compression → Impulse Break → Order Flow Confirm → Risk/RR Gate**

سیستم امتیازی ندارد؛ اگر حتی یک قفل رد شود، سیگنال حذف می‌شود.

## نکات اصلی نسخه تمیز

- همه فایل‌ها مستقیم در ریشه گیت‌هاب قرار می‌گیرند؛ پوشه لازم نیست.
- فایل‌های دردسرساز مثل `.env.example`، `env.example` و `.gitignore` داخل ZIP نیستند.
- فایل `toobit_client.py` ثابت مانده و دستکاری نشده است.
- دیتا، کندل، order book، trades، funding و open interest از OKX خوانده می‌شود.
- در حالت REAL فقط سفارش‌هایی که واقعی می‌شوند از Toobit اجرا می‌شوند.
- نتیجه معاملات REAL فقط از Toobit history / realized PnL چک و ثبت می‌شود.
- نتیجه معاملات NORMAL با کندل‌های OKX مانیتور و شبیه‌سازی می‌شود.
- `RR` کمتر از ۱ اجازه ورود ندارد.
- ۳۵ ارز پیش‌فرض تعریف شده‌اند و با `/validate_symbols` همخوانی OKX/Toobit چک می‌شود.

## نصب

```bash
pip install -r requirements.txt
```

## تنظیمات لازم

ربات از متغیرهای محیطی استفاده می‌کند. روی سرور، Render، Railway یا GitHub Secrets این مقادیر را مستقیم وارد کن. اگر روی سیستم خودت اجرا می‌کنی، می‌توانی خودت یک فایل `.env` بسازی؛ ولی داخل پروژه فایل نمونه env قرار داده نشده.

حداقل متغیرهای لازم:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_ID=
TOOBIT_API_KEY=
TOOBIT_API_SECRET=
BOT_MODE=NORMAL
REAL_TRADING_ENABLED=false
TRADE_AMOUNT_USDT=6
DEFAULT_LEVERAGE=10
```

برای اجرای واقعی:

```text
BOT_MODE=REAL
REAL_TRADING_ENABLED=true
```

داخل تلگرام هم باید بزنی:

```text
/real
/trade_on
```

تا وقتی `REAL_TRADING_ENABLED=false` باشد، حتی با `/real` هم سفارش واقعی ارسال نمی‌شود.

## اجرا

```bash
python main.py
```

## ۳۵ ارز پیش‌فرض

```text
BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT,ADAUSDT,TRXUSDT,AVAXUSDT,LINKUSDT,SUIUSDT,LTCUSDT,BCHUSDT,DOTUSDT,UNIUSDT,AAVEUSDT,NEARUSDT,OPUSDT,ARBUSDT,INJUSDT,ATOMUSDT,ETCUSDT,FILUSDT,APTUSDT,WLDUSDT,PEPEUSDT,SHIBUSDT,SEIUSDT,TONUSDT,ICPUSDT,HBARUSDT,ARUSDT,TIAUSDT,ORDIUSDT,JUPUSDT
```

ربات در شروع، اگر `VALIDATE_SYMBOLS_ON_START=true` باشد، این لیست را با OKX instruments و Toobit exchangeInfo چک می‌کند. اگر نمادی در یکی از دو صرافی نبود، تلگرام گزارش می‌دهد.

## مانیتورینگ نتیجه

فایل‌ها در ریشه ساخته می‌شوند:

- `active_trades.json` معاملات باز
- `signals.jsonl` همه سیگنال‌ها و سفارش‌های ارسال‌شده
- `results.jsonl` نتیجه هر معامله بسته‌شده
- `trade_history.csv` تاریخچه قابل اکسل
- `bot.log` لاگ ربات

در REAL:

```text
Signal source = OKX
Execution source = Toobit
Result source = Toobit history / realized PnL
```

در NORMAL:

```text
Signal source = OKX
Execution source = simulated
Result source = OKX 5m candles
```

## دستورات تلگرام

```text
/start
/menu
/help
/status
/normal
/real
/trade_on
/trade_off
/scan
/active
/results 10
/balance
/pnl
/positions
/symbols
/validate_symbols
/reset_symbols
/add BTCUSDT
/remove BTCUSDT
/set_amount 6
/set_leverage 10
/settings
```

## v6 تغییرات سرعت پنل
- دکمه‌های تلگرام حذف شدند؛ پنل فقط متنی است.
- دستورهای فارسی مثل `ترید` و `آمار` از اسکن جدا هستند و سریع جواب می‌دهند.
- اسکن و مانیتورینگ سنگین در thread جدا اجرا می‌شود تا polling تلگرام قفل نشود.
- برای اسکن دستی هنوز دستور `اسکن` جداگانه وجود دارد.
