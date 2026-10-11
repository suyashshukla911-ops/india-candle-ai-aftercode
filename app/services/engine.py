from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from typing import Any

import joblib
import pandas as pd

from app.config import INDEX_SYMBOLS, SECTOR_BY_SYMBOL, settings
from app.data.news import NewsService
from app.data.yahoo import YahooDataError, YahooProvider
from app.ml.features import FEATURES, build_features, explain_row, prepare_training_frame, regime_from_row
from app.ml.model import CandleModel
from app.services.db import audit, journal_signal, save_model_run
from app.services.repository import RepositoryMonitor

class AnalysisEngine:
    def __init__(self, market: YahooProvider, news: NewsService, repo: RepositoryMonitor):
        self.market = market
        self.news = news
        self.repo = repo
        self.models: dict[tuple[str, str], CandleModel] = {}
        self.snapshots: dict[tuple[str, str], dict[str, Any]] = {}
        self.lock = threading.RLock()
        self._repo_cache: tuple[float, dict[str, Any]] | None = None
        self._repo_cache_seconds = 2
        self._context_cache: dict[tuple[str, int], tuple[float, dict[str, pd.DataFrame]]] = {}
        self._context_cache_seconds = 300

    def _dataset_fingerprint(self, frame: pd.DataFrame) -> str:
        sample = frame[["timestamp", "open", "high", "low", "close", "volume"]].tail(1600).copy()
        return hashlib.sha256(sample.round(8).to_csv(index=False).encode()).hexdigest()

    def invalidate_repository_cache(self) -> None:
        self._repo_cache = None

    def _repo_state(self) -> dict[str, Any]:
        now = time.time()
        if self._repo_cache and now - self._repo_cache[0] < self._repo_cache_seconds:
            return self._repo_cache[1]
        state = self.repo.scan(False, record_audit=False)
        self._repo_cache = (now, state)
        return state

    def _context(self, interval: str, days: int) -> dict[str, pd.DataFrame]:
        key = (interval, int(days))
        now = time.time()
        hit = self._context_cache.get(key)
        if hit and now - hit[0] < self._context_cache_seconds:
            return hit[1]
        out: dict[str, pd.DataFrame] = {}
        for name, symbol in INDEX_SYMBOLS.items():
            try:
                snap = self.market.history(symbol, interval, days=min(days, 60))
                out[name] = snap.frame[["timestamp", "close"]].copy()
            except Exception:
                out[name] = pd.DataFrame()
        self._context_cache[key] = (now, out)
        return out

    @staticmethod
    def _prediction_environment_fingerprint(repo: dict[str, Any]) -> str:
        """Fingerprint only the repository components that can change prediction behaviour.

        External audit repositories never participate in model caching. For a model-bound
        repository, stale state deliberately keeps using the last accepted environment so
        the old model remains inspectable; once the new baseline is accepted, the live
        prediction-affecting fingerprint changes and forces a fresh model build.
        """
        if repo.get("scope") != "model":
            return ""
        accepted = repo.get("accepted")
        current = repo.get("current") or {}
        source = accepted if repo.get("state") == "STALE" and accepted else current
        components = source.get("components") or {}
        payload = {
            "model": components.get("model", ""),
            "services": components.get("services", ""),
            "data": components.get("data", ""),
            "dependencies": components.get("dependencies", ""),
            "config": components.get("config", ""),
        }
        if not any(payload.values()):
            return ""
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _get_model(self, snapshot, interval: str, force_retrain: bool = False, environment_fingerprint: str = ""):
        key = (snapshot.resolved_symbol, interval)
        dataset_fp = self._dataset_fingerprint(snapshot.frame)
        model = self.models.get(key)
        if (model and not force_retrain and model.report
                and model.report.dataset_fingerprint == dataset_fp
                and getattr(model.report, "environment_fingerprint", "") == environment_fingerprint):
            return model, False, "cache"

        cache_fp = hashlib.sha256(f"{dataset_fp}|{environment_fingerprint}".encode()).hexdigest()
        model_file = settings.runtime_dir / "models" / (
            re.sub(r"[^A-Za-z0-9_.-]", "_", snapshot.resolved_symbol) + f"_{interval}_{cache_fp[:12]}.joblib"
        )
        if not force_retrain and model_file.exists():
            try:
                loaded = joblib.load(model_file)
                if (getattr(loaded, "report", None)
                        and loaded.report.dataset_fingerprint == dataset_fp
                        and getattr(loaded.report, "environment_fingerprint", "") == environment_fingerprint):
                    self.models[key] = loaded
                    return loaded, False, "disk-cache"
            except Exception:
                pass

        context = self._context(interval, settings.train_days)
        train = prepare_training_frame(snapshot.frame, context=context)
        if len(train) < settings.min_train_rows:
            raise ValueError(
                f"Not enough clean training rows for {snapshot.symbol} at {interval}. "
                f"Need {settings.min_train_rows}, have {len(train)}. Try a larger timeframe or refresh the data."
            )
        model = CandleModel(min_train_rows=settings.min_train_rows)
        model.fit(train, FEATURES, dataset_fingerprint=dataset_fp, environment_fingerprint=environment_fingerprint)
        self.models[key] = model
        try:
            joblib.dump(model, model_file, compress=3)
        except Exception:
            pass
        save_model_run(snapshot.symbol, interval, model.report.model_version, model.report.public())
        audit("model-trained", "ok", {
            "symbol": snapshot.symbol, "interval": interval, "model_version": model.report.model_version,
            "precision": model.report.signal_precision, "gate_pass": model.report.gate_pass,
            "environment_fingerprint": environment_fingerprint[:16],
        })
        return model, True, "forced-retrain" if force_retrain else "environment-or-data-changed"

    @staticmethod
    def _data_state(snapshot) -> tuple[str, bool]:
        if snapshot.data_status == "FALLBACK":
            return "UNVERIFIED", False
        latest = pd.Timestamp(snapshot.latest_timestamp)
        now = pd.Timestamp.now(tz=latest.tz) if latest.tzinfo else pd.Timestamp.now()
        minutes = interval_to_minutes(snapshot.interval)
        # During the Indian cash session a missing candle is treated strictly. Outside
        # the session, the last completed market session remains usable for analysis.
        hour_min = now.hour * 60 + now.minute
        weekday = now.weekday() < 5
        market_open = 9 * 60 + 15
        market_close = 15 * 60 + 30
        if weekday and market_open <= hour_min <= market_close:
            limit = max(2 * minutes * 60, 15 * 60)
        elif snapshot.interval == "1d":
            limit = 4 * 24 * 3600
        else:
            limit = 36 * 3600
        current = snapshot.freshness_seconds <= limit
        return ("CURRENT" if current else "STALE"), current

    @staticmethod
    def _risk(snapshot, latest_row: pd.Series, prediction: dict[str, Any]) -> dict[str, Any]:
        price = float(prediction["predicted_close"] / max(1e-9, 1 + prediction.get("expected_return_pct", 0) / 100))
        atr_pct = float(latest_row.get("atr_pct", 0.0) or 0.0)
        vol20 = float(latest_row.get("volatility_20", 0.0) or 0.0)
        realized = max(atr_pct, vol20 * 1.6)
        if realized < 0.005:
            level, score = "LOW", 82
        elif realized < 0.012:
            level, score = "MODERATE", 61
        elif realized < 0.025:
            level, score = "HIGH", 38
        else:
            level, score = "VERY HIGH", 18
        stop_pct = max(realized * 1.5, 0.004)
        target_pct = max(abs(float(prediction.get("expected_return_pct", 0))) / 100 * 1.4, stop_pct * 1.25)
        action = prediction.get("trading_action", "HOLD")
        if action == "BUY":
            stop = price * (1 - stop_pct)
            target = price * (1 + target_pct)
        elif action == "SELL":
            stop = price * (1 + stop_pct)
            target = price * (1 - target_pct)
        else:
            stop, target = None, None
        rr = target_pct / stop_pct if stop_pct else 0
        guidance = {
            "BUY": "Protect capital with the calculated stop; target is model-derived and must be rechecked before entry.",
            "SELL": "Use the calculated stop as an invalidation level; downside target is model-derived.",
            "HOLD": "No directional edge strong enough to justify a new position under the current risk rules.",
        }.get(action, "Revalidate the environment before acting.")
        return {
            "level": level, "score": score,
            "atr_pct": round(atr_pct * 100, 3), "realized_volatility_pct": round(realized * 100, 3),
            "stop_loss": round(stop, 2) if stop is not None else None,
            "take_profit": round(target, 2) if target is not None else None,
            "risk_reward": round(rr, 2),
            "capital_action": action if action in {"BUY", "SELL"} else "HOLD",
            "guidance": guidance,
        }

    def analyze(self, symbol: str, interval: str, force_retrain: bool = False, refresh_data: bool = False) -> dict[str, Any]:
        with self.lock:
            if interval not in {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d"}:
                raise ValueError("Unsupported timeframe.")
            started = time.time()
            snap = self.market.history(symbol, interval, settings.train_days, refresh=refresh_data)
            repo = self._repo_state()
            environment_fingerprint = self._prediction_environment_fingerprint(repo)
            model, retrained, model_cache_state = self._get_model(snap, interval, force_retrain, environment_fingerprint)
            context = self._context(interval, min(settings.train_days, 60))
            live_features = build_features(snap.frame, context=context).dropna(subset=FEATURES)
            if live_features.empty:
                raise ValueError("Not enough clean rows for feature generation.")
            latest = live_features.iloc[[-1]]
            price = float(latest.close.iloc[0])
            regime = regime_from_row(latest.iloc[0], live_features)
            data_state, data_current = self._data_state(snap)
            # Only a repository bound to the model environment affects prediction trust.
            model_bound = bool(repo.get("scope") == "model")
            repo_current = repo["state"] == "CURRENT" if model_bound else True
            articles = self.news.fetch(snap.resolved_symbol, snap.name, limit=6)
            news = self.news.aggregate(articles)
            prediction = model.predict(
                latest, price, news["impact"], regime,
                repo_current=repo_current, data_current=data_current
            )
            security_blocking = bool(model_bound and repo.get("security_blocking"))
            if security_blocking:
                prediction["signal"] = "REVALIDATE"
                prediction["trading_action"] = "HOLD"
                prediction["confidence"] = min(float(prediction.get("confidence", 50)), 45.0)
            explanation = explain_row(latest.iloc[0], prediction["signal"], model.report.gate_pass)
            prediction["explanation"] = explanation
            prediction["environment"] = {
                "repository": repo["state"] if model_bound else "EXTERNAL AUDIT",
                "repository_scope": repo.get("scope", "model"),
                "data": data_state,
                "model_gate": "PASS" if model.report.gate_pass else "FAIL",
                "model_version": model.report.model_version,
                "training_seconds": model.report.training_seconds,
                "dataset_fingerprint": model.report.dataset_fingerprint[:16],
                "environment_fingerprint": getattr(model.report, "environment_fingerprint", "")[:16],
                "model_cache_state": model_cache_state,
                "repository_revalidation": repo.get("revalidation_required", False),
                "repository_security": "BLOCKED" if security_blocking else "CLEAR",
            }
            prediction["risk"] = self._risk(snap, latest.iloc[0], prediction)
            prediction["trust"] = self.trust_score(
                model=model, repo=repo, snapshot=snap, data_current=data_current,
                regime=regime, news_impact=news["impact"], model_bound=model_bound
            )
            last_ts = latest.timestamp.iloc[0]
            candles = snap.frame.tail(min(settings.max_candles_display, settings.chart_candles))
            result = {
                "instrument": {
                    "symbol": snap.symbol, "yahoo_symbol": snap.resolved_symbol, "name": snap.name,
                    "exchange": snap.exchange,
                    "sector": SECTOR_BY_SYMBOL.get(snap.resolved_symbol.replace(".NS", "").replace(".BO", "").upper(), "Unknown"),
                },
                "interval": interval,
                "current_price": price,
                "last_timestamp": last_ts.isoformat(),
                "data": {
                    "status": data_state, "freshness_seconds": round(snap.freshness_seconds, 1),
                    "fetched_at": snap.fetched_at, "history_rows": len(snap.frame),
                    "training_rows": model.report.train_rows,
                },
                "prediction": prediction,
                "news": {"summary": news, "articles": articles},
                "regime": regime,
                "model": model.report.public(),
                "model_operations": {
                    "retrained": retrained,
                    "training_seconds": model.report.training_seconds,
                    "model_version": model.report.model_version,
                    "dataset_fingerprint": model.report.dataset_fingerprint[:16],
                    "environment_fingerprint": getattr(model.report, "environment_fingerprint", "")[:16],
                    "cache_key": f"{snap.resolved_symbol}|{interval}|{getattr(model.report, 'environment_fingerprint', '')[:8]}",
                    "cache_state": model_cache_state,
                },
                "backtest": model.backtest(),
                "candles": [
                    {"time": r.timestamp.isoformat(), "open": float(r.open), "high": float(r.high),
                     "low": float(r.low), "close": float(r.close), "volume": float(r.volume)}
                    for r in candles.itertuples()
                ],
                "retrained": retrained,
                "elapsed_ms": round((time.time() - started) * 1000, 1),
            }
            journal_signal({
                "symbol": snap.resolved_symbol, "interval": interval, "signal": prediction["signal"],
                "confidence": prediction["confidence"], "probability_up": prediction["probability_up"],
                "precision": model.report.signal_precision, "model_version": model.report.model_version,
                "repo_state": repo["state"], "data_state": data_state, "current_price": price,
                "predicted_close": prediction["predicted_close"],
            })
            self.snapshots[(snap.resolved_symbol, interval)] = result
            return result

    def trust_score(self, model: CandleModel, repo: dict[str, Any], snapshot, data_current: bool,
                    regime: dict[str, str], news_impact: float, model_bound: bool = True) -> dict[str, Any]:
        score = 100.0
        checks = []
        if model_bound:
            if repo["state"] != "CURRENT":
                score -= 35; checks.append(("Repository freshness", "FAIL", "Model environment changed; accept a new baseline."))
            else:
                checks.append(("Repository freshness", "PASS", "Accepted baseline matches the current model environment."))
        else:
            checks.append(("Repository scope", "INFO", "External repository is being audited and is not bound to the market model."))
        if data_current:
            checks.append(("Market data freshness", "PASS", snapshot.data_status))
        else:
            score -= 25; checks.append(("Market data freshness", "FAIL", "Latest market candle is stale or unverified."))
        if model_bound and repo.get("security_blocking"):
            score -= 30; checks.append(("Repository security", "FAIL", "A HIGH-severity repository finding blocks model trust until remediated."))
        elif model_bound:
            checks.append(("Repository security", "PASS", "No HIGH-severity finding blocks model trust."))
        if model.report.gate_pass:
            checks.append(("90% signal precision gate", "PASS", f"{model.report.signal_precision*100:.2f}%"))
        else:
            score -= 30; checks.append(("90% signal precision gate", "FAIL", f"{model.report.signal_precision*100:.2f}%"))
        if regime["volatility"] == "HIGH":
            score -= 8; checks.append(("Volatility", "WARN", "High"))
        else:
            checks.append(("Volatility", "PASS", regime["volatility"]))
        if abs(news_impact) > 0.60:
            score -= 5; checks.append(("News conflict", "WARN", f"impact {news_impact:+.2f}"))
        else:
            checks.append(("News conflict", "PASS", f"impact {news_impact:+.2f}"))
        score = max(0, min(100, score))
        if model_bound and repo["security_blocking"]:
            status = "SECURITY REVALIDATION REQUIRED"
        elif model_bound and repo["state"] != "CURRENT":
            status = "REVALIDATION REQUIRED"
        elif not data_current:
            status = "DATA REVALIDATION REQUIRED"
        elif not model.report.gate_pass:
            status = "NO-TRADE QUALITY GATE"
        elif score >= 80:
            status = "TRUSTED"
        else:
            status = "CAUTION"
        return {"score": round(score, 1), "status": status,
                "checks": [{"name": a, "status": b, "detail": c} for a, b, c in checks]}

    def full_analysis(self, symbol: str, interval: str) -> dict[str, Any]:
        return self.analyze(symbol, interval, force_retrain=False, refresh_data=True)

    def backtest_only(self, symbol: str, interval: str) -> dict[str, Any]:
        return self.analyze(symbol, interval, force_retrain=False)["backtest"]

def interval_to_minutes(v: str) -> int:
    if v.endswith("m"):
        return int(v[:-1])
    if v.endswith("h"):
        return int(v[:-1]) * 60
    if v == "1d":
        return 1440
    return 1
