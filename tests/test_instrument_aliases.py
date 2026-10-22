import pytest

from market_data.instruments import InstrumentResolver


class FakeREST:
    def __init__(self, rows):
        self.rows = rows

    async def instrument_list(self):
        return self.rows


@pytest.mark.asyncio
async def test_legacy_tatamotors_resolves_to_current_tmpv_alias():
    resolver = InstrumentResolver(FakeREST([
        {"trading_symbol": "TMPV", "segment": "NSE_EQ", "instrument_key": "NSE_EQ|TMPV"},
        {"trading_symbol": "TMPV26OCTFUT", "segment": "NSE_FO", "instrument_key": "NSE_FO|TMPV26OCTFUT"},
    ]))
    assert await resolver.resolve("TATAMOTORS", "NSE_EQ") == "NSE_EQ|TMPV"


@pytest.mark.asyncio
async def test_normal_symbol_resolves_to_preferred_segment():
    resolver = InstrumentResolver(FakeREST([
        {"trading_symbol": "RELIANCE", "segment": "NSE_FO", "instrument_key": "NSE_FO|RELIANCE"},
        {"trading_symbol": "RELIANCE", "segment": "NSE_EQ", "instrument_key": "NSE_EQ|RELIANCE"},
    ]))
    assert await resolver.resolve("RELIANCE", "NSE_EQ") == "NSE_EQ|RELIANCE"
