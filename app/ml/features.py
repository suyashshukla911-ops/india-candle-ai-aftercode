
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = [
    "return_1","return_2","return_5","return_10","return_20",
    "range_pct","body_pct","upper_wick_pct","lower_wick_pct",
    "atr_pct","rsi_14","ema_9_gap","ema_20_gap","ema_50_gap","ema_spread",
    "macd","macd_signal","macd_hist","bb_pos","volatility_20","volatility_60",
    "volume_z","volume_ratio","vwap_gap","day_position","day_sin","day_cos",
    "dow_sin","dow_cos","session_gap","close_session_high_gap","close_session_low_gap",
    "momentum_10","momentum_20","trend_strength","volatility_regime"
]

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100/(1+rs)).fillna(50)

def build_features(df: pd.DataFrame, context: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    d = df.copy().sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if d.empty:
        return d
    for c in ["open","high","low","close","volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
    prev = d["close"].shift(1)

    for n in [1,2,5,10,20]:
        d[f"return_{n}"] = d["close"].pct_change(n)
    d["range_pct"] = (d["high"] - d["low"]) / d["close"].replace(0, np.nan)
    d["body_pct"] = (d["close"] - d["open"]) / d["close"].replace(0, np.nan)
    top = d[["open","close"]].max(axis=1)
    bottom = d[["open","close"]].min(axis=1)
    d["upper_wick_pct"] = (d["high"] - top) / d["close"].replace(0, np.nan)
    d["lower_wick_pct"] = (bottom - d["low"]) / d["close"].replace(0, np.nan)

    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev).abs(),
        (d["low"] - prev).abs()
    ], axis=1).max(axis=1)
    d["atr_pct"] = tr.rolling(14).mean() / d["close"].replace(0, np.nan)

    ema9 = d["close"].ewm(span=9, adjust=False).mean()
    ema20 = d["close"].ewm(span=20, adjust=False).mean()
    ema50 = d["close"].ewm(span=50, adjust=False).mean()
    d["rsi_14"] = rsi(d["close"])
    d["ema_9_gap"] = d["close"]/ema9 - 1
    d["ema_20_gap"] = d["close"]/ema20 - 1
    d["ema_50_gap"] = d["close"]/ema50 - 1
    d["ema_spread"] = ema9/ema20 - 1

    macd = ema9 - ema20
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    d["macd"] = macd / d["close"].replace(0, np.nan)
    d["macd_signal"] = macd_signal / d["close"].replace(0, np.nan)
    d["macd_hist"] = (macd - macd_signal) / d["close"].replace(0, np.nan)

    rolling_mean = d["close"].rolling(20).mean()
    rolling_std = d["close"].rolling(20).std()
    upper = rolling_mean + 2 * rolling_std
    lower = rolling_mean - 2 * rolling_std
    d["bb_pos"] = (d["close"] - lower) / (upper - lower).replace(0, np.nan)

    ret = d["return_1"]
    d["volatility_20"] = ret.rolling(20).std()
    d["volatility_60"] = ret.rolling(60).std()
    vol_mean = d["volume"].rolling(30).mean()
    vol_std = d["volume"].rolling(30).std().replace(0, np.nan)
    d["volume_z"] = (d["volume"] - vol_mean) / vol_std
    d["volume_ratio"] = d["volume"] / vol_mean.replace(0, np.nan)

    typical = (d["high"] + d["low"] + d["close"]) / 3
    sess = d["timestamp"].dt.date
    pv = typical * d["volume"].fillna(0)
    cum_pv = pv.groupby(sess).cumsum()
    cum_v = d["volume"].groupby(sess).cumsum().replace(0, np.nan)
    vwap = cum_pv / cum_v
    d["vwap_gap"] = d["close"] / vwap - 1

    minutes = d["timestamp"].dt.hour * 60 + d["timestamp"].dt.minute
    d["day_position"] = ((minutes - 555).clip(lower=0, upper=375))/375.0
    d["day_sin"] = np.sin(2*np.pi*d["day_position"])
    d["day_cos"] = np.cos(2*np.pi*d["day_position"])
    dow = d["timestamp"].dt.dayofweek
    d["dow_sin"] = np.sin(2*np.pi*dow/5)
    d["dow_cos"] = np.cos(2*np.pi*dow/5)

    session_open = d.groupby(sess)["open"].transform("first")
    session_close = d.groupby(sess)["close"].last()
    prev_session_close = pd.Series(sess).map(session_close.shift(1)).to_numpy()
    d["session_gap"] = session_open.to_numpy() / prev_session_close - 1
    sh = d.groupby(sess)["high"].cummax()
    sl = d.groupby(sess)["low"].cummin()
    d["close_session_high_gap"] = d["close"]/sh - 1
    d["close_session_low_gap"] = d["close"]/sl - 1

    d["momentum_10"] = d["close"]/d["close"].shift(10) - 1
    d["momentum_20"] = d["close"]/d["close"].shift(20) - 1
    d["trend_strength"] = (d["ema_9_gap"].abs() + d["ema_20_gap"].abs() + d["macd_hist"].abs())
    vol_med = d["volatility_20"].rolling(80).median()
    d["volatility_regime"] = d["volatility_20"] / vol_med.replace(0, np.nan)

    # Optional market context from Yahoo index candles.
    if context:
        for name, ctx in context.items():
            if ctx is None or ctx.empty:
                d[f"{name}_return"] = 0.0
                continue
            c = ctx[["timestamp","close"]].sort_values("timestamp").copy()
            c[f"{name}_return"] = c["close"].pct_change()
            c = c[["timestamp", f"{name}_return"]]
            d = pd.merge_asof(
                d.sort_values("timestamp"), c, on="timestamp",
                direction="backward", tolerance=pd.Timedelta("30min")
            )
            d[f"{name}_return"] = d[f"{name}_return"].fillna(0.0)
            # Context columns are not part of the required baseline features;
            # they are included separately by engine when available.
    return d.replace([np.inf,-np.inf], np.nan)

