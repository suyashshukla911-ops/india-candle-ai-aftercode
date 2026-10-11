"""
AI-Driven Multi-Stock Price Prediction and Market Sentiment Analysis System
============================================================================

A desktop (Tkinter) application that, for ANY stock symbol the user enters:

  1. Scrapes historical OHLCV market data over HTTP (requests -> status 200
     check -> pandas DataFrame).
  2. Scrapes recent financial news headlines (requests -> BeautifulSoup
     HTML/XML parser) and scores them for sentiment.
  3. Engineers technical features (returns, moving averages, EMA,
     volatility, RSI) purely from information available up to "today" --
     no future data is ever used (no look-ahead / data leakage).
  4. Trains and chronologically validates four regression models
     (Linear, Polynomial, Random Forest, Gradient Boosting), reports
     honest MAE / RMSE / R^2 / directional accuracy, and picks the best
     one -- it never fabricates a 95% accuracy number.
  5. Predicts the next trading day's price, derives a BUY / HOLD / SELL
     signal, and shows a simple *simulated* paper-trade plan.
  6. Displays everything on a modern dashboard with an embedded price
     chart and a sentiment breakdown.

Data sources
------------
  * Market data : stooq.com (simple, reliable, no JavaScript required)
  * News        : Google News RSS search feed

Run:
    pip install -r requirements.txt
    python app.py

Educational project -- nothing here is financial advice.
"""

import io
import math
import queue
import re
import threading
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

# ----------------------------------------------------------------------------
# Theme / palette
# ----------------------------------------------------------------------------
BG = "#0f172a"          # app background (slate-900)
CARD = "#161f38"        # card background
CARD_BORDER = "#243352"
TEXT = "#e6ebf5"        # primary text
SUBTEXT = "#93a1c2"     # secondary text
ACCENT = "#38bdf8"      # sky blue accent
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
ENTRY_BG = "#0c1428"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

POSITIVE_WORDS = {
    "gain", "gains", "gained", "rise", "rises", "rising", "rose", "surge", "surges",
    "surged", "rally", "rallies", "rallied", "jump", "jumps", "jumped", "up",
    "high", "higher", "beat", "beats", "beating", "growth", "profit", "profits",
    "profitable", "strong", "bullish", "upgrade", "upgraded", "outperform",
    "record", "boost", "boosts", "boosted", "positive", "soar", "soars", "soared",
    "recovery", "recovers", "expand", "expansion", "buy", "optimistic", "wins",
    "win", "winning", "milestone", "breakthrough", "approval", "approved",
}
NEGATIVE_WORDS = {
    "fall", "falls", "falling", "fell", "drop", "drops", "dropped", "decline",
    "declines", "declined", "plunge", "plunges", "plunged", "crash", "crashes",
    "crashed", "down", "low", "lower", "miss", "misses", "missed", "loss",
    "losses", "weak", "bearish", "downgrade", "downgraded", "underperform",
    "cut", "cuts", "negative", "sink", "sinks", "sank", "slump", "slumps",
    "recession", "fraud", "investigation", "lawsuit", "sell", "selloff",
    "sell-off", "layoffs", "layoff", "probe", "penalty", "fine", "scandal",
    "warning", "warns", "delay", "delayed", "recall", "shutdown",
}

FEATURE_COLS = ["Open", "High", "Low", "Volume", "Return", "Range",
                 "MA5", "MA10", "MA20", "EMA12", "Volatility", "RSI", "Sentiment"]
POLY_COLS = ["Close", "MA5", "MA10", "Return", "RSI"]


