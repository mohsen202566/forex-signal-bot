"""مانیتورینگ ثبت و ارسال نتیجه معاملات.

- NORMAL: نتیجه با کندل‌های OKX شبیه‌سازی و ثبت می‌شود.
- REAL: نتیجه قطعی از Toobit history / realized PnL خوانده می‌شود.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from state import BotState
from trade_manager import TradeManager

NotifyFn = Callable[[str], Awaitable[None]]


class ResultMonitor:
    def __init__(self, manager: TradeManager, notify: NotifyFn | None = None):
        self.manager = manager
        self.notify = notify

    async def check_once(self) -> list[dict]:
        state = BotState.load()
        closed = self.manager.update_results(state)
        if self.notify:
            for item in closed:
                await self.notify(self.manager.format_result(item))
        return closed
