"""حلقه اصلی ربات کم‌فایل.

این فایل عمداً سبک است:
- اسکن ۱۰ کوین هر ۲۰ تا ۳۰ ثانیه
- مانیتورینگ هر ۲ تا ۳ ثانیه
- تلگرام/Toobit واقعی با Adapter قابل اتصال است.
"""
from __future__ import annotations

import time
from typing import Any

import config
from command_router import CommandRouter
from exchange_clients import OKXClient, ToobitAdapter
from position_monitor import PositionMonitor
from state_store import StateStore, now_ts
from strategy_engine import StrategyEngine, estimated_net_profit_usdt
from telegram_ui import signal_message, result_message


class TelegramSink:
    """برای نسخه واقعی، این کلاس را به python-telegram-bot وصل کن."""
    def send(self, text: str) -> int | None:
        print("\n--- TELEGRAM SEND ---\n" + text)
        return None

    def reply(self, message_id: int | None, text: str) -> None:
        print(f"\n--- TELEGRAM REPLY to {message_id} ---\n{text}")


class Bot:
    def __init__(self):
        self.state = StateStore()
        self.okx = OKXClient()
        self.tobit = ToobitAdapter()
        self.strategy = StrategyEngine()
        self.telegram = TelegramSink()
        self.router = CommandRouter(self.state, self.tobit)
        self.monitor = PositionMonitor(self.state, self.okx, self.tobit, self.telegram.reply)
        self.last_scan = 0

    def run_forever(self) -> None:
        print("Crypto Helper 15m bot started.")
        while True:
            self.monitor.tick()
            if time.time() - self.last_scan >= config.COIN_SCAN_SECONDS:
                self.scan_all()
                self.last_scan = time.time()
            time.sleep(config.PRICE_MONITOR_SECONDS)

    def scan_all(self) -> None:
        self.state.data["last_scan"] = now_ts()
        self.state.save()
        for coin in config.WATCHLIST:
            try:
                c15 = self.okx.get_candles(coin, "15m", 120)
                c1h = self.okx.get_candles(coin, "1H", 80)
                oi = self.okx.get_open_interest_series(coin)
                plan = self.strategy.analyze(coin, c15, c1h, oi)
                if plan:
                    self.handle_plan(plan.to_dict())
            except Exception as e:
                print(f"scan error {coin}: {e}")

    def handle_plan(self, plan: dict[str, Any]) -> None:
        # اول همیشه سیگنال عادی برای ارزیابی موتور تحلیل صادر می‌شود.
        if not self._duplicate_or_replace_signal(plan, kind="SIGNAL"):
            self._emit_signal(plan, kind="SIGNAL")

        # REAL فقط وقتی ترید فعال باشد و قوانین پاس شوند.
        settings = self.state.settings()
        if not settings.get("real_trade_enabled"):
            return
        if self.state.has_active_real_for_coin(plan["coin"]):
            return
        if self.state.open_real_count() >= int(settings.get("max_open_positions", 1)):
            return

        net_profit = estimated_net_profit_usdt(
            margin_usdt=float(settings["trade_margin_usdt"]),
            leverage=int(settings["leverage"]),
            tp_percent=float(plan["tp_percent"]),
            fee_rate=config.DEFAULT_FEE_RATE,
            slippage_rate=config.SLIPPAGE_BUFFER_RATE,
        )
        if net_profit < float(settings["min_net_profit_usdt"]):
            return
        if self._duplicate_or_replace_signal(plan, kind="TOBIT"):
            return
        self._open_real(plan)

    def _duplicate_or_replace_signal(self, plan: dict[str, Any], kind: str) -> bool:
        same = [s for s in self.state.active_by_coin(plan["coin"], kind) if s.get("side") == plan["side"]]
        if not same:
            return False
        strongest = max(same, key=lambda s: float(s.get("final_score", 0)))
        if float(plan["final_score"]) >= float(strongest.get("final_score", 0)) + config.REPLACE_SIGNAL_MIN_IMPROVEMENT and kind == "SIGNAL":
            self.state.close_signal(strongest["id"], "REPLACED")
            self.telegram.reply(strongest.get("telegram_message_id"), result_message(strongest, "REPLACED"))
            return False
        return True

    def _emit_signal(self, plan: dict[str, Any], kind: str) -> str:
        sig = dict(plan)
        sig.update({"kind": kind, "status": "ACTIVE", "created_at": now_ts()})
        sid = self.state.add_signal(sig)
        sig["id"] = sid
        msg_id = self.telegram.send(signal_message(sig))
        if msg_id:
            self.state.data["active_signals"][sid]["telegram_message_id"] = msg_id
            self.state.save()
        return sid

    def _open_real(self, plan: dict[str, Any]) -> None:
        settings = self.state.settings()
        sig = dict(plan)
        sig.update({"kind": "TOBIT", "status": "PENDING_OPEN", "created_at": now_ts()})
        sid = self.state.add_signal(sig)  # اسلات فوراً فرضی پر می‌شود.
        sig["id"] = sid
        msg_id = self.telegram.send(signal_message(sig))
        if msg_id:
            self.state.data["active_signals"][sid]["telegram_message_id"] = msg_id
            self.state.save()
        res = self.tobit.open_position_with_tp_sl(
            symbol=plan["coin"], side=plan["side"],
            margin_usdt=float(settings["trade_margin_usdt"]),
            leverage=int(settings["leverage"]),
            entry=float(plan["entry"]), tp=float(plan["tp"]), sl=float(plan["sl"]),
        )
        if not res.get("ok", False):
            # اگر ارسال سفارش اصلاً fail شد، اسلات آزاد شود.
            self.state.close_signal(sid, "FAILED_OPEN", {"error": res.get("error")})
            self.telegram.reply(msg_id, result_message(sig, "FAILED_OPEN"))
        # اگر ارسال ok بود، وضعیت PENDING_OPEN می‌ماند و ۷۰ ثانیه بعد monitor تایید می‌کند.


if __name__ == "__main__":
    Bot().run_forever()
