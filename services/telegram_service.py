"""Minimal asynchronous Telegram Bot API client and polling command router."""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger(__name__)


class TelegramService:
    def __init__(self, token: str, chat_id: str = "", admin_ids=()):
        self.token = token
        self.chat_id = str(chat_id)
        self.admin_ids = set(admin_ids)
        self.offset = 0
        # Telegram long polling may wait for 20 seconds. The HTTP read timeout
        # must be longer than that server-side wait, otherwise every idle poll
        # can raise ReadTimeout even when Telegram is healthy.
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=40.0, write=15.0, pool=10.0)
        )
        self.paused = False
        self.commands = {}

    async def close(self):
        await self.client.aclose()

    async def call(self, method, payload=None):
        if not self.token:
            return None
        response = await self.client.post(
            f"https://api.telegram.org/bot{self.token}/{method}",
            json=payload or {},
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            # Avoid logging the bot token, which is embedded in Telegram URLs.
            raise RuntimeError(f"Telegram API call {method} failed")
        return data.get("result")

    async def send(self, text, chat_id=None):
        chat = str(chat_id or self.chat_id)
        if not self.token or not chat:
            return False
        try:
            await self.call(
                "sendMessage",
                {"chat_id": chat, "text": text, "disable_web_page_preview": True},
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Telegram send failed (%s)", type(exc).__name__)
            return False

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
                # A timeout is recoverable; keep the polling task alive without
                # emitting a full traceback for a routine long-poll delay.
                log.warning("Telegram long poll timed out; retrying")
                await asyncio.sleep(1)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                log.warning("Telegram transport error (%s); retrying", type(exc).__name__)
                await asyncio.sleep(3)
            except Exception:
                log.exception("Telegram polling error")
                await asyncio.sleep(3)
