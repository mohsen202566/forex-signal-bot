"""حلقه اصلی ربات ۱۵ تا ۳۰ دقیقه‌ای.

قفل‌های اجرایی:
- OKX منبع تحلیل، کندل، قیمت و نتیجه سیگنال عادی است.
- Toobit فقط برای REAL استفاده می‌شود: باز کردن پوزیشن، تأیید باز شدن و نتیجه واقعی.
- سیگنال عادی همیشه صادر و مانیتور می‌شود، حتی وقتی ترید واقعی خاموش است.
- REAL فقط وقتی ترید فعال باشد، حداقل سود خالص پاس شود، اسلات خالی باشد و برای آن کوین REAL فعال/Pending نباشد.
- بعد از ارسال سفارش REAL، اسلات فوراً با PENDING_OPEN پر می‌شود و position_monitor.py بعد از ۷۰ ثانیه تأیید/آزاد می‌کند.
- پوزیشن Toobit باید با TP/SL همزمان از طریق tobit_client.py ارسال شود.
- این فایل فقط orchestration است: تلگرام، اسکن، مانیتورینگ و اتصال اجزا.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

import config
from command_router import CommandRouter
from exchange_clients import OKXClient, ToobitAdapter
from position_monitor import PositionMonitor
from state_store import StateStore, now_ts
from strategy_engine import StrategyEngine, estimated_net_profit_usdt
from telegram_ui import result_message, signal_message

try:
    from telegram_ui import main_buttons
except Exception:
    def main_buttons() -> list[list[tuple[str, str]]]:
        return [
            [("📊 پنل", "panel"), ("📈 آمار", "stats")],
            [("✅ ترید فعال", "trade_on"), ("⏸ ترید خاموش", "trade_off")],
            [("📂 پوزیشن‌ها", "positions"), ("🪙 کوین‌ها", "coins")],
            [("❓ راهنما", "help")],
        ]


def _load_env_file(path: str = ".env") -> None:
    """لود ساده .env بدون وابستگی اضافه؛ مقادیر موجود env را overwrite نمی‌کند."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class TelegramSink:
    """ارسال/دریافت تلگرام با Bot API.

    این کلاس عمداً بدون python-telegram-bot نوشته شده تا تعداد فایل/وابستگی کم بماند.
    اگر TELEGRAM_BOT_TOKEN تنظیم نباشد، پیام‌ها فقط در کنسول چاپ می‌شوند.
    """

    def __init__(self) -> None:
        _load_env_file()

        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.timeout = int(os.getenv("TELEGRAM_TIMEOUT_SECONDS", "15"))
        self.offset = int(os.getenv("TELEGRAM_INITIAL_OFFSET", "0") or "0")
        self.session = requests.Session()
        self.api_base = f"https://api.telegram.org/bot{self.token}" if self.token else ""
        self._last_poll_log_ts = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def startup_check(self) -> None:
        if not self.enabled:
            print("telegram disabled: TELEGRAM_BOT_TOKEN is empty", flush=True)
            return

        try:
            # اگر webhook قبلاً ست شده باشد، getUpdates جواب نمی‌دهد؛ پس مطمئن می‌شویم پاک است.
            self.session.post(
                f"{self.api_base}/deleteWebhook",
                json={"drop_pending_updates": False},
                timeout=self.timeout,
            )
        except Exception as exc:
            print(f"telegram deleteWebhook warning: {exc}", flush=True)

        try:
            response = self.session.get(f"{self.api_base}/getMe", timeout=self.timeout)
            payload = response.json()
            if payload.get("ok"):
                username = payload.get("result", {}).get("username")
                print(f"telegram connected: @{username} chat_id={self.chat_id or 'AUTO/UNSET'}", flush=True)
            else:
                print(f"telegram getMe failed: {payload}", flush=True)
        except Exception as exc:
            print(f"telegram getMe error: {exc}", flush=True)

    def send(self, text: str, *, buttons: list[list[tuple[str, str]]] | None = None, chat_id: str | int | None = None) -> int | None:
        return self._send_message(text=text, reply_to_message_id=None, buttons=buttons, chat_id=chat_id)

    def reply(self, message_id: int | None, text: str) -> None:
        self._send_message(text=text, reply_to_message_id=message_id, buttons=None, chat_id=None)

    def reply_to_chat(self, chat_id: str | int | None, message_id: int | None, text: str, *, buttons: list[list[tuple[str, str]]] | None = None) -> int | None:
        return self._send_message(text=text, reply_to_message_id=message_id, buttons=buttons, chat_id=chat_id)

    def poll_updates(self) -> list[dict[str, Any]]:
        if not self.enabled:
            now = time.time()
            if now - self._last_poll_log_ts > 60:
                print("telegram polling skipped: token is empty", flush=True)
                self._last_poll_log_ts = now
            return []

        try:
            response = self.session.get(
                f"{self.api_base}/getUpdates",
                params={
                    "offset": self.offset,
                    "timeout": 1,
                    "allowed_updates": json.dumps(["message", "callback_query"], ensure_ascii=False),
                },
                timeout=max(self.timeout, 5),
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                print(f"telegram poll not ok: {payload}", flush=True)
                return []

            updates = payload.get("result", [])
            if updates:
                print(f"telegram updates received: {len(updates)}", flush=True)

            for update in updates:
                self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
            return updates
        except Exception as exc:
            print(f"telegram poll error: {exc}", flush=True)
            return []

    def answer_callback(self, callback_query_id: str) -> None:
        if not self.enabled or not callback_query_id:
            return
        try:
            self.session.post(
                f"{self.api_base}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id},
                timeout=self.timeout,
            )
        except Exception as exc:
            print(f"telegram callback answer error: {exc}", flush=True)

    def _send_message(
        self,
        *,
        text: str,
        reply_to_message_id: int | None,
        buttons: list[list[tuple[str, str]]] | None,
        chat_id: str | int | None,
    ) -> int | None:
        target_chat_id = str(chat_id or self.chat_id or "").strip()

        if not self.enabled or not target_chat_id:
            label = f"--- TELEGRAM REPLY to {reply_to_message_id} ---" if reply_to_message_id else "--- TELEGRAM SEND ---"
            print(f"\n{label}\n{text}", flush=True)
            if self.enabled and not target_chat_id:
                print("telegram send skipped: TELEGRAM_CHAT_ID is empty and no chat_id was provided", flush=True)
            return None

        data: dict[str, Any] = {
            "chat_id": target_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            data["reply_to_message_id"] = int(reply_to_message_id)
            data["allow_sending_without_reply"] = True
        if buttons:
            data["reply_markup"] = self._inline_keyboard(buttons)

        try:
            response = self.session.post(f"{self.api_base}/sendMessage", json=data, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok"):
                return int(payload["result"]["message_id"])
            print(f"telegram send failed: {payload}", flush=True)
            return None
        except Exception as exc:
            print(f"telegram send error: {exc}", flush=True)
            return None

    @staticmethod
    def _inline_keyboard(buttons: list[list[tuple[str, str]]]) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": label, "callback_data": callback} for label, callback in row]
                for row in buttons
            ]
        }


class Bot:
    def __init__(self) -> None:
        self.state = StateStore()
        self.okx = OKXClient()
        self.tobit = ToobitAdapter()
        self.strategy = StrategyEngine()
        self.telegram = TelegramSink()
        self.router = CommandRouter(self.state, self.tobit)
        self.monitor = PositionMonitor(self.state, self.okx, self.tobit, self.telegram.reply)
        self.last_scan = 0.0

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run_forever(self) -> None:
        print("Crypto Helper 15m bot started.", flush=True)
        self.telegram.startup_check()
        self.state.update_runtime(engine_health="STARTED")

        while True:
            self.run_once()
            time.sleep(float(getattr(config, "PRICE_MONITOR_SECONDS", 3)))

    def run_once(self) -> None:
        # اول تلگرام، تا دستورهای کاربر پشت اسکن بازار گیر نکنند.
        self._handle_telegram_updates()
        self.monitor.tick()

        current = time.time()
        if current - self.last_scan >= float(getattr(config, "COIN_SCAN_SECONDS", 25)):
            self.scan_all()
            self.last_scan = current

    # ------------------------------------------------------------------
    # Telegram command handling
    # ------------------------------------------------------------------
    def _handle_telegram_updates(self) -> None:
        for update in self.telegram.poll_updates():
            try:
                if "message" in update:
                    self._handle_message_update(update["message"])
                elif "callback_query" in update:
                    self._handle_callback_update(update["callback_query"])
            except Exception as exc:
                print(f"telegram update handle error: {exc}", flush=True)

    def _is_allowed_chat(self, message_or_callback_message: dict[str, Any]) -> bool:
        configured = str(self.telegram.chat_id or "").strip()
        if not configured:
            return True
        chat = message_or_callback_message.get("chat") or {}
        incoming = str(chat.get("id", "")).strip()
        allowed = incoming == configured
        if not allowed:
            print(f"telegram ignored chat: incoming={incoming} allowed={configured}", flush=True)
        return allowed

    @staticmethod
    def _chat_id_from_message(message: dict[str, Any]) -> str | None:
        chat = message.get("chat") or {}
        cid = chat.get("id")
        return str(cid) if cid is not None else None

    def _handle_message_update(self, message: dict[str, Any]) -> None:
        if not self._is_allowed_chat(message):
            return

        text = str(message.get("text") or "").strip()
        if not text:
            return

        normalized_text = self._normalize_command(text)
        chat_id = self._chat_id_from_message(message)
        msg_id = message.get("message_id")

        print(f"telegram command received: chat={chat_id} text={normalized_text}", flush=True)

        reply = self.router.handle(normalized_text)
        buttons = main_buttons() if normalized_text in {"ترید", "وضعیت"} else None

        self.telegram.reply_to_chat(
            chat_id=chat_id,
            message_id=int(msg_id) if msg_id else None,
            text=reply,
            buttons=buttons,
        )

    def _handle_callback_update(self, callback: dict[str, Any]) -> None:
        data = str(callback.get("data") or "")
        callback_id = str(callback.get("id") or "")
        self.telegram.answer_callback(callback_id)

        message = callback.get("message") or {}
        if not self._is_allowed_chat(message):
            return

        chat_id = self._chat_id_from_message(message)
        msg_id = message.get("message_id")

        print(f"telegram callback received: chat={chat_id} data={data}", flush=True)

        if hasattr(self.router, "handle_callback"):
            reply = self.router.handle_callback(data)
        else:
            callback_to_command = {
                "panel": "ترید",
                "trade_on": "ترید فعال",
                "trade_off": "ترید خاموش",
                "stats": "آمار",
                "positions": "پوزیشن",
                "coins": "کوین‌ها",
                "help": "راهنما",
            }
            reply = self.router.handle(callback_to_command.get(data, "ترید"))

        buttons = main_buttons() if data in {"panel", "trade_on", "trade_off", "stats", "positions", "coins", "help"} else None
        self.telegram.reply_to_chat(
            chat_id=chat_id,
            message_id=int(msg_id) if msg_id else None,
            text=reply,
            buttons=buttons,
        )

    @staticmethod
    def _normalize_command(text: str) -> str:
        t = " ".join(text.strip().split())
        low = t.lower()
        if low in {"/start", "start", "/panel", "panel"} or t in {"پنل", "منو"}:
            return "ترید"
        if low in {"/stats", "stats"}:
            return "آمار"
        if low in {"/positions", "positions"}:
            return "پوزیشن"
        if low in {"/coins", "coins"}:
            return "کوین‌ها"
        if low in {"/help", "help"}:
            return "راهنما"
        return t

    # ------------------------------------------------------------------
    # Scanning / strategy orchestration
    # ------------------------------------------------------------------
    def scan_all(self) -> None:
        scan_ts = now_ts()
        self.state.update_runtime(last_scan=scan_ts, engine_health="SCANNING")

        plans_count = 0
        errors_count = 0

        for coin in config.WATCHLIST:
            try:
                plan = self._analyze_coin(coin)
                if not plan:
                    continue
                plans_count += 1
                self.handle_plan(plan.to_dict())
            except Exception as exc:
                errors_count += 1
                print(f"scan error {coin}: {exc}", flush=True)

        if plans_count > 0:
            health = "ACTIVE"
        elif errors_count >= len(config.WATCHLIST):
            health = "ERROR"
        elif errors_count > 0:
            health = "PARTIAL"
        else:
            health = "QUIET"

        self.state.update_runtime(engine_health=health)

    def _analyze_coin(self, coin: str):
        candles_15m = self.okx.get_candles(coin, "15m", 120)
        candles_1h = self.okx.get_candles(coin, "1H", 80)
        oi_values = self.okx.get_open_interest_series(coin)
        return self.strategy.analyze(coin, candles_15m, candles_1h, oi_values)

    def handle_plan(self, plan: dict[str, Any]) -> None:
        # ۱) سیگنال عادی همیشه برای ارزیابی موتور تحلیل صادر می‌شود.
        emitted_signal_id = self._emit_or_replace_signal(plan)
        if emitted_signal_id:
            self.state.update_runtime(last_signal_id=emitted_signal_id)

        # ۲) REAL فقط وقتی ترید فعال است و همه قوانین ریسک پاس شوند.
        settings = self.state.settings()
        if not bool(settings.get("real_trade_enabled")):
            return

        if not self.state.can_open_real(plan["coin"]):
            return

        net_profit = estimated_net_profit_usdt(
            margin_usdt=float(settings["trade_margin_usdt"]),
            leverage=int(settings["leverage"]),
            tp_percent=float(plan["tp_percent"]),
            fee_rate=config.DEFAULT_FEE_RATE,
            slippage_rate=config.SLIPPAGE_BUFFER_RATE,
        )
        if net_profit < float(settings["min_net_profit_usdt"]):
            self.state.update_runtime(
                last_real_block_reason=(
                    f"MIN_NET_PROFIT: {plan['coin']} net={net_profit:.4f} < "
                    f"min={float(settings['min_net_profit_usdt']):.4f}"
                )
            )
            return

        self._open_real(plan, estimated_net_profit=net_profit)

    # ------------------------------------------------------------------
    # Signal / REAL helpers
    # ------------------------------------------------------------------
    def _emit_or_replace_signal(self, plan: dict[str, Any]) -> str | None:
        same = [
            sig
            for sig in self.state.active_by_coin(plan["coin"], "SIGNAL")
            if sig.get("side") == plan.get("side")
        ]
        if same:
            strongest = max(same, key=lambda sig: float(sig.get("final_score", 0.0)))
            new_score = float(plan.get("final_score", 0.0))
            old_score = float(strongest.get("final_score", 0.0))
            can_replace = bool(plan.get("can_replace", True))
            if can_replace and new_score >= old_score + config.REPLACE_SIGNAL_MIN_IMPROVEMENT:
                self.state.replace_signal(strongest["id"], {"replaced_by_score": new_score})
                self.telegram.reply(strongest.get("telegram_message_id"), result_message(strongest, "REPLACED"))
            else:
                return None

        return self._emit_signal(plan, kind="SIGNAL", status="ACTIVE")

    def _emit_signal(self, plan: dict[str, Any], *, kind: str, status: str) -> str:
        sig = dict(plan)
        sig.update({"kind": kind, "status": status, "created_at": now_ts()})
        sid = self.state.add_signal(sig)
        sig["id"] = sid

        # state_store برای سیگنال عادی expires_at می‌سازد؛ بعد از add بخوانیم که پیام دقیق‌تر باشد.
        stored = self.state.data["active_signals"].get(sid, sig)
        msg_id = self.telegram.send(signal_message(stored))
        if msg_id:
            stored["telegram_message_id"] = msg_id
            self.state.save()
        return sid

    def _open_real(self, plan: dict[str, Any], *, estimated_net_profit: float) -> None:
        settings = self.state.settings()
        sig = dict(plan)
        sig.update(
            {
                "kind": "TOBIT",
                "status": "PENDING_OPEN",
                "created_at": now_ts(),
                "estimated_net_profit_usdt": round(float(estimated_net_profit), 8),
            }
        )

        try:
            sid = self.state.add_signal(sig)  # اسلات فوراً فرضی پر می‌شود.
        except Exception as exc:
            print(f"real slot reserve failed {plan.get('coin')}: {exc}", flush=True)
            return

        stored = self.state.data["active_signals"][sid]
        msg_id = self.telegram.send(signal_message(stored))
        if msg_id:
            stored["telegram_message_id"] = msg_id
            self.state.save()

        result = self.tobit.open_position_with_tp_sl(
            symbol=plan["coin"],
            side=plan["side"],
            margin_usdt=float(settings["trade_margin_usdt"]),
            leverage=int(settings["leverage"]),
            entry=float(plan["entry"]),
            tp=float(plan["tp"]),
            sl=float(plan["sl"]),
        )

        if not result.get("ok", False):
            # اگر سفارش اصلاً پذیرفته نشد، اسلات آزاد و نتیجه ثبت شود.
            self.state.mark_failed_open(sid, {"error": result.get("error"), "open_result": result})
            self.telegram.reply(msg_id, result_message(stored, "FAILED_OPEN"))
            return

        # سفارش پذیرفته شده؛ وضعیت PENDING_OPEN می‌ماند تا مانیتور بعد از ۷۰ ثانیه
        # وجود پوزیشن را از Toobit تأیید کند.
        self._patch_signal(
            sid,
            {
                "order_id": result.get("order_id"),
                "exchange_position_id": result.get("position_id"),
                "open_result": result,
                "actual_margin_usdt": result.get("actual_margin_usdt"),
                "quantity": result.get("quantity"),
            },
        )

    def _patch_signal(self, signal_id: str, patch: dict[str, Any]) -> None:
        sig = self.state.data.get("active_signals", {}).get(signal_id)
        if not sig:
            return
        for key, value in patch.items():
            if value is not None:
                sig[key] = value
        self.state.save()


if __name__ == "__main__":
    Bot().run_forever()
