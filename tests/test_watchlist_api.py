import pytest
from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def test_symbols_lists_configured_with_tick(data_root):
    j = client.get("/api/symbols").json()
    by = {s["symbol"]: s for s in j}
    assert by["BTCUSDT"]["tick"] == 0.1 and by["XAUUSDT"]["tick"] == 0.01


def test_first_read_seeds_with_all_configured_symbols(data_root):
    assert client.get("/api/watchlist").json() == {"symbols": ["BTCUSDT", "XAUUSDT", "XAUUSD"]}
    assert client.get("/api/watchlist").json() == {"symbols": ["BTCUSDT", "XAUUSDT", "XAUUSD"]}   # đọc lại không nhân đôi


def test_put_replaces_and_keeps_order(data_root):
    r = client.put("/api/watchlist", json={"symbols": ["xauusdt", "BTCUSDT"]})
    assert r.status_code == 200 and r.json() == {"symbols": ["XAUUSDT", "BTCUSDT"]}
    assert client.get("/api/watchlist").json() == {"symbols": ["XAUUSDT", "BTCUSDT"]}


def test_put_dedupes_and_allows_empty_then_reseeds(data_root):
    assert client.put("/api/watchlist", json={"symbols": ["BTCUSDT", "BTCUSDT"]}).json() == {"symbols": ["BTCUSDT"]}
    assert client.put("/api/watchlist", json={"symbols": []}).json() == {"symbols": []}
    # danh sách rỗng được lưu đúng như người dùng muốn, nhưng lần đọc sau tự khởi tạo lại
    assert client.get("/api/watchlist").json()["symbols"] == ["BTCUSDT", "XAUUSDT", "XAUUSD"]


def test_put_rejects_unknown_symbol_and_keeps_previous(data_root):
    client.put("/api/watchlist", json={"symbols": ["BTCUSDT"]})
    r = client.put("/api/watchlist", json={"symbols": ["BTCUSDT", "DOGEUSDT"]})
    assert r.status_code == 422
    assert client.get("/api/watchlist").json() == {"symbols": ["BTCUSDT"]}


def test_put_validates_body(data_root):
    assert client.put("/api/watchlist", json={"nope": 1}).status_code == 422
    assert client.put("/api/watchlist", json={"symbols": "BTCUSDT"}).status_code == 422
