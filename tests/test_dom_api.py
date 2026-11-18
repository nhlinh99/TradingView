import httpx
import pytest
from fastapi.testclient import TestClient

from common import store
from server import dom_api
from server.main import app
from tests.test_bars_api import DAY, T0, data_root  # noqa: F401

client = TestClient(app)

DEPTH = {
    "lastUpdateId": 1, "E": T0 + 1000, "T": T0 + 900,
    "bids": [["67000.0", "1.5"], ["66999.5", "2.0"], ["66998.0", "3.0"], ["66990.0", "0"]],
    "asks": [["67000.5", "1.0"], ["67001.0", "2.5"], ["67003.2", "4.0"]],
}


@pytest.fixture(autouse=True)
def fake_rest(monkeypatch):
    dom_api._cache.clear()
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, json=DEPTH)

    monkeypatch.setattr(dom_api, "rest_client_factory", lambda: httpx.Client(base_url="https://x.test", transport=httpx.MockTransport(handler)))
    dom_api.calls = calls
    yield
    dom_api._cache.clear()


def test_dom_live_buckets_and_best_prices():
    r = client.get("/api/dom", params={"symbol": "BTCUSDT", "mult": 1})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["source"] == "live" and j["bucket"] == 1.0
    assert j["best_bid"] == 67000.0 and j["best_ask"] == 67000.5
    # bucket 1.0: 67000.0 (bid 1.5), 66999.5 -> 66999.0 (2.0), 66998.0 (3.0); mức khối lượng 0 bị bỏ
    assert j["bids"] == [[67000.0, 1.5], [66999.0, 2.0], [66998.0, 3.0]]
    assert j["asks"] == [[67000.0, 1.0], [67001.0, 2.5], [67003.0, 4.0]]
    assert j["age_ms"] >= 0


def test_dom_bucket_multiplier_merges_levels():
    j = client.get("/api/dom", params={"symbol": "BTCUSDT", "mult": 5}).json()
    assert j["bucket"] == 5.0
    assert j["bids"] == [[67000.0, 1.5], [66995.0, 5.0]]
    assert sum(q for _, q in j["bids"]) == 6.5 and sum(q for _, q in j["asks"]) == 7.5


def test_dom_shares_one_request_between_callers():
    for _ in range(3):
        assert client.get("/api/dom", params={"symbol": "BTCUSDT"}).status_code == 200
    assert len(dom_api.calls) == 1


def test_dom_falls_back_to_stored_book_when_rest_fails(data_root, monkeypatch):
    def boom():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(dom_api, "rest_client_factory", boom)
    store.write_partition("book", "BTCUSDT", DAY, [(T0, 670000, 9.0, 0.0), (T0 + 5000, 670000, 2.0, 0.0), (T0 + 5000, 670010, 0.0, 3.0)], part="t")
    j = dom_api.get_dom("BTCUSDT", 1, now_ms=T0 + 20_000)
    assert j["source"] == "book" and j["ts"] == T0 + 5000 and j["age_ms"] == 15_000
    assert j["bids"] == [[67000.0, 2.0]] and j["asks"] == [[67001.0, 3.0]]
    with pytest.raises(Exception):
        dom_api.get_dom("BTCUSDT", 1, now_ms=T0 + 3_600_000)   # mẫu quá cũ (hơn 10 phút): không dùng


def test_dom_rejects_symbols_without_book(data_root):
    assert client.get("/api/dom", params={"symbol": "NOPE"}).status_code == 400
    assert client.get("/api/dom", params={"symbol": "XAUUSD"}).status_code == 400
