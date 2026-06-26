"""مانیتورینگ دقیق همه سیگنال‌ها.

قفل‌های اجرایی:
- سیگنال عادی با قیمت OKX مانیتور می‌شود.
- سیگنال توبیت با Toobit تایید می‌شود.
- نتیجه همیشه با reply روی پیام اصلی سیگنال اعلام می‌شود.
- سیگنال عادی فقط ۳ دقیقه معتبر است، مگر قبل از آن TP/SL بخورد.
- سیگنال توبیت بعد از ارسال سفارش، ۷۰ ثانیه در وضعیت PENDING_OPEN می‌ماند.
- اگر بعد از ۷۰ ثانیه پوزیشن واقعی پیدا نشد، اسلات آزاد و FAILED_OPEN ثبت می‌شود.
- اگر پوزیشن واقعی پیدا شد، وضعیت OPEN می‌شود و از آن به بعد نتیجه فقط از Toobit خوانده می‌شود.
"""
from __future__ import annotations

from typing import Any, Callable

import config
from state_store import StateStore, now_ts
from telegram_ui import result_message


_ACTIVE_STATUSES = {"ACTIVE", "PENDING_OPEN", "OPEN"}
_FINAL_STATUSES = {"TP", "SL", "EXPIRED", "FAILED_OPEN", "REPLACED"}


class PositionMonitor:
    def __init__(
        self,
        state: StateStore,
        okx_client: Any,
        tobit_client: Any,
        send_reply: Callable[[int | None, str], None],
    ) -> None:
        self.state = state
        self.okx = okx_client
        self.tobit = tobit_client
        self.send_reply = send_reply

    def tick(self) -> None:
        """یک دور مانیتورینگ سریع.

        bot.py این متد را هر ۲ تا ۳ ثانیه صدا می‌زند. این متد نباید تحلیل جدید
        بسازد؛ فقط سیگنال‌های فعال را تا نتیجه نهایی دنبال می‌کند.
        """
        for sig in list(self.state.all_active()):
            status = sig.get("status")
            if status not in _ACTIVE_STATUSES:
                continue

            if sig.get("kind") == "SIGNAL":
                self._monitor_signal(sig)
            elif sig.get("kind") == "TOBIT":
                self._monitor_tobit(sig)

    def _monitor_signal(self, sig: dict[str, Any]) -> None:
        """مانیتور سیگنال عادی با قیمت OKX.

        این سیگنال حتی وقتی ترید خاموش است صادر می‌شود و برای ارزیابی موتور تحلیل
        داخل آمار جداگانه SIGNAL ثبت می‌شود.
        """
        if sig.get("status") != "ACTIVE":
            return

        age = self._age_seconds(sig)
        price = self._safe_okx_price(sig.get("coin"))
        if price is None:
            return

        result = self._price_result(sig, price)
        if result:
            self._close_and_reply(sig, result, {"result_price": price}, price=price)
            return

        valid_seconds = int(sig.get("valid_seconds") or config.SIGNAL_VALID_SECONDS)
        if age >= valid_seconds:
            self._close_and_reply(sig, "EXPIRED", {"result_price": price}, price=price)

    def _monitor_tobit(self, sig: dict[str, Any]) -> None:
        """مانیتور سیگنال واقعی Toobit.

        PENDING_OPEN فقط بعد از ۷۰ ثانیه چک می‌شود. اگر پوزیشن پیدا شد OPEN؛ اگر
        نه FAILED_OPEN و اسلات آزاد می‌شود. نتیجه پوزیشن OPEN فقط از Toobit خوانده
        می‌شود، نه از قیمت OKX.
        """
        status = sig.get("status")
        age = self._age_seconds(sig)

        if status == "PENDING_OPEN":
            if age < config.TOBIT_OPEN_CONFIRM_SECONDS:
                return
            self._confirm_tobit_open(sig)
            return

        if status != "OPEN":
            return

        self._check_tobit_closed(sig)

    def _confirm_tobit_open(self, sig: dict[str, Any]) -> None:
        try:
            pos = self.tobit.position_exists(sig["coin"], sig.get("side"))
        except Exception as exc:
            # خطای موقت API نباید اسلات را آزاد کند؛ در tick بعدی دوباره بررسی می‌شود.
            print(f"toobit position_exists error {sig.get('coin')}: {exc}")
            return

        if pos.get("exists"):
            position_id = pos.get("position_id") or pos.get("id")
            self.state.mark_open(sig["id"], position_id)
            return

        self._close_and_reply(sig, "FAILED_OPEN", {"open_check": pos})

    def _check_tobit_closed(self, sig: dict[str, Any]) -> None:
        try:
            res = self.tobit.closed_result(
                sig["coin"],
                sig.get("side"),
                sig.get("exchange_position_id"),
            )
        except Exception as exc:
            print(f"toobit closed_result error {sig.get('coin')}: {exc}")
            return

        if not res.get("closed"):
            return

        result = self._normalize_tobit_result(res.get("result"))
        extra = {
            "net_pnl": float(res.get("net_pnl", 0.0) or 0.0),
            "result_price": res.get("price"),
            "tobit_result": res,
        }
        self._close_and_reply(
            sig,
            result,
            extra,
            price=res.get("price"),
            net_pnl=extra["net_pnl"],
        )

    def _close_and_reply(
        self,
        sig: dict[str, Any],
        result: str,
        extra: dict[str, Any] | None = None,
        *,
        price: float | None = None,
        net_pnl: float | None = None,
    ) -> None:
        """بستن سیگنال و ارسال نتیجه با reply، با محافظت در برابر تکرار."""
        if sig.get("status") in _FINAL_STATUSES:
            return

        self.state.close_signal(sig["id"], result, extra or {})
        self.send_reply(
            sig.get("telegram_message_id"),
            result_message(sig, result, price=price, net_pnl=net_pnl),
        )

    @staticmethod
    def _age_seconds(sig: dict[str, Any]) -> int:
        return now_ts() - int(sig.get("created_at", now_ts()))

    def _safe_okx_price(self, coin: str | None) -> float | None:
        if not coin:
            return None
        try:
            return float(self.okx.get_last_price(coin))
        except Exception as exc:
            print(f"okx price error {coin}: {exc}")
            return None

    @staticmethod
    def _normalize_tobit_result(raw_result: Any) -> str:
        value = str(raw_result or "").upper().strip()
        if value in {"TP", "TAKE_PROFIT", "TAKEPROFIT", "PROFIT"}:
            return "TP"
        if value in {"SL", "STOP_LOSS", "STOPLOSS", "LOSS"}:
            return "SL"
        if value in {"EXPIRED", "CLOSED", "MANUAL", "UNKNOWN"}:
            return "EXPIRED"
        return "EXPIRED"

    @staticmethod
    def _price_result(sig: dict[str, Any], price: float) -> str | None:
        side = sig.get("side")
        tp = float(sig["tp"])
        sl = float(sig["sl"])

        if side == "LONG":
            if price >= tp:
                return "TP"
            if price <= sl:
                return "SL"
            return None

        if side == "SHORT":
            if price <= tp:
                return "TP"
            if price >= sl:
                return "SL"
            return None

        return None
