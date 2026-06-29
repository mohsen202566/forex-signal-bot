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
