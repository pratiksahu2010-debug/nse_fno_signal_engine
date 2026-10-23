"""Minimal asynchronous Telegram Bot API client with outbound delivery diagnostics."""
from __future__ import annotations

import asyncio
import logging

import httpx
from utils.time_utils import now_ist

log = logging.getLogger(__name__)


class TelegramService:
    def __init__(self, token: str, chat_id: str = "", admin_ids=()):
        self.token = token.strip()
        self.chat_id = str(chat_id).strip()
        self.admin_ids = set(admin_ids)
        self.offset = 0
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=40.0, write=15.0, pool=10.0)
        )
        self.paused = False
        self.commands = {}
        self.messages_sent = 0
        self.messages_failed = 0
        self.last_attempt_at = None
        self.last_success_at = None
        self.last_error = None
        self.last_method = None
        self.bot_username = None

    async def close(self):
        await self.client.aclose()

    async def call(self, method, payload=None):
        if not self.token:
            raise RuntimeError("missing_bot_token")
        response = await self.client.post(
            f"https://api.telegram.org/bot{self.token}/{method}",
            json=payload or {},
        )
        try:
            data = response.json()
        except Exception:
            response.raise_for_status()
            raise RuntimeError(f"Telegram API {method} returned invalid JSON")
        if not response.is_success or not isinstance(data, dict) or not data.get("ok"):
            # Telegram's description is useful for diagnosis and does not contain
            # the bot token. Never log response URLs, which contain the token.
            description = data.get("description", "request rejected") if isinstance(data, dict) else "request rejected"
            raise RuntimeError(f"{method}: {description}")
        return data.get("result")

    async def send(self, text, chat_id=None, parse_mode=None):
        chat = str(chat_id or self.chat_id).strip()
        self.last_attempt_at = now_ist().isoformat()
        self.last_method = "sendMessage"
        if not self.token:
            self.messages_failed += 1
            self.last_error = "missing_bot_token"
            log.error("Telegram send skipped: TELEGRAM_BOT_TOKEN is missing")
            return False
        if not chat:
            self.messages_failed += 1
            self.last_error = "missing_chat_id"
            log.error("Telegram send skipped: TELEGRAM_CHAT_ID is missing")
            return False
        try:
            await self.call(
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": str(text),
                    "disable_web_page_preview": True,
                    **({"parse_mode": parse_mode} if parse_mode else {}),
                },
            )
            self.messages_sent += 1
            self.last_success_at = now_ist().isoformat()
            self.last_error = None
            log.info("Telegram message delivered successfully (total_sent=%d)", self.messages_sent)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.messages_failed += 1
            raw_error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            lowered = raw_error.lower()
            if "can't send messages to the bot" in lowered or "cannot send messages to the bot" in lowered:
                self.last_error = (
                    "TELEGRAM_CHAT_ID points to a bot chat. Set it to your own numeric Telegram user ID "
                    "or a group/channel chat ID; then open this bot and press Start (or add it to the group)."
                )
            elif "chat not found" in lowered:
                self.last_error = (
                    "Telegram chat not found. Verify TELEGRAM_CHAT_ID; for a private chat, open this bot "
                    "and press Start before sending alerts."
                )
            elif "bot was blocked by the user" in lowered:
                self.last_error = "Telegram bot was blocked by the destination user; unblock it and press Start."
            elif "not enough rights" in lowered or "forbidden" in lowered and "administrator" in lowered:
                self.last_error = "Telegram bot lacks permission in the target group/channel; grant send-message permission."
            else:
                self.last_error = raw_error[:240]
            log.error("Telegram message delivery failed: %s", self.last_error)
            return False

    async def startup_check(self):
        """Verify token and target chat, then send one explicit delivery test."""
        self.last_method = "getMe"
        if not self.token:
            self.last_error = "missing_bot_token"
            log.error("Telegram startup check failed: TELEGRAM_BOT_TOKEN is missing")
            return False
        if not self.chat_id:
            self.last_error = "missing_chat_id"
            log.error("Telegram startup check failed: TELEGRAM_CHAT_ID is missing")
            return False
        try:
            bot = await self.call("getMe")
            self.bot_username = bot.get("username") if isinstance(bot, dict) else None
            log.info("Telegram bot token verified; username=%s", self.bot_username or "unknown")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)[:240] if isinstance(exc, RuntimeError) else type(exc).__name__
            log.error("Telegram startup verification failed: %s", self.last_error)
            return False
        delivered = await self.send(
            "NSE F&O Signal Engine online. Telegram delivery test passed; signal alerts are enabled."
        )
        if not delivered:
            log.error(
                "Telegram startup test failed. In Render, set TELEGRAM_CHAT_ID to a human user's numeric ID "
                "or a group/channel ID, not a bot username or bot ID. For private delivery, the user must "
                "open this bot and press Start."
            )
        return delivered

    def status(self):
        return {
            "configured": bool(self.token and self.chat_id),
            "bot_username": self.bot_username,
            "messages_sent": self.messages_sent,
            "messages_failed": self.messages_failed,
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "last_method": self.last_method,
        }

    async def poll(self, handler):
        while True:
            try:
                updates = await self.call(
                    "getUpdates",
                    {
                        "offset": self.offset,
                        "timeout": 20,
                        "allowed_updates": ["message", "callback_query"],
                    },
                ) or []
                for update in updates:
                    self.offset = max(self.offset, int(update["update_id"]) + 1)
                    if "message" in update:
                        await handler(update["message"])
                    elif "callback_query" in update:
                        await self.call(
                            "answerCallbackQuery",
                            {"callback_query_id": update["callback_query"]["id"]},
                        )
            except asyncio.CancelledError:
                raise
            except httpx.ReadTimeout:
                log.warning("Telegram long poll timed out; retrying")
                await asyncio.sleep(1)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                log.warning("Telegram transport error (%s); retrying", type(exc).__name__)
                await asyncio.sleep(3)
            except Exception as exc:
                log.warning("Telegram polling error (%s); retrying", type(exc).__name__)
                await asyncio.sleep(3)
