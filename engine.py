"""هسته اسکن؛ همه تحلیل‌ها با OKX انجام می‌شود."""
from __future__ import annotations

import asyncio
from typing import Callable, Awaitable

from okx_client import OKXClient
from state import BotState
from strategy import DIFT5MStrategy, TradeSignal
from trade_manager import TradeManager
from utils import logger

NotifyFn = Callable[[str], Awaitable[None]]


class BotEngine:
    def __init__(self, notify: NotifyFn | None = None):
        self.okx = OKXClient()
        self.strategy = DIFT5MStrategy()
        self.manager = TradeManager(self.okx)
        self.notify = notify
        self.running = False
        self.last_rejections: dict[str, str] = {}
        self.last_signal: TradeSignal | None = None

    async def send(self, text: str) -> None:
        if self.notify:
            await self.notify(text)

    async def scan_once(self) -> list[TradeSignal]:
        state = BotState.load()
        signals: list[TradeSignal] = []
        for symbol in list(state.symbols):
            try:
                market = self.okx.get_market_data(symbol)
                result = self.strategy.analyze(market)
                if isinstance(result, TradeSignal):
                    signals.append(result)
                    self.last_signal = result
                    exec_result = self.manager.execute_or_track(result, state)
                    await self.send("🚨 سیگنال معتبر\n" + result.text() + f"\nAction: {exec_result.get('action')}\n{exec_result.get('reason','')}")
                else:
                    self.last_rejections[symbol] = result.reason
            except Exception as exc:
                self.last_rejections[symbol] = str(exc)
                logger.warning("اسکن %s ناموفق بود: %s", symbol, exc)
        return signals

    async def check_results_once(self) -> list[dict]:
        state = BotState.load()
        closed = self.manager.update_results(state)
        for r in closed:
            await self.send(
                "✅ نتیجه معامله\n"
                f"{r.get('mode')} | {r.get('symbol')} | {r.get('direction')}\n"
                f"Close: {r.get('close_price')}\n"
                f"PnL/Result: {r.get('pnl')} {r.get('result','')}\n"
                f"Source: {r.get('result_source')}"
            )
        return closed

    async def loop(self, interval_seconds: int) -> None:
        self.running = True
        while self.running:
            await self.scan_once()
            await self.check_results_once()
            await asyncio.sleep(max(5, int(interval_seconds)))

    def stop(self) -> None:
        self.running = False
