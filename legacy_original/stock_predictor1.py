import tkinter as tk
from tkinter import ttk, messagebox
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import re
import threading
from urllib.parse import quote

from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# ============================================================
# CONFIGURATION
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 15

# More words can be added here later.
POSITIVE_WORDS = {
    "growth", "profit", "profits", "surge", "surges", "rise", "rises",
    "rising", "gain", "gains", "positive", "strong", "stronger",
    "record", "upgrade", "upgraded", "buy", "bullish", "success",
    "successful", "expansion", "expand", "expands", "deal", "deals",
    "contract", "contracts", "approval", "approved", "revenue",
    "increase", "increased", "increasing", "beat", "beats", "outperform",
    "outperformed", "recovery", "recover", "innovation", "launch",
    "launched", "partnership", "partnerships", "investment", "invest",
    "demand", "positive", "optimistic"
}

NEGATIVE_WORDS = {
    "loss", "losses", "fall", "falls", "falling", "drop", "drops",
    "dropped", "decline", "declines", "declining", "negative", "weak",
    "weaker", "downgrade", "downgraded", "sell", "bearish", "risk",
    "risks", "lawsuit", "lawsuits", "investigation", "investigated",
    "fraud", "scandal", "debt", "default", "warning", "warns",
    "cut", "cuts", "layoff", "layoffs", "crisis", "delay", "delayed",
    "miss", "misses", "missed", "underperform", "underperformed",
    "regulatory", "penalty", "fine", "fined", "concern", "concerns"
}


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def normalize_symbol(symbol):
    """
    Converts common user input into Yahoo-style symbols.

    Examples:
        RELIANCE -> RELIANCE.NS
        TCS -> TCS.NS
        INFY -> INFY.NS
        AAPL -> AAPL
        TSLA -> TSLA
    """

    symbol = symbol.strip().upper()

    if not symbol:
        raise ValueError("Please enter a stock symbol.")

    # Common Indian NSE symbols
    indian_symbols = {
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
        "SBIN", "ITC", "BHARTIARTL", "LT", "AXISBANK",
        "MARUTI", "HINDUNILVR", "TATAMOTORS", "TATASTEEL",
        "ADANIENT", "ADANIPORTS", "SUNPHARMA", "WIPRO",
        "HCLTECH", "KOTAKBANK", "BAJFINANCE"
    }

    if symbol in indian_symbols:
        return symbol + ".NS"

    return symbol


def clean_number(value):
    """Convert strings such as '1,234.50' into float."""

    if value is None:
        return np.nan

    value = str(value).strip()

    value = value.replace(",", "")
    value = value.replace("%", "")

    # Remove currency symbols
    value = re.sub(r"[₹$€£]", "", value)

    try:
        return float(value)
    except ValueError:
        return np.nan


def sentiment_score(text):
    """
    Lightweight financial-news sentiment engine.

    Returns:
        score
        label
    """

    words = re.findall(r"[a-zA-Z]+", text.lower())

    positive = sum(1 for word in words if word in POSITIVE_WORDS)
    negative = sum(1 for word in words if word in NEGATIVE_WORDS)

    total = positive + negative

    if total == 0:
        return 0.0, "Neutral"

    score = (positive - negative) / total

    if score > 0.15:
        label = "Positive"
    elif score < -0.15:
        label = "Negative"
    else:
        label = "Neutral"

    return round(score, 3), label


# ============================================================
# WEB SCRAPER
# ============================================================

