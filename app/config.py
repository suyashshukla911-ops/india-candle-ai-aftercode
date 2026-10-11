from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

COMMON_INDIAN_STOCKS = [
    ("RELIANCE", "Reliance Industries"), ("TCS", "Tata Consultancy Services"),
    ("INFY", "Infosys"), ("HDFCBANK", "HDFC Bank"), ("ICICIBANK", "ICICI Bank"),
    ("SBIN", "State Bank of India"), ("BHARTIARTL", "Bharti Airtel"),
    ("ITC", "ITC"), ("LT", "Larsen & Toubro"), ("AXISBANK", "Axis Bank"),
    ("MARUTI", "Maruti Suzuki"), ("HINDUNILVR", "Hindustan Unilever"),
    ("TATAMOTORS", "Tata Motors"), ("TATASTEEL", "Tata Steel"),
    ("ADANIENT", "Adani Enterprises"), ("ADANIPORTS", "Adani Ports"),
    ("SUNPHARMA", "Sun Pharma"), ("WIPRO", "Wipro"), ("HCLTECH", "HCL Technologies"),
    ("KOTAKBANK", "Kotak Mahindra Bank"), ("BAJFINANCE", "Bajaj Finance"),
    ("M&M", "Mahindra & Mahindra"), ("ULTRACEMCO", "UltraTech Cement"),
    ("NTPC", "NTPC"), ("POWERGRID", "Power Grid"), ("ONGC", "ONGC"),
    ("COALINDIA", "Coal India"), ("TITAN", "Titan Company"), ("ASIANPAINT", "Asian Paints"),
    ("NESTLEIND", "Nestle India"), ("JSWSTEEL", "JSW Steel"), ("TECHM", "Tech Mahindra"),
    ("INDUSINDBK", "IndusInd Bank"), ("BAJAJFINSV", "Bajaj Finserv"),
    ("DIVISLAB", "Divi's Laboratories"), ("DRREDDY", "Dr Reddy's Laboratories"),
    ("CIPLA", "Cipla"), ("EICHERMOT", "Eicher Motors"), ("HEROMOTOCO", "Hero MotoCorp"),
    ("TVSMOTOR", "TVS Motor"), ("GRASIM", "Grasim Industries"), ("BRITANNIA", "Britannia"),
    ("APOLLOHOSP", "Apollo Hospitals"), ("BEL", "Bharat Electronics"),
    ("TRENT", "Trent"), ("ZOMATO", "Zomato"), ("JIOFIN", "Jio Financial Services"),
]

SECTOR_BY_SYMBOL = {
    "RELIANCE": "Energy / Telecom", "TCS": "IT", "INFY": "IT", "HDFCBANK": "Banking",
    "ICICIBANK": "Banking", "SBIN": "Banking", "BHARTIARTL": "Telecom", "ITC": "FMCG",
    "LT": "Infrastructure", "AXISBANK": "Banking", "MARUTI": "Automotive", "HINDUNILVR": "FMCG",
    "TATAMOTORS": "Automotive", "TATASTEEL": "Metals", "ADANIENT": "Conglomerate",
    "ADANIPORTS": "Logistics", "SUNPHARMA": "Pharma", "WIPRO": "IT", "HCLTECH": "IT",
    "KOTAKBANK": "Banking", "BAJFINANCE": "Financial Services", "M&M": "Automotive",
    "ULTRACEMCO": "Cement", "NTPC": "Power", "POWERGRID": "Power", "ONGC": "Energy",
    "COALINDIA": "Mining", "TITAN": "Consumer", "ASIANPAINT": "Consumer", "NESTLEIND": "FMCG",
    "JSWSTEEL": "Metals", "TECHM": "IT", "INDUSINDBK": "Banking", "BAJAJFINSV": "Financial Services",
    "DIVISLAB": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma", "EICHERMOT": "Automotive",
    "HEROMOTOCO": "Automotive", "TVSMOTOR": "Automotive", "GRASIM": "Conglomerate", "BRITANNIA": "FMCG",
    "APOLLOHOSP": "Healthcare", "BEL": "Defence", "TRENT": "Retail", "ZOMATO": "Internet / Consumer",
    "JIOFIN": "Financial Services",
}

INDEX_SYMBOLS = {"nifty": "^NSEI", "banknifty": "^NSEBANK", "vix": "^INDIAVIX"}

@dataclass(frozen=True)
class Settings:
    app_name: str
    default_interval: str
    train_days: int
    min_train_rows: int
    signal_precision_gate: float
    max_cache_hours: float
    data_timeout_seconds: float
    max_candles_display: int
    chart_candles: int
    runtime_dir: Path
    monitored_repo: Path
    allow_fallback: bool
    catalog_refresh_hours: float
    deep_security_scan: bool

    @classmethod
    def from_env(cls) -> "Settings":
        runtime = ROOT_DIR / os.getenv("RUNTIME_DIR", "runtime")
        monitored = ROOT_DIR / os.getenv("MONITORED_REPOSITORY", "workspace/monitored_repository")
        return cls(
            app_name=os.getenv("APP_NAME", "India Candle AI"),
            default_interval=os.getenv("DEFAULT_INTERVAL", "60m"),
            train_days=int(os.getenv("TRAIN_DAYS", "90")),
            min_train_rows=int(os.getenv("MIN_TRAIN_ROWS", "240")),
            signal_precision_gate=float(os.getenv("SIGNAL_PRECISION_GATE", "0.90")),
            max_cache_hours=float(os.getenv("MAX_CACHE_HOURS", "12")),
            data_timeout_seconds=float(os.getenv("DATA_TIMEOUT_SECONDS", "8")),
            max_candles_display=int(os.getenv("MAX_CANDLES_DISPLAY", "90")),
            chart_candles=int(os.getenv("CHART_CANDLES", "60")),
            runtime_dir=runtime,
            monitored_repo=monitored,
            allow_fallback=os.getenv("ALLOW_FALLBACK", "false").lower() == "true",
            catalog_refresh_hours=float(os.getenv("CATALOG_REFRESH_HOURS", "12")),
            deep_security_scan=os.getenv("DEEP_SECURITY_SCAN", "false").lower() == "true",
        )

settings = Settings.from_env()
settings.runtime_dir.mkdir(parents=True, exist_ok=True)
(settings.runtime_dir / "cache").mkdir(parents=True, exist_ok=True)
(settings.runtime_dir / "models").mkdir(parents=True, exist_ok=True)
settings.monitored_repo.mkdir(parents=True, exist_ok=True)
