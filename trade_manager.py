"""اجرا و مانیتور: دیتا OKX، اجرای واقعی و نتیجه واقعی Toobit."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import config
from okx_client import OKXClient
from state import BotState, load_active_trades, save_active_trades
from strategy import TradeSignal
from toobit_client import ToobitClient, ToobitError
from utils import append_jsonl, human_price, logger, now_ms, pct_distance


class TradeManager:
    def __init__(self, okx: OKXClient, toobit: ToobitClient | None = None):
        self.okx = okx
        self.toobit = toobit or ToobitClient()

    def active_count(self, symbol: str | None = None) -> int:
        trades = load_active_trades()
        if symbol:
            return sum(1 for t in trades if t.get("symbol") == symbol)
        return len(trades)

    def can_accept_signal(self, signal: TradeSignal, state: BotState) -> tuple[bool, str]:
        if state.in_symbol_cooldown(signal.symbol):
            return False, "نماد در cooldown است"
        if self.active_count() >= int(state.max_active_trades):
            return False, "تعداد کل معاملات فعال پر است"
        if self.active_count(signal.symbol) >= config.MAX_ACTIVE_PER_SYMBOL:
            return False, "برای این نماد معامله فعال وجود دارد"
        return True, "OK"

    def record_signal(self, signal: TradeSignal, state: BotState, status: str, extra: dict[str, Any] | None = None) -> None:
        item = signal.to_dict()
        item.update({"mode": state.mode, "status": status, "recorded_ms": now_ms()})
        if extra:
            item.update(extra)
        append_jsonl(config.SIGNALS_FILE, item)

    def execute_or_track(self, signal: TradeSignal, state: BotState) -> dict[str, Any]:
        ok, reason = self.can_accept_signal(signal, state)
        if not ok:
            self.record_signal(signal, state, "BLOCKED", {"block_reason": reason})
            return {"ok": False, "action": "blocked", "reason": reason}

        if not state.trading_enabled:
            self.record_signal(signal, state, "SIGNAL_ONLY", {"reason": "trading_disabled"})
            state.touch_signal(signal.symbol)
            return {"ok": True, "action": "signal_only", "reason": "ترید خاموش است؛ فقط سیگنال ثبت شد"}

        if state.mode == "REAL":
            return self._execute_real(signal, state)
        return self._track_normal(signal, state)

    def _execute_real(self, signal: TradeSignal, state: BotState) -> dict[str, Any]:
        if not config.REAL_TRADING_ENABLED:
            self.record_signal(signal, state, "REAL_BLOCKED", {"reason": "REAL_TRADING_ENABLED=false"})
            return {"ok": False, "action": "real_blocked", "reason": "اجازه اجرای واقعی در config فعال نیست"}
        try:
            exchange_symbols = self.toobit.get_exchange_symbols()
            toobit_symbol, symbol_info = self.toobit.validate_symbol(signal.symbol, exchange_symbols)
            toobit_mark = self.toobit.get_mark_price(toobit_symbol)
            dev = pct_distance(toobit_mark, signal.entry_price)
            if dev > config.MAX_TOOBIT_OKX_PRICE_DEVIATION_PCT:
                self.record_signal(signal, state, "REAL_REJECTED", {"reason": "toobit_okx_deviation", "toobit_mark": toobit_mark, "deviation_pct": dev})
                return {"ok": False, "action": "real_rejected", "reason": f"اختلاف قیمت OKX/Toobit زیاد است: {dev:.2f}%"}

            client_id = f"DIFT5M_{signal.symbol}_{signal.created_ms}"
            result = self.toobit.place_market_order(
                symbol=toobit_symbol,
                side=signal.side,
                entry_price=toobit_mark,
                trade_amount_usdt=float(state.trade_amount_usdt),
                leverage=int(state.leverage),
                tp_price=signal.tp_price,
                sl_price=signal.sl_price,
                client_order_id=client_id,
                symbol_info=symbol_info,
            )
            self.record_signal(signal, state, "REAL_SENT", {"toobit": result})
            state.touch_signal(signal.symbol)
            if result.get("opened"):
                self._add_active({
                    "mode": "REAL",
                    "symbol": signal.symbol,
                    "toobit_symbol": toobit_symbol,
                    "side": signal.side,
                    "direction": signal.direction,
                    "entry_price": result.get("entry_price") or toobit_mark,
                    "sl_price": result.get("sl_price") or signal.sl_price,
                    "tp_price": result.get("tp_price") or signal.tp_price,
                    "rr": signal.rr,
                    "opened_ms": now_ms(),
                    "signal_ms": signal.created_ms,
                    "order_id": result.get("order_id"),
                    "client_order_id": client_id,
                    "trade_amount_usdt": float(state.trade_amount_usdt),
                    "leverage": int(state.leverage),
                    "raw_open": result,
                })
            return {"ok": bool(result.get("opened")), "action": "real_order", "result": result}
        except Exception as exc:
            logger.exception("اجرای واقعی ناموفق شد")
            self.record_signal(signal, state, "REAL_ERROR", {"error": str(exc)})
            return {"ok": False, "action": "real_error", "reason": str(exc)}

    def _track_normal(self, signal: TradeSignal, state: BotState) -> dict[str, Any]:
        trade = {
            "mode": "NORMAL",
            "symbol": signal.symbol,
            "side": signal.side,
            "direction": signal.direction,
            "entry_price": signal.entry_price,
            "sl_price": signal.sl_price,
            "tp_price": signal.tp_price,
            "rr": signal.rr,
            "opened_ms": now_ms(),
            "signal_ms": signal.created_ms,
            "trade_amount_usdt": float(state.trade_amount_usdt),
            "leverage": int(state.leverage),
        }
        self._add_active(trade)
        self.record_signal(signal, state, "NORMAL_TRACKED")
        state.touch_signal(signal.symbol)
        return {"ok": True, "action": "normal_tracked", "trade": trade}

    def _add_active(self, trade: dict[str, Any]) -> None:
        trades = load_active_trades()
        trades.append(trade)
        save_active_trades(trades)

    def update_results(self, state: BotState) -> list[dict[str, Any]]:
        trades = load_active_trades()
        remaining: list[dict[str, Any]] = []
        closed: list[dict[str, Any]] = []
        for t in trades:
            try:
                result = self._check_one_trade(t)
                if result is None:
                    remaining.append(t)
                else:
                    closed.append(result)
                    self._append_history(result)
                    append_jsonl(config.RESULTS_FILE, result)
                    if float(result.get("pnl", 0) or 0) < 0:
                        state.touch_loss(str(result.get("symbol")))
            except Exception as exc:
                logger.warning("چک نتیجه ناموفق بود %s: %s", t.get("symbol"), exc)
                remaining.append(t)
        save_active_trades(remaining)
        return closed

    def _check_one_trade(self, t: dict[str, Any]) -> dict[str, Any] | None:
        mode = t.get("mode")
        if mode == "REAL":
            return self._check_real_result(t)
        return self._check_normal_result(t)

    def _check_real_result(self, t: dict[str, Any]) -> dict[str, Any] | None:
        symbol = str(t.get("toobit_symbol") or t.get("symbol"))
        side = str(t.get("side"))
        opened_ms = int(t.get("opened_ms") or t.get("signal_ms") or 0)

        # اگر پوزیشن هنوز باز است، نتیجه قطعی نداریم.
        try:
            if self.toobit.get_open_position(symbol, side):
                return None
        except ToobitError:
            # اگر endpoint پوزیشن خطا داد، برای جلوگیری از نتیجه اشتباه، history را هم امتحان می‌کنیم.
            pass

        res = self.toobit.find_realized_result(symbol=symbol, side=side, start_ms=opened_ms)
        if not res:
            return None

        close_price = res.get("close_price")
        result = self._infer_result_label(t, close_price, float(res.get("pnl") or 0))
        return {
            **t,
            "closed_ms": res.get("close_time_ms") or now_ms(),
            "close_price": close_price,
            "pnl": res.get("pnl"),
            "result": result,
            "result_source": "TOOBIT_HISTORY",
            "raw_result": res.get("raw"),
        }

    def _check_normal_result(self, t: dict[str, Any]) -> dict[str, Any] | None:
        symbol = str(t.get("symbol"))
        side = str(t.get("side"))
        tp = float(t.get("tp_price"))
        sl = float(t.get("sl_price"))
        entry = float(t.get("entry_price"))
        opened_ms = int(t.get("opened_ms") or t.get("signal_ms") or 0)

        # برای مانیتور نرمال، کندل‌های OKX را چک می‌کنیم تا اگر داخل کندل TP/SL خورد از دست نرود.
        candles = self.okx.get_candles(symbol, "5m", 200)
        relevant = [c for c in candles if int(c.ts) >= opened_ms]
        if not relevant:
            ticker = self.okx.get_ticker(symbol)
            price = float(ticker.get("last") or t.get("entry_price") or 0)
            relevant = []
        else:
            price = relevant[-1].close

        hit: str | None = None
        close_price = price
        closed_ms = now_ms()

        for c in relevant:
            if side == "BUY":
                sl_hit = c.low <= sl
                tp_hit = c.high >= tp
                if sl_hit and tp_hit:
                    hit = "SL_FIRST_CONSERVATIVE"
                    close_price = sl
                elif sl_hit:
                    hit = "SL"
                    close_price = sl
                elif tp_hit:
                    hit = "TP"
                    close_price = tp
            else:
                sl_hit = c.high >= sl
                tp_hit = c.low <= tp
                if sl_hit and tp_hit:
                    hit = "SL_FIRST_CONSERVATIVE"
                    close_price = sl
                elif sl_hit:
                    hit = "SL"
                    close_price = sl
                elif tp_hit:
                    hit = "TP"
                    close_price = tp
            if hit:
                closed_ms = int(c.ts)
                break

        if not hit:
            return None

        if side == "BUY":
            pnl_pct = (close_price - entry) / entry * 100 if entry else 0.0
        else:
            pnl_pct = (entry - close_price) / entry * 100 if entry else 0.0

        return {
            **t,
            "closed_ms": closed_ms,
            "close_price": close_price,
            "pnl": pnl_pct,
            "pnl_unit": "PCT_NORMAL_SIM",
            "result": hit,
            "result_source": "OKX_NORMAL_SIM_CANDLES",
        }

    @staticmethod
    def _infer_result_label(t: dict[str, Any], close_price: Any, pnl: float) -> str:
        try:
            cp = float(close_price)
            tp = float(t.get("tp_price"))
            sl = float(t.get("sl_price"))
            if cp > 0 and abs(cp - tp) / cp * 100 <= 0.15:
                return "TP"
            if cp > 0 and abs(cp - sl) / cp * 100 <= 0.15:
                return "SL"
        except Exception:
            pass
        return "PROFIT" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"

    def _append_history(self, result: dict[str, Any]) -> None:
        path = Path(config.TRADE_HISTORY_FILE)
        fields = ["mode", "symbol", "side", "entry_price", "sl_price", "tp_price", "rr", "opened_ms", "closed_ms", "close_price", "pnl", "pnl_unit", "result", "result_source"]
        exists = path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow({k: result.get(k) for k in fields})

    def format_active(self) -> str:
        trades = load_active_trades()
        if not trades:
            return "📌 پوزیشن فعالی وجود ندارد."
        lines = ["📌 پوزیشن‌های فعال"]
        for i, t in enumerate(trades, 1):
            side = str(t.get("direction") or "")
            emoji = "🟢" if side == "LONG" else "🔴"
            lines.append(
                f"\n#{i} | {t.get('symbol')} | {emoji} {side} | {t.get('mode')}\n"
                f"Entry: {human_price(float(t.get('entry_price') or 0))}\n"
                f"TP: {human_price(float(t.get('tp_price') or 0))} | SL: {human_price(float(t.get('sl_price') or 0))}\n"
                f"RR: {float(t.get('rr') or 0):.1f} | دلار: USDT {float(t.get('trade_amount_usdt') or getattr(config, 'DEFAULT_TRADE_AMOUNT_USDT', 0)):.2f} | لوریج: {int(t.get('leverage') or getattr(config, 'DEFAULT_LEVERAGE', 0))}x"
            )
        return "\n".join(lines)

    @staticmethod
    def _duration_text(opened_ms: Any, closed_ms: Any) -> str:
        try:
            sec = max(0, int(int(closed_ms) - int(opened_ms)) // 1000)
            h = sec // 3600
            m = (sec % 3600) // 60
            if h and m:
                return f"{h} ساعت و {m} دقیقه"
            if h:
                return f"{h} ساعت"
            return f"{m} دقیقه"
        except Exception:
            return "نامشخص"

    @staticmethod
    def _normal_pnl_usdt(result: dict[str, Any]) -> float:
        try:
            pct = float(result.get("pnl") or 0)
            margin = float(result.get("trade_amount_usdt") or getattr(config, "DEFAULT_TRADE_AMOUNT_USDT", 0))
            lev = float(result.get("leverage") or getattr(config, "DEFAULT_LEVERAGE", 1))
            return margin * lev * pct / 100.0
        except Exception:
            return 0.0

    @staticmethod
    def format_result(result: dict[str, Any]) -> str:
        result_label = str(result.get("result") or "")
        is_win = result_label.startswith("TP") or result_label == "PROFIT" or float(result.get("pnl") or 0) > 0
        hit = "✅ TP خورد" if is_win else "❌ SL خورد"
        side = str(result.get("direction") or "")
        symbol = result.get("symbol")
        mode = str(result.get("mode") or "NORMAL")
        entry = float(result.get("entry_price") or 0)
        close = float(result.get("close_price") or 0)
        pnl_raw = float(result.get("pnl") or 0)
        if mode == "REAL":
            pnl_usdt = pnl_raw
            move_pct = (close - entry) / entry * 100 if side == "LONG" and entry else (entry - close) / entry * 100 if entry else 0.0
        else:
            pnl_usdt = TradeManager._normal_pnl_usdt(result)
            move_pct = pnl_raw
        return (
            "📊 نتیجه سیگنال عادی\n"
            f"{hit}\n"
            f"{symbol} | {side}\n"
            f"Entry: {human_price(entry)}\n"
            f"Exit: {human_price(close)}\n"
            f"PnL خام: USDT {pnl_usdt:.2f}\n"
            f"PnL خالص/واقعی: USDT {pnl_usdt:.2f}\n"
            f"حرکت: {move_pct:.2f}%\n"
            "MFE: - | MAE: -\n"
            f"مدت معامله: {TradeManager._duration_text(result.get('opened_ms'), result.get('closed_ms'))}\n"
            f"close_reason: {result.get('result_source')} hit TP/SL."
        )

    def format_recent_results(self, limit: int = 30) -> str:
        path = Path(config.RESULTS_FILE)
        if not path.exists():
            return "هنوز نتیجه‌ای ثبت نشده است."
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        if not rows:
            return "هنوز نتیجه‌ای ثبت نشده است."
        recent = rows[-max(1, int(limit)):]
        normal = [r for r in rows if str(r.get("mode")) != "REAL"]
        real = [r for r in rows if str(r.get("mode")) == "REAL"]

        def pnl_usdt(r: dict[str, Any]) -> float:
            if str(r.get("mode")) == "REAL":
                return float(r.get("pnl") or 0)
            return self._normal_pnl_usdt(r)

        def is_tp(r: dict[str, Any]) -> bool:
            return str(r.get("result") or "").startswith("TP") or float(r.get("pnl") or 0) > 0

        def is_sl(r: dict[str, Any]) -> bool:
            return str(r.get("result") or "").startswith("SL") or float(r.get("pnl") or 0) < 0

        long_rows = [r for r in rows if str(r.get("direction")) == "LONG"]
        short_rows = [r for r in rows if str(r.get("direction")) == "SHORT"]
        total_pnl = sum(pnl_usdt(r) for r in rows)
        today_pnl = total_pnl

        def line_side(name: str, icon: str, data: list[dict[str, Any]]) -> str:
            if not data:
                return f"{icon} {name}: سیگنال 0 | TP 0 | SL 0 | وین‌ریت 0.0%"
            tp = sum(1 for r in data if is_tp(r))
            sl = sum(1 for r in data if is_sl(r))
            wr = tp / max(1, tp + sl) * 100
            return f"{icon} {name}: سیگنال {len(data)} | TP {tp} | SL {sl} | وین‌ریت {wr:.1f}%"

        normal_tp = sum(1 for r in normal if is_tp(r))
        normal_sl = sum(1 for r in normal if is_sl(r))
        normal_wr = normal_tp / max(1, normal_tp + normal_sl) * 100
        real_tp = sum(1 for r in real if is_tp(r))
        real_sl = sum(1 for r in real if is_sl(r))
        real_wr = real_tp / max(1, real_tp + real_sl) * 100

        text = (
            f"📊 آمار {limit} نتیجه اخیر\n"
            f"💰 سود/ضرر کل: USDT {total_pnl:.2f}\n"
            f"📅 سود/ضرر امروز: USDT {today_pnl:.2f}\n"
            "آمار شماری از آخرین «حذف آمار» محاسبه شده؛ سود/ضرر کل و امروز حفظ شده‌اند.\n\n"
            f"{line_side('لانگ', '🟢', long_rows)}\n"
            f"{line_side('شورت', '🔴', short_rows)}\n\n"
            "📌 عادی:\n"
            f"تعداد: {len(normal)} | SL: {normal_sl} | TP: {normal_tp} | باز: 0\n"
            f"وین‌ریت: {normal_wr:.1f}% | PnL خالص تقریبی: {sum(pnl_usdt(r) for r in normal):.2f} USDT\n\n"
            "💰 واقعی:\n"
            f"تعداد: {len(real)} | SL: {real_sl} | TP: {real_tp} | EXIT: 0 | باز: 0\n"
            f"وین‌ریت: {real_wr:.1f}% | PnL واقعی/خالص: USDT {sum(pnl_usdt(r) for r in real):.2f}\n"
        )
        if limit <= 10:
            text += "\n" + "\n\n".join(self.format_result(x) for x in recent)
        return text