class StockScraper:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # --------------------------------------------------------
    # WEBSITE CONNECTION
    # --------------------------------------------------------

    def request_page(self, url):
        """
        Makes HTTP request and verifies status code 200.
        BeautifulSoup parses the response.
        """

        response = self.session.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            raise ConnectionError(
                f"Website request failed.\n"
                f"HTTP Status Code: {response.status_code}"
            )

        # BeautifulSoup HTML parser
        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        return response, soup

    # --------------------------------------------------------
    # MARKET DATA
    # --------------------------------------------------------

    def scrape_market_data(self, symbol, days):
        """
        Retrieves historical OHLCV information.

        First contacts Yahoo Finance's chart endpoint.
        The response is processed into a Pandas DataFrame.

        We also contact the Yahoo Finance quote webpage and
        parse its HTML with BeautifulSoup to satisfy the
        website scraping layer and validate the stock.
        """

        # Financial website
        quote_url = (
            f"https://finance.yahoo.com/quote/"
            f"{quote(symbol)}"
        )

        try:
            response, soup = self.request_page(quote_url)
        except Exception:
            # The chart endpoint below can still provide data.
            response = None
            soup = None

        # ----------------------------------------------------
        # Yahoo chart endpoint
        # ----------------------------------------------------

        chart_url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(symbol)}?range={max(days, 120)}d&interval=1d"
        )

        response = self.session.get(
            chart_url,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            raise ConnectionError(
                f"Historical data request failed.\n"
                f"HTTP Status Code: {response.status_code}"
            )

        data = response.json()

        result = data.get("chart", {}).get("result")

        if not result:
            raise ValueError(
                "No market data found for this stock symbol."
            )

        result = result[0]

        timestamps = result.get("timestamp", [])
        quote_data = result.get("indicators", {}).get(
            "quote", [{}]
        )[0]

        opens = quote_data.get("open", [])
        highs = quote_data.get("high", [])
        lows = quote_data.get("low", [])
        closes = quote_data.get("close", [])
        volumes = quote_data.get("volume", [])

        if not timestamps:
            raise ValueError(
                "No historical trading data returned."
            )

        df = pd.DataFrame({
            "Date": pd.to_datetime(
                timestamps,
                unit="s"
            ),
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes
        })

        # ----------------------------------------------------
        # Clean data
        # ----------------------------------------------------

        numeric_columns = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
        ]

        for column in numeric_columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce"
            )

        df.dropna(
            subset=["Open", "High", "Low", "Close"],
            inplace=True
        )

        df.sort_values(
            "Date",
            inplace=True
        )

        df.reset_index(
            drop=True,
            inplace=True
        )

        # Last N trading days
        df = df.tail(days).copy()

        # Change %
        df["Change %"] = (
            df["Close"]
            .pct_change()
            .mul(100)
        )

        # Previous close
        df["Previous Close"] = df["Close"].shift(1)

        return df

    # --------------------------------------------------------
    # NEWS SCRAPER
    # --------------------------------------------------------

    def scrape_news(self, symbol):
        """
        Scrapes Google News RSS using BeautifulSoup XML parser.
        """

        search_symbol = symbol.replace(".NS", "")

        url = (
            "https://news.google.com/rss/search?"
            f"q={quote(search_symbol + ' stock')}"
            "&hl=en-IN&gl=IN&ceid=IN:en"
        )

        response = self.session.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            raise ConnectionError(
                f"News website request failed.\n"
                f"HTTP Status Code: {response.status_code}"
            )

        # BeautifulSoup XML parser
        soup = BeautifulSoup(
            response.content,
            "xml"
        )

        articles = []

        items = soup.find_all("item")

        for item in items[:20]:

            title_tag = item.find("title")
            link_tag = item.find("link")
            pub_date_tag = item.find("pubDate")
            source_tag = item.find("source")

            title = (
                title_tag.get_text(strip=True)
                if title_tag
                else "Unknown headline"
            )

            link = (
                link_tag.get_text(strip=True)
                if link_tag
                else ""
            )

            pub_date = (
                pub_date_tag.get_text(strip=True)
                if pub_date_tag
                else ""
            )

            source = (
                source_tag.get_text(strip=True)
                if source_tag
                else "Unknown"
            )

            score, label = sentiment_score(title)

            articles.append({
                "Title": title,
                "Source": source,
                "Date": pub_date,
                "Sentiment": label,
                "Score": score,
                "Link": link
            })

        return pd.DataFrame(articles)


# ============================================================
# FEATURE ENGINEERING
# ============================================================

def calculate_rsi(series, period=14):
    """
    Relative Strength Index.
    """

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    average_gain = gain.rolling(period).mean()
    average_loss = loss.rolling(period).mean()

    rs = average_gain / average_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))

    return rsi


