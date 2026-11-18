import pytest
from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))


def pts(*xs):
    return {"points": [{"time": t, "price": p} for t, p in xs], "color": "#f0b90b"}


def test_crud_per_symbol(data_root):
    a = client.post("/api/drawings", json={"symbol": "btcusdt", "kind": "trend", "payload": pts((1000, 60000.5), (2000, 61000))}).json()
    b = client.post("/api/drawings", json={"symbol": "XAUUSDT", "kind": "hline", "payload": pts((1000, 3900))}).json()
    assert a["symbol"] == "BTCUSDT" and a["id"] != b["id"]
    lst = client.get("/api/drawings", params={"symbol": "BTCUSDT"}).json()
    assert [d["id"] for d in lst] == [a["id"]] and lst[0]["payload"]["points"][0]["price"] == 60000.5
    upd = client.put(f"/api/drawings/{a['id']}", json={"symbol": "BTCUSDT", "kind": "trend", "payload": pts((1500, 1), (2500, 2))})
    assert upd.status_code == 200
    assert client.get("/api/drawings", params={"symbol": "BTCUSDT"}).json()[0]["payload"]["points"][0]["time"] == 1500
    assert client.delete(f"/api/drawings/{a['id']}").json() == {"deleted": a["id"]}
    assert client.get("/api/drawings", params={"symbol": "BTCUSDT"}).json() == []
    assert len(client.get("/api/drawings", params={"symbol": "XAUUSDT"}).json()) == 1
    assert client.delete("/api/drawings", params={"symbol": "XAUUSDT"}).json() == {"deleted": 1}
    assert client.delete(f"/api/drawings/{a['id']}").status_code == 404


def test_fib_extension_needs_three_points(data_root):
    ok = client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "fibx", "payload": pts((1, 10), (2, 20), (3, 15))})
    assert ok.status_code == 200 and ok.json()["kind"] == "fibx"
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "fibx", "payload": pts((1, 10), (2, 20))}).status_code == 422


def test_ruler_needs_two_points(data_root):
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "ruler", "payload": pts((1, 10), (2, 20))}).status_code == 200
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "ruler", "payload": pts((1, 10))}).status_code == 422


def test_validation(data_root):
    bad = [
        {"symbol": "BTCUSDT", "kind": "star", "payload": pts((1, 1))},
        {"symbol": "BTCUSDT", "kind": "trend", "payload": pts((1, 1))},                 # thiếu điểm
        {"symbol": "BTCUSDT", "kind": "hline", "payload": {"points": [{"time": 1, "price": "x"}]}},
        {"symbol": "BTCUSDT", "kind": "hline", "payload": {"points": [{"time": 1, "price": float("inf")}]}} if False else
        {"symbol": "BTCUSDT", "kind": "hline", "payload": {"points": [{"time": 1}]}},
    ]
    for b in bad:
        assert client.post("/api/drawings", json=b).status_code == 422, b
    assert client.post("/api/drawings", json={"symbol": "NOPE", "kind": "hline", "payload": pts((1, 1))}).status_code == 404
    assert client.get("/api/drawings", params={"symbol": "NOPE"}).status_code == 404
