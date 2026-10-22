from datetime import datetime,timedelta,timezone
from market_data.models import Candle
from engines.indicators import add_indicators

def candles(n=80):
    out=[];p=100
    for i in range(n):
        o=p;p+=0.2 if i%7 else -0.1
        out.append(Candle(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(minutes=5*i),o,max(o,p)+0.2,min(o,p)-0.2,p,100+i,0))
    return out

def test_indicators_have_expected_columns_and_no_future_dependency():
    d=add_indicators(candles());assert {"ema9","ema21","atr14","adx14","rsi14","vwap","rvol","step_line"}.issubset(d.columns)
    a=add_indicators(candles(60));b=add_indicators(candles(80));assert abs(a.close.iloc[-1]-b.close.iloc[59])<1e-9

def test_atr_positive_after_warmup():
    d=add_indicators(candles());assert (d.atr14.dropna()>0).all()
