# Final Test Report

Automated verification in the packaged source:

```text
15 passed
JavaScript syntax check: passed
Python compile check: passed
```

The suite covers:
- feature generation and regime detection
- model fit/predict
- 90% threshold-gate behaviour
- backtest calculations
- repository CURRENT -> STALE -> CURRENT transitions
- dependency change detection
- security scanning
- `.git` exclusion during repository scans
- FastAPI bootstrap contract and lazy first paint
- listed-security search/catalog contract including BSE parser coverage
- model-bound environment fingerprint invalidation and external-audit isolation

Manual smoke flow used during development:

1. Start with `python -m uvicorn app.main:app`.
2. Open `http://127.0.0.1:8000`.
3. Analyze a stock at 5m/15m/30m/60m/1d.
4. Review model gate, regime, risk, news context and backtest.
5. Open Repository Health and accept a baseline.
6. Simulate an overnight model/dependency change.
7. Observe `STALE` and `FULL` revalidation impact.
8. Analyze again and observe `REVALIDATE` when the model environment is stale.
9. Accept the new baseline; the prediction-affecting environment fingerprint changes and the next analysis automatically retrains before producing a fresh decision.
10. Browse/search the exchange-backed directory; the first page stays fast because the full catalogue is loaded only when requested, and watchlist quotes are refreshed on demand rather than during initial paint.

The final package does not claim that every Yahoo-listed security was exercised live inside the build sandbox; outbound market connectivity is environment-dependent. The provider is designed to use live Yahoo data on the user's machine, recent disk cache when available, and an explicit offline fallback only when `ALLOW_FALLBACK=true` is deliberately enabled.
