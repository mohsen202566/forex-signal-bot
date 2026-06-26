"""کلاینت‌های OKX و Adapter توبیت برای ربات ۱۵ تا ۳۰ دقیقه‌ای.

قفل معماری:
- OKX منبع تحلیل، کندل، قیمت لحظه‌ای و مانیتورینگ سیگنال عادی است.
- Toobit فقط برای REAL استفاده می‌شود: پنل حساب، باز کردن پوزیشن واقعی،
  تأیید پوزیشن واقعی و نتیجه واقعی.
- این فایل تحلیل بازار انجام نمی‌دهد و سفارش مستقیم مستقل از Trade Manager نمی‌سازد.
- پوزیشن واقعی باید با TP/SL در یک درخواست/فرآیند واحد به tobit_client.py سپرده شود.
"""
from __future__ import annotations

import importlib
import inspect
import os
from dataclasses import asdict, is_dataclass
from typing import Any

import requests


class OKXClient:
    """کلاینت عمومی OKX برای دیتا و سیگنال عادی.

    این کلاینت هیچ سفارش واقعی ارسال نمی‌کند.
    """

    def __init__(self, base_url: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or os.getenv("OKX_BASE_URL", "https://www.okx.com")).rstrip("/")
        self.timeout = timeout or int(os.getenv("OKX_TIMEOUT_SECONDS", "10"))
        self.session = requests.Session()

    @staticmethod
    def _inst_id(symbol: str) -> str:
        symbol = symbol.upper().strip()
        if "-" in symbol:
            return symbol
        if symbol.endswith("USDT"):
            return symbol.replace("USDT", "-USDT-SWAP")
        return symbol

    def get_candles(self, symbol: str, bar: str = "15m", limit: int = 120) -> list[dict[str, float]]:
        """برگرداندن کندل‌ها به ترتیب قدیمی → جدید."""
        url = f"{self.base_url}/api/v5/market/candles"
        params = {"instId": self._inst_id(symbol), "bar": bar, "limit": str(int(limit))}
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") not in (None, "0", 0):
            raise RuntimeError(f"OKX candle error: {payload}")
        data = payload.get("data", [])
        candles: list[dict[str, float]] = []
        for row in reversed(data):
            # OKX: ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm
            candles.append(
                {
                    "ts": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        return candles

    def get_last_price(self, symbol: str) -> float:
        url = f"{self.base_url}/api/v5/market/ticker"
        r = self.session.get(url, params={"instId": self._inst_id(symbol)}, timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") not in (None, "0", 0):
            raise RuntimeError(f"OKX ticker error: {payload}")
        return float(payload["data"][0]["last"])

    def get_open_interest_series(self, symbol: str, period: str = "15m", limit: int = 20) -> list[float]:
        """OI عمومی OKX.

        اگر endpoint یا نماد پشتیبانی نشود، برای اینکه ربات نخوابد لیست خالی برمی‌گردد.
        StrategyEngine برای نبود OI جریمه/فرض خنثی دارد.
        """
        inst_id = self._inst_id(symbol)
        url = f"{self.base_url}/api/v5/rubik/stat/contracts/open-interest-history"
        params = {"instId": inst_id, "period": period, "limit": str(int(limit))}
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            payload = r.json()
            if payload.get("code") not in (None, "0", 0):
                return []
            values: list[float] = []
            for row in reversed(payload.get("data", [])):
                # ساختار OKX ممکن است list یا dict باشد؛ آخرین مقدار عددی را می‌گیریم.
                if isinstance(row, dict):
                    for key in ("oi", "openInterest", "value"):
                        if key in row:
                            values.append(float(row[key]))
                            break
                elif isinstance(row, list):
                    for item in reversed(row):
                        try:
                            values.append(float(item))
                            break
                        except (TypeError, ValueError):
                            continue
            return values[-int(limit):]
        except Exception:
            return []


class ToobitAdapter:
    """Adapter نازک برای فایل سالم `tobit_client.py`.

    هدف این کلاس هماهنگ کردن امضای فایل‌های ربات جدید با فایل تست‌شده توبیت است.
    اگر فایل توبیت متدهای بیشتری داشته باشد، از همان‌ها استفاده می‌شود؛ اگر نداشته باشد،
    این Adapter تا جای امن ممکن fallback می‌دهد و نتیجه جعلی نمی‌سازد.
    """

    def __init__(self) -> None:
        self.connected = False
        self.legacy: Any = None
        self.load_error: str | None = None
        try:
            module = importlib.import_module("tobit_client")
            if hasattr(module, "get_client") and callable(module.get_client):
                self.legacy = module.get_client()
            elif hasattr(module, "ToobitClient"):
                self.legacy = module.ToobitClient()
            else:
                self.legacy = module
            self.connected = True
        except Exception as exc:
            self.connected = False
            self.load_error = str(exc)

    def account_panel(self) -> dict[str, Any]:
        """داده پنل حساب از Toobit واقعی، نه عدد دستی."""
        if not self.connected or not self.legacy:
            return {"connected": False, "error": self.load_error or "TOBIT_CLIENT_NOT_CONNECTED"}

        for name in ("account_panel", "get_account_panel", "get_balance_panel"):
            fn = getattr(self.legacy, name, None)
            if callable(fn):
                out = _safe_dict(fn())
                out["connected"] = True
                return out

        out: dict[str, Any] = {"connected": True}
        try:
            if hasattr(self.legacy, "get_wallet_margin_usdt"):
                wallet = float(self.legacy.get_wallet_margin_usdt())
                out.update({"balance": wallet, "free_margin": wallet, "wallet_margin_usdt": wallet})
        except Exception as exc:
            out["balance_error"] = str(exc)
        try:
            if hasattr(self.legacy, "get_open_positions"):
                positions = self.legacy.get_open_positions()
                out["open_positions"] = len(positions or [])
        except Exception as exc:
            out["positions_error"] = str(exc)
        return out

    def open_position_with_tp_sl(
        self,
        *,
        symbol: str,
        side: str,
        margin_usdt: float,
        leverage: int,
        entry: float,
        tp: float,
        sl: float,
    ) -> dict[str, Any]:
        """ارسال REAL با TP/SL همزمان.

        خروجی همیشه dict سازگار با bot.py است:
        - ok=True یعنی سفارش/پوزیشن طبق کلاینت توبیت تأیید شده است.
        - ok=False یعنی اسلات باید آزاد شود.
        """
        if not self.connected or not self.legacy:
            return {"ok": False, "error": self.load_error or "TOBIT_CLIENT_NOT_CONNECTED"}

        side = side.upper().strip()
        if side not in {"LONG", "SHORT"}:
            return {"ok": False, "error": f"INVALID_SIDE:{side}"}

        fn = getattr(self.legacy, "open_position_with_tp_sl", None)
        if callable(fn):
            try:
                result = self._call_open_position_with_tp_sl(
                    fn=fn,
                    symbol=symbol,
                    side=side,
                    margin_usdt=margin_usdt,
                    leverage=leverage,
                    entry=entry,
                    tp=tp,
                    sl=sl,
                )
                return self._normalize_open_result(result)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        for name in ("place_order_with_tp_sl", "open_futures_position"):
            fn = getattr(self.legacy, name, None)
            if callable(fn):
                try:
                    result = fn(symbol=symbol, side=side, margin_usdt=margin_usdt, leverage=leverage, entry=entry, tp=tp, sl=sl)
                    return self._normalize_open_result(result)
                except Exception as exc:
                    return {"ok": False, "error": str(exc)}

        return {"ok": False, "error": "LEGACY_METHOD_NOT_FOUND"}

    @staticmethod
    def _call_open_position_with_tp_sl(
        *,
        fn: Any,
        symbol: str,
        side: str,
        margin_usdt: float,
        leverage: int,
        entry: float,
        tp: float,
        sl: float,
    ) -> Any:
        params = inspect.signature(fn).parameters
        if "direction" in params or "tp_price" in params or "sl_price" in params:
            return fn(
                symbol=symbol,
                direction=side,
                margin_usdt=margin_usdt,
                leverage=leverage,
                tp_price=tp,
                sl_price=sl,
                price=entry,
            )
        return fn(symbol=symbol, side=side, margin_usdt=margin_usdt, leverage=leverage, entry=entry, tp=tp, sl=sl)

    @staticmethod
    def _normalize_open_result(result: Any) -> dict[str, Any]:
        data = _to_plain_dict(result)
        if not data:
            return {"ok": bool(result), "raw": result}

        opened = bool(data.get("opened", data.get("ok", data.get("success", False))))
        out = {
            "ok": opened,
            "opened": opened,
            "order_id": data.get("order_id") or data.get("orderId") or data.get("id"),
            "position_id": _extract_position_id(data),
            "reason": data.get("reason"),
            "raw": data,
        }
        if not opened:
            out["error"] = data.get("error") or data.get("reason") or "POSITION_NOT_OPENED"
        for key in ("entry_price", "tp_price", "sl_price", "quantity", "actual_margin_usdt", "requested_margin_usdt"):
            if key in data:
                out[key] = data[key]
        return out

    def position_exists(self, symbol: str, side: str | None = None) -> dict[str, Any]:
        if not self.connected or not self.legacy:
            return {"exists": False, "error": self.load_error or "TOBIT_CLIENT_NOT_CONNECTED"}

        symbol = symbol.upper().strip()
        side = side.upper().strip() if side else None

        if hasattr(self.legacy, "get_open_positions") and callable(self.legacy.get_open_positions):
            try:
                positions = self.legacy.get_open_positions(symbol)
                for pos in positions or []:
                    data = _to_plain_dict(pos)
                    pos_side = str(data.get("side") or data.get("direction") or "").upper()
                    if side and pos_side and pos_side != side:
                        continue
                    return {"exists": True, "position_id": _extract_position_id(data), "raw": data}
                return {"exists": False}
            except Exception as exc:
                return {"exists": False, "error": str(exc)}

        for name in ("position_exists", "get_open_position", "get_position", "has_open_position"):
            fn = getattr(self.legacy, name, None)
            if callable(fn):
                try:
                    try:
                        result = fn(symbol=symbol, side=side) if side else fn(symbol=symbol)
                    except TypeError:
                        result = fn(symbol=symbol)
                    data = _to_plain_dict(result)
                    if data:
                        exists = bool(data.get("exists", data.get("opened", data.get("quantity", True))))
                        return {"exists": exists, "position_id": _extract_position_id(data), "raw": data}
                    return {"exists": bool(result), "raw": result}
                except Exception as exc:
                    return {"exists": False, "error": str(exc)}

        return {"exists": False, "error": "LEGACY_METHOD_NOT_FOUND"}

    def closed_result(self, symbol: str, side: str, position_id: str | None = None) -> dict[str, Any]:
        """نتیجه REAL فقط از Toobit.

        اگر فایل توبیت متد history/result نداشته باشد، نتیجه جعلی تولید نمی‌کنیم؛
        در این حالت مانیتور باز می‌ماند تا بعداً متد history به tobit_client.py اضافه شود.
        """
        if not self.connected or not self.legacy:
            return {"closed": False, "error": self.load_error or "TOBIT_CLIENT_NOT_CONNECTED"}

        for name in ("closed_result", "get_closed_result", "check_position_result", "get_position_result"):
            fn = getattr(self.legacy, name, None)
            if callable(fn):
                try:
                    try:
                        result = fn(symbol=symbol, side=side, position_id=position_id)
                    except TypeError:
                        result = fn(symbol=symbol, side=side)
                    data = _to_plain_dict(result)
                    if data:
                        data.setdefault("closed", bool(data.get("result") in {"TP", "SL"}))
                        return data
                    return {"closed": bool(result), "raw": result}
                except Exception as exc:
                    return {"closed": False, "error": str(exc)}

        return {"closed": False, "error": "CLOSED_RESULT_METHOD_NOT_FOUND"}


def _safe_dict(value: Any) -> dict[str, Any]:
    data = _to_plain_dict(value)
    return data if data else {"value": value}


def _to_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            out = value.to_dict()
            if isinstance(out, dict):
                return out
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _extract_position_id(data: dict[str, Any]) -> str | None:
    for key in ("position_id", "positionId", "id", "order_id", "orderId"):
        if data.get(key) not in (None, ""):
            return str(data[key])
    pos = data.get("position")
    if pos is not None:
        nested = _to_plain_dict(pos)
        for key in ("position_id", "positionId", "id"):
            if nested.get(key) not in (None, ""):
                return str(nested[key])
    return None


__all__ = ["OKXClient", "ToobitAdapter"]
