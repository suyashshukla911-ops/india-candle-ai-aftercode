
import numpy as np
import pandas as pd
from app.ml.features import FEATURES, prepare_training_frame
from app.ml.model import CandleModel

def candles(n=1500):
    ts=pd.date_range("2026-07-01 09:15",periods=n,freq="15min",tz="Asia/Kolkata")
    rng=np.random.default_rng(9)
    noise=rng.normal(0,0.015,n)
    signal=np.where(np.arange(n)%16<8,0.025,-0.02)
    close=100+np.cumsum(noise+signal)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)+0.05
    low=np.minimum(open_,close)-0.05
    volume=rng.integers(2000,12000,n)
    return pd.DataFrame({"timestamp":ts,"open":open_,"high":high,"low":low,"close":close,"volume":volume})

def test_model_fit_predict():
    frame=prepare_training_frame(candles())
    model=CandleModel(min_train_rows=240)
    report=model.fit(frame,FEATURES,dataset_fingerprint="test", environment_fingerprint="env-a")
    result=model.predict(frame.iloc[[-1]],float(frame.close.iloc[-1]),0.0,
                         {"regime":"TRENDING UP","volatility":"NORMAL","momentum":"POSITIVE"},
                         repo_current=True,data_current=True)
    assert report.model_version.startswith("v")
    assert report.environment_fingerprint == "env-a"
    assert result["signal"] in {"BUY","SELL","HOLD","REVALIDATE"}
    assert "backtest" in result

def test_threshold_gate_is_explicit():
    y=np.array([0,0,0,1,1,1,1,1,0,0])
    p=np.array([.1,.2,.2,.95,.93,.92,.91,.9,.15,.3])
    returns=np.array([-0.01,-0.01,-0.01,0.01,0.01,0.01,0.01,0.01,-0.01,-0.01])
    t,prec,cov,gate=CandleModel.optimize_threshold(y,p,0.90,actual_returns=returns)
    assert t>=0.55
    assert prec>=0.90
    assert gate is True
