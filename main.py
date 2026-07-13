"""نقطه شروع ربات UEM یک‌ساعته."""
from __future__ import annotations
from collections import OrderedDict
import logging
import sys
import threading
import time
import config
from health import HealthManager
from market_engine import (
    confirm_signal_diagnostic,
    detect_candidate_diagnostic,
    detect_impulse_candidate_diagnostic,
    update_watch_state,
)
from models import MarketCandidate, MarketSignal, RiskPlan, WatchState
from monitor import Monitor
from okx_client import OKXClient
from risk_engine import build_risk_plan_diagnostic
from storage import Storage
from symbols import SYMBOLS, SymbolMap
from telegram_bot import TelegramBot
from toobit_client import ToobitFuturesClient

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO), format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s", stream=sys.stdout)
logger = logging.getLogger("uem_1h")

class TradingBotApp:
    def __init__(self):
        self.storage = Storage(); self.health = HealthManager(self.storage)
        self.okx = OKXClient(); self.toobit = ToobitFuturesClient()
        self.telegram = TelegramBot(self.storage, self.health)
        self.monitor = Monitor(self.okx, self.toobit, self.storage, self.telegram, self.health)
        self.stop_event = threading.Event()
        self.watch: OrderedDict[str, WatchState] = OrderedDict()
        self.watch_lock = threading.RLock()
        self.last_signal: dict[str, int] = {}
        self._reject_log_cache: dict[tuple[str, str], tuple[str, float]] = {}

    @staticmethod
    def _metrics_text(metrics: dict) -> str:
        parts: list[str] = []
        for key in sorted(metrics):
            value = metrics[key]
            if isinstance(value, float):
                parts.append(f"{key}={value:.6g}")
            else:
                parts.append(f"{key}={value}")
        return " | ".join(parts)

    def _log_reject(self, stage: str, symbol_id: str, reason: str, metrics: dict | None = None, force: bool = False) -> None:
        if not getattr(config, "LOG_REJECT_REASONS", True):
            return
        key = (stage, symbol_id)
        now = time.time()
        previous_reason, previous_ts = self._reject_log_cache.get(key, ("", 0.0))
        repeat = float(getattr(config, "REJECT_LOG_REPEAT_SECONDS", 30.0))
        if not force and reason == previous_reason and now - previous_ts < repeat:
            return
        self._reject_log_cache[key] = (reason, now)
        detail = self._metrics_text(metrics or {})
        logger.info("رد | مرحله=%s | ارز=%s | علت=%s%s", stage, symbol_id, reason, f" | {detail}" if detail else "")

    def _eligibility(self, sym: SymbolMap) -> tuple[bool, str]:
        if self.storage.is_blacklisted(sym.id):
            return False, "ارز به‌دلیل خطای داده در بلک‌لیست موقت است"
        if any(x["symbol_id"] == sym.id for x in self.storage.get_open_signals()):
            return False, "برای این ارز سیگنال باز یا Pending وجود دارد"
        remaining = config.SIGNAL_COOLDOWN_SECONDS_PER_SYMBOL - (time.time() - self.last_signal.get(sym.id, 0))
        if remaining > 0:
            return False, f"کول‌داون پس از سیگنال فعال است؛ {int(remaining)} ثانیه باقی مانده"
        return True, "مجاز"

    def _eligible(self, sym: SymbolMap) -> bool:
        return self._eligibility(sym)[0]

    def _put_watch(self, candidate: MarketCandidate) -> None:
        now = time.time()
        with self.watch_lock:
            current = self.watch.get(candidate.symbol_id)
            if current is None:
                self.watch[candidate.symbol_id] = WatchState(
                    candidate.symbol_id, candidate.okx_symbol, candidate.toobit_symbol,
                    now, candidate, last_reanalysis_at=now, last_scenario_change_at=now,
                )
                logger.info("واچ جدید | ارز=%s | جهت=%s | منبع=%s | سطح=%.8g | ابطال=%.8g | علت=%s",
                            candidate.symbol_id, candidate.side, candidate.source,
                            candidate.structure_level, candidate.invalidation_price, candidate.direction_reason)
            else:
                old = current.candidate
                changed = old.side != candidate.side or old.source != candidate.source
                current.candidate = candidate
                current.last_reanalysis_at = now
                if changed:
                    current.last_scenario_change_at = now
                    current.prices.clear(); current.trade_values.clear(); current.book_values.clear(); current.micro_values.clear()
                    current.opposite_pressure_count = current.aligned_pressure_count = current.break_seen_count = 0
                    logger.info("تغییر سناریو | ارز=%s | %s/%s -> %s/%s | سطح %.8g -> %.8g | علت=%s",
                                candidate.symbol_id, old.side, old.source, candidate.side, candidate.source,
                                old.structure_level, candidate.structure_level, candidate.direction_reason)
                else:
                    logger.info("به‌روزرسانی سناریو | ارز=%s | جهت=%s | منبع=%s | سطح=%.8g | ابطال=%.8g",
                                candidate.symbol_id, candidate.side, candidate.source,
                                candidate.structure_level, candidate.invalidation_price)
                self.watch.move_to_end(candidate.symbol_id)
            while len(self.watch) > config.MAX_WATCH_SYMBOLS:
                removed_id, _ = self.watch.popitem(last=False)
                self._log_reject("watch-capacity", removed_id, "ظرفیت واچ پر شد و قدیمی‌ترین ارز حذف شد", force=True)

    def _fresh_candidate(self, sym: SymbolMap) -> tuple[MarketCandidate | None, str, dict]:
        candles_1h = self.okx.get_candles(sym.okx, bar=config.OKX_PRIMARY_BAR, limit=config.OKX_CANDLE_LIMIT)
        candidate, reason, metrics = detect_candidate_diagnostic(sym, candles_1h)
        atr = float(metrics.get("atr_pct") or 0.0)
        if candidate is not None:
            return candidate, reason, metrics
        try:
            candles_5m = self.okx.get_candles(sym.okx, bar=config.IMPULSE_BAR, limit=config.IMPULSE_CANDLE_LIMIT)
            impulse, impulse_reason, impulse_metrics = detect_impulse_candidate_diagnostic(sym, candles_5m, atr)
            if impulse is not None:
                return impulse, impulse_reason, {**metrics, **{f"impulse_{k}": v for k, v in impulse_metrics.items()}}
            return None, f"1H: {reason} | 5m: {impulse_reason}", {**metrics, **{f"impulse_{k}": v for k, v in impulse_metrics.items()}}
        except Exception as exc:
            return None, f"1H: {reason} | بررسی 5m ناموفق: {exc}", metrics

    def light_scan_loop(self) -> None:
        while not self.stop_event.is_set():
            start = time.time()
            for sym in SYMBOLS:
                if self.stop_event.is_set():
                    break
                eligible, eligibility_reason = self._eligibility(sym)
                if not eligible:
                    self._log_reject("eligibility", sym.id, eligibility_reason)
                    continue
                try:
                    candidate, reject_reason, metrics = self._fresh_candidate(sym)
                    self.health.mark("okx")
                    if candidate:
                        self._put_watch(candidate)
                    else:
                        self._log_reject("direction-or-impulse", sym.id, reject_reason, metrics)
                except Exception as exc:
                    message = str(exc)
                    logger.warning("scan %s: %s", sym.id, message)
                    global_data_error = "connection error" in message.lower() or "timeout" in message.lower() or "http 5" in message.lower()
                    if global_data_error:
                        self.storage.add_health_event("okx", "warning", message)
                    else:
                        self.storage.blacklist(sym.id, message, config.SYMBOL_ERROR_BLACKLIST_SECONDS)
            self.health.mark("signal")
            self.stop_event.wait(max(1.0, config.LIGHT_SCAN_INTERVAL_SECONDS - (time.time() - start)))

    def watch_loop(self) -> None:
        while not self.stop_event.is_set():
            with self.watch_lock:
                items = list(self.watch.items())
            for symbol_id, state in items:
                sym = next((s for s in SYMBOLS if s.id == symbol_id), None)
                if sym is None:
                    with self.watch_lock:
                        self.watch.pop(symbol_id, None)
                    continue
                age = time.time() - state.started_at
                eligible, eligibility_reason = self._eligibility(sym)
                if age > config.WATCH_MAX_SECONDS:
                    self._log_reject("watch-expired", symbol_id, f"عمر واچ تمام شد: {int(age)}>{config.WATCH_MAX_SECONDS} ثانیه", force=True)
                    with self.watch_lock:
                        self.watch.pop(symbol_id, None)
                    continue
                if not eligible:
                    self._log_reject("watch-eligibility", symbol_id, eligibility_reason, force=True)
                    with self.watch_lock:
                        self.watch.pop(symbol_id, None)
                    continue
                try:
                    snap = self.okx.get_micro_snapshot(state.okx_symbol)
                    action, action_reason, action_metrics = update_watch_state(state, snap)
                    self.health.mark("okx")

                    due = time.time() - state.last_reanalysis_at >= config.WATCH_REANALYZE_SECONDS
                    if action == "REANALYZE" or due:
                        fresh, fresh_reason, fresh_metrics = self._fresh_candidate(sym)
                        state.last_reanalysis_at = time.time()
                        if fresh is not None:
                            old_side = state.candidate.side
                            self._put_watch(fresh)
                            with self.watch_lock:
                                state = self.watch.get(symbol_id, state)
                            if old_side != fresh.side:
                                logger.info("چرخش جهت واچ | ارز=%s | %s -> %s | علت=%s | %s",
                                            symbol_id, old_side, fresh.side, action_reason, self._metrics_text(action_metrics))
                        elif action == "REANALYZE":
                            # سناریوی قبلی باطل شده، ولی خود ارز در واچ می‌ماند و در دور بعد دوباره تحلیل می‌شود.
                            logger.info("ابطال سناریو بدون خروج از واچ | ارز=%s | جهت قبلی=%s | علت=%s | تحلیل تازه=%s",
                                        symbol_id, state.candidate.side, action_reason, fresh_reason)
                            state.opposite_pressure_count = 0
                            state.break_seen_count = 0
                            self._log_reject("watch-reanalysis", symbol_id, fresh_reason, {**action_metrics, **fresh_metrics}, force=True)

                    signal, reject_reason, metrics = confirm_signal_diagnostic(state.candidate, snap, state)
                    if signal:
                        if self.publish_signal(signal):
                            with self.watch_lock:
                                self.watch.pop(symbol_id, None)
                    else:
                        self._log_reject("entry", symbol_id, reject_reason, metrics)
                except Exception as exc:
                    logger.warning("watch %s: %s", symbol_id, exc)
            self.stop_event.wait(config.WATCH_INTERVAL_SECONDS)

    def _reserve_real_slot(self) -> int | None:
        max_pos = int(self.storage.get("max_positions", config.MAX_POSITIONS_DEFAULT))
        count = self.storage.count_real_open()
        return count + 1 if count < max_pos else None

    def _signal_message(self, signal_id: int, sig: MarketSignal, risk: RiskPlan, mode: str, trade_usdt: float, leverage: int) -> str:
        icon = "🟢" if sig.side == "LONG" else "🔴"
        return (f"📊 سیگنال 1H UEM\n\n#{signal_id} | {sig.symbol_id}\n{icon} {sig.side} | {'واقعی' if mode=='real' else 'عادی'}\n"
                f"قدرت: {sig.strength}\nEntry: {risk.entry:.8g}\nTP: {risk.tp:.8g}\nSL: {risk.sl:.8g}\nRR خالص: {risk.rr_net:.3f}\n"
                f"دلار: {trade_usdt:g} | لوریج: {leverage}x | ارزش پوزیشن: {risk.notional:.4f} USDT\n"
                f"سود خالص تخمینی TP: {risk.estimated_tp_net:.4f} USDT\nزیان خالص تخمینی SL: {risk.estimated_sl_net_loss:.4f} USDT\n"
                f"جهت: {sig.direction_reason}\nقدرت: {sig.strength_reason}\nورود: {sig.entry_reason}")

    def publish_signal(self, sig: MarketSignal) -> bool:
        trade_usdt = float(self.storage.get("trade_usdt", config.TRADE_USDT_DEFAULT)); leverage = int(self.storage.get("leverage", config.LEVERAGE_DEFAULT))
        risk, reject_reason, metrics = build_risk_plan_diagnostic(sig, trade_usdt, leverage)
        if not risk:
            self._log_reject("risk", sig.symbol_id, reject_reason, metrics, force=True)
            return False
        trading = bool(self.storage.get("trading_enabled", False)); auto = bool(self.storage.get("auto_signal_enabled", True))
        connected = bool(self.storage.get("toobit_connected", False)); slot = self._reserve_real_slot() if trading and auto and connected else None
        is_real = slot is not None; mode = "real" if is_real else "virtual"
        data = {"symbol_id":sig.symbol_id,"okx_symbol":sig.okx_symbol,"toobit_symbol":sig.toobit_symbol,"side":sig.side,"strength":sig.strength,
                "entry":risk.entry,"tp":risk.tp,"sl":risk.sl,"rr":risk.rr_net,"trade_mode":mode,"status":"pending" if is_real else "open","is_real":is_real,"slot_id":slot,
                "message_id":None,"created_at":int(time.time()),"opened_at":None,"entry_real":None,"trade_usdt":trade_usdt,"leverage":leverage,"notional":risk.notional,"order_id":None,
                "raw":{"direction":sig.direction_reason,"strength":sig.strength_reason,"entry":sig.entry_reason,"risk":risk.reason}}
        signal_id = self.storage.create_signal(data)
        msg_id = self.telegram.send_message(self._signal_message(signal_id, sig, risk, mode, trade_usdt, leverage))
        if msg_id:
            self.storage.update_signal(signal_id, message_id=msg_id)
        if is_real:
            try:
                result = self.toobit.open_futures_position_with_tpsl(
                    sig.toobit_symbol, sig.side, trade_usdt, leverage, risk.entry, risk.tp, risk.sl,
                    f"uem_{signal_id}_{int(time.time())}",
                )
                self.storage.update_signal(signal_id, order_id=result.get("order_id"))
                threading.Thread(
                    target=self._check_after_70s,
                    args=(signal_id,),
                    daemon=True,
                    name=f"check70-{sig.symbol_id}",
                ).start()
            except Exception as exc:
                self.storage.update_signal(
                    signal_id, status="open", is_real=0, trade_mode="virtual", slot_id=None,
                    close_reason="REAL_OPEN_FAILED_TO_VIRTUAL",
                )
                self.storage.add_health_event("toobit_order", "warning", str(exc), sig.symbol_id)
                self.telegram.send_message(
                    f"⚠️ سفارش واقعی سیگنال #{signal_id} باز نشد و سیگنال به حالت عادی تبدیل شد.\nخطا: {exc}",
                    reply_to_message_id=msg_id,
                )
        self.last_signal[sig.symbol_id] = int(time.time())
        logger.info("signal #%s %s %s %s", signal_id, sig.symbol_id, sig.side, mode)
        return True

    def _check_after_70s(self, signal_id: int) -> None:
        time.sleep(config.ORDER_OPEN_CHECK_SECONDS)
        try:
            state = self.monitor.reconcile_pending_real(signal_id)
            sig = self.storage.get_signal(signal_id) or {}
            message_id = sig.get("message_id")
            if state == "opened":
                self.telegram.send_message(
                    f"✅ پوزیشن واقعی سیگنال #{signal_id} در توبیت تأیید شد.",
                    reply_to_message_id=message_id,
                )
            elif state == "closed":
                # نتیجه توسط مانیتور روی همان پیام ارسال شده است.
                return
            elif state == "not_found":
                # نبود پوزیشن و نبود نتیجه قطعی به معنی شکست سفارش نیست؛
                # سیگنال pending می‌ماند تا مانیتور دوباره از توبیت بررسی کند.
                self.storage.add_health_event(
                    "toobit_position", "warning",
                    "بعد از ۷۰ ثانیه نه پوزیشن باز و نه نتیجه قطعی سفارش پیدا شد؛ بررسی ادامه دارد",
                    sig.get("symbol_id"),
                )
                self.telegram.send_message(
                    f"⚠️ وضعیت سفارش واقعی سیگنال #{signal_id} هنوز قطعی نیست؛ مانیتور توبیت بررسی را ادامه می‌دهد.",
                    reply_to_message_id=message_id,
                )
        except Exception as exc:
            sig = self.storage.get_signal(signal_id) or {}
            self.storage.add_health_event(
                "toobit_position", "warning", f"70s check failed: {exc}", sig.get("symbol_id")
            )
            self.telegram.send_message(
                f"⚠️ بررسی ۷۰ ثانیه‌ای سیگنال #{signal_id} ناموفق بود؛ سیگنال واقعی حذف یا مجازی نشد و بررسی ادامه دارد.",
                reply_to_message_id=sig.get("message_id"),
            )

    def monitor_loop(self) -> None:
        while not self.stop_event.is_set():
            self.monitor.run_once(); self.stop_event.wait(config.MONITOR_INTERVAL_SECONDS)

    def toobit_status_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                bal = self.toobit.get_futures_balance()
                self.storage.set("toobit_connected", True); self.storage.set("toobit_available_usdt", bal["available"]); self.storage.set("toobit_total_usdt", bal["total"]); self.storage.set("toobit_margin_usdt", bal["margin"])
                self.storage.set("toobit_last_error", ""); self.storage.set("toobit_last_update", int(time.time())); self.storage.clear_health_component("toobit")
                self.health.mark("toobit")
            except Exception as exc:
                self.storage.set("toobit_connected", False)
                self.storage.set("toobit_last_error", str(exc))
                self.storage.set("toobit_last_update", int(time.time()))
                self.storage.add_health_event("toobit", "warning", str(exc))
            self.stop_event.wait(config.TOOBIT_STATUS_INTERVAL_SECONDS)

    def telegram_loop(self) -> None:
        while not self.stop_event.is_set():
            self.telegram.poll_once(); self.stop_event.wait(config.TELEGRAM_POLL_SECONDS)

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.light_scan_loop, daemon=True, name="light-scan"),
            threading.Thread(target=self.watch_loop, daemon=True, name="watch"),
            threading.Thread(target=self.monitor_loop, daemon=True, name="monitor"),
            threading.Thread(target=self.toobit_status_loop, daemon=True, name="toobit-status"),
            threading.Thread(target=self.telegram_loop, daemon=True, name="telegram"),
        ]
        for t in threads: t.start()
        logger.info("UEM 1H started with %d symbols", len(SYMBOLS))
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            self.stop_event.set()
            for t in threads: t.join(timeout=3)

if __name__ == "__main__":
    TradingBotApp().run()
