# India Candle AI

India Candle AI is a working stock-analysis prototype adapted for the AfterCode **Missing Update Window** challenge. The core product remains market prediction; the adaptation adds an environment-aware trust chain around the prediction.

## Core market product

- Searchable Indian listed-security universe (NSE equity + NSE SME + BSE active-equity discovery when reachable; public symbol/name resolution is extended with Yahoo search).
- Yahoo Finance market-data adapter with structured chart/history retrieval, in-memory + disk cache, and `.NS` / `.BO` resolution.
- Timeframes: 5m, 15m, 30m, 60m and 1d.
- Feature engineering: returns, candle structure, ATR, RSI, EMA structure, MACD, Bollinger position, volatility, volume, VWAP and session context.
- Chronological validation rather than random time-series shuffling.
- Automatic threshold optimization subject to a **90% selective-signal precision gate**.
- Market-regime detection, deterministic explainability, risk engine, historical backtest and buy-and-hold comparison.
- Model caching/versioning, environment-aware retraining, signal journal and watchlist.
- Market-data freshness is evaluated separately from repository freshness.

## TrustGraph adaptation

The application has one coherent trust decision:

```text
Market data freshness
        +
Model validation / 90% gate
        +
Market regime / volatility
        +
Repository freshness (when model-bound)
        +
Security / dependency state
        ↓
     TRUSTGRAPH
        ↓
BUY / SELL / HOLD / REVALIDATE
```

A BUY/SELL signal is not presented as trusted when the model-quality gate fails, market data is stale, or the model-bound repository is stale. The system deliberately abstains instead of inventing confidence. When a prediction-affecting code/dependency component changes and the new baseline is accepted, the model cache is invalidated by a prediction-environment fingerprint and the next analysis retrains.

## Repository Health: what Clone & Monitor actually does

Repository Health is **generic**. It is not limited to stock-market repositories.

1. Clone any public GitHub repository into an isolated local snapshot.
2. Create an accepted baseline consisting of the repository fingerprint, file manifest, component fingerprints, dependency state and accepted security findings.
3. Check or refresh the repository later.
4. Detect added, modified and removed files, dependency changes, security/code-quality findings and change impact.
5. Decide whether revalidation is audit-only, targeted, model+data, or full.
6. Keep an audit trail of source changes, scans and accepted baselines.
7. Only when the user explicitly binds an audited repository to model trust does repository state gate stock predictions.

The application never executes the monitored repository code.

## Live market data

The competition build uses live/cached market data and does not depend on an application API key. If a Yahoo Finance request fails, the UI reports that market history is unavailable or cached; it does not label the product as a demo. An explicit offline fallback can be enabled for testing with `ALLOW_FALLBACK=true`, but it is disabled by default.

The directory is intentionally broader than a fixed watchlist: search and Browse Directory use the refreshed exchange universe, including small/SME names when the exchange catalogue is reachable. Not every listed security necessarily has intraday history available from the market-data provider. The directory can therefore contain a security that is selectable but whose requested 5m/15m history is unavailable. The application reports that condition instead of silently changing the timeframe.

## Run

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app
```

Open `http://127.0.0.1:8000`.

For judging, use the command above without `--reload`.

## Recommended judging flow

1. Search any stock, choose 5m/15m/30m/60m/1d and run **ANALYZE STOCK**.
2. Explain the validation gate, confidence, regime, risk and backtest.
3. Open **Repository Health** and explain that the repository scanner is generic.
4. Clone any public GitHub repository and show **EXTERNAL AUDIT**.
5. Accept its baseline, modify/refresh it, and show change impact, dependency/security state and revalidation depth.
6. For the actual model environment, return to the model workspace, accept a baseline, simulate an overnight update and show `STALE → REVALIDATE → CURRENT`.

## Safety / scope

Paper analysis only. No orders are placed. A validation precision gate is a quality control, not a guarantee of future returns.


## GitHub + Render deployment

This is a FastAPI application, so GitHub Pages alone cannot run the server. Push this repository to GitHub and deploy the web service with the included `render.yaml`. See `DEPLOYMENT.md`.
