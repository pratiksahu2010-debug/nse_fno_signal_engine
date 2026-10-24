from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from engines.candidates import make_candidate,on_closed_candle
from engines.option_chain import assess_chain,option_liquidity_ok

def test_option_chain_empty_fails_closed():
    x=assess_chain([],"LONG");assert not x.available and x.adjustment==0

def test_option_chain_pcr_and_walls():
    rows=[{"strike_price":100,"call_options":{"market_data":{"oi":100}},"put_options":{"market_data":{"oi":200}}},{"strike_price":110,"call_options":{"market_data":{"oi":300}},"put_options":{"market_data":{"oi":100}}}]
    x=assess_chain(rows,"LONG");assert x.available and x.pcr==0.75 and x.call_wall==110 and x.put_wall==100

def test_candidate_levels_and_entry_lifecycle():
    c=SimpleNamespace(ts=datetime.now(timezone.utc),close=100,high=101,low=99)
    x=make_candidate("ABC","LONG","CORE","A1",80,c,2)
    assert x.stop<100 and x.t1>100 and x.t2>x.t1
    nextbar=SimpleNamespace(ts=c.ts+timedelta(minutes=5),close=100.1,high=100.4,low=99.9)
    result=on_closed_candle(x,nextbar);assert result=="ENTERED" and x.status=="ACTIVE"

def test_option_liquidity_rejects_wide_spread():
    ok,why=option_liquidity_ok({"market_data":{"ltp":100,"bid_price":90,"ask_price":110,"oi":500000,"volume":50000}})
    assert not ok and why=="wide_spread"

def test_targets_account_for_worst_entry_zone_edge():
    candle=SimpleNamespace(ts=datetime.now(timezone.utc),close=100,high=101,low=99)
    x=make_candidate("ABC","LONG","CORE","A1",80,candle,2)
    conservative_entry=x.entry_high
    risk=conservative_entry-x.stop
    assert abs((x.t1-conservative_entry)/risk-1.5) < 1e-9
    assert abs((x.t2-conservative_entry)/risk-2.5) < 1e-9
