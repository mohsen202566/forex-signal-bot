# Forex Scalper AI Helper

ربات Toobit Crypto Futures scalper با تحلیل OKX و اجرای واقعی فقط روی Toobit.

## قفل معماری این نسخه

این نسخه کلاسیک و خشک نیست. بجز کنترل‌های پنل ترید، همه تصمیم‌های تحلیلی نرم و زیر کنترل AI هستند:

- `Trade ON/OFF`
- `Margin / Dollar per trade`
- `Leverage`
- `Max positions / Slots`

فقط این موارد دست کاربر می‌مانند. بقیه چیزها AI-managed هستند.

## تصمیم نرم AI

AI برای هر ارز + جهت + الگو + entry quality + score bucket + market mode + session جدا یاد می‌گیرد و تصمیم می‌گیرد:

- فقط Watch بماند
- Normal Signal بدهد
- Real Toobit مجاز باشد
- Real بلاک شود ولی Normal/learning ادامه پیدا کند
- threshold نرم‌تر یا سخت‌تر شود

هیچ مورد تحلیلی مثل `PRECISION_WAIT`، ضعف حرکت، نویز، ریسک خستگی، pattern منفی یا range منفی قفل دائمی نیست. این‌ها فقط threshold و اجازه Real/Normal را تغییر می‌دهند.

## Threshold شروع

```env
BASE_SIGNAL_THRESHOLD=70
BASE_REAL_THRESHOLD=78
```

این‌ها فقط مقدار شروع هستند. AI بعد از نتیجه‌ها برای هر symbol/direction و context آن‌ها را تغییر می‌دهد.

## PRECISION_WAIT

`PRECISION_WAIT` دیگر جلوی Normal Signal را کامل نمی‌گیرد.

- برای شروع: Normal می‌تواند مجاز باشد.
- برای Real: سخت‌تر و محافظه‌کارانه‌تر است.
- بعد از یادگیری: اگر برای یک ارز/جهت/الگو خوب جواب بدهد، AI نرم‌ترش می‌کند؛ اگر بد جواب بدهد، سخت‌ترش می‌کند.

## Hard Safety

فقط safety اجرایی hard می‌ماند:

- API failure
- Symbol mismatch
- duplicate open signal/symbol
- max real slots
- Toobit execution/order/close safety
- OKX-Toobit sync
- net profit protection for Real

حتی این‌ها هم تحلیل را نابود نمی‌کنند؛ فقط اجرای واقعی را محافظت می‌کنند و Normal/learning می‌تواند ادامه پیدا کند.

## اجرا

```bash
python3 -m py_compile *.py
sudo systemctl restart forex-bot.service
journalctl -u forex-bot.service -f
```

## AI Exit / Hold Wave

در این نسخه TP دیگر خروج اجباری نیست؛ TP به عنوان Target Zone ذهنی استفاده می‌شود. ربات پوزیشن باز را ثانیه‌به‌ثانیه با قیمت OKX تماشا می‌کند:

- اگر موج سالم باشد، حتی بعد از عبور از Target Zone هیچ کاری نمی‌کند.
- اگر ضعف واقعی، برگشت چندثانیه‌ای، giveback سنگین یا تغییر جهت ببیند، خروج AI می‌زند.
- SL محافظ واقعی باقی می‌ماند.
- برای Real، به صورت پیش‌فرض فقط SL روی Toobit ثبت می‌شود و TP ثابت ثبت نمی‌شود تا AI بتواند موج را نگه دارد.

وضعیت‌های جدید نتیجه:

- `AI_EXIT_PROFIT`
- `AI_EXIT_BREAKEVEN`
- `AI_EXIT_DAMAGE_CONTROL`
- `AI_EXIT_REVERSAL`

تنظیمات مهم `.env`:

```env
AI_EXIT_ENABLED=true
AI_EXIT_MIN_ACTIVE_SECONDS=8
AI_EXIT_TARGET_ZONE_RATIO=0.72
AI_EXIT_MIN_PROFIT_PCT=0.0010
AI_EXIT_GIVEBACK_RATIO=0.32
AI_EXIT_RISKY_GIVEBACK_RATIO=0.24
AI_EXIT_DAMAGE_CONTROL_ADVERSE_RATIO=0.42
TOOBIT_PLACE_REAL_TP=false
TOOBIT_CLOSE_VERIFY_SECONDS=2
```
