import httpx
import pytest
from fastapi.testclient import TestClient

from collector import deribit
from common import gex, store
from server.main import app

client = TestClient(app)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))


def summary(now_ms, oi_scale=1.0):
    exp_name = "BTC-29JAN27-{k}-{cp}"
    rows = []
    for k, cp, oi in ((60000, "P", 50.0), (66000, "C", 10.0), (70000, "C", 30.0)):
        rows.append({"instrument_name": exp_name.format(k=k, cp=cp), "open_interest": oi * oi_scale, "mark_iv": 45.0,
                     "underlying_price": 66500.0, "estimated_delivery_price": 66000.0})
    rows.append({"instrument_name": "BTC-PERPETUAL", "open_interest": 1})
    return rows


def test_deribit_fetch_retries_then_stores_snapshot(data_root, monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"result": summary(0)})

    import collector.deribit as d
    monkeypatch.setattr(d.time, "sleep", lambda s: None)  # không chờ thật
    client_ = httpx.Client(transport=httpx.MockTransport(handler))
    n = d.snapshot_to_store(d.fetch_summary(client_), 1_794_664_800_000)
    assert len(calls) == 2 and n == 3


def test_gex_endpoint_uses_latest_snapshot(data_root, monkeypatch):
    now = 1_794_664_800_000
    deribit.snapshot_to_store(summary(now), now - 900_000)
    deribit.snapshot_to_store(summary(now, oi_scale=2.0), now)
    import time as _t
    monkeypatch.setattr(_t, "time", lambda: now / 1000 + 60)
    j = client.get("/api/gex").json()
    assert j["ts"] == now and j["spot"] == 66000.0
    assert {r["strike"] for r in j["by_strike"]} == {60000, 66000, 70000}
    assert j["put_wall"] == 60000 and j["call_wall"] in (66000, 70000)
    # tổng khớp công thức trực tiếp trên cùng dữ liệu
    rows, spot = gex.option_rows(summary(now, oi_scale=2.0))
    assert j["total"] == pytest.approx(gex.total_gex(rows_to_options(rows), now, spot), abs=0.01)
    # hỏi snapshot cũ hơn: lấy bản trước
    old = client.get("/api/gex", params={"ts": now - 1}).json()
    assert old["ts"] == now - 900_000
    assert abs(old["total"]) < abs(j["total"])  # OI gấp đôi thì GEX tổng gấp đôi


def rows_to_options(rows):
    return [(e, k, cp, oi, iv, fwd) for e, k, cp, oi, iv, fwd in rows]


def test_gex_404_when_empty(data_root):
    assert client.get("/api/gex").status_code == 404
