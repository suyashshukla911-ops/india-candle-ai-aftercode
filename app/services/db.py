
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings

DB_PATH = settings.runtime_dir / "trustgraph.sqlite3"

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            event TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signal_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            signal TEXT NOT NULL,
            confidence REAL,
            probability_up REAL,
            precision REAL,
            model_version TEXT,
            repo_state TEXT,
            data_state TEXT,
            current_price REAL,
            predicted_close REAL,
            actual_close REAL
        );
        CREATE TABLE IF NOT EXISTS model_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            model_version TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        """)

def audit(event: str, status: str, payload: Any):
    with connect() as con:
        con.execute(
            "INSERT INTO audit_events(ts,event,status,payload) VALUES(?,?,?,?)",
            (datetime.now().astimezone().isoformat(), event, status, json.dumps(payload, default=str))
        )
        con.commit()

def journal_signal(payload: dict[str, Any]):
    with connect() as con:
        con.execute("""
        INSERT INTO signal_journal(
            ts,symbol,interval,signal,confidence,probability_up,precision,
            model_version,repo_state,data_state,current_price,predicted_close
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().astimezone().isoformat(), payload["symbol"], payload["interval"],
            payload["signal"], payload.get("confidence"), payload.get("probability_up"),
            payload.get("precision"), payload.get("model_version"), payload.get("repo_state"),
            payload.get("data_state"), payload.get("current_price"), payload.get("predicted_close")
        ))
        con.commit()

def save_model_run(symbol: str, interval: str, model_version: str, payload: dict[str, Any]):
    with connect() as con:
        con.execute(
            "INSERT INTO model_runs(ts,symbol,interval,model_version,payload) VALUES(?,?,?,?,?)",
            (datetime.now().astimezone().isoformat(), symbol, interval, model_version, json.dumps(payload, default=str))
        )
        con.commit()

def recent(table: str, limit: int = 20):
    allowed = {"audit_events", "signal_journal", "model_runs"}
    if table not in allowed:
        raise ValueError("invalid table")
    with connect() as con:
        rows = con.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

# Ensure the audit store exists for direct service calls and test clients.
init_db()
