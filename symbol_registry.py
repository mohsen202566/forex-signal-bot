"""اعتبارسنجی نمادها؛ تحلیل با OKX، اجرای واقعی با Toobit.

نکته مهم:
بعضی VPSها/اکانت‌ها endpoint لیست نمادهای Toobit را با 404 برمی‌گردانند. برای همین
در شروع ربات، اسکن را به Toobit وابسته نمی‌کنیم. در حالت REAL، قبل از ارسال سفارش،
خود toobit_client.validate_symbol دوباره نماد واقعی را چک می‌کند.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
from okx_client import OKXClient
from toobit_client import ToobitClient
from utils import normalize_symbol, to_okx_inst_id, toobit_symbol_candidates, logger


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
    toobit_checked: bool = False
    toobit_error: str | None = None

    @property
    def ok(self) -> bool:
        if self.toobit_checked:
            return len(self.valid_common) >= int(self.required_count) and not self.missing_okx and not self.missing_toobit and not self.missing_both
        return len(self.valid_common) >= int(self.required_count) and not self.missing_okx

    def short_text(self) -> str:
        lines = [
            f"Configured: {len(self.configured)}",
            f"Valid for scan: {len(self.valid_common)}/{self.required_count}",
            f"OKX SWAP symbols seen: {self.okx_count}",
        ]
        if self.toobit_checked:
            lines.append(f"Toobit symbols seen: {self.toobit_count}")
        elif self.toobit_error:
            lines.append("Toobit list check: skipped/failed; REAL order still validates before execution")
        if self.valid_common:
            lines.append("Valid: " + ", ".join(self.valid_common))
        if self.missing_okx:
            lines.append("Missing OKX: " + ", ".join(self.missing_okx))
        if self.toobit_checked and self.missing_toobit:
            lines.append("Missing Toobit: " + ", ".join(self.missing_toobit))
        if self.toobit_checked and self.missing_both:
            lines.append("Missing Both: " + ", ".join(self.missing_both))
        return "\n".join(lines)


def _okx_symbol_from_inst_id(inst_id: str) -> str:
    parts = str(inst_id or "").upper().split("-")
    if len(parts) >= 2 and parts[1] == "USDT":
        return f"{parts[0]}USDT"
    return normalize_symbol(inst_id)


def load_okx_symbols(okx: OKXClient) -> set[str]:
    if hasattr(okx, "available_symbols"):
        return set(okx.available_symbols())
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
    return out


def validate_symbols(symbols: list[str], okx: OKXClient | None = None, toobit: ToobitClient | None = None) -> SymbolValidationReport:
    okx = okx or OKXClient()
    toobit = toobit or ToobitClient()

    configured: list[str] = []
    for s in symbols:
        n = normalize_symbol(s)
        if n and n not in configured:
            configured.append(n)

    okx_set = load_okx_symbols(okx)

    # پیش‌فرض: برای سرعت و جلوگیری از 404، Toobit را در شروع چک نمی‌کنیم.
    # اجرای REAL همچنان قبل از سفارش با Toobit validate_symbol می‌شود.
    check_toobit = bool(getattr(config, "CHECK_TOOBIT_SYMBOLS_ON_START", False))
    toobit_set: set[str] = set()
    toobit_error: str | None = None
    if check_toobit:
        try:
            toobit_set = load_toobit_symbols(toobit)
        except Exception as exc:
            toobit_error = str(exc)
            logger.warning("خواندن symbols توبیت ناموفق بود؛ اسکن با OKX ادامه دارد و REAL قبل سفارش چک می‌شود: %s", exc)

    valid: list[str] = []
    missing_okx: list[str] = []
    missing_toobit: list[str] = []
    missing_both: list[str] = []

    for symbol in configured:
        in_okx = symbol in okx_set
        if not check_toobit or toobit_error:
            if in_okx:
                valid.append(symbol)
            else:
                missing_okx.append(symbol)
            continue

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
        toobit_checked=check_toobit and not toobit_error,
        toobit_error=toobit_error,
    )


def default_symbols_text() -> str:
    return ",".join(config.DEFAULT_SYMBOLS_35)
