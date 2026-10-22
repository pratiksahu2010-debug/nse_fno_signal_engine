import asyncio

from market_data.instruments import InstrumentResolver


class FakeREST:
    def __init__(self, rows):
        self.rows = rows

    async def instrument_list(self):
        return self.rows


def test_legacy_tatamotors_resolves_to_current_tmpv_alias():
    resolver = InstrumentResolver(FakeREST([
        {"trading_symbol": "TMPV", "segment": "NSE_EQ", "instrument_key": "NSE_EQ|TMPV"},
        {"trading_symbol": "TMPV26OCTFUT", "segment": "NSE_FO", "instrument_key": "NSE_FO|TMPV26OCTFUT"},
    ]))
    assert asyncio.run(resolver.resolve("TATAMOTORS", "NSE_EQ")) == "NSE_EQ|TMPV"


def test_normal_symbol_resolves_to_preferred_segment():
    resolver = InstrumentResolver(FakeREST([
        {"trading_symbol": "RELIANCE", "segment": "NSE_FO", "instrument_key": "NSE_FO|RELIANCE"},
        {"trading_symbol": "RELIANCE", "segment": "NSE_EQ", "instrument_key": "NSE_EQ|RELIANCE"},
    ]))
    assert asyncio.run(resolver.resolve("RELIANCE", "NSE_EQ")) == "NSE_EQ|RELIANCE"
