"""مانیتورینگ نتایج.

Virtual فقط با دیتای ۱ دقیقه OKX برای ترتیب دقیق‌تر TP/SL بررسی می‌شود.
Real فقط از پوزیشن و تاریخچه واقعی Toobit نتیجه می‌گیرد و هرگز نتیجه را از OKX حدس نمی‌زند.
"""
from __future__ import annotations

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

    def _send_result(self, sig: dict, reason: str, exit_price: float, net: float, gross: float, fee: float, mfe: float = 0.0, mae: float = 0.0):
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
        self.storage.update_signal(sig["id"], status="closed", closed_at=int(time.time()), exit_price=exit_price, gross_pnl=gross, fee_usdt=fee, net_pnl=net, close_reason=reason, mfe=mfe, mae=mae)
        self.storage.add_profit(net)
        logger.info("[نتیجه عادی] شماره=%s | ارز=%s | نتیجه=%s | خالص=%.4f | خروج=%.8g", sig["id"], sig["symbol_id"], reason, net, exit_price)
        self._send_result(sig, reason, exit_price, net, gross, fee, mfe, mae)

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
        self.storage.update_signal(sig["id"], status="closed", closed_at=int(time.time()), exit_price=exit_price, gross_pnl=gross, fee_usdt=fee, net_pnl=net, close_reason=reason, raw_json=result.get("raw", {}))
        self.storage.add_profit(net)
        logger.info("[نتیجه واقعی] شماره=%s | ارز=%s | نتیجه=%s | خالص=%.4f | خروج=%.8g", sig["id"], sig["symbol_id"], reason, net, exit_price)
        self._send_result(sig, reason, exit_price, net, gross, fee)

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
