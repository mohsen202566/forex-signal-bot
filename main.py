from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field

import config
import messages_fa
from okx_client import OKXClient
from stats_manager import StatsManager
from storage import JsonStorage
from strategy import NoSignal, Signal, SimpleStrangeStrategy
from telegram_bot import TelegramBot
from trade_manager import TradeManager
from utils import normalize_base_symbol, okx_symbol, toobit_symbol

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("forex-bot")


@dataclass
class ScanReport:
    signals: list[Signal] = field(default_factory=list)
    rejected: int = 0
    errors: int = 0
    reasons: Counter[str] = field(default_factory=Counter)


class ForexBotApp:
    def __init__(self) -> None:
        self.storage = JsonStorage()
        self.stats = StatsManager(self.storage)
        self.okx = OKXClient()
        self.strategy = SimpleStrangeStrategy()
        self.trade_manager = TradeManager(self.storage)
        self.telegram = TelegramBot(self.storage, self.stats)
        self.symbols: list[str] = []
        self._tasks_started = False
        self._scanner_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None

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

    async def post_init(self, application) -> None:  # noqa: ANN001
        """Start background loops in Telegram's active asyncio loop.

        مهم: از application.create_task استفاده نمی‌کنیم، چون روی بعضی نسخه‌های
        python-telegram-bot قبل از run شدن Application هشدار می‌دهد و تسک‌ها
        درست اجرا نمی‌شوند. asyncio.create_task روی loop فعال همین run_polling
        پایدارتر است.
        """
        if self._tasks_started:
            return
        self._tasks_started = True
        self._scanner_task = asyncio.create_task(self.scan_loop(), name="forex-scan-loop")
        self._monitor_task = asyncio.create_task(self.monitor_loop(), name="forex-monitor-loop")
        logger.info("Forex background loops started.")

    async def scan_loop(self) -> None:
        while True:
            try:
                if not self.symbols:
                    self.symbols = await asyncio.to_thread(self.build_symbol_universe)
                    logger.info("نمادهای فعال: %s", len(self.symbols))

                report = await asyncio.to_thread(self.scan_once_collect)
                logger.info(
                    "پایان اسکن | سیگنال: %s | رد شده: %s | خطا: %s",
                    len(report.signals),
                    report.rejected,
                    report.errors,
                )
                for reason, count in report.reasons.most_common(10):
                    logger.info("دلیل رد %s نماد: %s", count, reason)

                for signal in report.signals:
                    await self.handle_signal(signal)

            except Exception as exc:
                logger.exception("خطا در حلقه اسکن: %s", exc)

            await asyncio.sleep(config.FULL_SCAN_SECONDS)

    def scan_once_collect(self) -> ScanReport:
        if not self.symbols:
            self.symbols = self.build_symbol_universe()

        logger.info("شروع اسکن: %s نماد", len(self.symbols))
        report = ScanReport()

        for base in self.symbols:
            try:
                c1d = self.okx.get_candles(okx_symbol(base), "1D", 220)
                c15 = self.okx.get_candles(okx_symbol(base), "15m", 120)
                c5 = self.okx.get_candles(okx_symbol(base), "5m", 120)
                result = self.strategy.evaluate(
                    base_symbol=base,
                    candles_1d=c1d,
                    candles_15m=c15,
                    candles_5m=c5,
                )
                if isinstance(result, Signal):
                    report.signals.append(result)
                    logger.info(
                        "سیگنال پیدا شد: %s %s entry=%s tp=%s sl=%s score=%s",
                        result.base_symbol,
                        result.direction,
                        result.entry_price,
                        result.tp_price,
                        result.sl_price,
                        result.score,
                    )
                else:
                    report.rejected += 1
                    reason = result.reason if isinstance(result, NoSignal) else "رد شد."
                    report.reasons[reason] += 1
            except Exception as exc:
                report.errors += 1
                logger.warning("خطا در بررسی %s: %s", base, exc)

        return report

    async def handle_signal(self, signal: Signal) -> None:
        # تا وقتی سیگنال قبلی همان ارز باز است، سیگنال تکراری نده.
        # نتیجه همان سیگنال قبلی همچنان مانیتور و ریپلای می‌شود.
        if self.storage.has_open_signal(signal.base_symbol):
            logger.info("سیگنال %s رد شد؛ یک سیگنال باز برای همین ارز وجود دارد.", signal.base_symbol)
            return

        settings = self.storage.state.settings
        text = messages_fa.signal_message(signal, settings.margin_usdt, settings.leverage)
        message_id = await self.telegram.send_signal(text)

        open_result = await asyncio.to_thread(self.trade_manager.open_from_signal, signal)
        if not open_result.signal_id:
            logger.info("سیگنال ثبت نشد: %s", open_result.message)
            return

        if message_id:
            self.storage.set_signal_message_id(open_result.signal_id, message_id)

        # پیام وضعیت اجرا ارسال نمی‌شود؛ فقط سیگنال اصلی و نتیجه نهایی ریپلای می‌شوند.
        # سیگنال همچنان در storage ثبت و مانیتور می‌شود.

    async def monitor_loop(self) -> None:
        loop = asyncio.get_running_loop()

        def send_reply(sig, text):  # noqa: ANN001
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self.telegram.reply_to_signal(sig, text)))

        while True:
            try:
                await asyncio.to_thread(self.trade_manager.monitor_open_positions, send_reply)
            except Exception as exc:
                logger.exception("خطا در مانیتور پوزیشن: %s", exc)
            await asyncio.sleep(config.MONITOR_INTERVAL_SECONDS)

    def run(self) -> None:
        self.telegram.run_polling(post_init=self.post_init)


if __name__ == "__main__":
    ForexBotApp().run()
