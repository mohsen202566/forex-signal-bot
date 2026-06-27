from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from typing import Any, Literal
from urllib.parse import urlencode

import requests

Direction = Literal["LONG", "SHORT"]
_CLIENT: "ToobitClient | None" = None


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _env_int(names: tuple[str, ...], default: int) -> int:
    value = _env_first(*names, default=str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _env_float(names: tuple[str, ...], default: float) -> float:
    value = _env_first(*names, default=str(default))
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _env_decimal(names: tuple[str, ...], default: str) -> Decimal:
    value = _env_first(*names, default=default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(str(default))


@dataclass(frozen=True)
class ToobitConfig:
    api_key: str
    secret_key: str
    base_url: str
    recv_window: int = 5000
    timeout_seconds: int = 12
    verify_after_error_seconds: int = 70
    margin_tolerance_pct: float = 1.0

    @classmethod
    def from_env(cls) -> "ToobitConfig":
        api_key = _env_first("TOOBIT_API_KEY", "TOBIT_API_KEY")
        secret_key = _env_first("TOOBIT_SECRET_KEY", "TOBIT_SECRET_KEY")
        base_url = _env_first("TOOBIT_BASE_URL", "TOBIT_BASE_URL", default="https://api.toobit.com").rstrip("/")
        if not api_key:
            raise RuntimeError("TOOBIT_API_KEY یا TOBIT_API_KEY تنظیم نشده است.")
        if not secret_key:
            raise RuntimeError("TOOBIT_SECRET_KEY یا TOBIT_SECRET_KEY تنظیم نشده است.")
        return cls(
            api_key=api_key,
            secret_key=secret_key,
            base_url=base_url,
            recv_window=_env_int(("TOOBIT_RECV_WINDOW", "TOBIT_RECV_WINDOW"), 5000),
            timeout_seconds=_env_int(("TOOBIT_TIMEOUT_SECONDS", "TOBIT_TIMEOUT_SECONDS"), 12),
            verify_after_error_seconds=_env_int(("TOOBIT_VERIFY_AFTER_ERROR_SECONDS", "TOBIT_VERIFY_AFTER_ERROR_SECONDS"), 70),
            margin_tolerance_pct=_env_float(("TOOBIT_MARGIN_TOLERANCE_PCT", "TOBIT_MARGIN_TOLERANCE_PCT"), 1.0),
        )


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    quantity_step: Decimal
    price_tick: Decimal
    min_quantity: Decimal
    min_notional: Decimal


@dataclass(frozen=True)
class PositionInfo:
    symbol: str
    side: Direction
    quantity: float
    entry_price: float
    unrealized_pnl: float
    raw: dict[str, Any]


@dataclass(frozen=True)
class OpenOrderInfo:
    symbol: str
    side: Direction | None
    order_id: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class OpenOrderResult:
    symbol: str
    direction: Direction
    requested_margin_usdt: float
    actual_margin_usdt: float
    leverage: int
    quantity: float | None
    entry_price: float
    tp_price: float
    sl_price: float
    opened: bool
    order_id: str | None
    position: PositionInfo | None
    reason: str
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class HistoryPositionInfo:
    symbol: str
    side: Direction | None
    realized_pnl: float
    open_time_ms: int | None
    close_time_ms: int | None
    raw: dict[str, Any]


class ToobitClient:
    def __init__(self, config: ToobitConfig | None = None, session: requests.Session | None = None) -> None:
        self.config = config or ToobitConfig.from_env()
        self.session = session or requests.Session()
        self.path_balance = _env_first("TOOBIT_PATH_BALANCE", "TOBIT_PATH_BALANCE", default="/api/v1/futures/balance")
        self.path_positions = _env_first("TOOBIT_PATH_POSITIONS", "TOBIT_PATH_POSITIONS", default="/api/v1/futures/positions")
        self.path_open_orders = _env_first("TOOBIT_PATH_OPEN_ORDERS", "TOBIT_PATH_OPEN_ORDERS", default="/api/v1/futures/openOrders")
        self.path_margin_mode = _env_first("TOOBIT_PATH_MARGIN_MODE", "TOBIT_PATH_MARGIN_MODE", default="/api/v1/futures/marginType")
        self.path_leverage = _env_first("TOOBIT_PATH_LEVERAGE", "TOBIT_PATH_LEVERAGE", default="/api/v1/futures/leverage")
        self.path_position_settings = _env_first("TOOBIT_PATH_POSITION_SETTINGS", "TOBIT_PATH_POSITION_SETTINGS", default="/api/v1/futures/accountLeverage")
        self.path_order = _env_first("TOOBIT_PATH_ORDER", "TOBIT_PATH_ORDER", default="/api/v1/futures/order")
        self.path_mark_price = _env_first("TOOBIT_PATH_MARK_PRICE", "TOBIT_PATH_MARK_PRICE", default="/api/v1/futures/markPrice")
        self.path_exchange_info = _env_first("TOOBIT_PATH_EXCHANGE_INFO", "TOBIT_PATH_EXCHANGE_INFO", default="/api/v1/futures/exchangeInfo")
        self.path_history_positions = _env_first("TOOBIT_PATH_HISTORY_POSITIONS", "TOBIT_PATH_HISTORY_POSITIONS", default="/api/v1/futures/historyPositions")
        self.path_today_pnl = _env_first("TOOBIT_PATH_TODAY_PNL", "TOBIT_PATH_TODAY_PNL", default="/api/v1/futures/todayPnl")
        self.param_tp = _env_first("TOOBIT_PARAM_TP", "TOBIT_PARAM_TP", default="takeProfit")
        self.param_sl = _env_first("TOOBIT_PARAM_SL", "TOBIT_PARAM_SL", default="stopLoss")

    def get_wallet_margin_usdt(self) -> float:
        payload = self._request("GET", self.path_balance, signed=True)
        for item in _extract_dicts(payload):
            asset = str(item.get("asset") or item.get("coin") or item.get("currency") or "").upper()
            if asset and asset != "USDT":
                continue
            value = _first_decimal(item, "availableBalance", "availableMargin", "available", "free", "balance", "walletBalance", "marginBalance", "equity", "accountEquity")
            if value is not None and value >= 0:
                return float(value)
        raise RuntimeError("موجودی/مارجین USDT از پاسخ توبیت قابل خواندن نیست.")

    def get_open_positions(self, symbol: str | None = None) -> list[PositionInfo]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        payload = self._request("GET", self.path_positions, params=params, signed=True)
        positions: list[PositionInfo] = []
        for item in _extract_dicts(payload):
            parsed = self._parse_position(item)
            if parsed is None:
                continue
            if symbol and parsed.symbol != symbol.upper():
                continue
            positions.append(parsed)
        return positions

    def get_open_orders(self, symbol: str | None = None) -> list[OpenOrderInfo]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        payload = self._request("GET", self.path_open_orders, params=params, signed=True)
        orders: list[OpenOrderInfo] = []
        for item in _extract_dicts(payload):
            parsed = self._parse_open_order(item)
            if parsed is None:
                continue
            if symbol and parsed.symbol != symbol.upper():
                continue
            orders.append(parsed)
        return orders

    def has_open_position(self, symbol: str) -> bool:
        return bool(self.get_open_positions(symbol))

    def has_open_order(self, symbol: str) -> bool:
        return bool(self.get_open_orders(symbol))

    def ensure_no_open_order(self, symbol: str) -> None:
        orders = self.get_open_orders(symbol)
        if orders:
            ids = ", ".join(order.order_id or "unknown" for order in orders)
            raise RuntimeError(f"برای {symbol.upper()} سفارش باز وجود دارد و سفارش جدید بلاک شد: {ids}")

    def ensure_no_open_position(self, symbol: str) -> None:
        if self.get_open_positions(symbol):
            raise RuntimeError(f"برای {symbol.upper()} پوزیشن باز وجود دارد و سفارش جدید بلاک شد.")

    def ensure_isolated_margin(self, symbol: str) -> None:
        symbol = symbol.upper()
        params = {"symbol": symbol, "marginType": "ISOLATED"}
        try:
            self._request("POST", self.path_margin_mode, params=params, signed=True)
        except ToobitAPIError as exc:
            message = str(exc).lower()
            if "no need" not in message and "already" not in message and "isolated" not in message:
                raise
        verified = self._read_margin_mode(symbol)
        if verified != "isolated":
            raise RuntimeError(f"حالت مارجین {symbol} بعد از تنظیم تایید نشد. actual={verified!r}")

    def ensure_leverage(self, symbol: str, leverage: int) -> None:
        if leverage <= 0:
            raise ValueError("لوریج باید مثبت باشد.")
        symbol = symbol.upper()
        self._request("POST", self.path_leverage, params={"symbol": symbol, "leverage": int(leverage)}, signed=True)
        actual = self._read_leverage(symbol)
        if actual != int(leverage):
            raise RuntimeError(f"لوریج {symbol} تایید نشد. requested={leverage} actual={actual}")

    def prepare_symbol_for_trade(self, symbol: str, leverage: int) -> None:
        self.ensure_no_open_position(symbol)
        self.ensure_no_open_order(symbol)
        self.ensure_isolated_margin(symbol)
        self.ensure_leverage(symbol, leverage)

    def open_position_with_tp_sl(
        self,
        *,
        symbol: str,
        direction: Direction,
        margin_usdt: float,
        leverage: int,
        tp_price: float,
        sl_price: float,
        price: float | None = None,
    ) -> OpenOrderResult:
        symbol = symbol.upper()
        _validate_direction(direction)
        if margin_usdt <= 0:
            raise ValueError("مارجین معامله باید مثبت باشد.")
        if leverage <= 0:
            raise ValueError("لوریج باید مثبت باشد.")
        self.prepare_symbol_for_trade(symbol, leverage)
        entry_price = Decimal(str(price if price is not None else self.get_mark_price(symbol)))
        rules = self.get_symbol_rules(symbol)
        tp_decimal = _round_price_to_tick(Decimal(str(tp_price)), rules.price_tick, direction, is_tp=True)
        sl_decimal = _round_price_to_tick(Decimal(str(sl_price)), rules.price_tick, direction, is_tp=False)
        self._validate_prices(direction, tp_price=tp_decimal, sl_price=sl_decimal, reference_price=entry_price)
        notional = Decimal(str(margin_usdt)) * Decimal(str(leverage))
        actual_margin = notional / Decimal(str(leverage))
        self._validate_actual_margin(requested_margin=Decimal(str(margin_usdt)), actual_margin=actual_margin)
        side = "BUY_OPEN" if direction == "LONG" else "SELL_OPEN"
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "priceType": "MARKET",
            "valueQuantity": _decimal_to_api(notional),
            "newClientOrderId": f"forex1h_{int(time.time() * 1000)}",
            self.param_tp: _decimal_to_api(tp_decimal),
            self.param_sl: _decimal_to_api(sl_decimal),
            "tpTriggerBy": "CONTRACT_PRICE",
            "slTriggerBy": "CONTRACT_PRICE",
            "tpOrderType": "MARKET",
            "slOrderType": "MARKET",
        }
        try:
            raw = self._request("POST", self.path_order, params=params, signed=True)
        except Exception as exc:
            position = self._verify_position_after_order(symbol, direction)
            return OpenOrderResult(
                symbol=symbol,
                direction=direction,
                requested_margin_usdt=float(margin_usdt),
                actual_margin_usdt=float(actual_margin),
                leverage=int(leverage),
                quantity=None,
                entry_price=float(entry_price),
                tp_price=float(tp_decimal),
                sl_price=float(sl_decimal),
                opened=position is not None,
                order_id=None,
                position=position,
                reason=(
                    f"سفارش خطا داد ولی بعد از تایید {self.config.verify_after_error_seconds} ثانیه‌ای پوزیشن باز پیدا شد: {exc}"
                    if position is not None
                    else f"سفارش خطا داد و بعد از تایید {self.config.verify_after_error_seconds} ثانیه‌ای پوزیشن باز نشد: {exc}"
                ),
                raw=None,
            )
        position = self._verify_position_after_order(symbol, direction)
        return OpenOrderResult(
            symbol=symbol,
            direction=direction,
            requested_margin_usdt=float(margin_usdt),
            actual_margin_usdt=float(actual_margin),
            leverage=int(leverage),
            quantity=position.quantity if position else None,
            entry_price=float(entry_price),
            tp_price=float(tp_decimal),
            sl_price=float(sl_decimal),
            opened=position is not None,
            order_id=_extract_order_id(raw),
            position=position,
            reason=f"سفارش ارسال شد و بعد از تایید {self.config.verify_after_error_seconds} ثانیه‌ای وضعیت پوزیشن بررسی شد.",
            raw=raw if isinstance(raw, dict) else {"response": raw},
        )

    def get_mark_price(self, symbol: str) -> float:
        payload = self._request("GET", self.path_mark_price, params={"symbol": symbol.upper()}, signed=False)
        for item in _extract_dicts(payload):
            value = _first_decimal(item, "markPrice", "price", "lastPrice", "indexPrice")
            if value is not None and value > 0:
                return float(value)
        raise RuntimeError(f"قیمت مارک برای {symbol} قابل خواندن نیست.")

    def get_symbol_rules(self, symbol: str) -> SymbolRules:
        symbol = symbol.upper()
        fallback_qty = _env_decimal(("TOOBIT_DEFAULT_QUANTITY_STEP", "TOBIT_DEFAULT_QUANTITY_STEP"), "0.0001")
        fallback_tick = _env_decimal(("TOOBIT_DEFAULT_PRICE_TICK", "TOBIT_DEFAULT_PRICE_TICK"), "0.0001")
        fallback_min_qty = _env_decimal(("TOOBIT_DEFAULT_MIN_QTY", "TOBIT_DEFAULT_MIN_QTY"), "0")
        fallback_min_notional = _env_decimal(("TOOBIT_DEFAULT_MIN_NOTIONAL", "TOBIT_DEFAULT_MIN_NOTIONAL"), "0")
        try:
            payload = self._request("GET", self.path_exchange_info, params={"symbol": symbol}, signed=False)
        except Exception:
            return SymbolRules(symbol, fallback_qty, fallback_tick, fallback_min_qty, fallback_min_notional)
        qty_step = fallback_qty
        price_tick = fallback_tick
        min_qty = fallback_min_qty
        min_notional = fallback_min_notional
        for item in _extract_dicts(payload):
            item_symbol = _symbol_from_item(item)
            if item_symbol and item_symbol != symbol:
                continue
            qty_step = _first_decimal(item, "stepSize", "quantityStep", "qtyStep", "lotSize") or qty_step
            price_tick = _first_decimal(item, "tickSize", "priceTick", "pricePrecisionStep") or price_tick
            min_qty = _first_decimal(item, "minQty", "minQuantity") or min_qty
            min_notional = _first_decimal(item, "minNotional", "minOrderValue") or min_notional
        return SymbolRules(symbol, qty_step if qty_step > 0 else fallback_qty, price_tick if price_tick > 0 else fallback_tick, min_qty if min_qty > 0 else fallback_min_qty, min_notional if min_notional > 0 else fallback_min_notional)

    def get_today_real_pnl(self) -> float:
        payload = self._request("GET", self.path_today_pnl, signed=True)
        for item in _extract_dicts(payload):
            value = _first_decimal(item, "dayProfit", "profit", "pnl", "realizedPnL", "realizedPnl")
            if value is not None:
                return float(value)
        raise RuntimeError("سود/ضرر امروز از توبیت قابل خواندن نیست.")

    def get_history_positions(self, *, symbol: str | None = None, start_ms: int | None = None, end_ms: int | None = None, limit: int = 50) -> list[HistoryPositionInfo]:
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 1000))}
        if symbol:
            params["symbol"] = symbol.upper()
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        payload = self._request("GET", self.path_history_positions, params=params, signed=True)
        positions: list[HistoryPositionInfo] = []
        for item in _extract_dicts(payload):
            parsed = self._parse_history_position(item)
            if parsed is None:
                continue
            if symbol and parsed.symbol != symbol.upper():
                continue
            positions.append(parsed)
        return positions

    def find_realized_pnl(self, *, symbol: str, side: Direction, start_ms: int, end_ms: int) -> float | None:
        positions = self.get_history_positions(symbol=symbol, start_ms=start_ms, end_ms=end_ms, limit=20)
        matches = [item for item in positions if item.side in (None, side)]
        if not matches:
            return None
        matches.sort(key=lambda item: item.close_time_ms or 0, reverse=True)
        return matches[0].realized_pnl

    def _verify_position_after_order(self, symbol: str, direction: Direction) -> PositionInfo | None:
        wait_seconds = max(0.0, float(self.config.verify_after_error_seconds))
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        return self._verify_position(symbol, direction)

    def _verify_position(self, symbol: str, direction: Direction) -> PositionInfo | None:
        for position in self.get_open_positions(symbol):
            if position.side == direction and position.quantity > 0:
                return position
        return None

    def _read_margin_mode(self, symbol: str) -> str:
        payload = self._request("GET", self.path_position_settings, params={"symbol": symbol.upper()}, signed=True)
        for item in _extract_dicts(payload):
            item_symbol = _symbol_from_item(item)
            if item_symbol and item_symbol != symbol.upper():
                continue
            raw_mode = item.get("marginType", item.get("marginMode", None))
            if raw_mode is not None and str(raw_mode).strip():
                mode = str(raw_mode).strip().lower()
                if mode in {"isolated", "isolate", "true", "1"}:
                    return "isolated"
                if mode in {"cross", "crossed", "false", "0"}:
                    return "cross"
        raise RuntimeError(f"وضعیت margin mode برای {symbol.upper()} از صرافی قابل خواندن نیست.")

    def _read_leverage(self, symbol: str) -> int:
        payload = self._request("GET", self.path_position_settings, params={"symbol": symbol.upper()}, signed=True)
        for item in _extract_dicts(payload):
            item_symbol = _symbol_from_item(item)
            if item_symbol and item_symbol != symbol.upper():
                continue
            value = _first_decimal(item, "leverage", "isolatedLeverage", "crossLeverage")
            if value is not None and value > 0:
                return int(value)
        raise RuntimeError(f"لوریج {symbol.upper()} از صرافی قابل خواندن نیست.")

    def _parse_position(self, item: dict[str, Any]) -> PositionInfo | None:
        symbol = _symbol_from_item(item)
        if not symbol:
            return None
        quantity = _first_decimal(item, "position", "positionAmt", "positionAmount", "size", "quantity", "qty")
        if quantity is None or quantity == 0:
            return None
        raw_side = str(item.get("side") or item.get("positionSide") or item.get("direction") or "").upper()
        if raw_side in {"LONG", "BUY", "BUY_OPEN"}:
            side: Direction = "LONG"
        elif raw_side in {"SHORT", "SELL", "SELL_OPEN"}:
            side = "SHORT"
        else:
            side = "LONG" if quantity > 0 else "SHORT"
        entry = _first_decimal(item, "entryPrice", "avgPrice", "averagePrice", "openAvgPrice") or Decimal("0")
        pnl = _first_decimal(item, "unrealizedPnL", "unrealizedPnl", "unrealizedProfit", "pnl") or Decimal("0")
        return PositionInfo(symbol=symbol, side=side, quantity=float(abs(quantity)), entry_price=float(entry), unrealized_pnl=float(pnl), raw=item)

    def _parse_open_order(self, item: dict[str, Any]) -> OpenOrderInfo | None:
        symbol = _symbol_from_item(item)
        if not symbol:
            return None
        status = str(item.get("status") or item.get("orderStatus") or "").upper()
        if status in {"FILLED", "ORDER_FILLED", "CANCELED", "CANCELLED", "ORDER_CANCELED", "REJECTED", "EXPIRED"}:
            return None
        raw_side = str(item.get("side") or item.get("positionSide") or "").upper()
        side: Direction | None
        if raw_side in {"BUY", "LONG", "BUY_OPEN"}:
            side = "LONG"
        elif raw_side in {"SELL", "SHORT", "SELL_OPEN"}:
            side = "SHORT"
        else:
            side = None
        return OpenOrderInfo(symbol=symbol, side=side, order_id=_extract_order_id(item), raw=item)

    def _parse_history_position(self, item: dict[str, Any]) -> HistoryPositionInfo | None:
        symbol = _symbol_from_item(item)
        if not symbol:
            return None
        pnl = _first_decimal(item, "realizedPnL", "realizedPnl", "realizedPnlWithoutFee", "pnl")
        if pnl is None:
            return None
        raw_side = str(item.get("side") or "").upper()
        side: Direction | None = "LONG" if raw_side == "LONG" else "SHORT" if raw_side == "SHORT" else None
        return HistoryPositionInfo(symbol=symbol, side=side, realized_pnl=float(pnl), open_time_ms=_int_or_none(item.get("openTime")), close_time_ms=_int_or_none(item.get("closeTime")), raw=item)

    def _validate_prices(self, direction: Direction, *, tp_price: Decimal, sl_price: Decimal, reference_price: Decimal) -> None:
        if tp_price <= 0 or sl_price <= 0 or reference_price <= 0:
            raise ValueError("قیمت ورود، TP و SL باید مثبت باشند.")
        if direction == "LONG" and not (tp_price > reference_price > sl_price):
            raise ValueError("برای LONG باید TP بالاتر از ورود و SL پایین‌تر از ورود باشد.")
        if direction == "SHORT" and not (tp_price < reference_price < sl_price):
            raise ValueError("برای SHORT باید TP پایین‌تر از ورود و SL بالاتر از ورود باشد.")

    def _validate_actual_margin(self, *, requested_margin: Decimal, actual_margin: Decimal) -> None:
        if requested_margin <= 0 or actual_margin <= 0:
            raise ValueError("مارجین واقعی/درخواستی باید مثبت باشد.")
        diff_pct = abs(requested_margin - actual_margin) / requested_margin * Decimal("100")
        if diff_pct > Decimal(str(self.config.margin_tolerance_pct)):
            raise ValueError(f"مارجین واقعی با مقدار تنظیم‌شده نمی‌خواند: requested={requested_margin}, actual={actual_margin}, diff={diff_pct:.4f}%")

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, signed: bool) -> Any:
        params = dict(params or {})
        headers = {"X-BB-APIKEY": self.config.api_key} if signed else {}
        if signed:
            params.setdefault("recvWindow", self.config.recv_window)
            params.setdefault("timestamp", int(time.time() * 1000))
            query = urlencode(params, doseq=True)
            params["signature"] = hmac.new(self.config.secret_key.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"{self.config.base_url}{path}"
        if method.upper() == "GET":
            response = self.session.get(url, params=params, headers=headers, timeout=self.config.timeout_seconds)
        elif method.upper() == "POST":
            response = self.session.post(url, data=params, headers=headers, timeout=self.config.timeout_seconds)
        else:
            raise ValueError(f"HTTP method پشتیبانی نمی‌شود: {method}")
        if response.status_code >= 400:
            raise ToobitAPIError(f"HTTP {response.status_code}: {response.text[:500]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ToobitAPIError("پاسخ توبیت JSON معتبر نیست.") from exc
        self._raise_if_api_error(payload)
        return payload

    @staticmethod
    def _raise_if_api_error(payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        code = payload.get("code") or payload.get("retCode") or payload.get("status")
        success_values = {None, 0, 200, "0", "200", "OK", "ok", "success", "SUCCESS", True}
        if code in success_values:
            return
        message = payload.get("msg") or payload.get("message") or payload.get("error") or payload
        raise ToobitAPIError(str(message))


def get_client(config: ToobitConfig | None = None, session: requests.Session | None = None) -> ToobitClient:
    global _CLIENT
    if config is not None or session is not None:
        return ToobitClient(config=config, session=session)
    if _CLIENT is None:
        _CLIENT = ToobitClient()
    return _CLIENT


class ToobitAPIError(RuntimeError):
    pass


def _validate_direction(direction: str) -> None:
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction باید LONG یا SHORT باشد.")


def _symbol_from_item(item: dict[str, Any]) -> str:
    return str(item.get("symbol") or item.get("symbolId") or item.get("contractCode") or "").upper()


def _extract_dicts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    result: list[dict[str, Any]] = []
    for key in ("data", "result", "balances", "positions", "rows", "list"):
        value = payload.get(key)
        if isinstance(value, dict):
            result.append(value)
            result.extend(_extract_dicts(value))
        elif isinstance(value, list):
            result.extend(item for item in value if isinstance(item, dict))
    if not result:
        result.append(payload)
    return result


def _first_decimal(item: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        if key not in item or item[key] in (None, ""):
            continue
        try:
            return Decimal(str(item[key]))
        except (InvalidOperation, ValueError):
            continue
    return None


def _round_price_to_tick(value: Decimal, tick: Decimal, direction: Direction, *, is_tp: bool) -> Decimal:
    if tick <= 0:
        return value
    units = value / tick
    if direction == "LONG":
        rounding = ROUND_DOWN if is_tp else ROUND_UP
    else:
        rounding = ROUND_UP if is_tp else ROUND_DOWN
    rounded = units.to_integral_value(rounding=rounding) * tick
    if rounded <= 0:
        rounded = units.to_integral_value(rounding=ROUND_HALF_UP) * tick
    return rounded


def _decimal_to_api(value: float | Decimal) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _extract_order_id(payload: Any) -> str | None:
    for item in _extract_dicts(payload):
        for key in ("orderId", "order_id", "id", "clientOrderId"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
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

# -----------------------------------------------------------------------------
# Compatibility layer for older Level-4 bot modules.
# The low-level Toobit client above is self-contained; older bot files import
# constants and helper methods from tobit_client.py, so they are added here.
# -----------------------------------------------------------------------------
from typing import Mapping
from decimal import ROUND_DOWN

from constants import (
    DIRECTION_LONG,
    DIRECTION_SHORT,
    STATUS_FAILED,
    STATUS_OK,
    SYSTEM_VERSION,
)
from models import TradeCloseResult, TradeOpenResult
from utils import normalize_direction, normalize_symbol, safe_float, safe_str

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
    reverse = {
        "1000PEPEUSDT": "PEPEUSDT",
        "1000BONKUSDT": "BONKUSDT",
        "1000SHIBUSDT": "SHIBUSDT",
        "1000FLOKIUSDT": "FLOKIUSDT",
    }
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
        return {
            "status": STATUS_OK,
            "asset": asset.upper(),
            "balance": available,
            "available": available,
            "credentials_loaded": True,
        }
    except Exception as exc:
        return {
            "status": STATUS_FAILED,
            "asset": asset.upper(),
            "balance": None,
            "available": None,
            "credentials_loaded": False,
            "error": str(exc),
        }


def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _validate_quantity(
    self: ToobitClient,
    symbol: str,
    quantity_estimate: Any,
    entry_price: Any,
) -> tuple[bool, float, str, SymbolRules]:
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
            raw={
                "opened": res.opened,
                "reason": res.reason,
                "raw": res.raw or {},
                "requested_margin_usdt": res.requested_margin_usdt,
                "actual_margin_usdt": res.actual_margin_usdt,
            },
        )
    except Exception as exc:
        return TradeOpenResult(
            status=STATUS_FAILED,
            symbol=symbol,
            direction=direction,
            entry=price,
            quantity=quantity,
            error=str(exc),
            raw={"exception": str(exc)},
        )


def _close_position(
    self: ToobitClient,
    symbol: str,
    direction: str,
    *,
    quantity: float,
    price: float | None = None,
) -> TradeCloseResult:
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
        return TradeCloseResult(
            status=STATUS_FAILED,
            symbol=symbol,
            direction=direction,
            close_price=mark,
            closed_quantity=qty,
            close_confirmed=False,
            error=str(exc),
            raw={"raw": raw},
        )


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
