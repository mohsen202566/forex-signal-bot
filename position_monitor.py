"""مانیتورینگ دقیق همه سیگنال‌ها.

- سیگنال عادی با قیمت OKX مانیتور می‌شود.
- سیگنال توبیت با Toobit تایید می‌شود.
- نتیجه باید با reply روی پیام اصلی سیگنال اعلام شود.
"""
from __future__ import annotations

import time
from typing import Callable, Any

import config
from state_store import StateStore, now_ts
from telegram_ui import result_message


class PositionMonitor:
    def __init__(self, state: StateStore, okx_client: Any, tobit_client: Any, send_reply: Callable[[int | None, str], None]):
        self.state = state
        self.okx = okx_client
        self.tobit = tobit_client
        self.send_reply = send_reply

    def tick(self) -> None:
        for sig in list(self.state.all_active()):
            if sig.get("kind") == "SIGNAL":
                self._monitor_signal(sig)
            elif sig.get("kind") == "TOBIT":
                self._monitor_tobit(sig)

    def _monitor_signal(self, sig: dict[str, Any]) -> None:
        age = now_ts() - int(sig.get("created_at", now_ts()))
        try:
            price = self.okx.get_last_price(sig["coin"])
        except Exception:
            return
        result = self._price_result(sig, price)
        if result:
            self.state.close_signal(sig["id"], result, {"result_price": price})
            self.send_reply(sig.get("telegram_message_id"), result_message(sig, result, price=price))
            return
        if age > config.POSITION_MAX_MINUTES * 60:
            self.state.close_signal(sig["id"], "EXPIRED", {"result_price": price})
            self.send_reply(sig.get("telegram_message_id"), result_message(sig, "EXPIRED", price=price))

    def _monitor_tobit(self, sig: dict[str, Any]) -> None:
        age = now_ts() - int(sig.get("created_at", now_ts()))
        if sig.get("status") == "PENDING_OPEN" and age >= config.TOBIT_OPEN_CONFIRM_SECONDS:
            pos = self.tobit.position_exists(sig["coin"], sig.get("side"))
            if pos.get("exists"):
                self.state.mark_open(sig["id"], pos.get("position_id"))
            else:
                self.state.close_signal(sig["id"], "FAILED_OPEN")
                self.send_reply(sig.get("telegram_message_id"), result_message(sig, "FAILED_OPEN"))
            return
        if sig.get("status") != "OPEN":
            return
        res = self.tobit.closed_result(sig["coin"], sig.get("side"), sig.get("exchange_position_id"))
        if res.get("closed"):
            result = "TP" if res.get("result") == "TP" else "SL" if res.get("result") == "SL" else "EXPIRED"
            self.state.close_signal(sig["id"], result, {"net_pnl": float(res.get("net_pnl", 0.0)), "result_price": res.get("price")})
            self.send_reply(sig.get("telegram_message_id"), result_message(sig, result, price=res.get("price"), net_pnl=float(res.get("net_pnl", 0.0))))

    @staticmethod
    def _price_result(sig: dict[str, Any], price: float) -> str | None:
        side = sig.get("side")
        if side == "LONG":
            if price >= float(sig["tp"]):
                return "TP"
            if price <= float(sig["sl"]):
                return "SL"
        else:
            if price <= float(sig["tp"]):
                return "TP"
            if price >= float(sig["sl"]):
                return "SL"
        return None
