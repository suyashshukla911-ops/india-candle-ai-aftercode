# Judging Guide — India Candle AI

## What stayed
The original project is still a stock-analysis and prediction system. The web version is the working application; the legacy Tkinter implementation is preserved under `legacy_original/`.

## What was adapted
The AfterCode Missing Update Window requirement is integrated into the original product instead of replacing it with a generic repository dashboard.

### Demonstration sequence
1. **Market Predictor** → search by company or symbol, or open **BROWSE DIRECTORY** → choose any listed security returned by the exchange-backed directory → 5m/15m/30m/60m/1d → **ANALYZE STOCK**.
2. Show current/next price estimates, signal, confidence, validation, risk, regime and backtest.
3. **Repository Health** → **SCAN & ACCEPT BASELINE**.
4. **SIMULATE OVERNIGHT UPDATE** on the model workspace.
5. Repository becomes **STALE** and impact identifies the changed model/dependency components.
6. Return to **Market Predictor** → the action becomes **REVALIDATE**.
7. Accept the new baseline → return to **CURRENT**.
8. Run the fresh market analysis again; if a prediction-affecting component changed, **MODEL OPERATIONS** shows that the cached model was invalidated and a fresh model was trained for the new environment.

## Generic GitHub repository use case
Repository Health can monitor any public GitHub repository, whether it is a stock system, LMS, API service, web application or any other source tree.

- **Clone & Monitor** creates an isolated snapshot.
- **Baseline** is an accepted cryptographic snapshot and associated manifest/findings.
- **Check for Updates** compares live files against that baseline.
- **Refresh Remote** updates a clean GitHub clone to the latest remote head.
- **Change Impact** classifies the affected component and revalidation depth.
- **Bind to Model Trust** is optional and should only be used when the repository is actually part of the model environment.

## 90% quality gate
The project does not claim that overall market direction accuracy is 90%. Instead, it requires **at least 90% validation precision for the directional signals that it is willing to promote to BUY/SELL**. If the validation evidence does not meet the gate, the system holds rather than fabricating confidence.
