from __future__ import annotations

import concurrent.futures
import csv
import io
import json
import time
from pathlib import Path
from typing import Any

import requests

from app.config import COMMON_INDIAN_STOCKS, settings

NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_SME_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"
BSE_EQUITY_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"


class IndianSecurityCatalog:
    """Broad searchable Indian equity universe.

    Discovery is refreshed from NSE equity, NSE SME and (when reachable) BSE active
    equity listings, then cached locally. Market-data availability is handled by
    the market provider separately, so being listed is not confused with having a
    particular OHLCV interval available.
    """

    def __init__(self, cache_file: Path | None = None):
        self.cache_file = Path(cache_file or settings.runtime_dir / "indian_security_catalog.json")
        self.max_age_seconds = max(1, settings.catalog_refresh_hours) * 3600
        self._rows: list[dict[str, str]] = []
        self._loaded = False

    def _fallback(self) -> list[dict[str, str]]:
        return [
            {
                "symbol": s,
                "name": n,
                "exchange": "NSE",
                "series": "EQ",
                "segment": "EQUITY",
                "yahoo_symbol": f"{s}.NS",
            }
            for s, n in COMMON_INDIAN_STOCKS
        ]

    def _save(self, rows: list[dict[str, str]]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps({"updated": time.time(), "rows": rows}, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _parse_nse_csv(payload: bytes, segment: str) -> list[dict[str, str]]:
        text = payload.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict[str, str]] = []
        for item in reader:
            symbol = (item.get("SYMBOL") or item.get("Symbol") or "").strip().upper()
            name = (
                item.get("NAME OF COMPANY")
                or item.get("NAME_OF_COMPANY")
                or item.get("Name of Company")
                or item.get("COMPANY NAME")
                or ""
            ).strip()
            series = (item.get(" SERIES") or item.get("SERIES") or "EQ").strip().upper()
            if not symbol or not name:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "exchange": "NSE",
                    "series": series or ("SM" if segment == "SME" else "EQ"),
                    "segment": segment,
                    "yahoo_symbol": f"{symbol}.NS",
                }
            )
        return rows

    @staticmethod
    def _parse_bse(payload: Any) -> list[dict[str, str]]:
        if isinstance(payload, dict):
            items = payload.get("Table") or payload.get("table") or payload.get("data") or []
        else:
            items = payload or []
        if not isinstance(items, list):
            return []
        rows: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = str(
                item.get("scrip_id")
                or item.get("Scrip_ID")
                or item.get("ScripId")
                or item.get("SYMBOL")
                or ""
            ).strip().upper()
            name = str(
                item.get("Scrip_Name")
                or item.get("SC_NAME")
                or item.get("Security_Name")
                or item.get("COMPANY_NAME")
                or ""
            ).strip()
            code = str(
                item.get("SCRIP_CD")
                or item.get("scripcode")
                or item.get("Security_Code")
                or ""
            ).strip()
            isin = str(item.get("ISIN_NUMBER") or item.get("ISIN") or "").strip()
            group = str(item.get("GROUP") or item.get("Group") or "").strip().upper()
            if not symbol and code:
                symbol = code
            if not symbol or not name:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "exchange": "BSE",
                    "series": group or "EQ",
                    "segment": "EQUITY",
                    "bse_code": code,
                    "isin": isin,
                    "yahoo_symbol": f"{symbol}.BO",
                }
            )
        return rows

    def _fetch_nse(self, url: str, segment: str) -> tuple[list[dict[str, str]], str | None]:
        try:
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 IndiaCandleAI/6.0",
                    "Accept": "text/csv,*/*;q=0.8",
                    "Referer": "https://www.nseindia.com/",
                }
            )
            response = session.get(url, timeout=min(settings.data_timeout_seconds, 8.0))
            response.raise_for_status()
            return self._parse_nse_csv(response.content, segment), None
        except Exception as exc:
            return [], f"{segment}: {exc}"

    def _fetch_bse(self) -> tuple[list[dict[str, str]], str | None]:
        try:
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 IndiaCandleAI/6.0",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.bseindia.com/",
                    "Origin": "https://www.bseindia.com",
                }
            )
            params = {
                "scripcode": "",
                "Group": "",
                "industry": "",
                "segment": "Equity",
                "status": "Active",
            }
            response = session.get(BSE_EQUITY_URL, params=params, timeout=min(settings.data_timeout_seconds, 8.0))
            response.raise_for_status()
            return self._parse_bse(response.json()), None
        except Exception as exc:
            return [], f"BSE: {exc}"

    def refresh(self) -> list[dict[str, str]]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(self._fetch_nse, NSE_EQUITY_URL, "EQUITY"),
                pool.submit(self._fetch_nse, NSE_SME_URL, "SME"),
                pool.submit(self._fetch_bse),
            ]
            fetched = [f.result() for f in futures]

        rows: list[dict[str, str]] = []
        for part, _error in fetched:
            rows.extend(part)

        # One visible security row per symbol, preferring NSE for an NSE+BSE dual
        # listing while preserving BSE metadata. BSE-only securities remain visible.
        dedup: dict[str, dict[str, str]] = {}
        for row in rows:
            key = row["symbol"]
            previous = dedup.get(key)
            if previous is None:
                dedup[key] = row
            elif previous.get("exchange") != "NSE" and row.get("exchange") == "NSE":
                merged = dict(row)
                if previous.get("bse_code"):
                    merged["bse_code"] = previous["bse_code"]
                if previous.get("isin"):
                    merged["isin"] = previous["isin"]
                merged["has_bse"] = "true"
                dedup[key] = merged
            elif row.get("exchange") == "BSE":
                previous["has_bse"] = "true"

        rows = sorted(dedup.values(), key=lambda x: (x["symbol"], x["name"]))
        if not rows:
            raise RuntimeError("Indian securities catalogue could not be refreshed.")
        self._save(rows)
        self._rows = rows
        self._loaded = True
        return rows

    def load(self, force: bool = False) -> list[dict[str, str]]:
        if self._loaded and not force:
            return self._rows
        if not force and self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                age = time.time() - float(data.get("updated", 0))
                rows = data.get("rows") or []
                if rows and age < self.max_age_seconds:
                    self._rows = rows
                    self._loaded = True
                    return rows
            except Exception:
                pass
        try:
            return self.refresh()
        except Exception:
            self._rows = self._fallback()
            self._loaded = True
            return self._rows

    def all(self, force: bool = False) -> list[dict[str, str]]:
        return [dict(r) for r in self.load(force=force)]

    def search(self, query: str, limit: int = 30) -> list[dict[str, str]]:
        rows = self.load()
        q = (query or "").strip().casefold()
        if not q:
            return [dict(x) for x in rows[:limit]]
        tokens = [t for t in q.replace("-", " ").split() if t]
        scored: list[tuple[int, dict[str, str]]] = []
        for row in rows:
            hay = f"{row['symbol']} {row['name']} {row.get('bse_code', '')}".casefold()
            if all(t in hay for t in tokens):
                score = 0
                if row["symbol"].casefold().startswith(q):
                    score += 100
                if row["name"].casefold().startswith(q):
                    score += 80
                if q in row["symbol"].casefold():
                    score += 50
                if q in row["name"].casefold():
                    score += 30
                if row.get("segment") == "EQUITY":
                    score += 2
                scored.append((score, row))
        scored.sort(key=lambda x: (-x[0], x[1]["symbol"]))
        return [dict(r) for _, r in scored[:limit]]

    def get(self, symbol: str) -> dict[str, str] | None:
        s = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
        for row in self.load():
            if row["symbol"] == s:
                return dict(row)
        return None

    def status(self) -> dict[str, Any]:
        rows = self._rows if self._loaded else []
        age = None
        if self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                age = max(0.0, time.time() - float(data.get("updated", 0)))
                if not rows:
                    rows = data.get("rows") or []
            except Exception:
                pass
        return {
            "count": len(rows),
            "updated_seconds_ago": age,
            "equity_count": sum(1 for r in rows if r.get("segment") == "EQUITY"),
            "sme_count": sum(1 for r in rows if r.get("segment") == "SME"),
            "bse_count": sum(1 for r in rows if r.get("exchange") == "BSE"),
            "search_ready": bool(rows),
        }
