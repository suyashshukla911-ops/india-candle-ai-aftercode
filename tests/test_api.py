
from fastapi.testclient import TestClient
from app.main import app

def test_bootstrap():
    c=TestClient(app)
    r=c.get("/api/bootstrap")
    assert r.status_code==200
    j=r.json()
    assert "repository" in j
    assert j["gate"]==0.90


def test_catalog_directory_and_search():
    c=TestClient(app)
    r=c.get("/api/stocks/search?q=TCS&limit=10")
    assert r.status_code==200
    assert any(x["symbol"]=="TCS" for x in r.json()["results"])
    r2=c.get("/api/stocks/catalog?full=true&limit=5000")
    assert r2.status_code==200
    assert r2.json()["count"] >= 1


def test_trustgraph_bootstrap_uses_dynamic_universe():
    c=TestClient(app)
    j=c.get("/api/bootstrap").json()
    assert "catalog" in j and "universe" in j
    assert isinstance(j["universe"], list)



def test_bootstrap_keeps_universe_lazy():
    c=TestClient(app)
    j=c.get("/api/bootstrap").json()
    assert isinstance(j["universe"], list)
    assert j["universe"] == []
