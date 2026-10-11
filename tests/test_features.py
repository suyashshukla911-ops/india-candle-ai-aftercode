
import numpy as np
import pandas as pd
from app.ml.features import FEATURES, prepare_training_frame, regime_from_row

def candles(n=900):
    ts=pd.date_range("2026-07-01 09:15",periods=n,freq="15min",tz="Asia/Kolkata")
    rng=np.random.default_rng(4)
    noise=rng.normal(0,0.05,n)
    close=100+np.cumsum(noise+0.018)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)+0.08
    low=np.minimum(open_,close)-0.08
    volume=rng.integers(1000,10000,n)
    return pd.DataFrame({"timestamp":ts,"open":open_,"high":high,"low":low,"close":close,"volume":volume})

def test_features_numeric():
    out=prepare_training_frame(candles())
    assert set(FEATURES).issubset(out.columns)
    assert len(out)>200
    assert np.isfinite(out[FEATURES].to_numpy()).all()

def test_regime_available():
    out=prepare_training_frame(candles())
    r=regime_from_row(out.iloc[-1],out)
    assert r["regime"] in {"TRENDING UP","TRENDING DOWN","HIGH VOLATILITY","SIDEWAYS","TRANSITION"}
