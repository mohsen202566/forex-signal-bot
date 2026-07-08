"""اعتبارسنجی ۳۵ نماد مشترک OKX/Toobit؛ همه چیز در ریشه پروژه است."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config
from okx_client import OKXClient
from toobit_client import ToobitClient
from utils import normalize_symbol, to_okx_inst_id, toobit_symbol_candidates


@dataclass(slots=True)
class SymbolValidationReport:
    configured: list[str]
    valid_common: list[str]
    missing_okx: list[str] = field(default_factory=list)
    missing_toobit: list[str] = field(default_factory=list)
    missing_both: list[str] = field(default_factory=list)
    okx_count: int = 0
    toobit_count: int = 0
    required_count: int = config.REQUIRED_COMMON_SYMBOL_COUNT

    @property
    def ok(self) -> bool:
        return len(self.valid_common) >= int(self.required_count) and not self.missing_okx and not self.missing_toobit and not self.missing_both

    def short_text(self) -> str:
        lines = [
            f"Configured: {len(self.configured)}",
            f"Common OKX+Toobit: {len(self.valid_common)}/{self.required_count}",
            f"OKX instruments seen: {self.okx_count}",
            f"Toobit symbols seen: {self.toobit_count}",
        ]
        if self.valid_common:
            lines.append("Valid: " + ", ".join(self.valid_common))
        if self.missing_okx:
            lines.append("Missing OKX: " + ", ".join(self.missing_okx))
        if self.missing_toobit:
            lines.append("Missing Toobit: " + ", ".join(self.missing_toobit))
        if self.missing_both:
            lines.append("Missing Both: " + ", ".join(self.missing_both))
        return "\n".join(lines)


def _okx_symbol_from_inst_id(inst_id: str) -> str:
    # BTC-USDT-SWAP -> BTCUSDT
    parts = str(inst_id or "").upper().split("-")
    if len(parts) >= 2 and parts[1] == "USDT":
        return f"{parts[0]}USDT"
    return normalize_symbol(inst_id)


def load_okx_symbols(okx: OKXClient) -> set[str]:
    instruments = okx.get_instruments()
    out: set[str] = set()
    for item in instruments:
        inst_id = str(item.get("instId") or "")
        state = str(item.get("state") or "").lower()
        if state and state not in {"live", "trading"}:
            continue
        if not inst_id.endswith(f"-USDT-{config.OKX_INST_TYPE}"):
            continue
        out.add(_okx_symbol_from_inst_id(inst_id))
    return out


def load_toobit_symbols(toobit: ToobitClient) -> set[str]:
    raw = toobit.get_exchange_symbols()
    out: set[str] = set()
    for name in raw.keys():
        s = normalize_symbol(str(name))
        if s.endswith("USDT"):
            out.add(s)
    # Toobit گاهی نام‌ها را داخل symbolName/symbolId با خط تیره برمی‌گرداند؛ get_exchange_symbols همه را key می‌کند.
    return out


def validate_symbols(symbols: list[str], okx: OKXClient | None = None, toobit: ToobitClient | None = None) -> SymbolValidationReport:
    okx = okx or OKXClient()
    toobit = toobit or ToobitClient()
    configured = []
    for s in symbols:
        n = normalize_symbol(s)
        if n and n not in configured:
            configured.append(n)

    okx_set = load_okx_symbols(okx)
    toobit_set = load_toobit_symbols(toobit)

    valid: list[str] = []
    missing_okx: list[str] = []
    missing_toobit: list[str] = []
    missing_both: list[str] = []

    for symbol in configured:
        in_okx = symbol in okx_set or to_okx_inst_id(symbol).replace("-", "").upper() in {x.replace("-", "").upper() for x in okx_set}
        in_toobit = any(normalize_symbol(c) in toobit_set for c in toobit_symbol_candidates(symbol))
        if in_okx and in_toobit:
            valid.append(symbol)
        elif not in_okx and not in_toobit:
            missing_both.append(symbol)
        elif not in_okx:
            missing_okx.append(symbol)
        else:
            missing_toobit.append(symbol)

    return SymbolValidationReport(
        configured=configured,
        valid_common=valid,
        missing_okx=missing_okx,
        missing_toobit=missing_toobit,
        missing_both=missing_both,
        okx_count=len(okx_set),
        toobit_count=len(toobit_set),
    )


def default_symbols_text() -> str:
    return ",".join(config.DEFAULT_SYMBOLS_35)
