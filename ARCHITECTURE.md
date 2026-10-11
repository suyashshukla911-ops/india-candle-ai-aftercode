# Architecture — India Candle AI

```text
                         INDIA CANDLE AI
                               |
                 +-------------+--------------+
                 |                            |
           MARKET INTELLIGENCE          REPOSITORY HEALTH
                 |                            |
      security catalogue + resolver     full fingerprint
      live/cached OHLCV                 component hashes
      feature engineering               dependency changes
      regime detection                  security/code checks
      model selection                  change impact
      threshold optimizer                    |
      confidence + risk                      |
                 |                            |
                 +-------------+--------------+
                               |
                          TRUSTGRAPH
                               |
             +-----------------+-----------------+
             |                 |                 |
          TRUSTED            HOLD           REVALIDATE
        BUY / SELL       no trade edge      stale input
```

## Market flow
1. The user searches the listed-security directory or enters a symbol/company name.
2. The provider resolves the instrument and attempts live market history, then a recent disk cache.
3. Features are built from OHLCV and session context.
4. The model evaluates chronological validation, optimizes the signal threshold and trains the next-return/high/low/EOD regressors.
5. The regime, risk engine, news context and model gate are combined into TrustGraph.

## Repository flow
1. A monitored source is cloned/selected.
2. The monitor fingerprints tracked files and component groups while excluding `.git`, virtual environments and generated runtime directories.
3. A baseline stores the accepted fingerprint, file manifest, component hashes, dependency state and accepted findings.
4. Later checks compare the live repository with the baseline and classify change impact.
5. External repositories are audit-only. A repository only gates the stock model after explicit `BIND TO MODEL TRUST`.

## Freshness boundary
Repository freshness, market-data freshness and model-validation quality are independent checks. A stale repository or stale market history prevents a result from being treated as trusted.

## Performance
Market context calls are cached for five minutes, models are cached by symbol/timeframe/dataset fingerprint, and CPU-heavy fitting runs in the FastAPI worker thread so the browser remains responsive.
