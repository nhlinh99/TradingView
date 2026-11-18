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
    assert rows == [[T0, 67000.0, 5.0, "buy", 2], [T0, 67001.0, 3.0, "sell", 1]]   # n: số lệnh gộp trong cụm
    assert client.get("/api/bubbles", params={"symbol": "BTCUSDT", "from": T0, "to": T0}).status_code == 400


def test_icebergs_flag_traded_far_above_displayed(data_root):
    # bucket 1.0 = 10 tick. ask hiển thị 2 BTC ở 67000.0 và 5 BTC ở 67001.0; bid hiển thị 3 BTC ở 66999.0
    put_book([(T0, 670000, 0.0, 2.0), (T0, 670010, 0.0, 5.0), (T0, 669990, 3.0, 0.0)])
    ticks = [
        (T0 + 1000, 1, 670000, 7.0, False),    # mua chủ động 7 vào ask 2: 7 > 2*2 -> iceberg mua
        (T0 + 2000, 2, 670010, 6.0, False),    # 6 vs ask 5: chưa vượt 2 lần -> không
        (T0 + 3000, 3, 669990, 9.0, True),     # bán chủ động 9 vào bid 3: 9 > 2*3 -> iceberg bán
        (T0 + 4000, 4, 670020, 50.0, False),   # mức giá không có thanh khoản hiển thị -> không đánh giá
    ]
    store.write_partition("ticks", "BTCUSDT", DAY, ticks, part="t")
    r = client.get("/api/icebergs", params={"symbol": "BTCUSDT", "from": T0, "to": T0 + 60_000, "tbucket": 5000, "factor": 2})
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [[T0, 66999.0, 9.0, 3.0, "sell"], [T0, 67000.0, 7.0, 2.0, "buy"]]
    top1 = client.get("/api/icebergs", params={"symbol": "BTCUSDT", "from": T0, "to": T0 + 60_000, "tbucket": 5000, "factor": 2, "top": 1}).json()
    assert top1["rows"] == [[T0, 66999.0, 9.0, 3.0, "sell"]]            # giữ ô khớp lớn nhất
    strict = client.get("/api/icebergs", params={"symbol": "BTCUSDT", "from": T0, "to": T0 + 60_000, "tbucket": 5000, "factor": 4})
    assert strict.json()["rows"] == []                  # ngưỡng 4 lần: 7 < 8 và 9 < 12
    assert client.get("/api/icebergs", params={"symbol": "BTCUSDT", "from": T0, "to": T0}).status_code == 400


@pytest.fixture(autouse=True)
def _clear_heavy_cache(monkeypatch):
    """Bộ nhớ gộp yêu cầu là toàn cục: các test đổi dữ liệu giữa hai lần gọi cùng tham số nên tắt nhớ kết quả (chỉ còn gộp yêu cầu đang chạy)."""
    from server import limits
    monkeypatch.setattr(limits, "CACHE_TTL", 0.0)
    limits._cache.clear()
    yield
    limits._cache.clear()


def test_coalesce_shares_one_run_between_identical_requests():
    import threading
    import time
    from server import limits
    calls = []
    gate = threading.Event()

    def slow():
        calls.append(1)
        gate.wait(5)
        return {"v": 1}

    out = []
    ts = [threading.Thread(target=lambda: out.append(limits.coalesce(("t", "same"), 5.0, slow))) for _ in range(4)]
    for t in ts:
        t.start()
    time.sleep(0.3)
    gate.set()
    for t in ts:
        t.join(5)
    assert len(calls) == 1 and out == [{"v": 1}] * 4
    assert limits.coalesce(("t", "same"), 5.0, slow) == {"v": 1} and len(calls) == 1   # còn trong bộ nhớ


def test_coalesce_does_not_cache_errors():
    from server import limits
    n = []

    def boom():
        n.append(1)
        raise RuntimeError("x")

    for _ in range(2):
        try:
            limits.coalesce(("t", "err"), 5.0, boom)
        except RuntimeError:
            pass
    assert len(n) == 2


def test_coverage_segments_merge_small_gaps_and_split_large(data_root):
    rows = [(T0 + i * 5000, 670000, 1.0, 1.0) for i in range(0, 60)]                 # 5 phút liên tục
    rows += [(T0 + 20 * 60_000 + i * 5000, 670000, 1.0, 1.0) for i in range(0, 60)]  # đoạn thứ hai cách 15 phút
    put_book(rows)
    r = client.get("/api/heatmap/coverage", params={"symbol": "BTCUSDT", "from": T0, "to": T0 + 3_600_000})
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["segments"]) == 2
    assert j["segments"][0][0] <= T0 and j["segments"][1][0] >= T0 + 20 * 60_000 - 60_000
    assert j["first"] == j["segments"][0][0] and j["last"] == j["segments"][1][1]
    assert 0 < j["covered_ms"] < 3_600_000
    empty = client.get("/api/heatmap/coverage", params={"symbol": "XAUUSDT", "from": T0, "to": T0 + 3_600_000}).json()
    assert empty["segments"] == [] and empty["first"] is None


