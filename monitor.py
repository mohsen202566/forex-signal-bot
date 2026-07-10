"""مانیتورینگ نتایج.

Virtual فقط با دیتای ۱ دقیقه OKX برای ترتیب دقیق‌تر TP/SL بررسی می‌شود.
Real فقط از پوزیشن و تاریخچه واقعی Toobit نتیجه می‌گیرد و هرگز نتیجه را از OKX حدس نمی‌زند.
"""
from __future__ import annotations

import json
import logging
import math
import time

import config
from okx_client import OKXClient
from storage import Storage
from toobit_client import ToobitFuturesClient

logger = logging.getLogger("futures_hunt_2.monitor")


class Monitor:
    def __init__(self, okx: OKXClient, toobit: ToobitFuturesClient, storage: Storage, telegram=None):
        self.okx = okx
        self.toobit = toobit
        self.storage = storage
        self.telegram = telegram

    @staticmethod
    def _position_values(sig: dict) -> tuple[float, int, float]:
        trade_usdt = float(sig.get("trade_usdt") or 0.0)
        leverage = int(sig.get("leverage") or 0)
        notional = float(sig.get("notional_usdt") or 0.0)
        if trade_usdt <= 0:
            trade_usdt = float(config.TRADE_USDT_DEFAULT)
        if leverage <= 0:
            leverage = int(config.LEVERAGE_DEFAULT)
        if notional <= 0:
            notional = trade_usdt * leverage
        return trade_usdt, leverage, notional

    def _pnl(self, sig: dict, entry: float, exit_price: float) -> tuple[float, float, float]:
        _, _, notional = self._position_values(sig)
        side = str(sig["side"]).upper()
        gross = notional * ((exit_price - entry) / entry) if side == "LONG" else notional * ((entry - exit_price) / entry)
        fee = float(sig.get("estimated_cost") or 0.0)
        if fee <= 0:
            fee = notional * (2.0 * (config.FALLBACK_FEE_PCT_PER_SIDE + config.SLIPPAGE_PCT_PER_SIDE) / 100.0)
        return gross, fee, gross - fee

    @staticmethod
    def _raw(sig: dict) -> dict:
        value = sig.get("raw_json") or {}
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _signed_return(side: str, start: float, end: float) -> float:
        if start <= 0:
            return 0.0
        raw = (end - start) / start * 100.0
        return raw if side.upper() == "LONG" else -raw

    def _diagnose_stop(self, sig: dict, candles: list[dict[str, float]], entry: float, exit_price: float,
                       mfe: float, mae: float) -> dict:
        """کالبدشکافی مبتنی بر داده؛ برچسبی را که داده پشتیبانش نیست قطعی اعلام نمی‌کند."""
        side = str(sig.get("side") or "").upper()
        created_ms = int(sig.get("created_at") or 0) * 1000
        seq = [c for c in candles if int(c.get("ts") or 0) > created_ms]
        raw = self._raw(sig)
        ctx = raw.get("diagnostic_context") if isinstance(raw.get("diagnostic_context"), dict) else {}
        tp_pct = abs(float(sig.get("tp") or entry) - entry) / max(entry, 1e-12) * 100.0
        sl_pct = abs(entry - float(sig.get("sl") or exit_price)) / max(entry, 1e-12) * 100.0
        duration_min = 0.0
        if seq:
            duration_min = max(0.0, (int(seq[-1]["ts"]) - created_ms) / 60000.0)

        signed_closes = [self._signed_return(side, entry, float(c["close"])) for c in seq]
        signed_opens = [self._signed_return(side, entry, float(c["open"])) for c in seq]
        candle_steps = []
        prev = entry
        for c in seq:
            close = float(c["close"])
            candle_steps.append(self._signed_return(side, prev, close))
            prev = close
        sign_changes = 0
        nonzero = [1 if x > 0.002 else -1 if x < -0.002 else 0 for x in candle_steps]
        last = 0
        for sign in nonzero:
            if sign and last and sign != last:
                sign_changes += 1
            if sign:
                last = sign
        total_path = sum(abs(x) for x in candle_steps)
        net_to_exit = self._signed_return(side, entry, exit_price)
        efficiency = abs(net_to_exit) / max(total_path, 1e-9)
        adverse_close_ratio = (sum(1 for x in signed_closes if x < 0) / len(signed_closes)) if signed_closes else 0.0
        first_close = signed_closes[0] if signed_closes else 0.0
        first_two = signed_closes[min(1, len(signed_closes)-1)] if signed_closes else 0.0
        mfe_fraction = mfe / max(tp_pct, 1e-9)

        strength_score = float(raw.get("strength_score") or 0.0)
        flow_bias = float(raw.get("flow_bias") or 0.0)
        direction_conf = float(raw.get("direction_confidence") or 0.0)
        pre_disp = abs(float(ctx.get("pre_entry_displacement_pct") or 0.0))
        late_limit = abs(float(ctx.get("late_limit_pct") or 0.0))
        side_changes = int(ctx.get("side_changes") or 0)
        watch_age = float(ctx.get("watch_age_seconds") or 0.0)

        # آیا برخورد بیشتر شبیه سایه سریع بوده یا حرکت تثبیت‌شده؟
        wick_like = False
        if seq:
            hit = seq[-1]
            hit_close_signed = self._signed_return(side, entry, float(hit["close"]))
            wick_like = hit_close_signed > -sl_pct * 0.35

        candidates: list[tuple[str, float, str]] = []
        def add(name: str, score: float, why: str):
            candidates.append((name, max(0.0, min(100.0, score)), why))

        # جهت از ابتدا اشتباه/قفل زودهنگام
        if mfe_fraction <= 0.18 and adverse_close_ratio >= 0.60:
            score = 70 + min(20, adverse_close_ratio * 20) + (8 if first_two < -sl_pct * 0.25 else 0)
            add("جهت از ابتدا درست قفل نشده بود", score,
                "قیمت تقریباً فرصت مفیدی در جهت سیگنال نداد و بیشتر مسیر پس از ورود در سمت مخالف بود.")

        # شروع جعلی: حرکت اولیه وجود داشت ولی ادامه نداد
        if mfe_fraction >= 0.18 and mfe_fraction < 0.80:
            score = 58 + min(28, mfe_fraction * 28) + (6 if net_to_exit < 0 else 0)
            add("شروع حرکت جعلی یا بدون ادامه", score,
                f"قیمت ابتدا {mfe:.3f}٪ در جهت سیگنال رفت، اما فشار لازم برای رسیدن به TP حفظ نشد و کامل برگشت.")

        # روند ضعیف در لحظه ورود
        if strength_score and strength_score < 68:
            add("قدرت روند در ورود مرزی یا ضعیف بود", 55 + (68-strength_score)*1.3,
                f"امتیاز قدرت ثبت‌شده هنگام ورود {strength_score:.1f} بود و حاشیه کافی برای ادامه موج نداشت.")
        elif str(sig.get("strength") or "") == "متوسط" and mfe_fraction < 0.55:
            add("روند متوسط نتوانست ادامه پیدا کند", 64,
                "سیگنال با قدرت متوسط صادر شد و حرکت پس از ورود به اندازه کافی توسعه پیدا نکرد.")

        # ورود دیر بر اساس داده واقعی واچ، نه حدس از نتیجه
        if late_limit > 0 and pre_disp >= late_limit * 0.70:
            add("ورود نزدیک انتهای محدوده مجاز انجام شد", 72 + min(18, pre_disp/max(late_limit,1e-9)*10),
                f"پیش از ورود {pre_disp:.3f}٪ حرکت انجام شده بود؛ این مقدار به حد دیرشدن {late_limit:.3f}٪ نزدیک بود.")

        # ناپایداری جهت در واچ
        if side_changes > 0:
            add("جهت واچ پیش از ورود تغییر کرده بود", 70,
                "جهت در مرحله واچ یک‌بار چرخیده بود؛ این نشانه ناپایداری ساختار کوتاه‌مدت است.")

        # نویز/رفت و برگشت
        if sign_changes >= 3 and total_path > sl_pct * 1.8:
            add("بازار نویزی و رفت‌وبرگشتی بود", 62 + min(25, sign_changes*5),
                f"تا استاپ {sign_changes} بار جهت حرکت کندلی عوض شد و مسیر طی‌شده چند برابر جابه‌جایی خالص بود.")

        # اسپایک
        if wick_like:
            add("استاپ با سایه یا اسپایک کوتاه فعال شد", 76,
                "قیمت در همان کندل به استاپ رسید اما بسته‌شدن کندل بخش بزرگی از حرکت مخالف را پس گرفت.")

        # حرکت پیوسته مخالف
        if adverse_close_ratio >= 0.75 and efficiency >= 0.45:
            add("حرکت واقعی و پیوسته خلاف جهت شکل گرفت", 78 + min(17, adverse_close_ratio*15),
                "حرکت خلاف جهت فقط یک سایه نبود؛ بیشتر بسته‌شدن‌ها مخالف سیگنال و مسیر نسبتاً یک‌طرفه بود.")

        # شواهد ورودی مرزی
        aligned_flow = flow_bias if side == "LONG" else -flow_bias
        if aligned_flow < 0.10:
            add("فشار جهت‌دار هنگام ورود حاشیه کمی داشت", 60 + min(20, max(0,0.10-aligned_flow)*150),
                f"عدم‌تعادل معاملات هم‌جهت در ورود فقط {aligned_flow:.3f} بود.")
        if direction_conf and direction_conf < 75:
            add("اطمینان قفل جهت مرزی بود", 58 + min(20, (75-direction_conf)*1.2),
                f"اعتماد جهت در لحظه ورود {direction_conf:.1f}٪ ثبت شده بود.")

        # اسلیپیج ورود واقعی
        entry_real = float(sig.get("entry_real") or 0.0)
        signal_entry = float(sig.get("entry") or entry)
        if entry_real > 0 and signal_entry > 0:
            slip_signed = self._signed_return(side, signal_entry, entry_real)
            # منفی یعنی ورود واقعی بدتر از قیمت سیگنال
            if slip_signed < -max(0.02, sl_pct*0.12):
                add("ورود واقعی با قیمت بدتر از سیگنال انجام شد", 82,
                    f"اختلاف ورود واقعی با سیگنال حدود {abs(slip_signed):.3f}٪ علیه معامله بود.")

        if not candidates:
            add("حرکت کوتاه‌مدت خلاف سیگنال", 55,
                "داده موجود علت تخصصی واحدی را قطعی نمی‌کند؛ قیمت پیش از رسیدن به TP وارد محدوده استاپ شد.")

        candidates.sort(key=lambda x: x[1], reverse=True)
        primary = candidates[0]
        secondary = candidates[1:4]
        events = [
            f"بیشترین حرکت موافق: {mfe:.3f}٪ ({mfe_fraction*100:.1f}٪ مسیر TP)",
            f"بیشترین حرکت مخالف: {mae:.3f}٪",
            f"مدت تقریبی معامله: {duration_min:.1f} دقیقه",
            f"نسبت بسته‌شدن‌های خلاف جهت: {adverse_close_ratio*100:.0f}٪",
            f"تعداد چرخش‌های کندلی: {sign_changes}",
        ]
        if watch_age > 0:
            events.append(f"مدت حضور در واچ پیش از ورود: {watch_age:.1f} ثانیه")
        return {
            "primary": primary[0],
            "confidence": round(primary[1], 1),
            "primary_explanation": primary[2],
            "secondary": [{"name": n, "confidence": round(sc,1), "explanation": w} for n,sc,w in secondary],
            "events": events,
            "metrics": {
                "tp_pct": round(tp_pct,6), "sl_pct": round(sl_pct,6), "mfe_fraction": round(mfe_fraction,4),
                "adverse_close_ratio": round(adverse_close_ratio,4), "sign_changes": sign_changes,
                "path_efficiency": round(efficiency,4), "pre_entry_displacement_pct": round(pre_disp,6),
            },
            "data_note": "تحلیل از زمینه ثبت‌شده هنگام ورود و مسیر قیمت OKX تا استاپ ساخته شده؛ تغییرات پس از ورودِ Order Flow فقط در صورت ثبت زنده قابل اثبات است.",
        }

    @staticmethod
    def _format_stop_analysis(analysis: dict) -> str:
        lines = [
            "", "🔎 علت دقیق استاپ", f"علت اصلی: {analysis.get('primary','نامشخص')}",
            f"اطمینان تحلیل: {float(analysis.get('confidence') or 0):.1f}%",
            f"توضیح: {analysis.get('primary_explanation','')}", "", "اتفاقات ثبت‌شده:",
        ]
        lines.extend(f"• {x}" for x in analysis.get("events", []))
        secondary = analysis.get("secondary") or []
        if secondary:
            lines.extend(["", "علت‌های فرعی:"])
            for item in secondary:
                lines.append(f"• {item.get('name')} ({float(item.get('confidence') or 0):.1f}٪): {item.get('explanation')}")
        lines.extend(["", f"یادداشت داده: {analysis.get('data_note','')}"])
        return "\n".join(lines)

    def _send_result(self, sig: dict, reason: str, exit_price: float, net: float, gross: float, fee: float, mfe: float = 0.0, mae: float = 0.0, stop_analysis: dict | None = None):
        if not self.telegram:
            return
        icon = "✅" if reason == "TP" else "❌"
        title = "TP خورد" if reason == "TP" else "SL خورد"
        text = (
            f"{icon} {title}\n\n#{sig['id']} | {sig['symbol_id']} | {sig['side']}\n"
            f"Entry: {float(sig.get('entry_real') or sig['entry']):.8g}\nExit: {exit_price:.8g}\n"
            f"PnL خام: {gross:.4f} USDT\nکارمزد/اسلیپیج: {fee:.4f} USDT\nPnL خالص: {net:.4f} USDT\n"
            f"MFE: {mfe:.3f}% | MAE: {mae:.3f}%\nclose_reason: {reason}"
        )
        if reason == "SL" and stop_analysis:
            text += self._format_stop_analysis(stop_analysis)
        self.telegram.send_message(text, reply_to_message_id=sig.get("message_id"))

    def check_virtual(self, sig: dict) -> None:
        # ۱ دقیقه فقط برای تعیین ترتیب برخورد؛ استراتژی همچنان ۵ دقیقه است.
        candles = self.okx.get_candles(sig["okx_symbol"], bar="1m", limit=300)
        reason, exit_price, _ = self.okx.reached_tp_or_sl(candles, sig["side"], float(sig["tp"]), float(sig["sl"]), int(sig["created_at"]) * 1000)
        if not reason or exit_price is None:
            if time.time() - int(sig["created_at"]) > config.VIRTUAL_MONITOR_MAX_MINUTES * 60:
                self.storage.update_signal(sig["id"], status="closed", closed_at=int(time.time()), close_reason="TIMEOUT")
            return
        gross, fee, net = self._pnl(sig, float(sig["entry"]), float(exit_price))
        mfe, mae = self.okx.max_favorable_adverse(candles, sig["side"], float(sig["entry"]), int(sig["created_at"]) * 1000)
        stop_analysis = self._diagnose_stop(sig, candles, float(sig["entry"]), float(exit_price), mfe, mae) if reason == "SL" else None
        self.storage.update_signal(
            sig["id"], status="closed", closed_at=int(time.time()), exit_price=exit_price, gross_pnl=gross,
            fee_usdt=fee, net_pnl=net, close_reason=reason, mfe=mfe, mae=mae,
            stop_primary=(stop_analysis or {}).get("primary", ""),
            stop_confidence=float((stop_analysis or {}).get("confidence", 0.0)),
            stop_analysis_json=stop_analysis or {},
        )
        self.storage.add_profit(net)
        logger.info("[نتیجه عادی] شماره=%s | ارز=%s | نتیجه=%s | خالص=%.4f | خروج=%.8g", sig["id"], sig["symbol_id"], reason, net, exit_price)
        self._send_result(sig, reason, exit_price, net, gross, fee, mfe, mae, stop_analysis)

    def check_real(self, sig: dict) -> None:
        if self.toobit.check_position_opened(sig["toobit_symbol"]):
            return
        opened_ms = int(sig.get("opened_at") or sig.get("created_at") or 0) * 1000
        result = self.toobit.get_closed_trade_result(sig["toobit_symbol"], sig["side"], opened_ms)
        if not result:
            logger.warning("[نتیجه واقعی] پوزیشن بسته است ولی تاریخچه قطعی هنوز نرسیده | شماره=%s | ارز=%s", sig["id"], sig["symbol_id"])
            return
        exit_price = float(result["exit_price"])
        entry = float(sig.get("entry_real") or sig["entry"])
        gross, estimated_fee, estimated_net = self._pnl(sig, entry, exit_price)
        real_fee = float(result.get("fee") or 0.0)
        realized = result.get("realized_pnl")
        if isinstance(realized, (int, float)) and math.isfinite(float(realized)):
            net = float(realized) - real_fee
            fee = real_fee
            gross = net + fee
        else:
            fee, net = estimated_fee, estimated_net
        tp_distance = abs(exit_price - float(sig["tp"]))
        sl_distance = abs(exit_price - float(sig["sl"]))
        reason = "TP" if tp_distance <= sl_distance else "SL"
        candles: list[dict[str, float]] = []
        mfe = mae = 0.0
        stop_analysis = None
        try:
            candles = self.okx.get_candles(sig["okx_symbol"], bar="1m", limit=300)
            mfe, mae = self.okx.max_favorable_adverse(candles, sig["side"], entry, opened_ms)
            if reason == "SL":
                stop_analysis = self._diagnose_stop(sig, candles, entry, exit_price, mfe, mae)
        except Exception as exc:
            logger.warning("[تحلیل استاپ] دریافت مسیر OKX برای معامله واقعی ناموفق بود | شماره=%s | خطا=%s", sig["id"], exc)
        self.storage.update_signal(
            sig["id"], status="closed", closed_at=int(time.time()), exit_price=exit_price, gross_pnl=gross,
            fee_usdt=fee, net_pnl=net, close_reason=reason, mfe=mfe, mae=mae, raw_json=result.get("raw", {}),
            stop_primary=(stop_analysis or {}).get("primary", ""),
            stop_confidence=float((stop_analysis or {}).get("confidence", 0.0)),
            stop_analysis_json=stop_analysis or {},
        )
        self.storage.add_profit(net)
        logger.info("[نتیجه واقعی] شماره=%s | ارز=%s | نتیجه=%s | خالص=%.4f | خروج=%.8g", sig["id"], sig["symbol_id"], reason, net, exit_price)
        self._send_result(sig, reason, exit_price, net, gross, fee, mfe, mae, stop_analysis)

    def tick(self) -> None:
        for sig in self.storage.get_open_signals():
            try:
                if int(sig.get("is_real") or 0):
                    self.check_real(sig)
                else:
                    self.check_virtual(sig)
            except Exception as exc:
                logger.warning("[مانیتور] خطای سیگنال | شماره=%s | ارز=%s | خطا=%s", sig.get("id"), sig.get("symbol_id"), exc)
                self.storage.add_health_event("monitor", "warning", f"monitor failed: {exc}", sig.get("symbol_id"))
