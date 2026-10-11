from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import accuracy_score, mean_absolute_error, precision_score, r2_score

from app.config import settings

@dataclass
class ModelReport:
    direction_accuracy: float
    signal_precision: float
    signal_coverage: float
    next_return_mae: float
    next_return_r2: float
    threshold: float
    gate_pass: bool
    train_rows: int
    validation_rows: int
    classifier_name: str
    dataset_fingerprint: str = ""
    model_version: str = ""
    trained_at: str = ""
    training_seconds: float = 0.0
    environment_fingerprint: str = ""

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["direction_accuracy"] = round(d["direction_accuracy"] * 100, 2)
        d["signal_precision"] = round(d["signal_precision"] * 100, 2)
        d["signal_coverage"] = round(d["signal_coverage"] * 100, 2)
        d["next_return_mae"] = round(d["next_return_mae"], 6)
        d["next_return_r2"] = round(d["next_return_r2"], 4)
        d["threshold"] = round(d["threshold"], 3)
        return d

class CandleModel:
    def __init__(self, min_train_rows: int | None = None):
        self.min_train_rows = min_train_rows or settings.min_train_rows
        self.features: list[str] = []
        self.classifier = None
        self.regressors: dict[str, Any] = {}
        self.report: ModelReport | None = None
        self.validation_predictions: pd.DataFrame | None = None

    @staticmethod
    def _candidate_classifiers():
        return [
            ("histgb", HistGradientBoostingClassifier(
                max_depth=5, learning_rate=0.055, max_iter=120,
                l2_regularization=0.7, random_state=42
            )),
            ("extratrees", ExtraTreesClassifier(
                n_estimators=80, max_depth=12, min_samples_leaf=3,
                n_jobs=-1, class_weight="balanced", random_state=42
            )),
        ]

    @staticmethod
    def _candidate_regressor():
        return HistGradientBoostingRegressor(
            max_depth=5, learning_rate=0.055, max_iter=110,
            l2_regularization=0.7, loss="absolute_error", random_state=42
        )

    @staticmethod
    def optimize_threshold(y_true: np.ndarray, p_up: np.ndarray, minimum_precision: float = 0.90,
                           actual_returns: np.ndarray | None = None):
        candidates = []
        n = len(y_true)
        if n == 0:
            return 0.90, 0.0, 0.0, False
        for t in np.arange(0.55, 0.951, 0.01):
            long = p_up >= t
            short = p_up <= (1 - t)
            mask = long | short
            count = int(mask.sum())
            if count < max(5, int(n * 0.015)):
                continue
            if actual_returns is not None:
                returns = np.asarray(actual_returns)[mask]
                side_long = long[mask]
                wins = ((side_long & (returns > 0)) | ((~side_long) & (returns < 0)))
                precision = float(wins.mean()) if len(wins) else 0.0
            else:
                preds = np.where(long[mask], 1, 0)
                precision = float(precision_score(y_true[mask], preds, zero_division=0))
            coverage = count / n
            candidates.append((precision, coverage, float(t)))
        passing = [x for x in candidates if x[0] >= minimum_precision]
        if passing:
            passing.sort(key=lambda x: (x[1], x[0]), reverse=True)
            return (*passing[0], True)
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            return (*candidates[0], False)
        return 0.90, 0.0, 0.0, False

    def _pick_classifier(self, Xt, yt, Xv, yv, actual_returns):
        best = None
        best_key = (-1, -1.0, -1.0, -1.0)
        for name, candidate in self._candidate_classifiers():
            candidate.fit(Xt, yt)
            p = candidate.predict_proba(Xv)[:, 1]
            acc = float(accuracy_score(yv, (p >= 0.5).astype(int)))
            t, precision, coverage, gate = self.optimize_threshold(
                yv.to_numpy(), p, settings.signal_precision_gate, actual_returns=actual_returns
            )
            # Prefer a passing gate, then coverage, then precision, then direction accuracy.
            key = (1 if gate else 0, coverage if gate else precision, precision, acc)
            if key > best_key:
                best_key = key
                best = (name, candidate, p, t, precision, coverage, gate, acc)
        return best

    def fit(self, train_df: pd.DataFrame, features: list[str], dataset_fingerprint: str = "", environment_fingerprint: str = "") -> ModelReport:
        if len(train_df) < self.min_train_rows:
            raise ValueError(f"Need at least {self.min_train_rows} clean rows; got {len(train_df)}.")
        start = datetime.now().timestamp()
        self.features = list(features)
        split = int(len(train_df) * 0.78)
        split = max(120, min(split, len(train_df) - 80))
        train = train_df.iloc[:split].copy()
        val = train_df.iloc[split:].copy()

        picked = self._pick_classifier(
            train[self.features], train.direction.astype(int),
            val[self.features], val.direction.astype(int),
            val.next_return.to_numpy()
        )
        name, selected, p_val, threshold, precision, coverage, gate_pass, direction_accuracy = picked

        self.classifier = selected
        self.regressors = {}
        reg_metrics = []
        for target in ["next_return", "next_high_return", "next_low_return", "eod_return"]:
            reg = self._candidate_regressor()
            reg.fit(train[self.features], train[target])
            pred = reg.predict(val[self.features])
            reg_metrics.append((target, mean_absolute_error(val[target], pred), r2_score(val[target], pred)))
            reg.fit(train_df[self.features], train_df[target])
            self.regressors[target] = reg

        self.classifier.fit(train_df[self.features], train_df.direction.astype(int))
        rr = next(x for x in reg_metrics if x[0] == "next_return")
        feature_meta = json.dumps({
            "features": self.features,
            "threshold": threshold,
            "classifier": name,
            "dataset": dataset_fingerprint,
            "environment": environment_fingerprint,
            "gate": settings.signal_precision_gate,
        }, sort_keys=True)
        version = "v" + hashlib.sha256(feature_meta.encode()).hexdigest()[:10]
        self.validation_predictions = pd.DataFrame({
            "timestamp": val["timestamp"].to_numpy(),
            "close": val["close"].to_numpy(),
            "actual_return": val["next_return"].to_numpy(),
            "p_up": p_val,
        })
        self.report = ModelReport(
            direction_accuracy=float(direction_accuracy), signal_precision=float(precision),
            signal_coverage=float(coverage), next_return_mae=float(rr[1]), next_return_r2=float(rr[2]),
            threshold=float(threshold), gate_pass=bool(gate_pass), train_rows=len(train),
            validation_rows=len(val), classifier_name=name, dataset_fingerprint=dataset_fingerprint,
            model_version=version, trained_at=datetime.now().astimezone().isoformat(),
            training_seconds=round(datetime.now().timestamp() - start, 3),
            environment_fingerprint=environment_fingerprint,
        )
        return self.report

    def backtest(self) -> dict[str, Any]:
        if self.report is None or self.validation_predictions is None:
            raise RuntimeError("Fit the model before backtesting.")
        d = self.validation_predictions.copy()
        t = self.report.threshold
        d["signal"] = "HOLD"
        d.loc[d.p_up >= t, "signal"] = "BUY"
        d.loc[d.p_up <= 1 - t, "signal"] = "SELL"
        d["strategy_return"] = np.where(
            d.signal.eq("BUY"), d.actual_return,
            np.where(d.signal.eq("SELL"), -d.actual_return, 0.0)
        )
        d["equity"] = (1 + d.strategy_return.fillna(0)).cumprod()
        d["buyhold_equity"] = (1 + d.actual_return.fillna(0)).cumprod()
        peak = d["equity"].cummax()
        drawdown = d["equity"] / peak - 1
        wins = d.loc[d.strategy_return > 0, "strategy_return"]
        losses = d.loc[d.strategy_return < 0, "strategy_return"]
        signals = d[d.signal != "HOLD"]
        return {
            "validation_period": f"{d.timestamp.iloc[0].isoformat()} → {d.timestamp.iloc[-1].isoformat()}",
            "signals": int(len(signals)), "wins": int((signals.strategy_return > 0).sum()),
            "losses": int((signals.strategy_return < 0).sum()),
            "signal_precision": round(float((signals.strategy_return > 0).mean() * 100) if len(signals) else 0.0, 2),
            "strategy_return_pct": round(float((d.equity.iloc[-1] - 1) * 100), 2),
            "buy_hold_return_pct": round(float((d.buyhold_equity.iloc[-1] - 1) * 100), 2),
            "max_drawdown_pct": round(float(drawdown.min() * 100), 2),
            "profit_factor": round(float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else 99.0, 2),
            "coverage_pct": round(float(len(signals) / len(d) * 100), 2),
        }

    def predict(self, latest: pd.DataFrame, current_price: float, news_impact: float, regime: dict[str, str],
                repo_current: bool, data_current: bool) -> dict[str, Any]:
        if not self.report or self.classifier is None:
            raise RuntimeError("Model is not trained.")
        X = latest[self.features]
        p_up = float(self.classifier.predict_proba(X)[0, 1])
        outputs = {key: float(model.predict(X)[0]) for key, model in self.regressors.items()}
        t = self.report.threshold
        signal = "HOLD"
        if not repo_current or not data_current:
            signal = "REVALIDATE"
        elif self.report.gate_pass:
            if p_up >= t and news_impact > -0.55:
                signal = "BUY"
            elif p_up <= 1 - t and news_impact < 0.55:
                signal = "SELL"

        confidence = 50 + abs(p_up - 0.5) * 100
        confidence += max(0, self.report.signal_precision * 100 - 90) * 0.45
        if regime["volatility"] == "NORMAL": confidence += 4
        elif regime["volatility"] == "HIGH": confidence -= 8
        if not repo_current or not data_current: confidence = min(confidence, 45)
        confidence = max(0, min(99.9, confidence))
        return {
            "signal": signal,
            "trading_action": signal if signal in {"BUY", "SELL"} else "HOLD",
            "probability_up": round(p_up, 4),
            "probability_down": round(1 - p_up, 4),
            "confidence": round(confidence, 2),
            "predicted_close": round(current_price * (1 + outputs["next_return"]), 4),
            "predicted_high": round(current_price * (1 + max(outputs["next_high_return"], outputs["next_return"])), 4),
            "predicted_low": round(current_price * (1 + min(outputs["next_low_return"], outputs["next_return"])), 4),
            "predicted_eod_close": round(current_price * (1 + outputs["eod_return"]), 4),
            "expected_return_pct": round(outputs["next_return"] * 100, 3),
            "validation": self.report.public(),
            "backtest": self.backtest(),
        }