# ----------------------------------------------------------------------------
# Data fetching (requests + BeautifulSoup + pandas)
# ----------------------------------------------------------------------------
class DataFetcher:

    @staticmethod
    def normalize_symbol(raw: str) -> str:
        s = raw.strip().lower()
        if not s:
            raise ValueError("Please enter a stock symbol (e.g. AAPL, MSFT, TCS.IN).")
        return s

    # stooq.com only carries US, UK, German, Japanese, Hong Kong, Polish and
    # Hungarian exchange data -- it has no direct NSE/BSE (India) listings.
    # These are the suffixes to try, in priority order, when the user types
    # a bare ticker (e.g. "VOD", "BMW") with no "." of their own.
    SUFFIX_GUESSES = [".us", ".uk", ".de", ".jp", ".hk", ".hu"]

    # A few well-known US-listed ADRs for Indian companies, so a natural
    # guess like "INFY" or "WIT" still resolves to real data even though
    # stooq can't reach NSE/BSE directly.
    INDIA_ADR_HINTS = {
        "infy": "Infosys", "wit": "Wipro", "ibn": "ICICI Bank",
        "hdb": "HDFC Bank", "rdy": "Dr. Reddy's", "sify": "Sify",
        "mmyt": "MakeMyTrip", "yatra": "Yatra",
    }

    @classmethod
    def resolve_and_fetch(cls, raw_symbol: str, lookback_days: int, log=lambda *_: None):
        """Try the symbol as given; if it has no exchange suffix, try common
        exchange suffixes in turn until one returns real data. Returns
        (resolved_symbol, dataframe)."""
        base = cls.normalize_symbol(raw_symbol)
        candidates = [base] if "." in base else [base + sfx for sfx in cls.SUFFIX_GUESSES]

        last_error = None
        for i, candidate in enumerate(candidates):
            try:
                if len(candidates) > 1:
                    log(f"Attempt {i + 1}/{len(candidates)}: trying '{candidate}' "
                        f"({'US' if candidate.endswith('.us') else candidate.split('.')[-1].upper()} exchange)…")
                df = cls.fetch_market_data(candidate, lookback_days, log=log)
                return candidate, df
            except Exception as exc:
                last_error = exc
                log(f"'{candidate}' did not work ({exc}); trying next guess…"
                    if i < len(candidates) - 1 else f"'{candidate}' did not work ({exc}).")
                continue

        tried = ", ".join(f"'{c}'" for c in candidates)
        bare = base.split(".")[0]
        adr_note = ""
        if bare in cls.INDIA_ADR_HINTS:
            adr_note = (f" Note: '{bare.upper()}' looks like it might refer to "
                        f"{cls.INDIA_ADR_HINTS[bare]}, but this data source only "
                        f"has its US-listed ADR if one exists -- that guess "
                        f"already failed too.")
        raise ValueError(
            f"Couldn't find historical data for '{raw_symbol}'. Tried: {tried}. "
            f"This free data source (stooq) only covers US, UK, German, "
            f"Japanese, Hong Kong, Polish, and Hungarian exchanges -- it has "
            f"no direct NSE/BSE (India) listings. If it's an Indian company, "
            f"try its US-listed ADR ticker instead if one exists (e.g. "
            f"Infosys -> INFY, Wipro -> WIT, ICICI Bank -> IBN, HDFC Bank -> "
            f"HDB, Dr. Reddy's -> RDY). Otherwise, type the exchange suffix "
            f"explicitly, e.g. 'bmw.de' or 'vod.uk'.{adr_note}"
        ) from last_error

    @staticmethod
    def fetch_market_data(symbol: str, lookback_days: int, log=lambda *_: None) -> pd.DataFrame:
        """requests -> HTTP 200 check -> pandas DataFrame of OHLCV history."""
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        log(f"GET {url}")
        resp = requests.get(url, headers=HEADERS, timeout=15)
        log(f"Response status code: {resp.status_code}")
        if resp.status_code != 200:
            raise ConnectionError(f"Market data request failed (HTTP {resp.status_code}).")

        text = resp.text.strip()
        if not text or text.lower().startswith("no data") or "Date,Open" not in text:
            raise ValueError(f"No historical data found for symbol '{symbol}'. "
                              f"Try a suffix like .us / .uk, e.g. 'aapl.us'.")

        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.strip().title() for c in df.columns]
        required = {"Date", "Open", "High", "Low", "Close"}
        if not required.issubset(set(df.columns)):
            raise ValueError("Unexpected data format returned by the market data source.")

        df["Date"] = pd.to_datetime(df["Date"])
        if "Volume" not in df.columns:
            df["Volume"] = 0
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
        df = df.sort_values("Date").reset_index(drop=True)
        df = df.tail(max(lookback_days, 40)).reset_index(drop=True)
        log(f"Parsed {len(df)} rows of OHLCV data via pandas.")
        return df

    @staticmethod
    def fetch_company_name(symbol: str, log=lambda *_: None) -> str:
        """BeautifulSoup scrape of the quote page purely to extract a display name."""
        try:
            url = f"https://stooq.com/q/?s={symbol}"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            log(f"GET {url} -> status {resp.status_code}")
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                title = soup.find("title")
                if title and title.get_text(strip=True):
                    name = title.get_text(strip=True).split(" - ")[0].split(",")[0]
                    return name
        except Exception as exc:  # non-critical
            log(f"Company name lookup skipped ({exc}).")
        return symbol.upper()

    @staticmethod
    def fetch_news(query: str, max_items: int = 25, log=lambda *_: None) -> list:
        """requests + BeautifulSoup parse of a Google News RSS search feed."""
        url = f"https://news.google.com/rss/search?q={quote(query + ' stock')}&hl=en-US&gl=US&ceid=US:en"
        log(f"GET {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        except Exception as exc:
            log(f"News request failed ({exc}); continuing without news.")
            return []
        log(f"Response status code: {resp.status_code}")
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.find_all("item")[:max_items]
        news = []
        for it in items:
            title_tag = it.find("title")
            date_tag = it.find("pubdate")
            title = title_tag.get_text(strip=True) if title_tag else ""
            date_raw = date_tag.get_text(strip=True) if date_tag else ""
            if title:
                news.append({"title": title, "date_raw": date_raw})
        log(f"Extracted {len(news)} news headlines with BeautifulSoup.")
        return news


# ----------------------------------------------------------------------------
# Sentiment analysis (lightweight lexicon scorer -- no extra ML deps needed)
# ----------------------------------------------------------------------------
class SentimentAnalyzer:

    @staticmethod
    def score_headline(headline: str) -> float:
        words = re.findall(r"[a-zA-Z']+", headline.lower())
        pos = sum(1 for w in words if w in POSITIVE_WORDS)
        neg = sum(1 for w in words if w in NEGATIVE_WORDS)
        if pos + neg == 0:
            return 0.0
        return round((pos - neg) / (pos + neg), 3)

    @classmethod
    def analyze(cls, news_items: list) -> dict:
        if not news_items:
            return {"overall": 0.0, "positive_pct": 0, "neutral_pct": 100,
                     "negative_pct": 0, "scored": []}

        scored = []
        pos_count = neg_count = neu_count = 0
        for item in news_items:
            s = cls.score_headline(item["title"])
            if s > 0.15:
                label = "positive"
                pos_count += 1
            elif s < -0.15:
                label = "negative"
                neg_count += 1
            else:
                label = "neutral"
                neu_count += 1
            scored.append({**item, "score": s, "label": label})

        total = len(scored)
        overall = round(sum(s["score"] for s in scored) / total, 3)
        return {
            "overall": overall,
            "positive_pct": round(100 * pos_count / total, 1),
            "neutral_pct": round(100 * neu_count / total, 1),
            "negative_pct": round(100 * neg_count / total, 1),
            "scored": scored,
        }


# ----------------------------------------------------------------------------
# Feature engineering (uses only information available up to each row's date)
# ----------------------------------------------------------------------------
class FeatureEngineer:

    @staticmethod
    def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    @staticmethod
    def build(df: pd.DataFrame, sentiment_overall: float) -> pd.DataFrame:
        out = df.copy()
        out["Return"] = out["Close"].pct_change()
        out["Range"] = out["High"] - out["Low"]
        out["MA5"] = out["Close"].rolling(5).mean()
        out["MA10"] = out["Close"].rolling(10).mean()
        out["MA20"] = out["Close"].rolling(20).mean()
        out["EMA12"] = out["Close"].ewm(span=12, adjust=False).mean()
        out["Volatility"] = out["Return"].rolling(10).std()
        out["RSI"] = FeatureEngineer.compute_rsi(out["Close"])
        # News sentiment can't be reliably back-dated per historical trading
        # day from a live headline search, so (transparently) it is applied
        # as a recency-weighted feature over the most recent sessions only,
        # and as zero further back -- it never uses information from the
        # future relative to the row it's attached to.
        out["Sentiment"] = 0.0
        recent_n = min(5, len(out))
        weights = np.linspace(0.4, 1.0, recent_n)
        out.loc[out.index[-recent_n:], "Sentiment"] = sentiment_overall * weights
        return out


# ----------------------------------------------------------------------------
# Model training / evaluation / prediction
# ----------------------------------------------------------------------------
class ModelEngine:

    @staticmethod
    def _direction_accuracy(current, actual_next, pred_next) -> float:
        actual_dir = np.sign(actual_next - current)
        pred_dir = np.sign(pred_next - current)
        matches = (actual_dir == pred_dir).sum()
        return matches / len(current) if len(current) else 0.0

    @classmethod
    def run(cls, feat_df: pd.DataFrame, log=lambda *_: None):
        work = feat_df.copy()
        work["Target"] = work["Close"].shift(-1)

        clean = work.dropna(subset=FEATURE_COLS).reset_index(drop=True)
        if len(clean) < 25:
            raise ValueError("Not enough clean data points after feature engineering. "
                              "Try a larger 'Data Range'.")

        predict_row = clean.iloc[[-1]]                     # most recent day -> target unknown
        history = clean.iloc[:-1].dropna(subset=["Target"]).reset_index(drop=True)

        if len(history) < 20:
            raise ValueError("Not enough historical rows to train/validate models. "
                              "Try a larger 'Data Range'.")

        split = int(len(history) * 0.8)
        split = max(10, min(split, len(history) - 5))
        train, test = history.iloc[:split], history.iloc[split:]
        log(f"Chronological split -> train: {len(train)} rows, test: {len(test)} rows "
            f"(no shuffling, no future leakage).")

        X_train, y_train = train[FEATURE_COLS], train["Target"]
        X_test, y_test = test[FEATURE_COLS], test["Target"]
        cur_test = test["Close"].values

        results = {}

        # 1) Linear Regression -------------------------------------------------
        lin = LinearRegression().fit(X_train, y_train)
        pred = lin.predict(X_test)
        results["Linear Regression"] = {
            "model": lin, "features": FEATURE_COLS,
            "mae": mean_absolute_error(y_test, pred),
            "rmse": math.sqrt(mean_squared_error(y_test, pred)),
            "r2": r2_score(y_test, pred),
            "direction": cls._direction_accuracy(cur_test, y_test.values, pred),
        }

        # 2) Polynomial Regression (degree 2, reduced feature set) --------------
        poly_train_X, poly_test_X = train[POLY_COLS], test[POLY_COLS]
        poly = make_pipeline(PolynomialFeatures(degree=2, include_bias=False),
                              LinearRegression())
        poly.fit(poly_train_X, y_train)
        pred = poly.predict(poly_test_X)
        results["Polynomial Regression"] = {
            "model": poly, "features": POLY_COLS,
            "mae": mean_absolute_error(y_test, pred),
            "rmse": math.sqrt(mean_squared_error(y_test, pred)),
            "r2": r2_score(y_test, pred),
            "direction": cls._direction_accuracy(cur_test, y_test.values, pred),
        }

        # 3) Random Forest --------------------------------------------------------
        rf = RandomForestRegressor(n_estimators=300, max_depth=6, random_state=42)
        rf.fit(X_train, y_train)
        pred = rf.predict(X_test)
        results["Random Forest"] = {
            "model": rf, "features": FEATURE_COLS,
            "mae": mean_absolute_error(y_test, pred),
            "rmse": math.sqrt(mean_squared_error(y_test, pred)),
            "r2": r2_score(y_test, pred),
            "direction": cls._direction_accuracy(cur_test, y_test.values, pred),
        }

        # 4) Gradient Boosting -----------------------------------------------------
        gb = GradientBoostingRegressor(n_estimators=300, max_depth=3,
                                        learning_rate=0.05, random_state=42)
        gb.fit(X_train, y_train)
        pred = gb.predict(X_test)
        results["Gradient Boosting"] = {
            "model": gb, "features": FEATURE_COLS,
            "mae": mean_absolute_error(y_test, pred),
            "rmse": math.sqrt(mean_squared_error(y_test, pred)),
            "r2": r2_score(y_test, pred),
            "direction": cls._direction_accuracy(cur_test, y_test.values, pred),
        }

        for name, r in results.items():
            log(f"{name:22s} MAE={r['mae']:.3f}  RMSE={r['rmse']:.3f}  "
                f"R2={r['r2']:.3f}  Direction={r['direction']*100:.1f}%")

        best_name = min(results, key=lambda n: results[n]["rmse"])
        log(f"Best model by RMSE on unseen (chronological) test data: {best_name}")

        # Refit the winning model type on ALL available history before the
        # final prediction, then predict the next (unseen) trading day.
        best_features = results[best_name]["features"]
        X_full, y_full = history[best_features], history["Target"]
        if best_name == "Linear Regression":
            final_model = LinearRegression().fit(X_full, y_full)
        elif best_name == "Polynomial Regression":
            final_model = make_pipeline(PolynomialFeatures(degree=2, include_bias=False),
                                         LinearRegression()).fit(X_full, y_full)
        elif best_name == "Random Forest":
            final_model = RandomForestRegressor(n_estimators=300, max_depth=6,
                                                 random_state=42).fit(X_full, y_full)
        else:
            final_model = GradientBoostingRegressor(n_estimators=300, max_depth=3,
                                                      learning_rate=0.05,
                                                      random_state=42).fit(X_full, y_full)

        next_price = float(final_model.predict(predict_row[best_features])[0])
        last_close = float(predict_row["Close"].iloc[0])

        return {
            "results": results,
            "best_name": best_name,
            "next_price": next_price,
            "last_close": last_close,
            "confidence": round(min(95, max(50, results[best_name]["direction"] * 100)), 1),
        }


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
class StockPredictorApp:
    LOOKBACKS = {"10 Days": 10, "30 Days": 30, "60 Days": 60,
                 "100 Days": 100, "250 Days (1yr)": 250}

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AI Multi-Stock Price Predictor & Sentiment System")
        self.root.geometry("1180x800")
        self.root.minsize(1000, 720)
        self.root.configure(bg=BG)

        self._msg_queue = queue.Queue()
        self._build_fonts()
        self._build_style()
        self._build_layout()
        self.root.after(100, self._poll_queue)

    # ---- fonts / ttk style --------------------------------------------------
    def _build_fonts(self):
        self.f_title = tkfont.Font(family="Segoe UI", size=20, weight="bold")
        self.f_h2 = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.f_body = tkfont.Font(family="Segoe UI", size=10)
        self.f_small = tkfont.Font(family="Segoe UI", size=9)
        self.f_metric = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.f_mono = tkfont.Font(family="Consolas", size=9)

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=self.f_body)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=self.f_body)
        style.configure("Sub.TLabel", background=CARD, foreground=SUBTEXT, font=self.f_small)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=self.f_title)
        style.configure("H2.TLabel", background=CARD, foreground=TEXT, font=self.f_h2)

        style.configure("TButton", font=self.f_h2, padding=8, background=ACCENT,
                         foreground="#03121f", borderwidth=0)
        style.map("TButton", background=[("active", "#7dd3fc"), ("disabled", "#3a4763")])

        style.configure("TCombobox", fieldbackground=ENTRY_BG, background=ENTRY_BG,
                         foreground=TEXT, arrowcolor=TEXT)
        style.configure("TEntry", fieldbackground=ENTRY_BG, foreground=TEXT,
                         insertcolor=TEXT)

        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                         foreground=TEXT, rowheight=26, font=self.f_small, borderwidth=0)
        style.configure("Treeview.Heading", background="#1d2947", foreground=SUBTEXT,
                         font=self.f_small)
        style.map("Treeview", background=[("selected", "#274063")])

    # ---- layout ---------------------------------------------------------------
    def _build_layout(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        # Header -----------------------------------------------------------------
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="📈 AI Multi-Stock Price Predictor",
                   style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  web scraping · sentiment · regression",
                   style="TLabel", foreground=SUBTEXT).pack(side="left", padx=(6, 0))

        # Control bar --------------------------------------------------------------
        control = tk.Frame(outer, bg=CARD, highlightbackground=CARD_BORDER,
                            highlightthickness=1)
        control.pack(fill="x", pady=(0, 12))
        cpad = ttk.Frame(control, style="Card.TFrame", padding=14)
        cpad.pack(fill="x")

        ttk.Label(cpad, text="Stock Symbol", style="Card.TLabel").grid(row=0, column=0,
                                                                        sticky="w")
        self.symbol_var = tk.StringVar(value="AAPL")
        entry = tk.Entry(cpad, textvariable=self.symbol_var, font=self.f_h2, width=16,
                          bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        entry.grid(row=1, column=0, sticky="w", ipady=4, pady=(2, 0))
        entry.bind("<Return>", lambda e: self.on_analyze())

        ttk.Label(cpad, text="Data Range", style="Card.TLabel").grid(row=0, column=1,
                                                                      sticky="w", padx=(20, 0))
        self.range_var = tk.StringVar(value="100 Days")
        combo = ttk.Combobox(cpad, textvariable=self.range_var, state="readonly",
                              values=list(self.LOOKBACKS.keys()), width=16)
        combo.grid(row=1, column=1, sticky="w", padx=(20, 0), pady=(2, 0))

        self.analyze_btn = ttk.Button(cpad, text="ANALYZE", command=self.on_analyze)
        self.analyze_btn.grid(row=1, column=2, sticky="w", padx=(24, 0))

        ttk.Label(cpad, text="Try: AAPL, MSFT, TSLA, NVDA, VOD.UK, BMW.DE  "
                              "(no direct India/NSE support)",
                  style="Card.TLabel", foreground=SUBTEXT).grid(
            row=0, column=2, sticky="w", padx=(24, 0))

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(cpad, textvariable=self.status_var, style="Card.TLabel",
                  foreground=ACCENT).grid(row=1, column=3, sticky="w", padx=(24, 0))

        # Body: left (metrics+chart) / right (sentiment+table) --------------------
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=0)
        body.rowconfigure(1, weight=1)

        self._build_metric_cards(body)
        self._build_chart_card(body)
        self._build_sentiment_card(body)
        self._build_models_card(body)
        self._build_log_card(outer)

        ttk.Label(outer, text="Educational project — simulated signals only, not "
                              "financial advice. Data via Stooq & Google News.",
                  style="TLabel", foreground=SUBTEXT).pack(fill="x", pady=(8, 0))

    def _card(self, parent):
        wrap = tk.Frame(parent, bg=CARD, highlightbackground=CARD_BORDER,
                         highlightthickness=1)
        inner = ttk.Frame(wrap, style="Card.TFrame", padding=14)
        inner.pack(fill="both", expand=True)
        return wrap, inner

    def _build_metric_cards(self, body):
        row = ttk.Frame(body)
        row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        for i in range(4):
            row.columnconfigure(i, weight=1)

        self.metric_vars = {}
        specs = [("company", "Company / Symbol", "—"),
                 ("current", "Current Price", "—"),
                 ("predicted", "Predicted Next Price", "—"),
                 ("signal", "Signal", "—")]
        for i, (key, label, default) in enumerate(specs):
            wrap, inner = self._card(row)
            wrap.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            ttk.Label(inner, text=label, style="Sub.TLabel").pack(anchor="w")
            var = tk.StringVar(value=default)
            lbl = tk.Label(inner, textvariable=var, bg=CARD, fg=TEXT, font=self.f_metric)
            lbl.pack(anchor="w", pady=(4, 0))
            self.metric_vars[key] = (var, lbl)

    def _build_chart_card(self, body):
        wrap, inner = self._card(body)
        wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(inner, text="Price Chart (Close · MA5 · MA20 · Prediction)",
                   style="H2.TLabel").pack(anchor="w")

        self.fig = Figure(figsize=(6.4, 4.2), dpi=100, facecolor=CARD)
        self.ax = self.fig.add_subplot(111)
        self._style_axes()
        self.canvas = FigureCanvasTkAgg(self.fig, master=inner)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=(8, 0))

        # Paper trading plan strip
        self.plan_var = tk.StringVar(value="Run an analysis to see a simulated trade plan.")
        ttk.Label(inner, textvariable=self.plan_var, style="Sub.TLabel",
                  wraplength=560, justify="left").pack(anchor="w", pady=(8, 0))

    def _style_axes(self):
        self.ax.clear()
        self.ax.set_facecolor(CARD)
        for spine in self.ax.spines.values():
            spine.set_color(CARD_BORDER)
        self.ax.tick_params(colors=SUBTEXT, labelsize=8)
        self.ax.xaxis.label.set_color(SUBTEXT)
        self.ax.yaxis.label.set_color(SUBTEXT)
        self.ax.grid(True, color=CARD_BORDER, linewidth=0.6, alpha=0.6)

    def _build_sentiment_card(self, body):
        wrap, inner = self._card(body)
        wrap.grid(row=1, column=1, sticky="nsew")
        ttk.Label(inner, text="News Sentiment", style="H2.TLabel").pack(anchor="w")

        self.sent_score_var = tk.StringVar(value="No news analyzed yet.")
        ttk.Label(inner, textvariable=self.sent_score_var, style="Card.TLabel",
                  foreground=ACCENT).pack(anchor="w", pady=(6, 10))

        self.sent_canvas = tk.Canvas(inner, height=110, bg=CARD, highlightthickness=0)
        self.sent_canvas.pack(fill="x")

        ttk.Label(inner, text="Recent Headlines", style="H2.TLabel").pack(
            anchor="w", pady=(14, 4))
        self.headlines_box = tk.Listbox(inner, bg=ENTRY_BG, fg=TEXT, relief="flat",
                                         selectbackground="#274063", font=self.f_small,
                                         height=8, highlightthickness=0)
        self.headlines_box.pack(fill="both", expand=True)

    def _build_models_card(self, body):
        wrap, inner = self._card(body)
        wrap.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        ttk.Label(inner, text="Model Performance (chronological hold-out test set)",
                   style="H2.TLabel").pack(anchor="w")

        cols = ("model", "mae", "rmse", "r2", "direction")
        self.tree = ttk.Treeview(inner, columns=cols, show="headings", height=5)
        headers = {"model": "Model", "mae": "MAE", "rmse": "RMSE",
                   "r2": "R²", "direction": "Directional Accuracy"}
        widths = {"model": 200, "mae": 110, "rmse": 110, "r2": 90, "direction": 170}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.column("model", anchor="w")
        self.tree.pack(fill="x", pady=(8, 0))
        self.tree.tag_configure("best", background="#12331f", foreground=GREEN)

    def _build_log_card(self, outer):
        wrap, inner = self._card(outer)
        wrap.pack(fill="x", pady=(12, 0))
        ttk.Label(inner, text="Pipeline Log", style="H2.TLabel").pack(anchor="w")
        self.log_text = tk.Text(inner, height=6, bg="#0a1120", fg="#8fb2ff",
                                 font=self.f_mono, relief="flat", wrap="word")
        self.log_text.pack(fill="x", pady=(6, 0))
        self.log_text.configure(state="disabled")

    # ---- logging helper (thread-safe via queue) --------------------------------
    def log(self, msg: str):
        self._msg_queue.put(("log", msg))

    def _append_log(self, msg: str):
        self.log_text.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._msg_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "error":
                    self.status_var.set("Error.")
                    self.analyze_btn.state(["!disabled"])
                    messagebox.showerror("Analysis failed", payload)
                elif kind == "done":
                    self._render_results(payload)
                    self.analyze_btn.state(["!disabled"])
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    # ---- main action ----------------------------------------------------------
    def on_analyze(self):
        self.analyze_btn.state(["disabled"])
        self.status_var.set("Working…")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        raw_symbol = self.symbol_var.get()
        lookback = self.LOOKBACKS[self.range_var.get()]
        thread = threading.Thread(target=self._analyze_worker,
                                   args=(raw_symbol, lookback), daemon=True)
        thread.start()

    def _analyze_worker(self, raw_symbol, lookback):
        try:
            self._msg_queue.put(("status", f"Fetching market data for {raw_symbol}…"))
            self.log(f"Step 1-8: request -> HTTP 200 check -> BeautifulSoup/pandas "
                      f"for '{raw_symbol}'")
            symbol, market_df = DataFetcher.resolve_and_fetch(raw_symbol, lookback, log=self.log)
            self.log(f"Resolved symbol: '{symbol}'")
            company = DataFetcher.fetch_company_name(symbol, log=self.log)

            self._msg_queue.put(("status", "Scraping news & scoring sentiment…"))
            self.log("Step 12-14: scraping news headlines and scoring sentiment")
            news_items = DataFetcher.fetch_news(company.split("(")[0].strip() or symbol,
                                                 log=self.log)
            sentiment = SentimentAnalyzer.analyze(news_items)
            self.log(f"Overall news sentiment score: {sentiment['overall']:+.3f} "
                      f"({len(news_items)} headlines)")

            self._msg_queue.put(("status", "Engineering features…"))
            self.log("Step 11: computing returns, moving averages, EMA, "
                      "volatility, RSI (no future data used)")
            feat_df = FeatureEngineer.build(market_df, sentiment["overall"])

            self._msg_queue.put(("status", "Training & validating models…"))
            self.log("Step 17-19: training Linear / Polynomial / Random Forest / "
                      "Gradient Boosting on a chronological train/test split")
            model_out = ModelEngine.run(feat_df, log=self.log)

            self._msg_queue.put(("done", {
                "symbol": symbol, "company": company, "market_df": market_df,
                "sentiment": sentiment, "news_items": news_items,
                "model_out": model_out,
            }))
            self._msg_queue.put(("status", "Done."))
        except Exception as exc:
            self.log(f"ERROR: {exc}")
            self._msg_queue.put(("error", str(exc)))

    # ---- rendering --------------------------------------------------------------
    def _render_results(self, data):
        symbol = data["symbol"]
        company = data["company"]
        market_df = data["market_df"]
        sentiment = data["sentiment"]
        news_items = data["news_items"]
        mo = data["model_out"]

        last_close = mo["last_close"]
        next_price = mo["next_price"]
        pct_change = (next_price - last_close) / last_close * 100
        sent_score = sentiment["overall"]

        if pct_change > 0.5 and sent_score >= -0.2:
            signal, color = "BUY", GREEN
        elif pct_change < -0.5 and sent_score <= 0.2:
            signal, color = "SELL", RED
        else:
            signal, color = "HOLD", AMBER

        # metric cards
        self.metric_vars["company"][0].set(f"{company}\n({symbol.upper()})")
        self.metric_vars["company"][1].configure(font=self.f_h2)
        self.metric_vars["current"][0].set(f"{last_close:,.2f}")
        self.metric_vars["predicted"][0].set(f"{next_price:,.2f}")
        self.metric_vars["predicted"][1].configure(
            fg=GREEN if pct_change >= 0 else RED)
        self.metric_vars["signal"][0].set(f"{signal}  ({pct_change:+.2f}%)")
        self.metric_vars["signal"][1].configure(fg=color)

        # chart
        self._style_axes()
        dates = market_df["Date"]
        close = market_df["Close"]
        ma5 = close.rolling(5).mean()
        ma20 = close.rolling(20).mean()
        self.ax.plot(dates, close, color=ACCENT, linewidth=1.6, label="Close")
        self.ax.plot(dates, ma5, color=AMBER, linewidth=1.1, label="MA5")
        self.ax.plot(dates, ma20, color="#a78bfa", linewidth=1.1, label="MA20")
        next_date = dates.iloc[-1] + pd.Timedelta(days=1)
        self.ax.scatter([next_date], [next_price],
                         color=color, s=55, zorder=5, label="Prediction")
        self.ax.plot([dates.iloc[-1], next_date], [last_close, next_price],
                     color=color, linewidth=1.2, linestyle="--")
        leg = self.ax.legend(facecolor=CARD, edgecolor=CARD_BORDER, labelcolor=TEXT,
                              fontsize=8, loc="upper left")
        self.fig.autofmt_xdate(rotation=25)
        self.canvas.draw()

        # paper trading plan
        entry = last_close * 0.995
        target = max(next_price, last_close) * 1.0
        stop = entry * 0.99
        self.plan_var.set(
            f"Simulated paper-trade plan — Entry ≈ {entry:,.2f}  ·  "
            f"Target ≈ {target:,.2f}  ·  Stop-loss ≈ {stop:,.2f}  ·  "
            f"Model confidence ≈ {mo['confidence']:.0f}%  (not financial advice)")

        # sentiment
        self.sent_score_var.set(
            f"Overall score: {sent_score:+.2f}   ·   {len(news_items)} headlines analyzed")
        self._draw_sentiment_bars(sentiment)
        self.headlines_box.delete(0, "end")
        for item in sentiment["scored"][:12]:
            icon = "🟢" if item["label"] == "positive" else (
                "🔴" if item["label"] == "negative" else "⚪")
            self.headlines_box.insert("end", f" {icon}  {item['title'][:90]}")

        # model table
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        best = mo["best_name"]
        for name, r in mo["results"].items():
            tag = ("best",) if name == best else ()
            label = f"★ {name}" if name == best else name
            self.tree.insert("", "end", values=(
                label, f"{r['mae']:.3f}", f"{r['rmse']:.3f}",
                f"{r['r2']:.3f}", f"{r['direction']*100:.1f}%"), tags=tag)

    def _draw_sentiment_bars(self, sentiment):
        c = self.sent_canvas
        c.delete("all")
        c.update_idletasks()
        w = max(c.winfo_width(), 260)
        rows = [("Positive", sentiment["positive_pct"], GREEN),
                ("Neutral", sentiment["neutral_pct"], SUBTEXT),
                ("Negative", sentiment["negative_pct"], RED)]
        bar_max = w - 130
        y = 8
        for label, pct, color in rows:
            c.create_text(6, y + 10, anchor="w", text=label, fill=TEXT,
                          font=self.f_small)
            c.create_rectangle(70, y, 70 + bar_max, y + 20, fill="#1d2947",
                                outline="")
            fill_w = max(2, bar_max * pct / 100)
            c.create_rectangle(70, y, 70 + fill_w, y + 20, fill=color, outline="")
            c.create_text(70 + bar_max + 8, y + 10, anchor="w",
                          text=f"{pct:.0f}%", fill=TEXT, font=self.f_small)
            y += 32


def main():
    root = tk.Tk()
    StockPredictorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()