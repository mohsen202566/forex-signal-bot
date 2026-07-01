from __future__ import annotations

import asyncio
import logging
import threading
import time

import config
import messages_fa
from okx_client import OKXClient
from stats_manager import StatsManager
from storage import JsonStorage
from strategy import NoSignal, Signal, SimpleStrangeStrategy
from telegram_bot import TelegramBot
from trade_manager import TradeManager
from utils import normalize_base_symbol, okx_symbol, toobit_symbol

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("forex-bot")


class ForexBotApp:
    def __init__(self) -> None:
        self.storage = JsonStorage()
        self.stats = StatsManager(self.storage)
        self.okx = OKXClient()
        self.strategy = SimpleStrangeStrategy()
        self.trade_manager = TradeManager(self.storage)
        self.telegram = TelegramBot(self.storage, self.stats)
        self.symbols: list[str] = []

    def build_symbol_universe(self) -> list[str]:
        okx_symbols = self.okx.get_swap_symbols()
        toobit_symbols = self._get_toobit_symbols()
        final: list[str] = []
        for base in config.BASE_SYMBOL_WHITELIST:
            base = normalize_base_symbol(base)
            if okx_symbol(base) in okx_symbols and toobit_symbol(base) in toobit_symbols:
                final.append(base)
        if len(final) < config.MIN_SYMBOLS_COUNT:
            logger.warning("تعداد نمادهای مشترک معتبر کمتر از حداقل است: %s", len(final))
        return final

    def _get_toobit_symbols(self) -> set[str]:
        client = self.trade_manager.toobit
        try:
            payload = client._request("GET", client.path_exchange_info, signed=False)  # noqa: SLF001
        except Exception as exc:
            logger.warning("خواندن لیست نمادهای Toobit ناموفق بود؛ از whitelist تبدیل‌شده استفاده می‌شود: %s", exc)
            return {toobit_symbol(base) for base in config.BASE_SYMBOL_WHITELIST}
        symbols: set[str] = set()
        stack = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                sym = str(item.get("symbol") or item.get("symbolId") or item.get("contractCode") or "").upper()
                if sym.endswith("-SWAP-USDT"):
                    symbols.add(sym)
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
        return symbols or {toobit_symbol(base) for base in config.BASE_SYMBOL_WHITELIST}

    async def scan_loop(self) -> None:
        self.symbols = self.build_symbol_universe()
        logger.info("نمادهای فعال: %s", len(self.symbols))
        while True:
            await self.scan_once()
            await asyncio.sleep(config.FULL_SCAN_SECONDS)

    async def scan_once(self) -> None:
        if not self.symbols:
            self.symbols = self.build_symbol_universe()
        try:
            btc_1d = self.okx.get_candles("BTC-USDT-SWAP", "1D", 220)
            eth_1d = self.okx.get_candles("ETH-USDT-SWAP", "1D", 220)
        except Exception as exc:
            logger.warning("دریافت BTC/ETH ناموفق بود: %s", exc)
            return
        for base in self.symbols:
            try:
                c1d = self.okx.get_candles(okx_symbol(base), "1D", 220)
                c15 = self.okx.get_candles(okx_symbol(base), "15m", 120)
                c5 = self.okx.get_candles(okx_symbol(base), "5m", 120)
                result = self.strategy.evaluate(base_symbol=base, candles_1d=c1d, candles_15m=c15, candles_5m=c5, btc_1d=btc_1d, eth_1d=eth_1d)
                if isinstance(result, Signal):
                    await self.handle_signal(result)
            except Exception as exc:
                logger.debug("خطا در بررسی %s: %s", base, exc)

    async def handle_signal(self, signal: Signal) -> None:
        settings = self.storage.state.settings
        text = messages_fa.signal_message(signal, settings.margin_usdt, settings.leverage)
        message_id = await self.telegram.send_signal(text)
        open_result = self.trade_manager.open_from_signal(signal)
        if open_result.signal_id and message_id:
            self.storage.set_signal_message_id(open_result.signal_id, message_id)
        if not open_result.opened:
            logger.info("سیگنال بدون اجرای سفارش: %s", open_result.message)

    async def monitor_loop(self) -> None:
        def send_reply(sig, text):
            asyncio.run_coroutine_threadsafe(self.telegram.reply_to_signal(sig, text), asyncio.get_running_loop())
        while True:
            try:
                self.trade_manager.monitor_open_positions(send_reply=send_reply)
            except Exception as exc:
                logger.warning("خطا در مانیتور پوزیشن: %s", exc)
            await asyncio.sleep(config.MONITOR_INTERVAL_SECONDS)

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(self.scan_loop())
        loop.create_task(self.monitor_loop())
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        self.telegram.run_polling()


if __name__ == "__main__":
    ForexBotApp().run()
