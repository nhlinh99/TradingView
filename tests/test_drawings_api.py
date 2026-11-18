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


def test_extended_line_needs_two_points(data_root):
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "xline", "payload": pts((1, 10), (2, 20))}).status_code == 200
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "xline", "payload": pts((1, 10))}).status_code == 422


def test_new_line_tools_point_counts(data_root):
    need = {"ray": 2, "hray": 1, "vline": 1, "cross": 1, "info": 2, "angle": 2, "arrow": 2, "channel": 3, "regression": 2,
            "daterange": 2, "pricerange": 2}
    for kind, n in need.items():
        good = pts(*[(i + 1, 10 + i) for i in range(n)])
        bad = pts(*[(i + 1, 10 + i) for i in range(n + 1)])
        assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": kind, "payload": good}).status_code == 200, kind
        assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": kind, "payload": bad}).status_code == 422, kind


def test_brush_accepts_many_points_but_not_too_many(data_root):
    many = pts(*[(i, 100 + i) for i in range(300)])
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "brush", "payload": many}).status_code == 200
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "brush", "payload": pts((1, 1))}).status_code == 422
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "brush", "payload": pts(*[(i, 1) for i in range(401)])}).status_code == 422


def test_recreate_with_same_id_for_undo(data_root):
    a = client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "hline", "payload": pts((1, 5))}).json()
    assert client.delete(f"/api/drawings/{a['id']}").status_code == 200
    back = client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "hline", "payload": pts((1, 5)), "id": a["id"]})
    assert back.status_code == 200 and back.json()["id"] == a["id"]
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "hline", "payload": pts((1, 5)), "id": a["id"]}).status_code == 409


def test_phase2_tools_point_counts(data_root):
    need = {"long": 3, "short": 3, "circle": 2, "ellipse": 2, "triangle": 3, "note": 1, "callout": 2, "pricelabel": 1, "flag": 1}
    for kind, n in need.items():
        good = pts(*[(i + 1, 10 + i) for i in range(n)])
        bad = pts(*[(i + 1, 10 + i) for i in range(n + 1)])
        assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": kind, "payload": good}).status_code == 200, kind
        assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": kind, "payload": bad}).status_code == 422, kind


def test_polyline_range(data_root):
    ok = pts(*[(i, 10 + i) for i in range(50)])
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "polyline", "payload": ok}).status_code == 200
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "polyline", "payload": pts((1, 1))}).status_code == 422
    assert client.post("/api/drawings", json={"symbol": "BTCUSDT", "kind": "polyline", "payload": pts(*[(i, 1) for i in range(51)])}).status_code == 422


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
