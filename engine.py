"""هسته اسکن و مانیتور؛ همه تحلیل‌ها با OKX، اجرای/نتیجه واقعی با Toobit."""
from __future__ import annotations

import asyncio
from typing import Callable, Awaitable

import config
from okx_client import OKXClient
from state import BotState
from strategy import DIFT5MStrategy, TradeSignal
from symbol_registry import SymbolValidationReport, validate_symbols
from trade_manager import TradeManager
from monitor import ResultMonitor
from utils import logger

NotifyFn = Callable[[str], Awaitable[None]]


class BotEngine:
    def __init__(self, notify: NotifyFn | None = None):
        self.okx = OKXClient()
        self.strategy = DIFT5MStrategy()
        self.manager = TradeManager(self.okx)
        self.monitor = ResultMonitor(self.manager, notify if config.SEND_RESULT_MESSAGES else None)
        self.notify = notify
        self.running = False
        self.last_rejections: dict[str, str] = {}
        self.last_signal: TradeSignal | None = None
        self.symbol_report: SymbolValidationReport | None = None
        self.valid_symbols: set[str] = set()

    async def send(self, text: str) -> None:
        if self.notify:
            await self.notify(text)

    async def validate_symbols_once(self, force: bool = False) -> SymbolValidationReport | None:
        if self.symbol_report is not None and not force:
            return self.symbol_report
        if not config.REQUIRE_EXCHANGE_SYMBOL_MATCH:
            return None
        state = BotState.load()
        try:
            report = validate_symbols(state.symbols, self.okx, self.manager.toobit)
            self.symbol_report = report
            self.valid_symbols = set(report.valid_common)
            if report.valid_common and state.symbols != report.valid_common and len(report.valid_common) >= config.REQUIRED_COMMON_SYMBOL_COUNT:
                state.symbols = list(report.valid_common)
                state.save()
            prefix = "✅ اعتبارسنجی ۳۵ نماد مشترک انجام شد" if report.ok else "⚠️ مشکل در همخوانی نمادهای OKX/Toobit"
            await self.send(prefix + "\n" + report.short_text())
            return report
        except Exception as exc:
            logger.warning("اعتبارسنجی نمادها ناموفق بود: %s", exc)
            await self.send(f"⚠️ اعتبارسنجی نمادهای OKX/Toobit ناموفق بود: {exc}")
            return None

    def _scan_once_sync(self) -> tuple[list[TradeSignal], list[str]]:
        """اسکن سنگین بازار در thread جدا اجرا می‌شود تا تلگرام دیر جواب ندهد."""
        state = BotState.load()
        messages: list[str] = []

        if config.VALIDATE_SYMBOLS_ON_START and self.symbol_report is None and config.REQUIRE_EXCHANGE_SYMBOL_MATCH:
            try:
                report = validate_symbols(state.symbols, self.okx, self.manager.toobit)
                self.symbol_report = report
                self.valid_symbols = set(report.valid_common)
                if report.valid_common and state.symbols != report.valid_common and len(report.valid_common) >= config.REQUIRED_COMMON_SYMBOL_COUNT:
                    state.symbols = list(report.valid_common)
                    state.save()
                prefix = "✅ اعتبارسنجی ۳۵ نماد مشترک انجام شد" if report.ok else "⚠️ مشکل در همخوانی نمادهای OKX/Toobit"
                messages.append(prefix + "\n" + report.short_text())
            except Exception as exc:
                logger.warning("اعتبارسنجی نمادها ناموفق بود: %s", exc)
                messages.append(f"⚠️ اعتبارسنجی نمادهای OKX/Toobit ناموفق بود: {exc}")

        scan_symbols = list(state.symbols)
        if config.REQUIRE_EXCHANGE_SYMBOL_MATCH and self.valid_symbols:
            scan_symbols = [s for s in scan_symbols if s in self.valid_symbols]

        signals: list[TradeSignal] = []
        for symbol in scan_symbols:
            try:
                market = self.okx.get_market_data(symbol)
                result = self.strategy.analyze(market)
                if isinstance(result, TradeSignal):
                    signals.append(result)
                    self.last_signal = result
                    exec_result = self.manager.execute_or_track(result, state)
                    if config.SEND_SIGNAL_MESSAGES:
                        messages.append("🚨 سیگنال معتبر\n" + result.text() + f"\nAction: {exec_result.get('action')}\n{exec_result.get('reason','')}")
                else:
                    self.last_rejections[symbol] = result.reason
            except Exception as exc:
                self.last_rejections[symbol] = str(exc)
                logger.warning("اسکن %s ناموفق بود: %s", symbol, exc)
        return signals, messages

    async def scan_once(self) -> list[TradeSignal]:
        signals, messages = await asyncio.to_thread(self._scan_once_sync)
        for msg in messages:
            await self.send(msg)
        return signals

    async def check_results_once(self) -> list[dict]:
        if not config.MONITORING_ENABLED:
            return []
        state = BotState.load()
        closed = await asyncio.to_thread(self.manager.update_results, state)
        if self.notify and config.SEND_RESULT_MESSAGES:
            for item in closed:
                await self.notify(self.manager.format_result(item))
        return closed

    async def scan_loop(self, interval_seconds: int) -> None:
        self.running = True
        while self.running:
            await self.scan_once()
            await asyncio.sleep(max(5, int(interval_seconds)))

    async def monitor_loop(self, interval_seconds: int) -> None:
        self.running = True
        while self.running:
            await self.check_results_once()
            await asyncio.sleep(max(5, int(interval_seconds)))

    async def loop(self, interval_seconds: int) -> None:
        """سازگاری با نسخه قبلی: اسکن و مانیتور را همزمان اجرا می‌کند."""
        await asyncio.gather(
            self.scan_loop(interval_seconds),
            self.monitor_loop(config.RESULT_CHECK_INTERVAL_SECONDS),
        )

    def stop(self) -> None:
        self.running = False