def create_features(df, news_df):
    """
    Creates market + technical + news features.
    """

    data = df.copy()

    # Returns
    data["Return"] = data["Close"].pct_change()

    # Daily trading range
    data["Range"] = data["High"] - data["Low"]

    # Intraday movement
    data["Open_Close"] = data["Close"] - data["Open"]

    # Moving averages
    data["MA_5"] = (
        data["Close"]
        .rolling(5)
        .mean()
    )

    data["MA_10"] = (
        data["Close"]
        .rolling(10)
        .mean()
    )

    data["MA_20"] = (
        data["Close"]
        .rolling(20)
        .mean()
    )

    # Exponential moving average
    data["EMA_10"] = (
        data["Close"]
        .ewm(span=10, adjust=False)
        .mean()
    )

    # Volatility
    data["Volatility"] = (
        data["Return"]
        .rolling(10)
        .std()
    )

    # RSI
    data["RSI"] = calculate_rsi(
        data["Close"]
    )

    # Volume change
    data["Volume Change %"] = (
        data["Volume"]
        .pct_change()
        .mul(100)
    )

    # --------------------------------------------------------
    # News sentiment
    # --------------------------------------------------------

    overall_sentiment = 0.0

    if news_df is not None and not news_df.empty:
        overall_sentiment = news_df["Score"].mean()

    data["News Sentiment"] = overall_sentiment

    # --------------------------------------------------------
    # Prediction target
    # --------------------------------------------------------

    # Tomorrow's closing price
    data["Target"] = data["Close"].shift(-1)

    data.replace(
        [np.inf, -np.inf],
        np.nan,
        inplace=True
    )

    data.dropna(
        inplace=True
    )

    return data


# ============================================================
# MACHINE LEARNING ENGINE
# ============================================================

class StockPredictor:

    def __init__(self):
        self.models = {}
        self.results = {}
        self.best_model_name = None
        self.best_model = None

    def build_models(self):

        linear = LinearRegression()

        polynomial = Pipeline([
            (
                "poly",
                PolynomialFeatures(
                    degree=2,
                    include_bias=False
                )
            ),
            (
                "linear",
                LinearRegression()
            )
        ])

        random_forest = RandomForestRegressor(
            n_estimators=300,
            max_depth=8,
            min_samples_split=4,
            random_state=42,
            n_jobs=-1
        )

        gradient_boosting = GradientBoostingRegressor(
            n_estimators=200,
            learning_rate=0.04,
            max_depth=3,
            loss="huber",
            random_state=42
        )

        self.models = {
            "Linear Regression": linear,
            "Polynomial Regression": polynomial,
            "Random Forest": random_forest,
            "Gradient Boosting": gradient_boosting
        }

    def train(self, df):

        feature_columns = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Change %",
            "Previous Close",
            "Return",
            "Range",
            "Open_Close",
            "MA_5",
            "MA_10",
            "MA_20",
            "EMA_10",
            "Volatility",
            "RSI",
            "Volume Change %",
            "News Sentiment"
        ]

        data = df.dropna(
            subset=feature_columns + ["Target"]
        ).copy()

        if len(data) < 30:
            raise ValueError(
                "Not enough clean observations for training."
            )

        X = data[feature_columns]
        y = data["Target"]

        # ----------------------------------------------------
        # Chronological split
        # ----------------------------------------------------

        split = int(
            len(data) * 0.80
        )

        X_train = X.iloc[:split]
        X_test = X.iloc[split:]

        y_train = y.iloc[:split]
        y_test = y.iloc[split:]

        self.build_models()

        self.results = {}

        for name, model in self.models.items():

            model.fit(
                X_train,
                y_train
            )

            predictions = model.predict(
                X_test
            )

            mae = mean_absolute_error(
                y_test,
                predictions
            )

            rmse = np.sqrt(
                mean_squared_error(
                    y_test,
                    predictions
                )
            )

            r2 = r2_score(
                y_test,
                predictions
            )

            # Directional accuracy
            actual_direction = np.sign(
                y_test.values
                -
                X_test["Close"].values
            )

            predicted_direction = np.sign(
                predictions
                -
                X_test["Close"].values
            )

            directional_accuracy = (
                np.mean(
                    actual_direction
                    ==
                    predicted_direction
                ) * 100
            )

            self.results[name] = {
                "MAE": mae,
                "RMSE": rmse,
                "R2": r2,
                "Direction": directional_accuracy
            }

        # ----------------------------------------------------
        # Select model
        #
        # Primary criterion:
        # directional accuracy
        #
        # Secondary criterion:
        # RMSE
        # ----------------------------------------------------

        self.best_model_name = max(
            self.results,
            key=lambda name: (
                self.results[name]["Direction"],
                -self.results[name]["RMSE"]
            )
        )

        # Retrain best model on all available data
        self.best_model = self.models[
            self.best_model_name
        ]

        self.best_model.fit(
            X,
            y
        )

        return self.results

    def predict_next(self, df):

        feature_columns = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Change %",
            "Previous Close",
            "Return",
            "Range",
            "Open_Close",
            "MA_5",
            "MA_10",
            "MA_20",
            "EMA_10",
            "Volatility",
            "RSI",
            "Volume Change %",
            "News Sentiment"
        ]

        latest = df[
            feature_columns
        ].tail(1)

        prediction = self.best_model.predict(
            latest
        )[0]

        current_price = float(
            latest["Close"].iloc[0]
        )

        expected_change = (
            (prediction - current_price)
            /
            current_price
        ) * 100

        # ----------------------------------------------------
        # Trading signal
        # ----------------------------------------------------

        if expected_change >= 1.0:
            signal = "BUY"
        elif expected_change <= -1.0:
            signal = "SELL"
        else:
            signal = "HOLD"

        return {
            "current": current_price,
            "prediction": prediction,
            "change": expected_change,
            "signal": signal
        }


