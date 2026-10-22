"""Minimal asynchronous Telegram Bot API client and polling command router."""
from __future__ import annotations
import asyncio, logging
import httpx
log=logging.getLogger(__name__)
class TelegramService:
    def __init__(self,token:str,chat_id:str="",admin_ids=()):self.token=token;self.chat_id=str(chat_id);self.admin_ids=set(admin_ids);self.offset=0;self.client=httpx.AsyncClient(timeout=20);self.paused=False;self.commands={}
    async def close(self):await self.client.aclose()
    async def call(self,method,payload=None):
        if not self.token:return None
        r=await self.client.post(f"https://api.telegram.org/bot{self.token}/{method}",json=payload or {});r.raise_for_status();d=r.json()
        if not d.get("ok"):raise RuntimeError(f"Telegram API failure: {d}")
        return d.get("result")
    async def send(self,text,chat_id=None):
        cid=str(chat_id or self.chat_id)
        if not self.token or not cid:return False
        try:await self.call("sendMessage",{"chat_id":cid,"text":text,"disable_web_page_preview":True});return True
        except Exception:log.exception("Telegram send failed");return False
    async def poll(self,handler):
        while True:
            try:
                updates=await self.call("getUpdates",{"offset":self.offset,"timeout":20,"allowed_updates":["message","callback_query"]}) or []
                for u in updates:
                    self.offset=max(self.offset,int(u["update_id"])+1)
                    if "message" in u: await handler(u["message"])
                    elif "callback_query" in u:
                        await self.call("answerCallbackQuery",{"callback_query_id":u["callback_query"]["id"]})
            except asyncio.CancelledError:raise
            except Exception:log.exception("Telegram polling error");await asyncio.sleep(3)
