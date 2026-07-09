"""نقطه شروع ربات 5M.
همه مسیرهای سنگین از مسیر تحلیل جدا هستند؛ دستورات تلگرام نباید شکار حرکت و جهت را کند کنند.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import config
from health import HealthManager
from monitor import Monitor
from okx_client import OKXClient
from profiles import ProfileBuilder
from risk_engine import build_risk_plan
from storage import Storage
from strategy import analyze_symbol
from symbols import SYMBOLS, SymbolMap
from telegram_bot import TelegramBot
from toobit_client import ToobitFuturesClient

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

    def can_signal(self, sym: SymbolMap) -> bool:
        if self.storage.is_blacklisted(sym.id):
            return False
        last = self._last_signal_ts.get(sym.id, 0)
        return time.time() - last >= config.SIGNAL_COOLDOWN_SECONDS_PER_SYMBOL

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
            return True, str(res.get("order_id") or client_id)
        except Exception as exc:
            self.storage.add_health_event("toobit_order", "warning", f"open real failed: {exc}", sym.id)
            return False, None

    def analyze_one(self, sym: SymbolMap) -> None:
        if not self.can_signal(sym):
            return
        try:
            candles = self.okx.get_candles(sym.okx)
            self.health.mark("okx")
            sig = analyze_symbol(sym.id, sym.okx, sym.toobit, candles)
            if not sig:
                return
            risk = build_risk_plan(sig, self.storage)
            if not risk or not risk.min_net_profit_ok:
                return
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
        except Exception as exc:
            self.storage.add_health_event("analysis", "warning", f"symbol skipped: {exc}", sym.id)
            self.storage.blacklist_symbol(sym.id, str(exc)[:180], config.SYMBOL_ERROR_BLACKLIST_SECONDS)

    def _check_real_after_70s(self, signal_id: int, sym: SymbolMap) -> None:
        time.sleep(config.ORDER_OPEN_CHECK_SECONDS)
        try:
            opened = self.toobit.check_position_opened(sym.toobit)
            self.health.mark("toobit")
            if opened:
                self.storage.update_signal(signal_id, status="open", opened_at=int(time.time()))
            else:
                self.storage.update_signal(signal_id, status="open", is_real=0, slot_id=None, close_reason="NOT_OPENED_AFTER_70S")
                self.storage.add_health_event("toobit_position", "warning", "بعد ۷۰ ثانیه پوزیشن باز نبود؛ اسلات آزاد شد", sym.id)
        except Exception as exc:
            self.storage.update_signal(signal_id, status="open", is_real=0, slot_id=None, close_reason="POSITION_CHECK_FAILED")
            self.storage.add_health_event("toobit_position", "warning", f"70s check failed: {exc}", sym.id)

    def analysis_loop(self) -> None:
        while not self._stop.is_set():
            start = time.time()
            for sym in SYMBOLS:
                self.analyze_one(sym)
            self.health.mark("signal")
            elapsed = time.time() - start
            time.sleep(max(1.0, config.ANALYSIS_INTERVAL_SECONDS - elapsed))

    def monitor_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.monitor.tick()
                self.health.mark("monitor")
            except Exception as exc:
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
                    self.profiles.update_all()
                    self.health.mark("profiles")
                    self._last_profile_day = day
                except Exception as exc:
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
                self.storage.set("toobit_margin_usdt", float(bal.get("margin", 0.0) or 0.0))
                self.storage.set("toobit_available_usdt", float(bal.get("available", 0.0) or 0.0))
                self.storage.set("toobit_total_usdt", float(bal.get("total", 0.0) or 0.0))
                self.storage.set("toobit_last_error", "")
                self.storage.set("toobit_last_update", now_ts)
                self.health.mark("toobit")
            except Exception as exc:
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
            self.profiles.update_all()
            self.health.mark("profiles")
            self._last_profile_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        except Exception as exc:
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
        for t in threads:
            t.start()
        print("Trading bot started. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self._stop.set()
            print("Stopping...")

if __name__ == "__main__":
    TradingBotApp().run()
