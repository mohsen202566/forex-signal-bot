from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable

import config
import messages_fa
from storage import JsonStorage, StoredSignal
from strategy import Signal
from toobit_client import ClosePositionResult, ToobitClient, get_client
from utils import estimate_pnl_usdt, pct_change


@dataclass(frozen=True)
class TradeOpenResult:
    opened: bool
    signal_id: str | None
    message: str


class TradeManager:
    def __init__(self, storage: JsonStorage, toobit: ToobitClient | None = None) -> None:
        self.storage = storage
        self.toobit = toobit or get_client()

    def open_from_signal(self, signal: Signal) -> TradeOpenResult:
        settings = self.storage.state.settings
        if not settings.trade_enabled:
            return TradeOpenResult(False, None, "ترید خاموش است؛ فقط سیگنال نمایشی ساخته شد.")
        if len(self.storage.open_signals()) >= settings.max_positions:
            return TradeOpenResult(False, None, "حداکثر تعداد پوزیشن باز پر شده است.")

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
        if not result.opened:
            return TradeOpenResult(False, None, f"سفارش باز نشد: {result.reason}")

        signal_id = f"{signal.base_symbol}-{uuid.uuid4().hex[:10]}"
        self.storage.add_signal(
            StoredSignal(
                signal_id=signal_id,
                base_symbol=signal.base_symbol,
                toobit_symbol=signal.toobit_symbol,
                direction=signal.direction,
                entry_price=result.entry_price or signal.entry_price,
                tp_price=result.tp_price or signal.tp_price,
                sl_price=result.sl_price or signal.sl_price,
                margin_usdt=settings.margin_usdt,
                leverage=settings.leverage,
                opened_at_ms=int(time.time() * 1000),
            )
        )
        return TradeOpenResult(True, signal_id, result.reason)

    def monitor_open_positions(self, send_reply: Callable[[StoredSignal, str], None] | None = None) -> None:
        for sig in list(self.storage.open_signals()):
            try:
                price = self.toobit.get_mark_price(sig.toobit_symbol)
            except Exception:
                continue
            pnl_pct = pct_change(sig.entry_price, price, sig.direction)
            pnl_usdt = estimate_pnl_usdt(sig.margin_usdt, sig.leverage, pnl_pct)

            if self._hit_tp(sig, price):
                self.storage.close_signal(sig.signal_id, "tp", pnl_usdt)
                if send_reply:
                    send_reply(sig, messages_fa.result_tp(sig, price, pnl_pct, pnl_usdt))
                continue

            if self._hit_sl(sig, price):
                stop_reason = "قیمت به حد ضرر تعریف‌شده رسید و سناریوی معامله نامعتبر شد."
                self.storage.close_signal(sig.signal_id, "sl", pnl_usdt)
                if send_reply:
                    send_reply(sig, messages_fa.result_sl(sig, price, pnl_pct, pnl_usdt, stop_reason))
                continue

            if config.SMART_EXIT_ENABLED:
                smart_reason = self._smart_exit_reason(sig, price, pnl_pct)
                if smart_reason:
                    close_result = self.close_position_with_toobit_confirm(sig)
                    if close_result.closed:
                        self.storage.close_signal(sig.signal_id, "smart_exit", pnl_usdt)
                        if send_reply:
                            send_reply(sig, messages_fa.result_smart_exit(sig, price, pnl_pct, pnl_usdt, smart_reason))

    def close_position_with_toobit_confirm(self, sig: StoredSignal) -> ClosePositionResult:
        result = self.toobit.close_position_market(symbol=sig.toobit_symbol, direction=sig.direction)  # uploaded client stays unchanged
        if not config.TOOBIT_CLOSE_CONFIRM_REQUIRED:
            return result
        if config.TOOBIT_CLOSE_CONFIRM_DELAY_SECONDS > 0:
            time.sleep(float(config.TOOBIT_CLOSE_CONFIRM_DELAY_SECONDS))
        self._send_close_confirm(sig, result)
        # final verification uses the original client public method
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
                # Non-invasive: use the uploaded ToobitClient low-level request without editing toobit_client.py.
                self.toobit._request("POST", path, params=params, signed=True)  # noqa: SLF001
                return
            except Exception as exc:  # endpoint is account/API-version specific
                last_error = exc
                time.sleep(1.5)
        if last_error:
            print(f"خطا در Confirm Close توبیت برای {sig.toobit_symbol}: {last_error}")

    @staticmethod
    def _hit_tp(sig: StoredSignal, price: float) -> bool:
        return price >= sig.tp_price if sig.direction == "LONG" else price <= sig.tp_price

    @staticmethod
    def _hit_sl(sig: StoredSignal, price: float) -> bool:
        return price <= sig.sl_price if sig.direction == "LONG" else price >= sig.sl_price

    @staticmethod
    def _smart_exit_reason(sig: StoredSignal, price: float, pnl_pct: float) -> str | None:
        # This part is intentionally simple and anti-noise. It exits only after meaningful move/weakness.
        if pnl_pct >= config.SMART_EXIT_MIN_PROFIT_PCT:
            return "معامله وارد سود شد و خروج هوشمند برای حفظ سود فعال شد؛ برگشت باید با تاییدهای 5M/15M در نسخه تحلیل زنده بررسی شود."
        if -config.SMART_EXIT_DEFENSE_MAX_LOSS_PCT <= pnl_pct <= 0:
            return "معامله بعد از ورود حرکت تاییدی نداد؛ برای جلوگیری از خوردن SL کامل، خروج نزدیک سر به سر فعال شد."
        return None
