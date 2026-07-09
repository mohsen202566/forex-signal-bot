"""وضعیت runtime در فایل‌های ریشه‌ای؛ بدون دیتابیس و بدون پوشه."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config
from utils import load_json, save_json, now_ms


@dataclass
class BotState:
    mode: str = config.BOT_MODE
    trading_enabled: bool = False
    symbols: list[str] = field(default_factory=lambda: list(config.SYMBOLS))
    trade_amount_usdt: float = config.TRADE_AMOUNT_USDT
    leverage: int = config.LEVERAGE
    default_rr: float = config.DEFAULT_RR
    min_rr: float = config.MIN_RR
    max_active_trades: int = config.MAX_ACTIVE_TRADES
    last_signal_ms: dict[str, int] = field(default_factory=dict)
    loss_cooldown_until_ms: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "BotState":
        data = load_json(config.STATE_FILE, {})
        state = cls()
        for k, v in data.items():
            if hasattr(state, k):
                setattr(state, k, v)
        state.mode = str(state.mode or "NORMAL").upper()
        if state.mode not in {"NORMAL", "REAL"}:
            state.mode = "NORMAL"
        state.min_rr = max(1.0, float(state.min_rr))
        state.default_rr = max(state.min_rr, float(state.default_rr))
        # مهاجرت امن نمادها بعد از آپدیت: TONUSDT در OKX SWAP این پروژه معتبر نبود؛ WIFUSDT جایگزین شد.
        original_symbols = list(state.symbols or [])
        cleaned: list[str] = []
        for raw in original_symbols:
            sym = str(raw).upper().replace("-", "").replace("/", "")
            if sym == "TONUSDT":
                sym = "WIFUSDT"
            if sym and sym not in cleaned:
                cleaned.append(sym)

        # اگر لیست قبلی از پیش‌فرض‌های ربات بوده و با آپدیت ناقص مانده، آن را با لیست ۳۵تایی جدید همسان کن.
        default_set = set(config.DEFAULT_SYMBOLS_35)
        if len(cleaned) >= 30 and ("WIFUSDT" not in cleaned or any(x not in default_set for x in cleaned)):
            cleaned = list(config.DEFAULT_SYMBOLS_35)
        state.symbols = cleaned
        if original_symbols != cleaned:
            try:
                state.save()
            except Exception:
                pass
        return state

    def save(self) -> None:
        save_json(config.STATE_FILE, self.__dict__)

    def in_symbol_cooldown(self, symbol: str) -> bool:
        now = now_ms()
        last = int(self.last_signal_ms.get(symbol, 0))
        loss_until = int(self.loss_cooldown_until_ms.get(symbol, 0))
        return (now - last) < config.COOLDOWN_AFTER_SIGNAL_SECONDS * 1000 or now < loss_until

    def touch_signal(self, symbol: str) -> None:
        self.last_signal_ms[symbol] = now_ms()
        self.save()

    def touch_loss(self, symbol: str) -> None:
        self.loss_cooldown_until_ms[symbol] = now_ms() + config.COOLDOWN_AFTER_LOSS_SECONDS * 1000
        self.save()

    def set_mode(self, mode: str) -> None:
        mode = str(mode).upper()
        if mode not in {"NORMAL", "REAL"}:
            raise ValueError("mode باید NORMAL یا REAL باشد")
        self.mode = mode
        self.save()

    def set_trading(self, enabled: bool) -> None:
        self.trading_enabled = bool(enabled)
        self.save()

    def add_symbol(self, symbol: str) -> None:
        s = symbol.upper().replace("-", "").replace("/", "")
        if s not in self.symbols:
            self.symbols.append(s)
            self.save()

    def remove_symbol(self, symbol: str) -> None:
        s = symbol.upper().replace("-", "").replace("/", "")
        self.symbols = [x for x in self.symbols if x != s]
        self.save()


def load_active_trades() -> list[dict[str, Any]]:
    data = load_json(config.ACTIVE_TRADES_FILE, [])
    return data if isinstance(data, list) else []


def save_active_trades(trades: list[dict[str, Any]]) -> None:
    save_json(config.ACTIVE_TRADES_FILE, trades)
