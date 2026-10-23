import asyncio

from services.telegram_service import TelegramService


def test_telegram_startup_check_records_success(monkeypatch):
    async def run():
        service = TelegramService("fake-token", "12345")
        async def fake_call(method, payload=None):
            if method == "getMe":
                return {"username": "test_signal_bot"}
            if method == "sendMessage":
                return {"message_id": 1}
            raise AssertionError(method)
        monkeypatch.setattr(service, "call", fake_call)
        try:
            assert await service.startup_check() is True
            state = service.status()
            assert state["bot_username"] == "test_signal_bot"
            assert state["messages_sent"] == 1
            assert state["messages_failed"] == 0
            assert state["last_success_at"]
            assert state["last_error"] is None
        finally:
            await service.close()
    asyncio.run(run())


def test_telegram_send_failure_is_visible(monkeypatch):
    async def run():
        service = TelegramService("fake-token", "bad-chat")
        async def fake_call(method, payload=None):
            raise RuntimeError("sendMessage: Bad Request: chat not found")
        monkeypatch.setattr(service, "call", fake_call)
        try:
            assert await service.send("test") is False
            state = service.status()
            assert state["messages_sent"] == 0
            assert state["messages_failed"] == 1
            assert "chat not found" in state["last_error"]
        finally:
            await service.close()
    asyncio.run(run())


def test_telegram_missing_credentials_are_visible():
    async def run():
        service = TelegramService("", "")
        try:
            assert await service.startup_check() is False
            assert service.status()["last_error"] == "missing_bot_token"
        finally:
            await service.close()
    asyncio.run(run())



def test_telegram_bot_destination_error_is_actionable(monkeypatch):
    async def run():
        service = TelegramService("fake-token", "99999")
        async def fake_call(method, payload=None):
            raise RuntimeError("sendMessage: Forbidden: the bot can't send messages to the bot")
        monkeypatch.setattr(service, "call", fake_call)
        try:
            assert await service.send("test") is False
            error = service.status()["last_error"].lower()
            assert "numeric telegram user id" in error
            assert "group/channel" in error
        finally:
            await service.close()
    asyncio.run(run())
