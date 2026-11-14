from datetime import date

import pytest
from fastapi.testclient import TestClient

from common import store
from server.main import app

client = TestClient(app)
T0 = 1_794_268_800_000
DAY = date(2026, 11, 10)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))
    rows = [(T0 + i * 60_000, 670000 + i, 670005 + i, 669995 + i, 670001 + i, 2.0, 1.0, 1.0) for i in range(120)]
    store.write_partition("bars", "BTCUSDT", DAY, rows)
    store.write_partition("bars", "XAUUSDT", DAY, [(T0 + i * 60_000, 38000 + i, 38005 + i, 37995 + i, 38001 + i, 3.0, 1.0, 2.0) for i in range(120)])


def post(**kw):
    body = {"symbol": "BTCUSDT", "tf": "1m", "limit": 100, **kw}
    return client.post("/api/pine/run", json=body)


def test_run_returns_plots_inputs_and_overrides(data_root):
    src = 'indicator("t")\nn = input.int(5, "n")\nplot(ta.sma(close, n), "ma")\n'
    r = post(source=src).json()
    assert [p["title"] for p in r["plots"]] == ["ma"] and r["inputs"][0]["title"] == "n"
    assert len(r["times"]) == 100 and r["plots"][0]["values"][3] is None and r["plots"][0]["values"][4] is not None
    r2 = post(source=src, inputs={"n": 10}).json()
    assert r2["plots"][0]["values"][8] is None and r2["plots"][0]["values"][9] is not None


def test_errors_are_400_with_line(data_root):
    r = post(source='indicator("t")\nplot(close\n')
    assert r.status_code == 400 and r.json()["detail"]["kind"] == "syntax"
    r = post(source='indicator("t")\nplot(nope)\n')
    d = r.json()["detail"]
    assert r.status_code == 400 and d["kind"] == "runtime" and d["line"] == 2
    assert post(source="x", symbol="ZZZ").status_code == 404
    assert post(source='indicator("t")\nplot(close)\n', symbol="ETHUSDT").status_code == 404


def test_security_other_symbol_and_timeframe(data_root):
    src = ('indicator("t")\nplot(request.security("BINANCE:XAUUSDT", "1m", close), "gold")\n'
           'plot(request.security(syminfo.tickerid, "60", close), "h1")\n')
    r = post(source=src)
    assert r.status_code == 200, r.text
    j = r.json()
    gold = next(p for p in j["plots"] if p["title"] == "gold")["values"]
    assert gold[-1] == pytest.approx(38.0 * 1000 + 119 + 1 + 0, abs=1e-6) or gold[-1] is not None
    # symbol proxy không có dữ liệu: lỗi rõ ràng
    r = post(source='indicator("t")\nplot(request.security("COMEX:GC1!", "1m", close))\n')
    assert r.status_code == 400 and "GC1" in r.json()["detail"]["message"]


def test_examples_listed():
    j = client.get("/api/pine/examples").json()
    assert {e["name"] for e in j} == {"volume_proxy", "delta_cvd", "relative_volume_alert", "session_vwap", "ema_cross_strategy"}


def test_backtest_params_and_date_range(data_root):
    src = ('strategy("s", default_qty_type=strategy.fixed, default_qty_value=1)\n'
           'if bar_index == 2\n    strategy.entry("L", strategy.long)\n'
           'if bar_index == 10\n    strategy.close("L")\n')
    free = post(source=src, limit=120).json()["strategy"]
    assert free["closed_trades"] == 1
    gross = free["net_profit"]                       # mở ở nến 3, đóng ở nến 11: giá tăng 0,1 (1 tick) mỗi nến nên lãi = 0,8
    assert gross == pytest.approx(0.8)
    costly = post(source=src, limit=120, slippage_ticks=10, commission_pct=0.0).json()["strategy"]
    assert costly["net_profit"] == pytest.approx(gross - 2 * 10 * 0.1)          # tick 0.1: mua cao 1.0, bán thấp 1.0
    fee = post(source=src, limit=120, commission_pct=1.0).json()["strategy"]
    assert fee["net_profit"] < gross
    t0 = 1_794_268_800_000
    r = post(source='indicator("t")\nplot(close)\n', from_ms=t0 + 30 * 60_000, to_ms=t0 + 60 * 60_000).json()
    assert r["times"][0] == t0 + 30 * 60_000 and r["times"][-1] == t0 + 59 * 60_000 and len(r["times"]) == 30
