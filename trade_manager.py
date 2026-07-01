from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable

import requests

import config
import messages_fa
from storage import JsonStorage, StoredSignal
from strategy import Signal
from toobit_client import ClosePositionResult, ToobitClient, get_client
from utils import estimate_pnl_usdt, pct_change

logger = logging.getLogger("forex-bot")


@dataclass(frozen=True)
class TradeOpenResult:
    opened: bool
    signal_id: str | None
    message: str
    execution_mode: str = "paper"


class TradeManager:
    def __init__(self, storage: JsonStorage, toobit: ToobitClient | None = None) -> None:
        self.storage = storage
        self.toobit = toobit or get_client()
        self._smart_exit_confirmations: dict[str, int] = {}

    def open_from_signal(self, signal: Signal) -> TradeOpenResult:
        """Register every signal for performance tracking.

        If trading is off, slots are full, or Toobit opening fails, the signal is still stored as a paper/virtual
        signal so TP/SL/smart-exit results can be replied to the original Telegram signal.
        """
        settings = self.storage.state.settings

        if not settings.trade_enabled:
            sig = self._create_stored_signal(signal, execution_mode="paper_trade_off", execution_reason="ترید خاموش بود؛ سیگنال برای تست عملکرد به صورت نمایشی مانیتور می‌شود.")
            self.storage.add_signal(sig)
            return TradeOpenResult(False, sig.signal_id, sig.execution_reason, sig.execution_mode)

        used_slots, total_slots, free_slots = self.storage.slot_status()
        if free_slots <= 0:
            reason = f"اسلات واقعی پر است ({used_slots}/{total_slots})؛ سیگنال بدون اجرای Toobit و برای سنجش عملکرد مانیتور می‌شود."
            sig = self._create_stored_signal(signal, execution_mode="paper_slots_full", execution_reason=reason)
            self.storage.add_signal(sig)
            return TradeOpenResult(False, sig.signal_id, reason, sig.execution_mode)

        try:
            result = self.toobit.open_position_with_tp_sl(
                symbol=signal.toobit_symbol,
                direction=signal.direction,
                margin_usdt=settings.margin_usdt,
                leverage=settings.leverage,
                tp_price=signal.tp_price,
                sl_price=signal.sl_price,
                price=signal.entry_price,
                place_tp=config.TOOBIT_PLACE_REAL_TP,
            )
        except Exception as exc:
            reason = f"خطا در اجرای Toobit؛ سیگنال برای سنجش عملکرد به صورت نمایشی مانیتور می‌شود: {exc}"
            sig = self._create_stored_signal(signal, execution_mode="paper_order_failed", execution_reason=reason)
            self.storage.add_signal(sig)
            return TradeOpenResult(False, sig.signal_id, reason, sig.execution_mode)

        if not result.opened:
            reason = f"سفارش در Toobit باز نشد؛ سیگنال برای سنجش عملکرد به صورت نمایشی مانیتور می‌شود: {result.reason}"
            sig = self._create_stored_signal(signal, execution_mode="paper_order_failed", execution_reason=reason)
            self.storage.add_signal(sig)
            return TradeOpenResult(False, sig.signal_id, reason, sig.execution_mode)

        sig = self._create_stored_signal(
            signal,
            execution_mode="real",
            execution_reason="پوزیشن واقعی در Toobit باز شد.",
            entry_price=result.entry_price or signal.entry_price,
            tp_price=result.tp_price or signal.tp_price,
            sl_price=result.sl_price or signal.sl_price,
            order_id=result.order_id,
        )
        self.storage.add_signal(sig)
        return TradeOpenResult(True, sig.signal_id, result.reason, sig.execution_mode)

    def monitor_open_positions(self, send_reply: Callable[[StoredSignal, str], None] | None = None) -> None:
        """Check every open signal and send TP/SL/smart-exit results.

        قانون منبع قیمت:
        - پوزیشن واقعی Toobit با قیمت Toobit مانیتور می‌شود.
        - سیگنال عادی/نمایشی با قیمت OKX SWAP مانیتور می‌شود.
        """
        signals = list(self.storage.open_signals())
        if not signals:
            return

        paper_signals = [sig for sig in signals if sig.execution_mode != "real"]
        okx_prices = self._fetch_okx_swap_prices() if paper_signals else {}
        logger.info(
            "مانیتور نتیجه: %s سیگنال باز | واقعی: %s | نمایشی: %s | قیمت‌های OKX: %s",
            len(signals),
            len(signals) - len(paper_signals),
            len(paper_signals),
            len(okx_prices),
        )

        for sig in signals:
            price_source = "Toobit" if sig.execution_mode == "real" else "OKX"
            price: float | None = None

            if sig.execution_mode == "real":
                try:
                    price = float(self.toobit.get_mark_price(sig.toobit_symbol))
                except Exception as exc:
                    logger.warning(
                        "مانیتور نتیجه: قیمت واقعی %s از Toobit دریافت نشد: %s",
                        sig.base_symbol,
                        exc,
                    )
                    continue
            else:
                price = okx_prices.get(str(sig.base_symbol).upper())
                if price is None:
                    logger.warning(
                        "مانیتور نتیجه: قیمت نمایشی %s از OKX دریافت نشد.",
                        sig.base_symbol,
                    )
                    continue

            if price is None or price <= 0:
                logger.warning("مانیتور نتیجه: قیمت نامعتبر برای %s از %s: %s", sig.base_symbol, price_source, price)
                continue

            logger.info(
                "مانیتور نتیجه %s %s [%s]: price=%s entry=%s tp=%s sl=%s mode=%s",
                sig.base_symbol,
                sig.direction,
                price_source,
                price,
                sig.entry_price,
                sig.tp_price,
                sig.sl_price,
                sig.execution_mode,
            )

            if self._hit_tp(sig, price):
                exit_price = float(sig.tp_price)
                pnl_pct = pct_change(sig.entry_price, exit_price, sig.direction)
                pnl_usdt = estimate_pnl_usdt(sig.margin_usdt, sig.leverage, pnl_pct)
                self.storage.close_signal(sig.signal_id, "tp", pnl_usdt)
                self._smart_exit_confirmations.pop(sig.signal_id, None)
                logger.info("نتیجه سیگنال %s: TP [%s]", sig.signal_id, price_source)
                if send_reply:
                    send_reply(sig, messages_fa.result_tp(sig, exit_price, pnl_pct, pnl_usdt))
                continue

            if self._hit_sl(sig, price):
                exit_price = float(sig.sl_price)
                pnl_pct = pct_change(sig.entry_price, exit_price, sig.direction)
                pnl_usdt = estimate_pnl_usdt(sig.margin_usdt, sig.leverage, pnl_pct)
                stop_reason = self._stop_reason(sig)
                self.storage.close_signal(sig.signal_id, "sl", pnl_usdt)
                self._smart_exit_confirmations.pop(sig.signal_id, None)
                logger.info("نتیجه سیگنال %s: SL [%s]", sig.signal_id, price_source)
                if send_reply:
                    send_reply(sig, messages_fa.result_sl(sig, exit_price, pnl_pct, pnl_usdt, stop_reason))
                continue

            pnl_pct = pct_change(sig.entry_price, price, sig.direction)
            pnl_usdt = estimate_pnl_usdt(sig.margin_usdt, sig.leverage, pnl_pct)

            if config.SMART_EXIT_ENABLED:
                smart_reason = self._smart_exit_reason(sig, price, pnl_pct)
                if not smart_reason:
                    self._smart_exit_confirmations.pop(sig.signal_id, None)
                    continue

                confirmations = self._smart_exit_confirmations.get(sig.signal_id, 0) + 1
                self._smart_exit_confirmations[sig.signal_id] = confirmations
                required = max(1, int(config.SMART_EXIT_CONFIRMATIONS_REQUIRED))
                logger.info(
                    "خروج هوشمند %s تایید %s/%s | pnl=%s | source=%s",
                    sig.signal_id,
                    confirmations,
                    required,
                    pnl_pct,
                    price_source,
                )
                if confirmations < required:
                    continue

                if sig.execution_mode == "real":
                    close_result = self.close_position_with_toobit_confirm(sig)
                    if not close_result.closed:
                        logger.warning("خروج هوشمند واقعی %s انجام نشد: %s", sig.signal_id, close_result.reason)
                        continue

                self.storage.close_signal(sig.signal_id, "smart_exit", pnl_usdt)
                self._smart_exit_confirmations.pop(sig.signal_id, None)
                logger.info("نتیجه سیگنال %s: SMART_EXIT [%s]", sig.signal_id, price_source)
                if send_reply:
                    send_reply(sig, messages_fa.result_smart_exit(sig, price, pnl_pct, pnl_usdt, smart_reason))

    def _fetch_okx_swap_prices(self) -> dict[str, float]:
        """Return latest OKX USDT-SWAP prices as {BASE: last_price}."""
        url = f"{config.OKX_BASE_URL}/api/v5/market/tickers"
        try:
            response = requests.get(
                url,
                params={"instType": "SWAP"},
                timeout=config.OKX_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("مانیتور نتیجه: دریافت قیمت‌های OKX ناموفق بود: %s", exc)
            return {}

        if str(payload.get("code", "0")) != "0":
            logger.warning("مانیتور نتیجه: پاسخ OKX نامعتبر بود: %s", payload)
            return {}

        prices: dict[str, float] = {}
        for item in payload.get("data", []):
            inst_id = str(item.get("instId") or "").upper()
            if not inst_id.endswith("-USDT-SWAP"):
                continue
            try:
                last = float(item.get("last") or item.get("markPx") or 0)
            except (TypeError, ValueError):
                continue
            if last <= 0:
                continue
            base = inst_id.removesuffix("-USDT-SWAP")
            prices[base] = last
        return prices

    def close_position_with_toobit_confirm(self, sig: StoredSignal) -> ClosePositionResult:
        result = self.toobit.close_position_market(symbol=sig.toobit_symbol, direction=sig.direction)  # uploaded client stays unchanged
        if not config.TOOBIT_CLOSE_CONFIRM_REQUIRED:
            return result
        if config.TOOBIT_CLOSE_CONFIRM_DELAY_SECONDS > 0:
            time.sleep(float(config.TOOBIT_CLOSE_CONFIRM_DELAY_SECONDS))
        self._send_close_confirm(sig, result)
        still_open = [p for p in self.toobit.get_open_positions(sig.toobit_symbol) if p.side == sig.direction and p.quantity > 0]
        return ClosePositionResult(
            symbol=sig.toobit_symbol,
            direction=sig.direction,  # type: ignore[arg-type]
            closed=not bool(still_open),
            order_id=result.order_id,
            reason=(result.reason + " | درخواست Confirm Close نیز ارسال/بررسی شد."),
            raw=result.raw,
        )

    def _send_close_confirm(self, sig: StoredSignal, close_result: ClosePositionResult) -> None:
        path = config.TOOBIT_PATH_CLOSE_CONFIRM
        if not path:
            return
        params = {
            "symbol": sig.toobit_symbol,
            "side": "SELL_CLOSE" if sig.direction == "LONG" else "BUY_CLOSE",
        }
        if close_result.order_id:
            params["orderId"] = close_result.order_id
        last_error: Exception | None = None
        for _ in range(max(1, config.TOOBIT_CLOSE_CONFIRM_RETRY)):
            try:
                self.toobit._request("POST", path, params=params, signed=True)  # noqa: SLF001
                return
            except Exception as exc:
                last_error = exc
                time.sleep(1.5)
        if last_error:
            print(f"خطا در Confirm Close توبیت برای {sig.toobit_symbol}: {last_error}")

    def _create_stored_signal(
        self,
        signal: Signal,
        *,
        execution_mode: str,
        execution_reason: str,
        entry_price: float | None = None,
        tp_price: float | None = None,
        sl_price: float | None = None,
        order_id: str | None = None,
    ) -> StoredSignal:
        settings = self.storage.state.settings
        signal_id = f"{signal.base_symbol}-{uuid.uuid4().hex[:10]}"
        return StoredSignal(
            signal_id=signal_id,
            base_symbol=signal.base_symbol,
            toobit_symbol=signal.toobit_symbol,
            direction=signal.direction,
            entry_price=float(entry_price if entry_price is not None else signal.entry_price),
            tp_price=float(tp_price if tp_price is not None else signal.tp_price),
            sl_price=float(sl_price if sl_price is not None else signal.sl_price),
            margin_usdt=float(settings.margin_usdt),
            leverage=int(settings.leverage),
            opened_at_ms=int(time.time() * 1000),
            execution_mode=execution_mode,
            execution_reason=execution_reason,
            order_id=order_id,
        )

    @staticmethod
    def _hit_tp(sig: StoredSignal, price: float) -> bool:
        return price >= sig.tp_price if sig.direction == "LONG" else price <= sig.tp_price

    @staticmethod
    def _hit_sl(sig: StoredSignal, price: float) -> bool:
        return price <= sig.sl_price if sig.direction == "LONG" else price >= sig.sl_price

    @staticmethod
    def _stop_reason(sig: StoredSignal) -> str:
        if sig.execution_mode == "real":
            return "قیمت به حد ضرر تعریف‌شده رسید و سناریوی معامله نامعتبر شد."
        return "قیمت به حد ضرر سیگنال نمایشی رسید؛ نتیجه برای سنجش عملکرد ربات ثبت شد، بدون اجرای واقعی در Toobit."

    @staticmethod
    def _smart_exit_reason(sig: StoredSignal, price: float, pnl_pct: float) -> str | None:
        if pnl_pct >= config.SMART_EXIT_MIN_PROFIT_PCT:
            base = "معامله وارد سود شد و خروج هوشمند برای حفظ سود فعال شد."
            if sig.execution_mode != "real":
                return base + " این سیگنال نمایشی بود و نتیجه فقط برای آمار ثبت شد."
            return base
        if -config.SMART_EXIT_DEFENSE_MAX_LOSS_PCT <= pnl_pct <= 0:
            base = "معامله بعد از ورود حرکت تاییدی نداد؛ برای جلوگیری از خوردن SL کامل، خروج نزدیک سر به سر فعال شد."
            if sig.execution_mode != "real":
                return base + " این سیگنال نمایشی بود و نتیجه فقط برای آمار ثبت شد."
            return base
        return None
