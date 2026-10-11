from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.config import COMMON_INDIAN_STOCKS, settings
from app.data.news import NewsService
from app.data.yahoo import YahooProvider, YahooDataError
from app.services.db import init_db, recent
from app.services.engine import AnalysisEngine
from app.services.repository import RepositoryMonitor

BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"
market = YahooProvider()
news = NewsService()
repo = RepositoryMonitor()
engine = AnalysisEngine(market, news, repo)

AUTH_ENABLED = os.getenv("AUTH_ENABLED", os.getenv("DEMO_AUTH_ENABLED", "false")).lower() == "true"
AUTH_USER = os.getenv("AUTH_USERNAME", os.getenv("DEMO_USERNAME", "judge"))
AUTH_PASS = os.getenv("AUTH_PASSWORD", os.getenv("DEMO_PASSWORD", "change-me"))
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sample = settings.monitored_repo
    seed = {
        "app/ml/model.py": "# monitored model component\nMODEL_VERSION = '4.0'\n",
        "app/data/provider.py": "# monitored market provider component\nPROVIDER = 'market-data'\n",
        "app/services/trust.py": "# monitored trust component\nTRUST_POLICY = 'baseline'\n",
        "frontend/index.html": "<!-- monitored presentation component -->\n",
        "requirements.txt": "numpy>=2.1\nscikit-learn>=1.6\n",
        "README.md": "# Monitored model environment\n",
    }
    for rel, content in seed.items():
        p = sample / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(content, encoding="utf-8")
    yield

app = FastAPI(title=settings.app_name, version="6.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.middleware("http")
async def optional_basic_auth(request: Request, call_next):
    if not AUTH_ENABLED or request.url.path.startswith("/static/") or request.url.path == "/":
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    valid = False
    if auth.startswith("Basic "):
        try:
            raw = base64.b64decode(auth.split(" ", 1)[1]).decode()
            user, pwd = raw.split(":", 1)
            valid = hmac.compare_digest(user, AUTH_USER) and hmac.compare_digest(pwd, AUTH_PASS)
        except Exception:
            valid = False
    if not valid:
        from fastapi.responses import Response
        return Response("Authentication required", status_code=401, headers={"WWW-Authenticate": "Basic"})
    return await call_next(request)

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/api/bootstrap")
def bootstrap():
    repo_state = repo.scan(False, record_audit=False)
    return {
        "app": settings.app_name,
        "mode": "LIVE MARKET DATA + CACHE",
        "default_interval": settings.default_interval,
        "gate": settings.signal_precision_gate,
        "repository": repo_state,
        "catalog": market.catalog_status(False),
        # Kept for backwards-compatible clients; the directory is loaded on demand
        # so first paint never blocks on a full exchange-list refresh.
        "universe": [],
    }

@app.get("/api/health")
def health():
    return {"ok": True, "market": "ready", "repository": repo.scan(False, record_audit=False)["state"], "catalog": market.catalog_status(False)}

@app.get("/api/stocks/search")
def search(q: str = Query("", max_length=120), limit: int = Query(30, ge=1, le=100)):
    return {"results": market.search(q, limit)}

@app.get("/api/stocks/catalog")
def catalog(refresh: bool = False, full: bool = False, limit: int = Query(5000, ge=1, le=10000)):
    if full:
        rows = market.catalog.all(force=refresh)
        return {"results": rows[:limit], "count": len(rows)}
    return market.catalog_status(refresh)

@app.get("/api/analyze")
async def analyze(symbol: str = Query(..., min_length=1, max_length=120), interval: str = Query(settings.default_interval), retrain: bool = False, refresh_data: bool = False):
    try:
        return await run_in_threadpool(engine.analyze, symbol, interval, retrain, refresh_data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except YahooDataError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(503, f"Analysis unavailable: {e}")

@app.get("/api/full-analysis")
async def full_analysis(symbol: str, interval: str = settings.default_interval):
    try:
        return await run_in_threadpool(engine.full_analysis, symbol, interval)
    except Exception as e:
        raise HTTPException(503, f"Full analysis unavailable: {e}")

@app.get("/api/backtest")
async def backtest(symbol: str, interval: str = settings.default_interval):
    try:
        return await run_in_threadpool(engine.backtest_only, symbol, interval)
    except Exception as e:
        raise HTTPException(503, f"Backtest unavailable: {e}")

@app.get("/api/pulse")
async def pulse(symbols: str | None = None, limit: int = Query(12, ge=1, le=24)):
    if symbols:
        selected = [x.strip() for x in symbols.split(",") if x.strip()][:24]
    else:
        selected = [s for s, _ in COMMON_INDIAN_STOCKS[:limit]]
    return {"results": await run_in_threadpool(market.pulse, selected)}

@app.get("/api/journal")
def journal(limit: int = Query(25, ge=1, le=100)):
    return {"results": recent("signal_journal", limit)}

@app.get("/api/audit")
def audit_events(limit: int = Query(30, ge=1, le=100)):
    return {"results": recent("audit_events", limit)}

@app.post("/api/repository/check")
async def repo_check():
    result = await run_in_threadpool(repo.scan, False)
    engine.invalidate_repository_cache()
    return result

@app.post("/api/repository/accept")
async def repo_accept():
    result = await run_in_threadpool(repo.scan, True)
    engine.invalidate_repository_cache()
    return result

@app.post("/api/repository/reset")
async def repo_reset():
    result = await run_in_threadpool(repo.reset)
    engine.invalidate_repository_cache()
    return result

@app.post("/api/repository/simulate")
async def repo_simulate():
    result = await run_in_threadpool(repo.simulate_overnight)
    engine.invalidate_repository_cache()
    return result

@app.post("/api/repository/source/local")
async def repo_source_local(path: str):
    try:
        result = await run_in_threadpool(repo.set_path, path)
        engine.invalidate_repository_cache()
        return result
    except Exception as e:
        raise HTTPException(422, str(e))

@app.post("/api/repository/source/github")
async def repo_source_github(url: str):
    try:
        result = await run_in_threadpool(repo.clone_public_github, url)
        engine.invalidate_repository_cache()
        return result
    except Exception as e:
        raise HTTPException(422, str(e))

@app.post("/api/repository/bind-model")
async def repo_bind_model():
    try:
        result = await run_in_threadpool(repo.bind_to_model)
        engine.invalidate_repository_cache()
        return result
    except Exception as e:
        raise HTTPException(422, str(e))

@app.post("/api/repository/source/github/refresh")
async def repo_source_github_refresh():
    try:
        result = await run_in_threadpool(repo.refresh_public_github)
        engine.invalidate_repository_cache()
        return result
    except Exception as e:
        raise HTTPException(422, str(e))

@app.post("/api/webhook/github")
async def github_webhook(request: Request):
    body = await request.body()
    if GITHUB_WEBHOOK_SECRET:
        signature = request.headers.get("X-Hub-Signature-256", "")
        digest = "sha256=" + hmac.new(GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, digest):
            raise HTTPException(401, "Invalid webhook signature.")
    try:
        payload = json.loads(body.decode() or "{}")
    except Exception:
        payload = {}
    event = request.headers.get("X-GitHub-Event", "ping")
    result = await run_in_threadpool(repo.scan, False)
    return {"ok": True, "event": event, "repository_state": result["state"], "impact": result["impact"],
            "repository": payload.get("repository", {}).get("full_name")}

@app.get("/api/trust")
async def trust(symbol: str = "TCS", interval: str = settings.default_interval):
    data = await run_in_threadpool(engine.analyze, symbol, interval, False, False)
    return data["prediction"]["trust"]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
