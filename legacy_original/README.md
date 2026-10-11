# AI Multi-Stock Price Predictor & Sentiment System

A Tkinter desktop app that scrapes real market data, scrapes real news,
scores sentiment, engineers technical features, trains/validates four
regression models, and predicts the next trading day's price with an
honest performance report (no fabricated accuracy numbers).

## 1. Install

Requires Python 3.9+. Tkinter ships with standard Python on Windows/Mac;
on Linux you may need `sudo apt install python3-tk` first.

```bash
cd stock_predictor
pip install -r requirements.txt
```

## 2. Run

```bash
python app.py
```

## 3. Use

1. Type a stock symbol (e.g. `AAPL`, `MSFT`, `TSLA`, `NVDA`). For non-US
   listings, add the stooq suffix yourself, e.g. `TCS.IN`, `RELIANCE.IN`,
   `VOD.UK` — if you type a plain ticker with no dot, `.us` is assumed.
2. Pick a data range (10 / 30 / 60 / 100 / 250 days).
3. Click **ANALYZE**. The app will, in order:
   - `requests.get()` the market-data source and check for **HTTP 200**
   - Parse the response into a **pandas DataFrame**
   - `requests.get()` a news search feed and parse it with
     **BeautifulSoup** (`html.parser`)
   - Score each headline's sentiment
   - Engineer features: return, high‑low range, MA5/MA10/MA20, EMA12,
     rolling volatility, RSI, and a recency-weighted sentiment feature
   - Train **Linear Regression, Polynomial Regression, Random Forest,
     and Gradient Boosting** on a **chronological** (not shuffled)
     train/test split, so no future information leaks into training
   - Report **MAE, RMSE, R², and directional accuracy** for each model
     and pick the best one by RMSE
   - Predict the next trading day's price, show a **BUY / HOLD / SELL**
     signal, and a *simulated* paper-trade entry/target/stop-loss

## Why no 95% accuracy claim?

Real stock prices are close to a random walk in the short term, so a
credible project reports honest, back-tested numbers instead of a
manufactured accuracy figure. This app always shows the model's real
MAE/RMSE/R²/directional accuracy on data it never trained on.

## Data sources

- **Market data**: [stooq.com](https://stooq.com) daily OHLCV CSV export
  (simple, reliable, no JavaScript rendering required by the scraper).
- **News**: Google News RSS search results for the company name.

Both are free public endpoints, but they can occasionally rate-limit,
change format, or have no data for an obscure ticker — the app surfaces
these as readable error messages and logs every step in the "Pipeline
Log" panel at the bottom of the window.

## Project structure

```
stock_predictor/
├── app.py            # everything: scraping, sentiment, features, models, GUI
├── requirements.txt
└── README.md
```

Everything lives in one file for easy running/grading, but it is
internally organized into clear classes — `DataFetcher`,
`SentimentAnalyzer`, `FeatureEngineer`, `ModelEngine`, and
`StockPredictorApp` — mirroring the pipeline architecture:

```
Symbol -> Scrape (requests+BS4) -> Pandas DataFrame -> Feature Engineering
       -> News Sentiment -> Model Training (4 models, time-based split)
       -> Model Comparison -> Next-Price Prediction -> BUY/HOLD/SELL -> GUI
```

## Disclaimer

Educational project. Nothing here is financial advice, and the
"paper-trade plan" is simulated only — no real trades are placed.
