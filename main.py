"""نقطه شروع ربات 5M.
همه مسیرهای سنگین از مسیر تحلیل جدا هستند؛ دستورات تلگرام نباید شکار حرکت و جهت را کند کنند.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, timezone
from collections import Counter

import config
from health import HealthManager
from monitor import Monitor
from okx_client import OKXClient
from profiles import ProfileBuilder
from risk_engine import build_risk_plan
from storage import Storage
from strategy import analyze_symbol_detailed
from symbols import SYMBOLS, SymbolMap
from telegram_bot import TelegramBot
from toobit_client import ToobitFuturesClient


def _build_logger() -> logging.Logger:
    level = getattr(logging, str(getattr(config, "LOG_LEVEL", "INFO")).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    return logging.getLogger("futures_hunt_2")


logger = _build_logger()

class TradingBotApp:
    def __init__(self):
        self.storage = Storage()
        self.health = HealthManager(self.storage)
        self.okx = OKXClient()
        self.toobit = ToobitFuturesClient()
        self.telegram = TelegramBot(self.storage, self.health)
        self.monitor = Monitor(self.okx, self.toobit, self.storage, self.telegram)
        self.profiles = ProfileBuilder(self.okx, self.storage)
        self._stop = threading.Event()
        self._last_signal_ts: dict[str, int] = {}
        self._last_profile_day: str | None = None
        self._scan_count = 0
        self._signal_count = 0

    def signal_eligibility(self, sym: SymbolMap) -> tuple[bool, str]:
        if self.storage.is_blacklisted(sym.id):
            return False, "blacklisted"
        last = self._last_signal_ts.get(sym.id, 0)
        if time.time() - last < config.SIGNAL_COOLDOWN_SECONDS_PER_SYMBOL:
            return False, "cooldown"
        return True, "eligible"

    def reserve_real_slot(self) -> int | None:
        max_pos = int(self.storage.get("max_positions", config.MAX_POSITIONS_DEFAULT))
        open_real = self.storage.count_real_open()
        if open_real >= max_pos:
            return None
        return open_real + 1

    def send_signal_message(self, signal_data: dict, risk) -> int | None:
        side_icon = "🟢" if signal_data["side"] == "LONG" else "🔴"
        txt = (
            f"📊 سیگنال 5M\n\n"
            f"#{signal_data.get('id','?')} | {signal_data['symbol_id']}\n"
            f"{side_icon} {signal_data['side']}\n"
            f"قدرت تخمینی: {signal_data['strength']}\n"
            f"Entry: {signal_data['entry']:.8g}\n"
            f"TP: {risk.tp:.8g}\n"
            f"SL: {risk.sl:.8g}\n"
            f"RR: {risk.rr}\n"
            f"سود خالص تخمینی: {risk.estimated_net_profit:.4f} USDT\n"
            f"مدل: Compression + Flow + Absorption"
        )
        return self.telegram.send_message(txt)

    def try_open_real(self, sym: SymbolMap, data: dict, risk) -> tuple[bool, str | None]:
        try:
            leverage = int(self.storage.get("leverage", config.LEVERAGE_DEFAULT))
            trade_usdt = float(self.storage.get("trade_usdt", config.TRADE_USDT_DEFAULT))
            client_id = f"bot_{data['symbol_id']}_{int(time.time())}"
            res = self.toobit.open_futures_position_with_tpsl(
                symbol=sym.toobit,
                side=data["side"],
                usdt_amount=trade_usdt,
                leverage=leverage,
                entry_price=data["entry"],
                tp_price=risk.tp,
                sl_price=risk.sl,
                client_order_id=client_id,
            )
            self.health.mark("toobit")
            logger.info("REAL_ORDER_SENT symbol=%s side=%s order_id=%s", sym.id, data["side"], res.get("order_id") or client_id)
            return True, str(res.get("order_id") or client_id)
        except Exception as exc:
            logger.warning("REAL_ORDER_FAILED symbol=%s error=%s", sym.id, exc)
            self.storage.add_health_event("toobit_order", "warning", f"open real failed: {exc}", sym.id)
            return False, None

    def analyze_one(self, sym: SymbolMap) -> tuple[str, dict]:
        eligible, eligibility_reason = self.signal_eligibility(sym)
        if not eligible:
            return eligibility_reason, {}
        try:
            candles = self.okx.get_candles(sym.okx)
            self.health.mark("okx")
            analysis = analyze_symbol_detailed(sym.id, sym.okx, sym.toobit, candles)
            if not analysis.signal:
                return analysis.reject_reason, analysis.details
            sig = analysis.signal

            risk = build_risk_plan(sig, self.storage)
            if risk is None:
                profile = self.storage.get_profile(sig.symbol_id) or {}
                if not profile or float(profile.get("min_sl_pct") or 0.0) <= 0:
                    return "noise_profile_fail", analysis.details
                if int(profile.get("signal_count") or 0) < int(getattr(config, "PROFILE_MIN_SIGNALS", 8)):
                    d = dict(analysis.details)
                    d["profile_signal_count"] = int(profile.get("signal_count") or 0)
                    return "tp_profile_samples_fail", d
                return "risk_plan_fail", analysis.details
            if not risk.min_net_profit_ok:
                reason = "min_net_profit_fail" if risk.estimated_net_profit < config.MIN_NET_PROFIT_USDT else "tp_profile_fail"
                d = dict(analysis.details)
                d["estimated_net_profit"] = round(risk.estimated_net_profit, 6)
                d["risk_reason"] = risk.reason
                return reason, d

            trading_on = bool(self.storage.get("trading_enabled", False))
            auto_on = bool(self.storage.get("auto_signal_enabled", True))
            slot = self.reserve_real_slot() if trading_on and auto_on else None
            is_real = slot is not None
            data = {
                "symbol_id": sig.symbol_id,
                "okx_symbol": sig.okx_symbol,
                "toobit_symbol": sig.toobit_symbol,
                "side": sig.side,
                "strength": sig.strength,
                "entry": sig.entry,
                "tp": risk.tp,
                "sl": risk.sl,
                "rr": risk.rr,
                "trade_mode": "real" if is_real else "virtual",
                "status": "pending" if is_real else "open",
                "is_real": is_real,
                "slot_id": slot,
                "raw": {"reason": sig.reason, "risk_reason": risk.reason},
            }
            signal_id = self.storage.create_signal(data)
            data["id"] = signal_id
            msg_id = self.send_signal_message(data, risk)
            if msg_id:
                self.storage.update_signal(signal_id, message_id=msg_id)
            if is_real:
                opened_sent, order_id = self.try_open_real(sym, data, risk)
                self.storage.update_signal(signal_id, order_id=order_id)
                if not opened_sent:
                    self.storage.update_signal(signal_id, status="open", is_real=0, slot_id=None, close_reason="REAL_OPEN_FAILED_TO_VIRTUAL")
                else:
                    threading.Thread(target=self._check_real_after_70s, args=(signal_id, sym), daemon=True).start()
            self._last_signal_ts[sym.id] = int(time.time())
            self._signal_count += 1
            logger.info("SIGNAL id=%s symbol=%s side=%s strength=%s mode=%s entry=%.8g tp=%.8g sl=%.8g", signal_id, sym.id, data["side"], data["strength"], data["trade_mode"], data["entry"], data["tp"], data["sl"])
            return "accepted", analysis.details
        except Exception as exc:
            logger.warning("SYMBOL_SKIPPED symbol=%s error=%s", sym.id, exc)
            self.storage.add_health_event("analysis", "warning", f"symbol skipped: {exc}", sym.id)
            self.storage.blacklist_symbol(sym.id, str(exc)[:180], config.SYMBOL_ERROR_BLACKLIST_SECONDS)
            return "symbol_error", {"error": str(exc)[:180]}

    def _check_real_after_70s(self, signal_id: int, sym: SymbolMap) -> None:
        time.sleep(config.ORDER_OPEN_CHECK_SECONDS)
        try:
            opened = self.toobit.check_position_opened(sym.toobit)
            self.health.mark("toobit")
            if opened:
                logger.info("REAL_POSITION_CONFIRMED signal_id=%s symbol=%s", signal_id, sym.id)
                self.storage.update_signal(signal_id, status="open", opened_at=int(time.time()))
            else:
                logger.warning("REAL_POSITION_NOT_OPEN signal_id=%s symbol=%s slot_released=true", signal_id, sym.id)
                self.storage.update_signal(signal_id, status="open", is_real=0, slot_id=None, close_reason="NOT_OPENED_AFTER_70S")
                self.storage.add_health_event("toobit_position", "warning", "بعد ۷۰ ثانیه پوزیشن باز نبود؛ اسلات آزاد شد", sym.id)
        except Exception as exc:
            logger.warning("REAL_POSITION_CHECK_FAILED signal_id=%s symbol=%s error=%s", signal_id, sym.id, exc)
            self.storage.update_signal(signal_id, status="open", is_real=0, slot_id=None, close_reason="POSITION_CHECK_FAILED")
            self.storage.add_health_event("toobit_position", "warning", f"70s check failed: {exc}", sym.id)

    def analysis_loop(self) -> None:
        while not self._stop.is_set():
            start = time.time()
            rejects: Counter[str] = Counter()
            detail_rows: list[tuple[str, str, dict]] = []
            for sym in SYMBOLS:
                reason, details = self.analyze_one(sym)
                rejects[reason] += 1
                if (
                    getattr(config, "DEBUG_REJECTS", True)
                    and reason not in {"accepted", "compression_fail", "candles_too_few", "cooldown", "blacklisted"}
                    and len(detail_rows) < int(getattr(config, "REJECT_DETAIL_LIMIT_PER_CYCLE", 8))
                ):
                    detail_rows.append((sym.id, reason, details))
            self.health.mark("signal")
            self._scan_count += 1
            elapsed = time.time() - start
            logger.info("SCAN_DONE cycle=%s symbols=%s elapsed=%.2fs total_signals=%s open_signals=%s", self._scan_count, len(SYMBOLS), elapsed, self._signal_count, len(self.storage.get_open_signals()))

            every = max(1, int(getattr(config, "REJECT_SUMMARY_EVERY_CYCLES", 1)))
            if getattr(config, "DEBUG_REJECTS", True) and self._scan_count % every == 0:
                ordered = [
                    "compression_fail", "candles_too_few", "flow_fail", "absorption_fail",
                    "weak_strength", "min_strength_fail", "noise_profile_fail",
                    "tp_profile_samples_fail", "tp_profile_fail", "min_net_profit_fail",
                    "risk_plan_fail", "cooldown", "blacklisted", "symbol_error", "accepted",
                ]
                summary = " ".join(f"{k}={rejects.get(k, 0)}" for k in ordered)
                logger.info("REJECT_SUMMARY cycle=%s %s", self._scan_count, summary)
                for symbol_id, reason, details in detail_rows:
                    compact = ",".join(f"{k}={v}" for k, v in details.items() if k != "compression_detail")
                    logger.info("SIGNAL_REJECTED symbol=%s reason=%s %s", symbol_id, reason, compact)

            time.sleep(max(1.0, config.ANALYSIS_INTERVAL_SECONDS - elapsed))

    def monitor_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.monitor.tick()
                self.health.mark("monitor")
            except Exception as exc:
                logger.warning("MONITOR_LOOP_ERROR error=%s", exc)
                self.storage.add_health_event("monitor_loop", "warning", str(exc))
            time.sleep(5)

    def telegram_loop(self) -> None:
        while not self._stop.is_set():
            self.telegram.poll_once()
            self.health.mark("telegram")
            time.sleep(config.TELEGRAM_POLL_SECONDS)

    def profile_loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            day = now.strftime("%Y-%m-%d")
            should_run = (
                self._last_profile_day != day
                and now.hour == config.PROFILE_UPDATE_HOUR_UTC
                and now.minute >= config.PROFILE_UPDATE_MINUTE_UTC
            )
            if should_run:
                try:
                    logger.info("PROFILE_UPDATE_START mode=daily")
                    self.profiles.update_all()
                    self.health.mark("profiles")
                    logger.info("PROFILE_UPDATE_DONE mode=daily")
                    self._last_profile_day = day
                except Exception as exc:
                    logger.warning("PROFILE_UPDATE_FAILED mode=daily error=%s", exc)
                    self.storage.add_health_event("profiles", "warning", f"daily profile failed: {exc}")
            time.sleep(30)

    def toobit_status_loop(self) -> None:
        """کش سبک وضعیت توبیت برای پنل ترید/سلامت.
        این لوپ جداست تا هیچ دستور تلگرام یا پنل، مسیر تحلیل را کند نکند.
        """
        while not self._stop.is_set():
            try:
                bal = self.toobit.get_futures_balance()
                now_ts = int(time.time())
                self.storage.set("toobit_connected", True)
                available_usdt = float(bal.get("available", 0.0) or 0.0)
                total_usdt = float(bal.get("total", 0.0) or 0.0)
                raw_margin_usdt = float(bal.get("margin", 0.0) or 0.0)
                # بعضی پاسخ‌های Toobit فیلد margin/equity جدا نمی‌دهند یا صفر می‌دهند،
                # در فیوچرز ایزوله معیار قابل استفاده برای پنل همان موجودی آزاد است.
                usable_margin_usdt = raw_margin_usdt if raw_margin_usdt > 0 else available_usdt
                self.storage.set("toobit_margin_usdt", usable_margin_usdt)
                self.storage.set("toobit_available_usdt", available_usdt)
                self.storage.set("toobit_total_usdt", total_usdt)
                self.storage.set("toobit_last_error", "")
                self.storage.set("toobit_last_update", now_ts)
                self.health.mark("toobit")
                logger.info("TOOBIT_STATUS connected=true available=%.4f total=%.4f usable_margin=%.4f", available_usdt, total_usdt, usable_margin_usdt)
            except Exception as exc:
                logger.warning("TOOBIT_STATUS connected=false error=%s", exc)
                self.storage.set("toobit_connected", False)
                self.storage.set("toobit_last_error", str(exc)[:240])
                self.storage.set("toobit_last_update", int(time.time()))
                self.storage.add_health_event("toobit_balance", "warning", f"balance/status failed: {exc}")
            time.sleep(max(5, int(getattr(config, "TOOBIT_STATUS_INTERVAL_SECONDS", 15))))

    def startup_profile_update(self) -> None:
        """یک بار بعد از روشن شدن ربات پروفایل‌ها را در بک‌گراند می‌سازد.
        مسیر تحلیل کند نمی‌شود؛ تا قبل از آماده شدن پروفایل‌ها، risk_engine سیگنال خام صادر نمی‌کند.
        """
        try:
            logger.info("PROFILE_UPDATE_START mode=startup")
            self.profiles.update_all()
            self.health.mark("profiles")
            self._last_profile_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logger.info("PROFILE_UPDATE_DONE mode=startup")
        except Exception as exc:
            logger.warning("PROFILE_UPDATE_FAILED mode=startup error=%s", exc)
            self.storage.add_health_event("profiles", "warning", f"startup profile failed: {exc}")

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.analysis_loop, daemon=True),
            threading.Thread(target=self.monitor_loop, daemon=True),
            threading.Thread(target=self.telegram_loop, daemon=True),
            threading.Thread(target=self.profile_loop, daemon=True),
            threading.Thread(target=self.toobit_status_loop, daemon=True),
            threading.Thread(target=self.startup_profile_update, daemon=True),
        ]
        logger.info("BOT_START version=live-logging symbols=%s analysis_interval=%ss", len(SYMBOLS), config.ANALYSIS_INTERVAL_SECONDS)
        for t in threads:
            t.start()
            logger.info("THREAD_STARTED name=%s", t.name)
        logger.info("BOT_READY trading_enabled=%s auto_signal=%s", self.storage.get("trading_enabled", False), self.storage.get("auto_signal_enabled", True))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self._stop.set()
            logger.info("BOT_STOP requested=keyboard_interrupt")

if __name__ == "__main__":
    TradingBotApp().run()
