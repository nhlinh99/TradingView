import json
from datetime import date, datetime, timezone

import httpx
import pytest

from collector import vn
from common import store

DAY_MS = 86_400_000


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))
    f = tmp_path / "vn100.json"
    f.write_text(json.dumps({"symbols": ["VNM", "FPT"]}), encoding="utf-8")
    monkeypatch.setattr(store, "VN100_FILE", f)
    monkeypatch.setattr(store, "_symbols_cache", None)
    return tmp_path


def group_payload(n=100, exchange="hose"):
    return {"code": "SUCCESS", "data": [{"stockSymbol": f"S{i:03d}", "exchange": exchange, "stockType": "s"} for i in range(n)]}


def client_for(handler):
    return vn.make_client(httpx.MockTransport(handler))


def test_vn_symbols_have_default_config(data_root):
    cfg = store.symbol_config("VNM")
    assert cfg["tick"] == 0.001 and cfg["market"] == "vn"
    assert store.to_int_price("VNM", 54.155) == 54155
    assert store.from_int_price("VNM", 54155) == 54.155
    with pytest.raises(KeyError):
        store.symbol_config("ZZZ")


def test_refresh_requires_exactly_100_on_hose(data_root, tmp_path):
    out = tmp_path / "out.json"
    syms = vn.refresh_vn100(client_for(lambda r: httpx.Response(200, json=group_payload())), path=out)
    assert len(syms) == 100 and json.loads(out.read_text())["symbols"] == syms
    for bad in (group_payload(99), group_payload(100, exchange="hnx")):
        out2 = tmp_path / "bad.json"
        with pytest.raises(RuntimeError):
            vn.refresh_vn100(client_for(lambda r, b=bad: httpx.Response(200, json=b)), path=out2)
        assert not out2.exists()


def test_history_to_bars_and_sync_writes_days(data_root, monkeypatch):
    monkeypatch.setattr(vn.time, "sleep", lambda s: None)
    t0 = int(datetime(2026, 11, 12, 2, 15, tzinfo=timezone.utc).timestamp())
    t1 = int(datetime(2026, 11, 13, 2, 15, tzinfo=timezone.utc).timestamp())
    calls = []

    def handler(req):
        calls.append(dict(req.url.params))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"s": "ok", "t": [t0, t0 + 60, t1], "o": [54.155, 54.2, 55.0], "h": [54.3, 54.3, 55.1],
                                         "l": [54.1, 54.2, 54.9], "c": [54.2, 54.25, 55.05], "v": [1000, 500, 300]})

    now = int(datetime(2026, 11, 14, 5, tzinfo=timezone.utc).timestamp() * 1000)
    r = vn.sync_bars(client_for(handler), "VNM", days=5, now_ms=now)
    assert r == {"bars": 3, "days": 2} and len(calls) == 2
    assert calls[1]["resolution"] == "1"
    rows = store.read("bars", "VNM")
    assert [x[5] for x in rows] == [1000.0, 500.0, 300.0]
    assert rows[0][1] == 54155 and rows[0][0] == t0 * 1000
    assert store.list_days("bars", "VNM") == [date(2026, 11, 12), date(2026, 11, 13)]
    # lần sau chỉ tải từ đầu ngày của nến cuối cùng
    calls.clear()
    vn.sync_bars(client_for(lambda req: (calls.append(dict(req.url.params)), httpx.Response(200, json={"s": "no_data"}))[1]),
                 "VNM", now_ms=now)
    assert int(calls[0]["from"]) == t1 // 86400 * 86400


def test_bars_api_for_vn_symbol(data_root, monkeypatch):
    from fastapi.testclient import TestClient
    from server import bars_api
    from server.main import app

    def boom(*a, **k):
        raise AssertionError("cổ phiếu VN không được gọi REST của Binance")
    monkeypatch.setattr(bars_api, "rest_client_factory", boom)
    t0 = int(datetime(2026, 11, 13, 2, 15, tzinfo=timezone.utc).timestamp() * 1000)
    store.write_partition("bars", "VNM", date(2026, 11, 13),
                          [(t0, 54155, 54300, 54100, 54200, 1000.0, 0.0, 0.0), (t0 + 60000, 54200, 54250, 54150, 54250, 500.0, 0.0, 0.0)])
    c = TestClient(app)
    j = c.get("/api/bars", params={"symbol": "VNM", "tf": "5m"}).json()
    assert j["tick"] == 0.001 and j["last_trade_id"] is None
    assert j["bars"] == [[t0 // 300000 * 300000, 54.155, 54.3, 54.1, 54.25, 1500.0, 0.0, 0.0]]
    assert c.get("/api/bars", params={"symbol": "VNM", "tf": "1s"}).status_code == 422
    syms = {s["symbol"] for s in c.get("/api/symbols").json()}
    assert {"VNM", "FPT", "BTCUSDT"} <= syms
