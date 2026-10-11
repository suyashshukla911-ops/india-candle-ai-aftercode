# Runbook

## Install
```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
```

## Start
```powershell
python -m uvicorn app.main:app
```

Open `http://127.0.0.1:8000`.

Do not use `--reload` during the competition demonstration; the monitored repository is intentionally mutable.

## Market workflow
1. Open **Market Predictor**.
2. Search the stock by symbol or company name; use **BROWSE LIST** for the full indexed listed-security directory.
3. Pick 5m, 15m, 30m, 60m or 1d.
4. Run **ANALYZE STOCK**.
5. Review validation precision, confidence, regime, risk, news context and backtest.
6. Use **RETRAIN MODEL** only when you explicitly want to rebuild the cached model for the current dataset.
7. Use **RUN FULL ANALYSIS** when you want a fresh market-data pull before evaluating the current result.

## Repository workflow — any public GitHub repository
1. Open **Repository Health**.
2. Paste any public GitHub repository URL and click **CLONE & MONITOR**.
3. Explain that this is an **EXTERNAL AUDIT** target and does not automatically affect stock-model trust.
4. Click **SCAN & ACCEPT BASELINE**. The baseline is the accepted repository fingerprint + manifest + component hashes + dependency/security state.
5. Later use **CHECK FOR UPDATES** or **REFRESH REMOTE**.
6. Review added/modified/removed files, dependency changes, security findings and required revalidation depth.
7. Only click **BIND TO MODEL TRUST** when the repository is actually part of the market-model environment.

## AfterCode demonstration
1. Return to the model workspace with **RETURN TO MODEL WORKSPACE**.
2. **SCAN & ACCEPT BASELINE**.
3. **SIMULATE OVERNIGHT UPDATE**.
4. Show `STALE`, changed model/dependency files and `FULL` revalidation.
5. Return to Market Predictor and run the analysis again. The trusted action becomes `REVALIDATE` while the repository is stale.
6. Accept the new baseline.
7. Run a fresh analysis.

## Manual change test
Open:
`workspace\monitored_repository\app\ml\model.py`

Add a comment, save, then use **CHECK FOR UPDATES**. The repository should become `STALE` and the change should be classified under the model component.

## Market-data behaviour
The normal path is live structured market data plus a recent cache. If the requested instrument/timeframe has no market history, the application reports the limitation instead of silently switching the requested timeframe.