def test_depthbands_turn_cumulative_depth_into_density_per_percent(data_root):
    # độ sâu cộng dồn tới 1% là 100, tới 2% là 300 -> dải 0-1% mật độ 100/1%, dải 1-2% mật độ 200/1%
    rows = [(T0, -1.0, 1.0, 100.0), (T0, -2.0, 3.0, 300.0), (T0, 1.0, 1.0, 50.0), (T0, 2.0, 2.0, 80.0)]
    store.write_partition("bookdepth", "BTCUSDT", DAY, rows)
    r = client.get("/api/depthbands", params={"symbol": "BTCUSDT", "from": T0, "to": T0 + 600_000, "tbucket": 600_000})
    assert r.status_code == 200, r.text
    j = r.json()
    got = {(x[1], x[2]): x[3] for x in j["rows"]}
    assert got[(-1.0, 0.0)] == 100.0 and got[(-2.0, -1.0)] == 200.0
    assert got[(0.0, 1.0)] == 50.0 and got[(1.0, 2.0)] == 30.0
    assert j["scale"] > 0
    assert client.get("/api/depthbands", params={"symbol": "NOPE", "from": T0, "to": T0 + 1000}).status_code == 400


def zones(**kw):
    p = {"symbol": "BTCUSDT", "from": T0, "to": T0 + 3_600_000, "mult": 1, "min": 0.3, **kw}
    r = client.get("/api/liqzones", params=p)
    assert r.status_code == 200, r.text
    return r.json()


def test_liqzones_pulled_filled_active_and_noise(data_root):
    rows = []
    for i in range(0, 120):                                    # 10 phút, mẫu cách 5 giây
        t = T0 + i * 5000
        rows.append((t, 670100, 0.0, 0.1))                      # nền nhỏ để có mẫu ở mọi thời điểm
        if i < 40:
            rows.append((t, 670000, 50.0, 0.0))                 # tường mua 200 giây rồi biến mất, không có lệnh khớp: bị rút
            rows.append((t, 671000, 0.0, 40.0))                 # tường bán 200 giây rồi biến mất, có lệnh khớp mua: bị khớp
        if i >= 80:
            rows.append((t, 672000, 45.0, 0.0))                 # tường mua còn tới mẫu cuối: còn hiệu lực
        if 10 <= i < 12:
            rows.append((t, 673000, 60.0, 0.0))                 # chỉ 10 giây: nhiễu
    put_book(rows)
    # lệnh khớp ở mức 671000 ngay sau khi tường bán biến mất (phía mua chủ động: m = False)
    store.write_partition("ticks", "BTCUSDT", DAY, [(T0 + 40 * 5000 + 1000, 1, 671000, 39.0, False)])
    j = zones(top=50)
    by = {(r[0], r[1]): r for r in j["rows"]}
    assert j["bucket"] == 1.0
    pulled = by[("bid", 67000.0)]
    assert pulled[6] == "pulled" and pulled[2] == T0 and pulled[3] == T0 + 40 * 5000
    assert by[("ask", 67100.0)][6] == "filled"
    assert by[("bid", 67200.0)][6] == "active"
    assert ("bid", 67300.0) not in by                           # đoạn 10 giây bị bỏ vì quá ngắn
    assert all(r[4] >= 1 for r in j["rows"])                    # nền nhỏ (0,1) dưới ngưỡng nên không thành vùng


def test_liqzones_recording_gap_is_not_a_pull(data_root):
    rows = [(T0 + i * 5000, 670000, 50.0, 0.0) for i in range(0, 30)]      # tường 150 giây
    rows += [(T0 + 20 * 60_000 + i * 5000, 670500, 0.0, 0.1) for i in range(0, 12)]   # mẫu kế tiếp cách 20 phút: collector tắt
    put_book(rows)
    got = {(r[0], r[1]): r for r in zones()["rows"]}
    assert got[("bid", 67000.0)][6] == "gap"


def test_liqzones_empty_and_bad_symbol(data_root):
    assert zones(symbol="XAUUSDT")["rows"] == []
    assert client.get("/api/liqzones", params={"symbol": "NOPE", "from": T0, "to": T0 + 1000}).status_code == 400