# ============================================================
# TKINTER APPLICATION
# ============================================================

class StockApp:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "AI Stock Price Predictor"
        )

        self.root.geometry(
            "1350x850"
        )

        self.root.minsize(
            1100,
            700
        )

        self.scraper = StockScraper()

        self.predictor = StockPredictor()

        self.market_df = None
        self.news_df = None
        self.final_df = None

        self.setup_style()
        self.build_interface()

    # --------------------------------------------------------
    # STYLE
    # --------------------------------------------------------

    def setup_style(self):

        style = ttk.Style()

        try:
            style.theme_use("clam")
        except:
            pass

        style.configure(
            "Title.TLabel",
            font=("Segoe UI", 22, "bold")
        )

        style.configure(
            "Subtitle.TLabel",
            font=("Segoe UI", 10)
        )

        style.configure(
            "Header.TLabel",
            font=("Segoe UI", 12, "bold")
        )

        style.configure(
            "Metric.TLabel",
            font=("Segoe UI", 16, "bold")
        )

    # --------------------------------------------------------
    # INTERFACE
    # --------------------------------------------------------

    def build_interface(self):

        # ====================================================
        # HEADER
        # ====================================================

        header = ttk.Frame(
            self.root,
            padding=15
        )

        header.pack(
            fill="x"
        )

        ttk.Label(
            header,
            text="AI Stock Price Predictor",
            style="Title.TLabel"
        ).pack(
            anchor="w"
        )

        ttk.Label(
            header,
            text=(
                "Web Scraping + Market Data + News Sentiment "
                "+ Machine Learning"
            ),
            style="Subtitle.TLabel"
        ).pack(
            anchor="w",
            pady=(3, 10)
        )

        # ====================================================
        # INPUT
        # ====================================================

        input_frame = ttk.LabelFrame(
            self.root,
            text="Stock Analysis",
            padding=12
        )

        input_frame.pack(
            fill="x",
            padx=15,
            pady=5
        )

        ttk.Label(
            input_frame,
            text="Stock Symbol:"
        ).grid(
            row=0,
            column=0,
            padx=5
        )

        self.symbol_entry = ttk.Entry(
            input_frame,
            width=22,
            font=("Segoe UI", 11)
        )

        self.symbol_entry.grid(
            row=0,
            column=1,
            padx=5
        )

        self.symbol_entry.insert(
            0,
            "RELIANCE.NS"
        )

        ttk.Label(
            input_frame,
            text="Historical Days:"
        ).grid(
            row=0,
            column=2,
            padx=(20, 5)
        )

        self.days_var = tk.StringVar(
            value="100"
        )

        days_combo = ttk.Combobox(
            input_frame,
            textvariable=self.days_var,
            values=[
                "10",
                "30",
                "60",
                "100",
                "180"
            ],
            width=10,
            state="readonly"
        )

        days_combo.grid(
            row=0,
            column=3,
            padx=5
        )

        self.analyze_button = ttk.Button(
            input_frame,
            text="ANALYZE STOCK",
            command=self.start_analysis
        )

        self.analyze_button.grid(
            row=0,
            column=4,
            padx=(20, 5)
        )

        self.status_var = tk.StringVar(
            value="Ready"
        )

        ttk.Label(
            input_frame,
            textvariable=self.status_var
        ).grid(
            row=0,
            column=5,
            padx=15
        )

        # ====================================================
        # MAIN PANED WINDOW
        # ====================================================

        main = ttk.PanedWindow(
            self.root,
            orient="vertical"
        )

        main.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=10
        )

        # ====================================================
        # TOP AREA
        # ====================================================

        top = ttk.Frame(
            main
        )

        main.add(
            top,
            weight=1
        )

        # ----------------------------------------------------
        # Prediction Metrics
        # ----------------------------------------------------

        metrics = ttk.LabelFrame(
            top,
            text="Prediction",
            padding=12
        )

        metrics.pack(
            fill="x",
            pady=(0, 8)
        )

        self.current_var = tk.StringVar(
            value="-"
        )

        self.predicted_var = tk.StringVar(
            value="-"
        )

        self.change_var = tk.StringVar(
            value="-"
        )

        self.signal_var = tk.StringVar(
            value="-"
        )

        self.model_var = tk.StringVar(
            value="-"
        )

        metric_items = [
            ("Current Price", self.current_var),
            ("Predicted Price", self.predicted_var),
            ("Expected Change", self.change_var),
            ("Signal", self.signal_var),
            ("Best Model", self.model_var)
        ]

        for i, (label, variable) in enumerate(
            metric_items
        ):

            box = ttk.Frame(
                metrics,
                padding=8
            )

            box.grid(
                row=0,
                column=i,
                sticky="ew"
            )

            metrics.columnconfigure(
                i,
                weight=1
            )

            ttk.Label(
                box,
                text=label
            ).pack()

            ttk.Label(
                box,
                textvariable=variable,
                style="Metric.TLabel"
            ).pack(
                pady=5
            )

        # ----------------------------------------------------
        # CHART
        # ----------------------------------------------------

        chart_frame = ttk.LabelFrame(
            top,
            text="Historical Price",
            padding=5
        )

        chart_frame.pack(
            fill="both",
            expand=True
        )

        self.figure = Figure(
            figsize=(10, 4),
            dpi=100
        )

        self.ax = self.figure.add_subplot(
            111
        )

        self.ax.set_title(
            "Stock Price"
        )

        self.ax.set_xlabel(
            "Date"
        )

        self.ax.set_ylabel(
            "Price"
        )

        self.canvas = FigureCanvasTkAgg(
            self.figure,
            chart_frame
        )

        self.canvas.get_tk_widget().pack(
            fill="both",
            expand=True
        )

        # ====================================================
        # BOTTOM AREA
        # ====================================================

        bottom = ttk.Frame(
            main
        )

        main.add(
            bottom,
            weight=1
        )

        # ----------------------------------------------------
        # Notebook
        # ----------------------------------------------------

        notebook = ttk.Notebook(
            bottom
        )

        notebook.pack(
            fill="both",
            expand=True
        )

        # ====================================================
        # MARKET DATA TAB
        # ====================================================

        market_tab = ttk.Frame(
            notebook
        )

        notebook.add(
            market_tab,
            text="Market Data"
        )

        market_columns = [
            "Date",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Change %"
        ]

        self.market_tree = ttk.Treeview(
            market_tab,
            columns=market_columns,
            show="headings"
        )

        for column in market_columns:

            self.market_tree.heading(
                column,
                text=column
            )

            self.market_tree.column(
                column,
                width=130
            )

        market_scroll = ttk.Scrollbar(
            market_tab,
            orient="vertical",
            command=self.market_tree.yview
        )

        self.market_tree.configure(
            yscrollcommand=market_scroll.set
        )

        self.market_tree.pack(
            side="left",
            fill="both",
            expand=True
        )

        market_scroll.pack(
            side="right",
            fill="y"
        )

        # ====================================================
        # NEWS TAB
        # ====================================================

        news_tab = ttk.Frame(
            notebook
        )

        notebook.add(
            news_tab,
            text="News & Sentiment"
        )

        news_columns = [
            "Title",
            "Source",
            "Sentiment",
            "Score"
        ]

        self.news_tree = ttk.Treeview(
            news_tab,
            columns=news_columns,
            show="headings"
        )

        for column in news_columns:

            self.news_tree.heading(
                column,
                text=column
            )

            self.news_tree.column(
                column,
                width=180
            )

        self.news_tree.column(
            "Title",
            width=600
        )

        news_scroll = ttk.Scrollbar(
            news_tab,
            orient="vertical",
            command=self.news_tree.yview
        )

        self.news_tree.configure(
            yscrollcommand=news_scroll.set
        )

        self.news_tree.pack(
            side="left",
            fill="both",
            expand=True
        )

        news_scroll.pack(
            side="right",
            fill="y"
        )

        # ====================================================
        # MODEL TAB
        # ====================================================

        model_tab = ttk.Frame(
            notebook
        )

        notebook.add(
            model_tab,
            text="Model Performance"
        )

        model_columns = [
            "Model",
            "MAE",
            "RMSE",
            "R²",
            "Directional Accuracy"
        ]

        self.model_tree = ttk.Treeview(
            model_tab,
            columns=model_columns,
            show="headings"
        )

        for column in model_columns:

            self.model_tree.heading(
                column,
                text=column
            )

            self.model_tree.column(
                column,
                width=180
            )

        self.model_tree.pack(
            fill="both",
            expand=True
        )

        # ====================================================
        # LOG TAB
        # ====================================================

        log_tab = ttk.Frame(
            notebook
        )

        notebook.add(
            log_tab,
            text="System Log"
        )

        self.log_text = tk.Text(
            log_tab,
            height=10,
            wrap="word",
            font=("Consolas", 10)
        )

        self.log_text.pack(
            fill="both",
            expand=True
        )

    # ========================================================
    # LOGGING
    # ========================================================

    def log(self, message):

        def write():

            self.log_text.insert(
                "end",
                message + "\n"
            )

            self.log_text.see(
                "end"
            )

        self.root.after(
            0,
            write
        )

    # ========================================================
    # START ANALYSIS
    # ========================================================

    def start_analysis(self):

        symbol = self.symbol_entry.get().strip()

        if not symbol:
            messagebox.showwarning(
                "Input Required",
                "Please enter a stock symbol."
            )
            return

        try:
            days = int(
                self.days_var.get()
            )
        except:
            messagebox.showerror(
                "Invalid Days",
                "Please select a valid historical period."
            )
            return

        self.analyze_button.config(
            state="disabled"
        )

        self.status_var.set(
            "Analyzing..."
        )

        self.log_text.delete(
            "1.0",
            "end"
        )

        thread = threading.Thread(
            target=self.run_analysis,
            args=(symbol, days),
            daemon=True
        )

        thread.start()

    # ========================================================
    # ANALYSIS PIPELINE
    # ========================================================

    def run_analysis(
        self,
        symbol,
        days
    ):

        try:

            symbol = normalize_symbol(
                symbol
            )

            self.log(
                f"Stock requested: {symbol}"
            )

            # ------------------------------------------------
            # STEP 1
            # ------------------------------------------------

            self.log(
                "STEP 1: Connecting to financial website..."
            )

            self.log(
                "STEP 2: Sending HTTP GET request..."
            )

            self.log(
                "STEP 3: Verifying HTTP status code 200..."
            )

            # ------------------------------------------------
            # STEP 2 - MARKET DATA
            # ------------------------------------------------

            self.market_df = (
                self.scraper.scrape_market_data(
                    symbol,
                    days
                )
            )

            self.log(
                f"Market data received: "
                f"{len(self.market_df)} trading days"
            )

            self.log(
                "STEP 4: BeautifulSoup website parsing completed."
            )

            self.log(
                "STEP 5: Converting market data to Pandas DataFrame."
            )

            # ------------------------------------------------
            # STEP 3 - NEWS
            # ------------------------------------------------

            self.log(
                "STEP 6: Searching financial news..."
            )

            try:

                self.news_df = (
                    self.scraper.scrape_news(
                        symbol
                    )
                )

                self.log(
                    f"News articles collected: "
                    f"{len(self.news_df)}"
                )

            except Exception as news_error:

                self.news_df = pd.DataFrame(
                    columns=[
                        "Title",
                        "Source",
                        "Date",
                        "Sentiment",
                        "Score",
                        "Link"
                    ]
                )

                self.log(
                    f"News warning: {news_error}"
                )

            # ------------------------------------------------
            # STEP 4 - FEATURES
            # ------------------------------------------------

            self.log(
                "STEP 7: Creating technical indicators..."
            )

            self.final_df = create_features(
                self.market_df,
                self.news_df
            )

            self.log(
                "STEP 8: Feature engineering completed."
            )

            # ------------------------------------------------
            # STEP 5 - MACHINE LEARNING
            # ------------------------------------------------

            self.log(
                "STEP 9: Training regression models..."
            )

            results = self.predictor.train(
                self.final_df
            )

            self.log(
                "STEP 10: Chronological train/test validation completed."
            )

            self.log(
                f"Best model: "
                f"{self.predictor.best_model_name}"
            )

            # ------------------------------------------------
            # STEP 6 - PREDICTION
            # ------------------------------------------------

            prediction = (
                self.predictor.predict_next(
                    self.final_df
                )
            )

            self.log(
                "STEP 11: Next-price prediction completed."
            )

            self.log(
                f"Current price: "
                f"{prediction['current']:.2f}"
            )

            self.log(
                f"Predicted price: "
                f"{prediction['prediction']:.2f}"
            )

            self.log(
                f"Expected movement: "
                f"{prediction['change']:.2f}%"
            )

            self.log(
                f"Signal: "
                f"{prediction['signal']}"
            )

            self.root.after(
                0,
                self.display_results,
                prediction,
                results
            )

        except Exception as error:

            self.root.after(
                0,
                self.analysis_error,
                str(error)
            )

    # ========================================================
    # DISPLAY RESULTS
    # ========================================================

    def display_results(
        self,
        prediction,
        results
    ):

        self.current_var.set(
            f"{prediction['current']:.2f}"
        )

        self.predicted_var.set(
            f"{prediction['prediction']:.2f}"
        )

        self.change_var.set(
            f"{prediction['change']:+.2f}%"
        )

        self.signal_var.set(
            prediction["signal"]
        )

        self.model_var.set(
            self.predictor.best_model_name
        )

        # ----------------------------------------------------
        # Market table
        # ----------------------------------------------------

        for item in self.market_tree.get_children():

            self.market_tree.delete(
                item
            )

        display_df = self.market_df.tail(30)

        for _, row in display_df.iterrows():

            date = row["Date"].strftime(
                "%Y-%m-%d"
            )

            volume = (
                f"{row['Volume']:,.0f}"
                if pd.notna(row["Volume"])
                else "-"
            )

            change = (
                f"{row['Change %']:.2f}%"
                if pd.notna(row["Change %"])
                else "-"
            )

            self.market_tree.insert(
                "",
                "end",
                values=[
                    date,
                    f"{row['Open']:.2f}",
                    f"{row['High']:.2f}",
                    f"{row['Low']:.2f}",
                    f"{row['Close']:.2f}",
                    volume,
                    change
                ]
            )

        # ----------------------------------------------------
        # News table
        # ----------------------------------------------------

        for item in self.news_tree.get_children():

            self.news_tree.delete(
                item
            )

        if self.news_df is not None:

            for _, row in self.news_df.iterrows():

                self.news_tree.insert(
                    "",
                    "end",
                    values=[
                        row["Title"],
                        row["Source"],
                        row["Sentiment"],
                        row["Score"]
                    ]
                )

        # ----------------------------------------------------
        # Model table
        # ----------------------------------------------------

        for item in self.model_tree.get_children():

            self.model_tree.delete(
                item
            )

        for model_name, result in results.items():

            self.model_tree.insert(
                "",
                "end",
                values=[
                    model_name,
                    f"{result['MAE']:.4f}",
                    f"{result['RMSE']:.4f}",
                    f"{result['R2']:.4f}",
                    f"{result['Direction']:.2f}%"
                ]
            )

        # ----------------------------------------------------
        # Chart
        # ----------------------------------------------------

        self.ax.clear()

        self.ax.plot(
            self.market_df["Date"],
            self.market_df["Close"],
            linewidth=2,
            label="Close Price"
        )

        self.ax.plot(
            self.market_df["Date"],
            self.market_df["Close"].rolling(20).mean(),
            linewidth=1.5,
            label="20-Day MA"
        )

        self.ax.set_title(
            "Historical Closing Price"
        )

        self.ax.set_xlabel(
            "Date"
        )

        self.ax.set_ylabel(
            "Price"
        )

        self.ax.legend()

        self.figure.autofmt_xdate()

        self.canvas.draw()

        self.status_var.set(
            "Analysis complete"
        )

        self.analyze_button.config(
            state="normal"
        )

    # ========================================================
    # ERROR HANDLING
    # ========================================================

    def analysis_error(
        self,
        error
    ):

        self.status_var.set(
            "Analysis failed"
        )

        self.analyze_button.config(
            state="normal"
        )

        self.log(
            f"ERROR: {error}"
        )

        messagebox.showerror(
            "Analysis Error",
            error
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    root = tk.Tk()

    app = StockApp(
        root
    )

    root.mainloop()