# India Candle AI — Model Policy

## 1. What the model predicts
The core engine learns from OHLCV history and technical/session features and produces:
- next-candle return/close scenario
- next-candle high/low scenario
- same-session EOD scenario
- probability of upward movement
- BUY / SELL / HOLD / REVALIDATE

## 2. Validation
Validation is chronological; rows are not shuffled. A validation window is held out from the end of the historical sample.

## 3. 90% gate
The application does **not** claim that overall direction accuracy is 90%.

Instead, trusted BUY/SELL signals require selective validation precision >= `SIGNAL_PRECISION_GATE` (default 90%).

The threshold is automatically optimized across a grid. The objective is:

> maximize signal coverage subject to validation precision >= 90%.

When no threshold satisfies the gate, the application records a gate failure and deliberately uses HOLD instead of inventing confidence.

## 4. Trust decision
A BUY/SELL signal can be treated as trusted only when:
1. the model validation gate passes;
2. market data is current;
3. the model-bound repository is current;
4. no other trust check forces revalidation.

When repository or market-data freshness fails, the action becomes `REVALIDATE`. If a prediction-affecting repository update is accepted, the model environment fingerprint changes and the next analysis retrains under the new environment before producing a fresh trusted decision.

## 5. Model version
Every training run creates a deterministic model version from:
- feature list
- threshold
- classifier choice
- dataset fingerprint
- prediction-environment fingerprint (prediction-affecting repository components/dependencies)
- gate setting

When a model-bound repository changes in a prediction-affecting component, the next accepted baseline changes the environment fingerprint and the cached model is invalidated automatically. Presentation-only or documentation-only changes do not force an unnecessary retrain.

## 6. Risk
Risk is calculated from ATR/realized volatility and is presented separately from the directional model. Stop loss / take profit are model-derived reference levels, not guaranteed execution prices.

## 7. Limitations
Financial markets are stochastic. No metric shown by the application guarantees future profit or future accuracy. A 90% precision gate is a historical quality threshold for selective signals, not a promise of future returns.
