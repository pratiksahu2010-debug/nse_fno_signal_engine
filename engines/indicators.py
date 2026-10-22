"""Causal indicator calculations over CLOSED candles only."""
from __future__ import annotations
import numpy as np
import pandas as pd

def frame(candles):
    if isinstance(candles,pd.DataFrame): return candles.copy()
    return pd.DataFrame([c.as_dict() if hasattr(c,"as_dict") else dict(c) for c in candles])

def add_indicators(candles):
    d=frame(candles)
    if d.empty:return d
    d=d.sort_values("ts").drop_duplicates("ts",keep="last").reset_index(drop=True)
    for col in ("open","high","low","close","volume"): d[col]=pd.to_numeric(d[col],errors="coerce")
    c,h,l=d.close,d.high,d.low
    d["ema9"]=c.ewm(span=9,adjust=False).mean(); d["ema21"]=c.ewm(span=21,adjust=False).mean()
    prev=c.shift(1); tr=pd.concat([(h-l),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    d["atr14"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    up=h.diff(); down=-l.diff(); plus=np.where((up>down)&(up>0),up,0.0); minus=np.where((down>up)&(down>0),down,0.0)
    atr=d["atr14"].replace(0,np.nan)
    pdi=100*pd.Series(plus,index=d.index).ewm(alpha=1/14,adjust=False).mean()/atr
    mdi=100*pd.Series(minus,index=d.index).ewm(alpha=1/14,adjust=False).mean()/atr
    d["plus_di"]=pdi; d["minus_di"]=mdi; dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan); d["adx14"]=dx.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    delta=c.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean(); loss=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    d["rsi14"]=100-100/(1+gain/loss.replace(0,np.nan))
    d["roc10"]=c.pct_change(10)*100
    d["er10"]=c.diff(10).abs()/c.diff().abs().rolling(10).sum().replace(0,np.nan)
    d["vol_sma20"]=d.volume.rolling(20,min_periods=5).mean(); d["rvol"]=d.volume/d.vol_sma20.replace(0,np.nan)
    d["vwap"]=((h+l+c)/3*d.volume).groupby(pd.to_datetime(d.ts).dt.date).cumsum()/d.volume.groupby(pd.to_datetime(d.ts).dt.date).cumsum().replace(0,np.nan)
    d["body_ratio"]=(c-d.open).abs()/(h-l).replace(0,np.nan)
    d["clv"]=((c-l)-(h-c))/(h-l).replace(0,np.nan)
    d["tr"]=tr; d["tr_atr"]=tr/atr
    d["donchian_high20"]=h.shift(1).rolling(20,min_periods=10).max(); d["donchian_low20"]=l.shift(1).rolling(20,min_periods=10).min()
    # Causal adaptive step state; thresholds only use ATR known at the candle close.
    steps=[]; state=0; level=np.nan
    for i,row in d.iterrows():
        close=float(row.close); a=row.atr14
        if not np.isfinite(a) or a<=0: steps.append(np.nan); continue
        if not np.isfinite(level): level=close; state=0
        if close>level+0.35*a: level=close-0.25*a; state=1
        elif close<level-0.35*a: level=close+0.25*a; state=-1
        steps.append(level)
    d["step_line"]=steps; d["step_state"]=[1 if i>0 and d.close.iloc[i]>d.step_line.iloc[i] else -1 if i>0 and d.close.iloc[i]<d.step_line.iloc[i] else 0 for i in range(len(d))]
    return d
