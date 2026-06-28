# تغییرات نسخه اسکالپ

- تبدیل منطق 1H Hunter به 5m/15m Scalper Hunter
- حذف hard reject بر اساس 1H خنثی؛ 1H فقط context است
- اضافه شدن `entry_quality.py` برای تشخیص EARLY_IGNITION / GOOD_ENTRY / LATE_ENTRY
- اضافه شدن `indicator_range_ai.py` برای یادگیری بازه RSI/MACD/ADX/ATR/Volume برای هر ارز و جهت
- اضافه شدن `tp_sl_result_engine.py` برای تفکیک TP/SL واقعی Toobit و TP/SL عادی ربات
- حداقل سود خالص ثابت `0.10 USDT`
- حذف دستورهای پنلی حداقل سود و درصد سود
- سرعت اسکن/واچ/مانیتور سریع‌تر شد
- پنل فارسی و پنل AI به نسخه اسکالپ به‌روزرسانی شد
- آمار TP/SL واقعی Toobit و عادی جدا شد
- ذخیره‌سازی ستون‌های یادگیری اسکالپ و اندیکاتورها اضافه شد
