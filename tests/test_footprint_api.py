import random
from datetime import date

import pytest
from fastapi.testclient import TestClient

from common import store
from server import bars_api
from server.main import app
from tests.test_bars_api import DAY, MIN, T0, data_root, no_network_rest  # noqa: F401 (fixtures)

client = TestClient(app)


def make_ticks(n=600, seed=1):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        ts = T0 + i * 7_000 + rnd.randint(0, 6_000)
        out.append((ts, 1000 + i, 670000 + rnd.randint(-30, 30), rnd.choice([0.5, 1.0, 2.0, 0.25]), rnd.random() < 0.5))
    return out


def put(ticks):
    store.write_partition("ticks", "BTCUSDT", DAY, ticks, part="t")


def fp(**kw):
    p = {"symbol": "BTCUSDT", "from": T0, "to": T0 + 60 * MIN, **kw}
    r = client.get("/api/footprint", params=p)
    assert r.status_code == 200, r.text
    return r.json()


def test_delta_matches_bars_for_every_candle(data_root):
    put(make_ticks())
    for tf in ("1m", "5m", "15m"):
        f = fp(tf=tf)
        per_bar: dict[int, list[float]] = {}
        for bar, _p, buy, sell in f["rows"]:
            d = per_bar.setdefault(bar, [0.0, 0.0])
            d[0] += buy
            d[1] += sell
        b = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": tf, "from": T0, "to": T0 + 60 * MIN}).json()
        assert b["bars"], tf
        for row in b["bars"]:
            buy, sell = per_bar[row[0]]
            assert buy == pytest.approx(row[6], abs=1e-4)
            assert sell == pytest.approx(row[7], abs=1e-4)
            assert buy - sell == pytest.approx(row[6] - row[7], abs=1e-4)


def test_price_levels_use_bucket(data_root):
    put(make_ticks())
    f = fp()
    assert f["bucket"] == 1.0
    assert all(abs(r[1] - round(r[1])) < 1e-9 for r in f["rows"])  # tick 0.1, bucket 1.0
    coarse = fp(mult=10)
    assert coarse["bucket"] == 10.0
    assert sum(r[2] + r[3] for r in coarse["rows"]) == pytest.approx(sum(r[2] + r[3] for r in f["rows"]), abs=1e-3)
    assert len(coarse["rows"]) < len(f["rows"])


def test_compacted_day_matches_tick_day(data_root):
    ticks = make_ticks()
    put(ticks)
    before = fp(tf="5m")["rows"]
    from collector import compact
    sql = compact._footprint_select("BTCUSDT", DAY)
    import duckdb
    rows = duckdb.sql(sql).fetchall()
    # đổi sang trạng thái sau nén: có footprint_1m, không còn tick
    for p in store.day_files("ticks", "BTCUSDT", DAY):
        p.unlink()
    store.write_partition("footprint_1m", "BTCUSDT", DAY, rows)
    after = fp(tf="5m")["rows"]
    assert len(after) == len(before)
    for a, b in zip(after, before):
        assert a[:2] == b[:2]
        assert a[2] == pytest.approx(b[2], rel=1e-5)
        assert a[3] == pytest.approx(b[3], rel=1e-5)


def test_empty_and_bad_requests(data_root):
    assert fp()["rows"] == []
    for params in ({"tf": "30s"}, {"tf": "bogus"}, {"to": T0}):
        r = client.get("/api/footprint", params={"symbol": "BTCUSDT", "from": T0, "to": T0 + 60 * MIN, **params})
        assert r.status_code == 400
    assert client.get("/api/footprint", params={"symbol": "NOPE"}).status_code == 400
