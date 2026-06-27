"""
tobit_client.py - compatibility wrapper for the current Toobit client.

Canonical low-level client is toobit_client.py. This wrapper keeps the older
Level-4 bot modules working while using the uploaded Toobit implementation.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping
import time

from constants import DIRECTION_LONG, DIRECTION_SHORT, STATUS_FAILED, STATUS_OK, STATUS_RECOVERED, SYSTEM_VERSION
from models import TradeCloseResult, TradeOpenResult
from utils import normalize_direction, normalize_symbol, profit_usdt, safe_float, safe_int, safe_str

from toobit_client import (  # noqa: F401
    Direction,
    HistoryPositionInfo,
    OpenOrderInfo,
    OpenOrderResult,
    PositionInfo,
    SymbolRules,
    ToobitAPIError,
    ToobitClient,
    ToobitConfig,
    get_client,
)

TOBIT_CLIENT_VERSION: str = SYSTEM_VERSION
MARGIN_ISOLATED = "ISOLATED"
MARGIN_CROSS = "CROSS"


def _rules_to_dict(self: SymbolRules) -> dict[str, Any]:
    return {
        "symbol": self.symbol,
        "exchange_symbol": self.symbol,
        "quantity_step": float(self.quantity_step),
        "qty_step": float(self.quantity_step),
        "price_tick": float(self.price_tick),
        "min_quantity": float(self.min_quantity),
        "min_qty": float(self.min_quantity),
        "min_notional": float(self.min_notional),
    }

if not hasattr(SymbolRules, "to_dict"):
    SymbolRules.to_dict = _rules_to_dict  # type: ignore[attr-defined]


def _position_to_row(pos: PositionInfo) -> dict[str, Any]:
    row = dict(pos.raw or {})
    row.setdefault("symbol", pos.symbol)
    row.setdefault("direction", pos.side)
    row.setdefault("side", pos.side)
    row.setdefault("positionAmt", pos.quantity)
    row.setdefault("qty", pos.quantity)
    row.setdefault("entryPrice", pos.entry_price)
    row.setdefault("avgPrice", pos.entry_price)
    row.setdefault("unrealizedPnl", pos.unrealized_pnl)
    row.setdefault("pnl", pos.unrealized_pnl)
    return row


def _normalize_bot_symbol(self: ToobitClient, symbol: str) -> str:
    # Current client already uses plain symbols. Keep special 1000 contracts readable.
    s = normalize_symbol(symbol)
    reverse = {"1000PEPEUSDT": "PEPEUSDT", "1000BONKUSDT": "BONKUSDT", "1000SHIBUSDT": "SHIBUSDT", "1000FLOKIUSDT": "FLOKIUSDT"}
    return reverse.get(s, s)


def _position_direction(self: ToobitClient, row: Mapping[str, Any]) -> str:
    raw = safe_str(row.get("direction") or row.get("side") or row.get("positionSide")).upper()
    if raw in {"LONG", "BUY", "BUY_OPEN"}:
        return DIRECTION_LONG
    if raw in {"SHORT", "SELL", "SELL_OPEN"}:
        return DIRECTION_SHORT
    qty = safe_float(row.get("positionAmt") or row.get("qty") or row.get("quantity") or row.get("size"), 0.0) or 0.0
    return DIRECTION_LONG if qty >= 0 else DIRECTION_SHORT


def _position_qty(self: ToobitClient, row: Mapping[str, Any]) -> float:
    return abs(safe_float(row.get("positionAmt") or row.get("qty") or row.get("quantity") or row.get("size"), 0.0) or 0.0)


def _get_account_balance(self: ToobitClient, asset: str = "USDT") -> dict[str, Any]:
    try:
        available = float(self.get_wallet_margin_usdt())
        return {"status": STATUS_OK, "asset": asset.upper(), "balance": available, "available": available, "credentials_loaded": True}
    except Exception as exc:
        return {"status": STATUS_FAILED, "asset": asset.upper(), "balance": None, "available": None, "credentials_loaded": False, "error": str(exc)}


def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _validate_quantity(self: ToobitClient, symbol: str, quantity_estimate: Any, entry_price: Any) -> tuple[bool, float, str, SymbolRules]:
    rules = self.get_symbol_rules(symbol)
    qty = Decimal(str(safe_float(quantity_estimate, 0.0) or 0.0))
    entry = Decimal(str(safe_float(entry_price, 0.0) or 0.0))
    if qty <= 0 or entry <= 0:
        return False, 0.0, "invalid_quantity_or_entry", rules
    qty = _quantize_down(qty, rules.quantity_step)
    if qty <= 0:
        return False, 0.0, "quantity_rounded_to_zero", rules
    if rules.min_quantity > 0 and qty < rules.min_quantity:
        return False, float(qty), f"min_quantity_not_met:{qty}<{rules.min_quantity}", rules
    notional = qty * entry
    if rules.min_notional > 0 and notional < rules.min_notional:
        return False, float(qty), f"min_notional_not_met:{notional}<{rules.min_notional}", rules
    return True, float(qty), "ok", rules


def _verify_leverage(self: ToobitClient, symbol: str, leverage: int) -> tuple[bool, str]:
    try:
        self.ensure_leverage(symbol, int(leverage))
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _get_position(self: ToobitClient, symbol: str, direction: str | None = None) -> dict[str, Any] | None:
    d = normalize_direction(direction) if direction else ""
    for pos in self.get_open_positions(symbol):
        if d and pos.side != d:
            continue
        return _position_to_row(pos)
    return None


def _open_futures_position(
    self: ToobitClient,
    *,
    symbol: str,
    direction: str,
    quantity: float,
    price: float,
    order_type: str = "MARKET",
    margin_mode: str = MARGIN_ISOLATED,
    leverage: int = 1,
    take_profit: float,
    take_profit_2: float | None = None,
    stop_loss: float,
    client_order_id: str = "",
) -> TradeOpenResult:
    try:
        notional = (safe_float(quantity, 0.0) or 0.0) * (safe_float(price, 0.0) or 0.0)
        margin = notional / max(1, int(leverage))
        res = self.open_position_with_tp_sl(
            symbol=symbol,
            direction=normalize_direction(direction),
            margin_usdt=margin,
            leverage=int(leverage),
            tp_price=float(take_profit),
            sl_price=float(stop_loss),
            price=float(price) if price else None,
        )
        return TradeOpenResult(
            status=STATUS_OK if res.opened else STATUS_FAILED,
            exchange_order_id=res.order_id or "",
            symbol=res.symbol,
            direction=res.direction,
            entry=res.position.entry_price if res.position else res.entry_price,
            quantity=res.position.quantity if res.position else (res.quantity or 0.0),
            message=res.reason,
            error="" if res.opened else res.reason,
            raw={"opened": res.opened, "reason": res.reason, "raw": res.raw or {}, "requested_margin_usdt": res.requested_margin_usdt, "actual_margin_usdt": res.actual_margin_usdt},
        )
    except Exception as exc:
        return TradeOpenResult(status=STATUS_FAILED, symbol=symbol, direction=direction, entry=price, quantity=quantity, error=str(exc), raw={"exception": str(exc)})


def _close_position(self: ToobitClient, symbol: str, direction: str, *, quantity: float, price: float | None = None) -> TradeCloseResult:
    """Best-effort market close. Verify by reading open positions after the close request."""
    symbol = normalize_symbol(symbol)
    direction = normalize_direction(direction)
    qty = safe_float(quantity, 0.0) or 0.0
    mark = safe_float(price, 0.0) or 0.0
    if mark <= 0:
        try:
            mark = float(self.get_mark_price(symbol))
        except Exception:
            mark = 0.0
    side = "SELL_CLOSE" if direction == DIRECTION_LONG else "BUY_CLOSE"
    raw: Any = None
    error = ""
    try:
        params = {"symbol": symbol, "side": side, "type": "MARKET", "priceType": "MARKET", "quantity": qty}
        raw = self._request("POST", self.path_order, params=params, signed=True)
        # Give Toobit a moment to reflect the close.
        time.sleep(2)
        still_open = self.get_position(symbol, direction)
        confirmed = still_open is None
        return TradeCloseResult(
            status=STATUS_OK if confirmed else STATUS_FAILED,
            symbol=symbol,
            direction=direction,
            close_price=mark,
            closed_quantity=qty,
            pnl_usdt=None,
            pnl_confirmed=False,
            close_confirmed=confirmed,
            message="close_order_sent" if confirmed else "close_order_sent_but_position_still_open",
            error="" if confirmed else "position_still_open_after_close_request",
            raw={"raw": raw},
        )
    except Exception as exc:
        error = str(exc)
        return TradeCloseResult(status=STATUS_FAILED, symbol=symbol, direction=direction, close_price=mark, closed_quantity=qty, close_confirmed=False, error=error, raw={"raw": raw})


# Monkey-patch compatibility methods onto the uploaded class.
ToobitClient.normalize_bot_symbol = _normalize_bot_symbol  # type: ignore[attr-defined]
ToobitClient._position_direction = _position_direction  # type: ignore[attr-defined]
ToobitClient._position_qty = _position_qty  # type: ignore[attr-defined]
ToobitClient.get_account_balance = _get_account_balance  # type: ignore[attr-defined]
ToobitClient.validate_quantity = _validate_quantity  # type: ignore[attr-defined]
ToobitClient.verify_leverage = _verify_leverage  # type: ignore[attr-defined]
ToobitClient.get_position = _get_position  # type: ignore[attr-defined]
ToobitClient.open_futures_position = _open_futures_position  # type: ignore[attr-defined]
ToobitClient.close_position = _close_position  # type: ignore[attr-defined]

__all__ = [
    "TOBIT_CLIENT_VERSION",
    "MARGIN_ISOLATED",
    "MARGIN_CROSS",
    "Direction",
    "HistoryPositionInfo",
    "OpenOrderInfo",
    "OpenOrderResult",
    "PositionInfo",
    "SymbolRules",
    "ToobitAPIError",
    "ToobitClient",
    "ToobitConfig",
    "get_client",
]
