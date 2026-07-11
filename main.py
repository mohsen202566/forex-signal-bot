"""نقطه شروع ربات 15M با معماری واچ‌لیست زنده.

پنل‌ها، توبیت، مانیتور و دستورات مستقل از مسیر تحلیل‌اند.
تلگرام فقط سیگنال نهایی را می‌بیند؛ رویدادهای واچ فقط در لاگ فارسی VPS ثبت می‌شوند.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from collections import Counter

import config
from health import HealthManager
from monitor import Monitor
from okx_client import OKXClient
from risk_engine import build_risk_plan
from storage import Storage
from strategy import StrategySignal, WatchState, detect_watch_candidate, evaluate_watch
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
        self._stop = threading.Event()
        self._last_signal_ts: dict[str, int] = {}
        self._scan_count = 0
        self._signal_count = 0
        self._watch: dict[str, WatchState] = {}
        self._watch_lock = threading.RLock()
        self._slot_lock = threading.RLock()
        self._reserved_slots: set[int] = set()
        self._last_watch_progress: dict[str, float] = {}
        self._watch_stats: Counter[str] = Counter()
        self._last_watch_summary = 0.0
        self._symbols_by_id = {s.id: s for s in SYMBOLS}

    def _has_open_signal(self, symbol_id: str) -> bool:
        return any(str(x.get("symbol_id")) == symbol_id for x in self.storage.get_open_signals())

    def signal_eligibility(self, sym: SymbolMap) -> tuple[bool, str]:
        if self.storage.is_blacklisted(sym.id):
            return False, "ارز موقتاً در لیست خطا قرار دارد"
        if self._has_open_signal(sym.id):
            return False, "برای این ارز سیگنال باز وجود دارد"
        last = self._last_signal_ts.get(sym.id, 0)
        if time.time() - last < config.SIGNAL_COOLDOWN_SECONDS_PER_SYMBOL:
            return False, "زمان استراحت بعد از سیگنال هنوز تمام نشده"
        return True, "مجاز"

    def reserve_real_slot(self) -> int | None:
        # جلوگیری از رزرو هم‌زمان یک اسلات توسط دو سیگنال.
        with self._slot_lock:
            max_pos = int(self.storage.get("max_positions", config.MAX_POSITIONS_DEFAULT))
            used = {int(x.get("slot_id")) for x in self.storage.get_open_signals() if int(x.get("is_real") or 0) and x.get("slot_id")}
            used.update(self._reserved_slots)
            for slot in range(1, max_pos + 1):
                if slot not in used:
                    self._reserved_slots.add(slot)
                    return slot
            return None

    def send_signal_message(self, signal_data: dict, risk) -> int | None:
        side_icon = "🟢" if signal_data["side"] == "LONG" else "🔴"
        txt = (
            f"📊 سیگنال 15M\n\n"
            f"#{signal_data.get('id','?')} | {signal_data['symbol_id']}\n"
            f"{side_icon} {signal_data['side']}\n"
            f"قدرت تخمینی: {signal_data['strength']}\n"
            f"Entry: {signal_data['entry']:.8g}\n"
            f"TP: {risk.tp:.8g}\n"
            f"SL: {risk.sl:.8g}\n"
            f"RR: {risk.rr}\n"
            f"سود خالص تخمینی: {risk.estimated_net_profit:.4f} USDT\n"
            f"مدل: سناریوی یکپارچه جهت + قدرت + تازگی + ورود + ایمنی"
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
            logger.info("[ترید واقعی] سفارش ارسال شد | ارز=%s | جهت=%s | شناسه=%s", sym.id, data["side"], res.get("order_id") or client_id)
            return True, str(res.get("order_id") or client_id)
        except Exception as exc:
            logger.warning("[ترید واقعی] ارسال سفارش ناموفق بود | ارز=%s | خطا=%s", sym.id, exc)
            self.storage.add_health_event("toobit_order", "warning", f"open real failed: {exc}", sym.id)
            return False, None

    def _publish_signal(self, sym: SymbolMap, sig: StrategySignal) -> tuple[bool, str]:
        """تنها در این نقطه سیگنال ساخته و به تلگرام فرستاده می‌شود."""
        eligible, reason = self.signal_eligibility(sym)
        if not eligible:
            return False, reason
        risk = build_risk_plan(sig, self.storage)
        if risk is None:
            return False, "برنامه ریسک معتبر ساخته نشد"
        if not risk.min_net_profit_ok:
            return False, risk.reason

        trading_on = bool(self.storage.get("trading_enabled", False))
        auto_on = bool(self.storage.get("auto_signal_enabled", True))
        if not auto_on:
            return False, "اتو سیگنال غیرفعال است"
        slot = self.reserve_real_slot() if trading_on else None
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
            "net_rr": risk.net_rr,
            "trade_usdt": risk.trade_usdt,
            "leverage": risk.leverage,
            "notional_usdt": risk.notional_usdt,
            "estimated_net_profit": risk.estimated_net_profit,
            "estimated_net_loss": risk.estimated_net_loss,
            "estimated_cost": risk.fee_estimate,
            "trade_mode": "real" if is_real else "virtual",
            "status": "pending" if is_real else "open",
            "is_real": is_real,
            "slot_id": slot,
            "raw": {
                "reason": sig.reason,
                "risk_reason": risk.reason,
                "strength_score": sig.strength_score,
                "flow_bias": sig.flow_bias,
                "direction_confidence": sig.absorption_score,
                "diagnostic_context": dict(sig.diagnostic_context or {}),
            },
        }
        try:
            signal_id = self.storage.create_signal(data)
        except Exception:
            self._release_reserved_slot(slot)
            raise
        self._release_reserved_slot(slot)
        data["id"] = signal_id
        msg_id = self.send_signal_message(data, risk)
        if msg_id:
            self.storage.update_signal(signal_id, message_id=msg_id)
        if is_real:
            opened_sent, order_id = self.try_open_real(sym, data, risk)
            self.storage.update_signal(signal_id, order_id=order_id)
            if not opened_sent:
                self.storage.update_signal(signal_id, status="open", is_real=0, trade_mode="virtual", slot_id=None, close_reason="REAL_OPEN_FAILED_TO_VIRTUAL")
            else:
                threading.Thread(target=self._check_real_after_70s, args=(signal_id, sym), daemon=True, name=f"بررسی-پوزیشن-{sym.id}").start()
        self._last_signal_ts[sym.id] = int(time.time())
        self._signal_count += 1
        logger.info(
            "[سیگنال] صادر شد | شماره=%s | ارز=%s | جهت=%s | قدرت=%s | نوع=%s | ورود=%.8g | تی‌پی=%.8g | استاپ=%.8g",
            signal_id, sym.id, data["side"], data["strength"], data["trade_mode"], data["entry"], data["tp"], data["sl"],
        )
        return True, "سیگنال صادر شد"

    def _check_real_after_70s(self, signal_id: int, sym: SymbolMap) -> None:
        time.sleep(config.ORDER_OPEN_CHECK_SECONDS)
        current = self.storage.get_signal(signal_id)
        # مانیتور ممکن است معامله سریع را پیش از ۷۰ ثانیه بسته باشد؛ هرگز نتیجه بسته را زنده نکن.
        if not current or str(current.get("status")) == "closed" or not int(current.get("is_real") or 0):
            return
        try:
            opened = self.toobit.check_position_opened(sym.toobit)
            self.health.mark("toobit")
            if opened:
                logger.info("[ترید واقعی] پوزیشن بعد از ۷۰ ثانیه تأیید شد | شماره=%s | ارز=%s", signal_id, sym.id)
                self.storage.update_signal(signal_id, status="open", opened_at=int(current.get("opened_at") or time.time()))
                return
            # ممکن است پوزیشن خیلی سریع باز و با TP/SL بسته شده باشد؛ قبل از تبدیل به مجازی تاریخچه را بررسی کن.
            opened_ms = int(current.get("opened_at") or current.get("created_at") or 0) * 1000
            closed = self.toobit.get_closed_trade_result(sym.toobit, str(current.get("side") or ""), opened_ms)
            if closed:
                logger.info("[ترید واقعی] پوزیشن پیش از بررسی ۷۰ ثانیه‌ای بسته شده؛ مانیتور نتیجه را ثبت می‌کند | شماره=%s", signal_id)
                return
            logger.warning("[ترید واقعی] هیچ پوزیشن یا سابقه بسته‌شدن قطعی یافت نشد؛ به مجازی تبدیل شد | شماره=%s | ارز=%s", signal_id, sym.id)
            self.storage.update_signal(signal_id, status="open", is_real=0, trade_mode="virtual", slot_id=None, close_reason="NOT_OPENED_AFTER_70S")
            self.storage.add_health_event("toobit_position", "warning", "بعد ۷۰ ثانیه نه پوزیشن و نه سابقه بسته‌شدن قطعی یافت شد", sym.id)
        except Exception as exc:
            # خطای بررسی نباید معامله واقعی احتمالی را به مجازی تبدیل کند؛ مانیتور دور بعد دوباره بررسی می‌کند.
            logger.warning("[ترید واقعی] بررسی ۷۰ ثانیه‌ای ناموفق بود؛ وضعیت واقعی حفظ شد | شماره=%s | ارز=%s | خطا=%s", signal_id, sym.id, exc)
            self.storage.add_health_event("toobit_position", "warning", f"70s check failed: {exc}", sym.id)

    @staticmethod
    def _is_transient_data_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(token in text for token in (
            "429", "too many requests", "timeout", "timed out", "connection",
            "temporarily", "remote disconnected", "502", "503", "504",
        ))

    def _release_reserved_slot(self, slot: int | None) -> None:
        if slot is None:
            return
        with self._slot_lock:
            self._reserved_slots.discard(int(slot))

    @staticmethod
    def _compact_details(details: dict | None, limit: int = 8) -> str:
        if not isinstance(details, dict) or not details:
            return "ندارد"
        parts: list[str] = []
        for key, value in list(details.items())[:max(1, int(limit))]:
            if isinstance(value, float):
                text = f"{value:.4f}"
            elif isinstance(value, dict):
                continue
            else:
                text = str(value)
            parts.append(f"{key}={text}")
        return " | ".join(parts) if parts else "ندارد"

    def _log_scan_reject(self, symbol_id: str, reason: str, details: dict | None, detail_no: int) -> int:
        if not bool(getattr(config, "DEBUG_REJECTS", False)):
            return detail_no
        limit = max(0, int(getattr(config, "REJECT_DETAIL_LIMIT_PER_CYCLE", 0)))
        if detail_no >= limit:
            return detail_no
        logger.info(
            "[رد اسکن] ارز=%s | دلیل=%s | جزئیات=%s",
            symbol_id, reason, self._compact_details(details),
        )
        return detail_no + 1

    def light_scan_loop(self) -> None:
        """اسکن ۱۵ دقیقه‌ای همه ارزها و ثبت علت دقیق رد هر ارز."""
        while not self._stop.is_set():
            cycle_start = time.time()
            self._scan_count += 1
            reasons: Counter[str] = Counter()
            detail_no = 0
            error_count = 0
            for sym in SYMBOLS:
                if self._stop.is_set():
                    break
                with self._watch_lock:
                    already_watched = sym.id in self._watch
                if already_watched:
                    reason = "از قبل در واچ"
                    reasons[reason] += 1
                    detail_no = self._log_scan_reject(sym.id, reason, None, detail_no)
                    continue
                eligible, eligibility_reason = self.signal_eligibility(sym)
                if not eligible:
                    reasons[eligibility_reason] += 1
                    detail_no = self._log_scan_reject(sym.id, eligibility_reason, None, detail_no)
                    continue
                try:
                    candles = self.okx.get_candles(sym.okx)
                    self.health.mark("okx")
                    self.storage.clear_health_events("analysis", sym.id)
                    candidate, reason, details = detect_watch_candidate(candles)
                    self.health.mark("signal")
                    self.storage.set("signal_engine_last_ts", int(time.time()))
                    if not candidate:
                        reasons[reason] += 1
                        detail_no = self._log_scan_reject(sym.id, reason, details, detail_no)
                        continue
                    state = WatchState(
                        symbol_id=sym.id,
                        okx_symbol=sym.okx,
                        toobit_symbol=sym.toobit,
                        side=candidate.side,
                        trigger=candidate.trigger,
                        start_price=candidate.start_price,
                        created_at=time.time(),
                        expected_move_pct=candidate.expected_move_pct,
                        late_limit_pct=candidate.late_limit_pct,
                        early_flow=candidate.early_flow,
                        compression_score=candidate.compression_score,
                        details=dict(candidate.details or {}),
                        last_price=candidate.start_price,
                        last_update=time.time(),
                    )
                    added = False
                    with self._watch_lock:
                        if sym.id not in self._watch and not self._has_open_signal(sym.id):
                            self._watch[sym.id] = state
                            self._watch_stats["وارد_واچ"] += 1
                            added = True
                            logger.info(
                                "[واچ] ارز وارد واچ‌لیست شد | ارز=%s | جهت اولیه=%s | دلیل=%s | فشار اولیه=%.4f | حد دیرشدن=%.4f%%",
                                sym.id, self._fa_side(state.side), state.trigger, state.early_flow, state.late_limit_pct,
                            )
                    if added:
                        reasons["وارد واچ"] += 1
                    else:
                        reason = "هم‌زمان با اسکن، ارز وارد واچ یا دارای سیگنال باز شد"
                        reasons[reason] += 1
                        detail_no = self._log_scan_reject(sym.id, reason, details, detail_no)
                except Exception as exc:
                    reason = "خطای داده"
                    reasons[reason] += 1
                    error_count += 1
                    transient = self._is_transient_data_error(exc)
                    logger.warning("[اسکن] ارز به علت خطا رد شد | ارز=%s | موقت=%s | خطا=%s", sym.id, transient, exc)
                    self.storage.add_health_event("analysis", "warning", f"light scan skipped: {exc}", sym.id)
                    if not transient:
                        self.storage.blacklist_symbol(sym.id, str(exc)[:180], config.SYMBOL_ERROR_BLACKLIST_SECONDS)

            elapsed = time.time() - cycle_start
            now_ts = int(time.time())
            with self._watch_lock:
                active = len(self._watch)
            reason_summary = dict(reasons)
            self.storage.set("scan_last_ts", now_ts)
            self.storage.set("scan_last_cycle", self._scan_count)
            self.storage.set("scan_last_duration", round(elapsed, 3))
            self.storage.set("scan_last_symbols", len(SYMBOLS))
            self.storage.set("scan_last_watch_active", active)
            self.storage.set("scan_last_watch_added", reasons.get("وارد واچ", 0))
            self.storage.set("scan_last_error_count", error_count)
            self.storage.set("scan_last_reason_summary", reason_summary)
            self.storage.set("scan_running", True)

            every = max(1, int(getattr(config, "REJECT_SUMMARY_EVERY_CYCLES", 1)))
            if self._scan_count % every == 0:
                summary_text = " | ".join(f"{k}={v}" for k, v in reasons.most_common()) or "بدون رد"
                logger.info(
                    "[خلاصه اسکن] دور=%s | ارزها=%s | واچ فعال=%s | وارد واچ=%s | خطا=%s | زمان=%.2f ثانیه | دلایل=%s",
                    self._scan_count, len(SYMBOLS), active, reasons.get("وارد واچ", 0), error_count, elapsed, summary_text,
                )
            wait = max(0.25, float(config.LIGHT_SCAN_INTERVAL_SECONDS) - elapsed)
            self._stop.wait(wait)

    @staticmethod
    def _fa_side(side: str) -> str:
        return {"LONG": "لانگ", "SHORT": "شورت", "UNCERTAIN": "نامشخص"}.get(side, side)

    def watch_loop(self) -> None:
        """فقط ارزهای واچ را سریع و دقیق بررسی می‌کند."""
        while not self._stop.is_set():
            loop_start = time.time()
            with self._watch_lock:
                states = list(self._watch.values())
            for state in states:
                if self._stop.is_set():
                    break
                sym = self._symbols_by_id.get(state.symbol_id)
                if not sym:
                    with self._watch_lock:
                        self._watch.pop(state.symbol_id, None)
                    continue
                if self._has_open_signal(state.symbol_id):
                    with self._watch_lock:
                        self._watch.pop(state.symbol_id, None)
                    logger.info("[حذف واچ] ارز=%s | دلیل=برای این ارز سیگنال باز وجود دارد", state.symbol_id)
                    continue
                try:
                    snapshot = self.okx.get_micro_snapshot(state.okx_symbol)
                    state.data_error_count = 0
                    self.health.mark("okx")
                    self.storage.clear_health_events("analysis", state.symbol_id)
                    evaluation = evaluate_watch(state, snapshot)
                    state.last_price = float(snapshot.get("mid_price") or snapshot.get("last_price") or state.last_price)
                    state.last_update = time.time()

                    if evaluation.action == "SIDE_CHANGED":
                        old = state.side
                        state.side = evaluation.side
                        state.side_changes += 1
                        state.confirm_count = 0
                        state.bad_count = 0
                        state.direction_locked = False
                        logger.info(
                            "[واچ] جهت واچ تغییر کرد | ارز=%s | از=%s | به=%s | دلیل=%s",
                            state.symbol_id, self._fa_side(old), self._fa_side(state.side), evaluation.reason_fa,
                        )
                        continue

                    if evaluation.action == "REMOVE":
                        with self._watch_lock:
                            self._watch.pop(state.symbol_id, None)
                        self._watch_stats["حذف"] += 1
                        logger.info(
                            "[حذف واچ] ارز=%s | جهت=%s | دلیل=%s | جزئیات=%s",
                            state.symbol_id, self._fa_side(state.side), evaluation.reason_fa, self._metrics_text(evaluation.metrics),
                        )
                        continue

                    if evaluation.action == "SIGNAL" and evaluation.signal:
                        ok, publish_reason = self._publish_signal(sym, evaluation.signal)
                        with self._watch_lock:
                            self._watch.pop(state.symbol_id, None)
                        if ok:
                            self._watch_stats["سیگنال"] += 1
                        else:
                            self._watch_stats["رد_نهایی"] += 1
                            logger.info(
                                "[رد نهایی واچ] ارز=%s | جهت=%s | دلیل=%s | جزئیات=%s",
                                state.symbol_id, self._fa_side(evaluation.side), publish_reason, self._metrics_text(evaluation.metrics),
                            )
                        continue

                    # لاگ پیشرفت محدود و فارسی؛ نه در هر تیک تا سرعت و خوانایی حفظ شود.
                    last_log = self._last_watch_progress.get(state.symbol_id, 0.0)
                    if time.time() - last_log >= float(config.WATCH_LOG_PROGRESS_SECONDS):
                        self._last_watch_progress[state.symbol_id] = time.time()
                        logger.info(
                            "[وضعیت واچ] ارز=%s | جهت فعلی=%s | وضعیت=%s | جزئیات=%s",
                            state.symbol_id, self._fa_side(evaluation.side if evaluation.side != "UNCERTAIN" else state.side), evaluation.reason_fa, self._metrics_text(evaluation.metrics),
                        )
                except Exception as exc:
                    transient = self._is_transient_data_error(exc)
                    state.data_error_count += 1
                    logger.warning("[واچ] خطای داده؛ واچ فعلاً حفظ شد | ارز=%s | شمار خطا=%s | موقت=%s | خطا=%s", state.symbol_id, state.data_error_count, transient, exc)
                    # خطای شبکه نباید به‌عنوان تناقض بازار شمرده شود یا واچ خوب را حذف کند.
                    if not transient and state.data_error_count >= int(config.WATCH_BAD_OBSERVATIONS_TO_REMOVE):
                        with self._watch_lock:
                            self._watch.pop(state.symbol_id, None)
                        logger.warning("[حذف واچ] ارز=%s | دلیل=خطای داده غیرموقت چند بار تکرار شد", state.symbol_id)
                        self.storage.blacklist_symbol(state.symbol_id, str(exc)[:180], config.SYMBOL_ERROR_BLACKLIST_SECONDS)

            now = time.time()
            if now - self._last_watch_summary >= float(config.WATCH_SUMMARY_SECONDS):
                self._last_watch_summary = now
                with self._watch_lock:
                    active = len(self._watch)
                    names = ",".join(self._watch.keys()) if self._watch else "ندارد"
                self.storage.set("watch_last_ts", int(now))
                self.storage.set("watch_active_count", active)
                self.storage.set("watch_active_symbols", names)
                logger.info(
                    "[خلاصه واچ] فعال=%s | ارزهای فعال=%s | ورودها=%s | حذف‌ها=%s | سیگنال‌ها=%s | رد نهایی=%s",
                    active, names, self._watch_stats.get("وارد_واچ", 0), self._watch_stats.get("حذف", 0), self._watch_stats.get("سیگنال", 0), self._watch_stats.get("رد_نهایی", 0),
                )
            elapsed = time.time() - loop_start
            self._stop.wait(max(0.10, float(config.WATCH_POLL_INTERVAL_SECONDS) - elapsed))

    @staticmethod
    def _metrics_text(metrics: dict[str, float | str]) -> str:
        return " | ".join(f"{k}={v}" for k, v in metrics.items())

    def monitor_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.monitor.tick()
                self.health.mark("monitor")
                self.storage.set("monitor_last_ts", int(time.time()))
                self.storage.set("monitor_running", True)
            except Exception as exc:
                logger.warning("[مانیتور] خطای حلقه مانیتور | خطا=%s", exc)
                self.storage.add_health_event("monitor_loop", "warning", str(exc))
            self._stop.wait(5)

    def telegram_loop(self) -> None:
        while not self._stop.is_set():
            self.telegram.poll_once()
            self.health.mark("telegram")
            self._stop.wait(config.TELEGRAM_POLL_SECONDS)

    def toobit_status_loop(self) -> None:
        while not self._stop.is_set():
            try:
                bal = self.toobit.get_futures_balance()
                now_ts = int(time.time())
                self.storage.set("toobit_connected", True)
                available_usdt = float(bal.get("available", 0.0) or 0.0)
                total_usdt = float(bal.get("total", 0.0) or 0.0)
                raw_margin_usdt = float(bal.get("margin", 0.0) or 0.0)
                usable_margin_usdt = raw_margin_usdt if raw_margin_usdt > 0 else available_usdt
                self.storage.set("toobit_margin_usdt", usable_margin_usdt)
                self.storage.set("toobit_available_usdt", available_usdt)
                self.storage.set("toobit_total_usdt", total_usdt)
                self.storage.set("toobit_last_error", "")
                self.storage.set("toobit_last_update", now_ts)
                self.health.mark("toobit")
                self.storage.clear_health_events("toobit_balance")
                logger.info("[توبیت] اتصال سالم | آزاد=%.4f | کل=%.4f | مارجین قابل استفاده=%.4f", available_usdt, total_usdt, usable_margin_usdt)
            except Exception as exc:
                logger.warning("[توبیت] اتصال یا دریافت موجودی ناموفق | خطا=%s", exc)
                self.storage.set("toobit_connected", False)
                self.storage.set("toobit_last_error", str(exc)[:240])
                self.storage.set("toobit_last_update", int(time.time()))
                self.storage.add_health_event("toobit_balance", "warning", f"balance/status failed: {exc}")
            self._stop.wait(max(5, int(getattr(config, "TOOBIT_STATUS_INTERVAL_SECONDS", 15))))

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.light_scan_loop, daemon=True, name="اسکن-سبک"),
            threading.Thread(target=self.watch_loop, daemon=True, name="واچ-زنده"),
            threading.Thread(target=self.monitor_loop, daemon=True, name="مانیتور-نتیجه"),
            threading.Thread(target=self.telegram_loop, daemon=True, name="تلگرام"),
            threading.Thread(target=self.toobit_status_loop, daemon=True, name="وضعیت-توبیت"),
        ]
        logger.info("[شروع ربات] نسخه=واچ‌لیست-زنده | تعداد ارز=%s | فاصله اسکن=%.2f ثانیه", len(SYMBOLS), config.LIGHT_SCAN_INTERVAL_SECONDS)
        for thread in threads:
            thread.start()
            logger.info("[شروع بخش] نام=%s", thread.name)
        logger.info("[ربات آماده] ترید واقعی=%s | اتوسیگنال=%s", self.storage.get("trading_enabled", False), self.storage.get("auto_signal_enabled", True))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self._stop.set()
            logger.info("[توقف ربات] درخواست توقف از صفحه‌کلید دریافت شد")


if __name__ == "__main__":
    TradingBotApp().run()