def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    sess = d["timestamp"].dt.date
    d["next_return"] = d["close"].shift(-1)/d["close"] - 1
    d["next_high_return"] = d["high"].shift(-1)/d["close"] - 1
    d["next_low_return"] = d["low"].shift(-1)/d["close"] - 1
    d["direction"] = (d["next_return"] > 0).astype(int)
    session_close = d.groupby(sess)["close"].transform("last")
    d["eod_return"] = session_close/d["close"] - 1
    d["is_session_last"] = d["timestamp"].eq(d.groupby(sess)["timestamp"].transform("max"))
    return d

def prepare_training_frame(df: pd.DataFrame, context: dict[str,pd.DataFrame] | None=None) -> pd.DataFrame:
    d = add_targets(build_features(df, context=context))
    d = d.loc[~d["is_session_last"]].copy()
    d = d.dropna(subset=FEATURES + ["next_return","next_high_return","next_low_return","direction","eod_return"])
    return d

def regime_from_row(row: pd.Series, history: pd.DataFrame) -> dict[str, str]:
    trend = float(row.get("trend_strength", 0))
    vol = float(row.get("volatility_regime", 1))
    momentum = float(row.get("momentum_10", 0))
    if vol >= 1.7:
        regime = "HIGH VOLATILITY"
    elif trend >= 0.0045 and abs(momentum) >= 0.003:
        regime = "TRENDING UP" if momentum > 0 else "TRENDING DOWN"
    elif trend < 0.0015:
        regime = "SIDEWAYS"
    else:
        regime = "TRANSITION"
    return {
        "regime": regime,
        "volatility": "HIGH" if vol >= 1.4 else ("LOW" if vol <= 0.75 else "NORMAL"),
        "momentum": "POSITIVE" if momentum > 0.001 else ("NEGATIVE" if momentum < -0.001 else "FLAT"),
    }

def explain_row(row: pd.Series, signal: str, gate_pass: bool) -> dict[str, list[str]]:
    reasons: list[str] = []
    risks: list[str] = []
    ema_gap = float(row.get("ema_9_gap", 0) or 0)
    ema_spread = float(row.get("ema_spread", 0) or 0)
    macd_hist = float(row.get("macd_hist", 0) or 0)
    rsi_value = float(row.get("rsi_14", 50) or 50)
    volume_z = float(row.get("volume_z", 0) or 0)
    momentum = float(row.get("momentum_10", 0) or 0)
    vol_regime = float(row.get("volatility_regime", 1) or 1)

    bullish = []
    bearish = []
    if ema_gap > 0 and ema_spread > 0:
        bullish.append("Price is above its short EMAs and the EMA structure is aligned upward.")
    if ema_gap < 0 and ema_spread < 0:
        bearish.append("Price is below its short EMAs and the EMA structure is aligned downward.")
    if macd_hist > 0:
        bullish.append("MACD histogram supports upward momentum.")
    elif macd_hist < 0:
        bearish.append("MACD histogram supports downward momentum.")
    if rsi_value > 55:
        bullish.append("RSI is above the neutral zone.")
    elif rsi_value < 45:
        bearish.append("RSI is below the neutral zone.")
    if volume_z > 0.75:
        reasons.append("Volume is elevated relative to its recent baseline.")
    if momentum > 0:
        bullish.append("Short-horizon momentum is positive.")
    elif momentum < 0:
        bearish.append("Short-horizon momentum is negative.")

    if signal == "BUY":
        reasons.extend(bullish[:4])
        risks.extend(bearish[:2])
    elif signal == "SELL":
        reasons.extend(bearish[:4])
        risks.extend(bullish[:2])
    elif signal == "HOLD":
        reasons.extend((bullish + bearish)[:3])
        if len(bullish) and len(bearish):
            risks.append("Bullish and bearish evidence is mixed; the model is holding instead of forcing a trade.")
        else:
            risks.append("The directional evidence is not strong enough to justify a new position.")
    else:
        reasons.extend((bullish + bearish)[:3])

    if rsi_value >= 70:
        risks.append("RSI is in an elevated zone; reversal risk is higher.")
    elif rsi_value <= 30:
        risks.append("RSI is in a depressed zone; volatility/reversal risk is higher.")
    if vol_regime > 1.6:
        risks.append("Volatility is elevated versus the recent baseline.")
    if not gate_pass:
        risks.append("The 90% selective-signal precision gate is not satisfied.")
    if signal == "REVALIDATE":
        risks.append("The environment or market-data freshness gate requires revalidation.")
    return {"reasons": reasons[:5] or ["No single feature cluster dominates the current setup."], "risks": risks[:5] or ["No major rule-based risk flag."]}

