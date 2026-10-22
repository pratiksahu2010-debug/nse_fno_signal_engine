"""Upstox Market Data Feed V3 transport boundary.

Upstox V3 feed uses protobuf binary frames. This module deliberately refuses to treat raw
binary data as JSON. Install the official Upstox SDK/protobuf model and implement decode_frame
for the currently published schema before enabling live WebSocket mode. The production app
uses REST closed-candle polling by default, which remains signal-only and does not fake ticks.
"""
from __future__ import annotations
import logging
log=logging.getLogger(__name__)
class UpstoxWebSocketAdapter:
    def __init__(self,token,on_tick):self.token=token;self.on_tick=on_tick;self.connected=False
    async def run(self,instrument_keys):
        if not instrument_keys:raise ValueError("No instrument keys to subscribe")
        raise RuntimeError("V3 protobuf decoder not bundled: use REST candle polling or add the current official Upstox MarketDataFeedV3 protobuf schema/SDK. WS is intentionally not falsely marked connected.")
