import pytest
from fastapi.testclient import TestClient

from common import store
from server.main import app
from tests.test_bars_api import DAY, T0, data_root, no_network_rest  # noqa: F401

client = TestClient(app)


def put_book(rows, kind="book"):
    store.write_partition(kind, "BTCUSDT", DAY, rows, part="t" if kind == "book" else None)


def hm(**kw):
    p = {"symbol": "BTCUSDT", "from": T0, "to": T0 + 600_000, "tbucket": 5000, **kw}
    r = client.get("/api/heatmap", params=p)
    assert r.status_code == 200, r.text
    return r.json()


def test_cells_and_max_aggregation(data_root):
    # 3 snapshot cách 5 giây; bucket giá 1.0 = 10 tick. Hai bucket cơ sở 670000 và 670010.
    put_book([
        (T0, 670000, 5.0, 0.0), (T0, 670010, 0.0, 2.0),
        (T0 + 5000, 670000, 1.0, 0.0),
        (T0 + 10000, 670000, 9.0, 0.0),
    ])
    j = hm()
    assert j["bucket"] == 1.0 and j["tbucket"] == 5000
    assert [T0, 67000.0, 5.0, 0.0] in j["rows"]
    # gộp thời gian 15 giây, giá x2: lấy max
    j = hm(tbucket=15000, mult=2)
    cell = [r for r in j["rows"] if r[1] == 67000.0]
    assert len(cell) == 1 and cell[0][2] == 9.0 and cell[0][3] == 2.0
    assert j["bucket"] == 2.0


def test_scale_is_p99_and_empty(data_root):
    assert hm()["rows"] == [] and hm()["scale"] == 0
    put_book([(T0 + i * 5000, 670000, float(i + 1), 0.0) for i in range(100)])
    j = hm(tbucket=5000)
    assert 95 <= j["scale"] <= 100


def test_compacted_day_uses_book_1m(data_root):
    put_book([(T0, 670000, 4.0, 1.0)], kind="book_1m")
    j = hm(tbucket=60000)
    assert j["rows"] == [[T0, 67000.0, 4.0, 1.0]]
    # ngày có cả hai nguồn: chỉ dùng book, không đếm trùng
    put_book([(T0 + 5000, 670000, 7.0, 0.0)])
    j = hm(tbucket=60000)
    assert j["rows"] == [[T0, 67000.0, 7.0, 0.0]]


def test_bad_requests(data_root):
    assert client.get("/api/heatmap", params={"symbol": "BTCUSDT", "from": T0, "to": T0}).status_code == 400
    assert client.get("/api/heatmap", params={"symbol": "NOPE", "from": T0, "to": T0 + 1}).status_code == 400


def test_bubbles_top_clusters(data_root):
    # id, ts, p, q, m: cụm mua lớn 5 BTC ở 67000.0, cụm bán 3 BTC ở 67001.0, vài lệnh nhỏ
    ticks = [
        (T0 + 1000, 1, 670000, 2.0, False), (T0 + 2000, 2, 670003, 3.0, False),
        (T0 + 3000, 3, 670010, 3.0, True), (T0 + 25_000, 4, 670000, 0.1, True),
    ]
    store.write_partition("ticks", "BTCUSDT", DAY, ticks, part="t")
    r = client.get("/api/bubbles", params={"symbol": "BTCUSDT", "from": T0, "to": T0 + 60_000, "tbucket": 10_000, "top": 2})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows == [[T0, 67000.0, 5.0, "buy"], [T0, 67001.0, 3.0, "sell"]]
    assert client.get("/api/bubbles", params={"symbol": "BTCUSDT", "from": T0, "to": T0}).status_code == 400
