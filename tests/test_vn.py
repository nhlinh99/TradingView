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


def test_sync_daily_and_vn_daily_bars(data_root, monkeypatch):
    from server import bars_api
    monkeypatch.setattr(vn, "refresh_daily", lambda s: False)   # không gọi mạng thật
    t = [int(datetime(2026, 11, d, tzinfo=timezone.utc).timestamp()) for d in (2, 3, 4)]   # Thứ Hai, Ba, Tư
    payload = {"s": "ok", "t": t, "o": [10, 11, 12], "h": [11, 13, 14], "l": [9, 10, 11], "c": [11, 12, 13], "v": [100, 200, 300]}
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=payload)

    with client_for(handler) as c:
        assert vn.sync_daily(c, "FPT") == {"bars": 3, "new": 3}
        assert vn.sync_daily(c, "FPT") == {"bars": 3, "new": 0}   # gộp theo ts, không nhân đôi
    assert seen[0]["resolution"] == "1D"
    cfg = store.symbol_config("FPT")
    d = bars_api.vn_daily_bars("FPT", "1d", 86_400_000, cfg, None, None, 100)
    assert [b[4] for b in d["bars"]] == [11, 12, 13]
    w = bars_api.vn_daily_bars("FPT", "1w", 7 * 86_400_000, cfg, None, None, 100)["bars"]
    assert len(w) == 1 and w[0][1:] == [10, 14, 9, 13, 600, 0.0, 0.0]
    m = bars_api.vn_daily_bars("FPT", "1M", 30 * 86_400_000, cfg, None, None, 100)["bars"]
    assert len(m) == 1 and m[0][2] == 14


def test_sync_hourly_and_vn_hourly_bars(data_root, monkeypatch):
    from server import bars_api
    monkeypatch.setattr(vn, "refresh_hourly", lambda s: False)   # không gọi mạng thật
    # một phiên: 9h, 10h, 11h sáng và 13h, 14h chiều giờ VN = 02, 03, 04, 06, 07 giờ UTC
    t = [int(datetime(2026, 3, 2, hh, tzinfo=timezone.utc).timestamp()) for hh in (2, 3, 4, 6, 7)]
    payload = {"t": t, "o": [10, 11, 12, 13, 14], "h": [11, 12, 13, 14, 15], "l": [9, 10, 11, 12, 13],
               "c": [11, 12, 13, 14, 15], "v": [100, 200, 300, 400, 500], "nextTime": 0}
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=payload)

    now = int(datetime(2026, 3, 3, tzinfo=timezone.utc).timestamp() * 1000)
    with client_for(handler) as c:
        assert vn.sync_hourly(c, "FPT", now_ms=now) == {"bars": 5, "new": 5}
        assert vn.sync_hourly(c, "FPT", now_ms=now) == {"bars": 5, "new": 0}   # gộp theo ts, không nhân đôi
    assert seen[0]["resolution"] == "1H" and seen[0]["symbol"] == "FPT"
    assert now // 1000 - int(seen[0]["from"]) > 365 * 86_400      # lần đầu lấy toàn bộ lịch sử
    assert now // 1000 - int(seen[1]["from"]) == 10 * 86_400       # lần sau chỉ lấy đuôi
    cfg = store.symbol_config("FPT")
    h = bars_api.vn_hourly_bars("FPT", "1h", 3_600_000, cfg, None, None, 100)["bars"]
    assert [b[0] // 1000 for b in h] == t and [b[4] for b in h] == [11, 12, 13, 14, 15]
    f = bars_api.vn_hourly_bars("FPT", "4h", 4 * 3_600_000, cfg, None, None, 100)["bars"]
    # 4h chia theo UTC như khi ghép từ nến 1 phút: (02, 03) -> 00h, (04, 06, 07) -> 04h
    assert [b[1:6] for b in f] == [[10, 12, 9, 12, 300], [12, 15, 11, 15, 1200]]
    # API đi qua nhánh nến giờ, kể cả khi có `from`/`to`
    from fastapi.testclient import TestClient
    from server.main import app
    j = TestClient(app).get("/api/bars", params={"symbol": "FPT", "tf": "1h", "from": t[0] * 1000, "to": t[3] * 1000}).json()
    assert [b[0] // 1000 for b in j["bars"]] == t[:3]


def test_vn_hourly_falls_back_to_minutes_without_file(data_root, monkeypatch):
    from fastapi.testclient import TestClient
    from server.main import app
    monkeypatch.setattr(vn, "refresh_hourly", lambda s: False)
    t0 = int(datetime(2026, 11, 13, 2, 15, tzinfo=timezone.utc).timestamp() * 1000)
    store.write_partition("bars", "VNM", date(2026, 11, 13), [(t0, 54155, 54300, 54100, 54200, 1000.0, 0.0, 0.0)])
    j = TestClient(app).get("/api/bars", params={"symbol": "VNM", "tf": "1h"}).json()
    assert j["bars"] == [[t0 // 3_600_000 * 3_600_000, 54.155, 54.3, 54.1, 54.2, 1000.0, 0.0, 0.0]]


def test_indices_are_configured_and_use_dnse_index_endpoint(data_root):
    assert store.symbol_config("VNINDEX")["tick"] == 0.01 and store.symbol_config("VN30")["market"] == "vn"
    assert store.vn_symbols()[:2] == ["VNINDEX", "VN30"]
    urls = []

    def handler(req):
        urls.append(req.url.path)
        return httpx.Response(200, json={"t": [1_794_880_800], "o": [1.0], "h": [1.0], "l": [1.0], "c": [1.0], "v": [1]})

    vn.sync_hourly(client_for(handler), "VN30", full=True, now_ms=1_794_900_000_000)
    assert urls == ["/chart-api/v2/ohlcs/index"]
