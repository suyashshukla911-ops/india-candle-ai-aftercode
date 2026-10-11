# Enhancement inventory

Implemented in this build:

1. Unified API client with timeout and one retry.
2. Responsive FastAPI worker-thread model execution.
3. Cached model reuse and persisted `joblib` models.
4. Yahoo structured data adapter with NSE/BSE resolution.
5. Yahoo symbol search for many tickers.
6. Disk cache with explicit offline fallback switch.
7. Yahoo outage circuit breaker to prevent repeated lag.
8. Technical feature expansion: RSI, ATR, EMAs, MACD, Bollinger position, VWAP, volume z-score, momentum, time/session features.
9. Market-regime detection.
10. Dynamic threshold optimization under a 90% selective-signal precision constraint.
11. Confidence / TrustGraph scoring.
12. Deterministic signal explainability.
13. Validation-window backtest.
14. Model-vs-buy-and-hold comparison.
15. Signal journal.
16. Model versioning.
17. Data freshness gate.
18. Repository freshness gate.
19. Component-level repository fingerprints.
20. Change-impact analysis.
21. Overnight update simulation.
22. Dependency-change detection.
23. Security/code-quality scanner.
24. Optional Bandit and pip-audit integration.
25. SQLite audit trail.
26. Public GitHub clone without an API key.
27. GitHub webhook endpoint with optional HMAC validation.
28. Optional Basic Auth for production direction.
29. Canvas chart (no Plotly CDN dependency).
30. One-click `RUN FULL ANALYSIS`.
31. Light responsive dashboard.
32. `REVALIDATE` state integrated into the stock-prediction decision.
33. Original legacy implementation preserved under `legacy_original/`.
