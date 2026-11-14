import json
import threading
import time

import pytest
from websockets.sync.server import serve

from collector import live_book
from collector.live_book import BookCollector, LocalBook, bucket_rows
from common import store

T0 = 1_794_268_800_000


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def ev(U, u, pu, b=(), a=()):
    return {"e": "depthUpdate", "E": 1, "T": 1, "s": "BTCUSDT", "U": U, "u": u, "pu": pu,
            "b": [[str(p), str(q)] for p, q in b], "a": [[str(p), str(q)] for p, q in a]}


def snap(L, bids, asks):
    return {"lastUpdateId": L, "bids": [[str(p), str(q)] for p, q in bids], "asks": [[str(p), str(q)] for p, q in asks]}


# ---------- LocalBook: quy tắc đồng bộ ----------

def test_snapshot_alignment_drops_old_and_applies_covering_event():
    b = LocalBook(0.1)
    ok = b.load_snapshot(snap(100, [(100.0, 1)], [(100.1, 1)]), [ev(80, 90, 70), ev(95, 105, 90, b=[(99.9, 2)])])
    assert ok and b.state == LocalBook.LIVE and b.last_u == 105
    assert b.bids[999] == 2.0 and b.bids[1000] == 1.0


def test_event_ending_exactly_at_snapshot_id_is_accepted():
    b = LocalBook(0.1)
    assert b.load_snapshot(snap(100, [(100.0, 1)], [(100.1, 1)]), [ev(95, 100, 90)])
    assert b.state == LocalBook.LIVE


def test_waits_when_all_buffered_events_are_older_than_snapshot():
    b = LocalBook(0.1)
    assert b.load_snapshot(snap(100, [(100.0, 1)], [(100.1, 1)]), [ev(80, 90, 70)])
    assert b.state == LocalBook.SYNC
    assert b.feed(ev(91, 99, 90))        # vẫn cũ hơn snapshot
    assert b.state == LocalBook.SYNC
    assert b.feed(ev(100, 110, 99)) and b.state == LocalBook.LIVE


def test_first_event_after_snapshot_with_hole_requires_resync():
    b = LocalBook(0.1)
    b.load_snapshot(snap(100, [(100.0, 1)], [(100.1, 1)]))
    assert b.feed(ev(150, 160, 149)) is False      # U > L: thiếu tin giữa snapshot và luồng


def test_buffered_hole_makes_load_snapshot_fail():
    b = LocalBook(0.1)
    assert b.load_snapshot(snap(100, [(100.0, 1)], [(100.1, 1)]), [ev(150, 160, 149)]) is False


def test_pu_must_equal_previous_u():
    b = LocalBook(0.1)
    b.load_snapshot(snap(100, [(100.0, 1)], [(100.1, 1)]), [ev(95, 105, 90)])
    assert b.feed(ev(106, 110, 105)) is True
    assert b.feed(ev(112, 115, 111)) is False      # pu 111 != u trước đó 110


def test_zero_quantity_removes_level_and_unknown_removal_is_fine():
    b = LocalBook(0.1)
    b.load_snapshot(snap(100, [(100.0, 1), (99.9, 1)], [(100.1, 1)]),
                    [ev(95, 105, 90, b=[(100.0, 0), (50.0, 0)], a=[(100.1, 3)])])
    assert 1000 not in b.bids and b.bids == {999: 1.0} and b.asks[1001] == 3.0


def test_quantity_replaces_not_adds():
    b = LocalBook(0.1)
    b.load_snapshot(snap(100, [(100.0, 5)], [(100.1, 1)]), [ev(95, 105, 90, b=[(100.0, 2)])])
    assert b.bids[1000] == 2.0


def test_wait_state_ignores_events():
    b = LocalBook(0.1)
    assert b.feed(ev(1, 2, 0)) is True and b.state == LocalBook.WAIT


def test_snapshot_band_is_recorded():
    b = LocalBook(0.1)
    b.load_snapshot(snap(1, [(100.0, 1), (99.0, 1)], [(100.1, 1), (101.0, 1)]))
    assert b.snapshot_band == (990, 1010)


# ---------- bucket_rows ----------

def test_bucket_rows_window_bucket_and_sides():
    b = LocalBook(0.1)
    # giá giữa ~ 1000 tick. cửa sổ ±1% = ±10 tick
    b.bids = {1000: 1.0, 995: 2.0, 991: 3.0, 980: 9.0}   # 980 nằm ngoài cửa sổ
    b.asks = {1001: 4.0, 1004: 5.0, 1015: 9.0}           # 1015 nằm ngoài
    rows = bucket_rows(b, T0, window_pct=1.0, bucket_ticks=5)
    got = {r[1]: (r[2], r[3]) for r in rows}
    assert got == {1000: (1.0, 4.0 + 5.0), 995: (2.0, 0.0), 990: (3.0, 0.0)}
    assert all(r[0] == T0 for r in rows)
    assert [r[1] for r in rows] == sorted(r[1] for r in rows)


def test_bucket_rows_empty_book():
    assert bucket_rows(LocalBook(0.1), T0, 0.15, 10) == []


# ---------- collector ----------

class FakeWs:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.connections = 0
        self.server = serve(self._handler, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/public/ws/btcusdt@depth@100ms"

    def _handler(self, ws):
        self.connections += 1
        msgs, close_after = self.scripts.pop(0) if self.scripts else ([], False)
        for m in msgs:
            ws.send(json.dumps(m))
        if close_after:
            return
        try:
            while True:
                ws.recv()
        except Exception:
            return

    def close(self):
        self.server.shutdown()


def run(c, until, timeout=10.0):
    stop = threading.Event()
    th = threading.Thread(target=c.run, args=(stop,), daemon=True)
    th.start()
    t0 = time.time()
    try:
        while time.time() - t0 < timeout:
            if until():
                break
            time.sleep(0.03)
        else:
            raise AssertionError("hết thời gian chờ")
    finally:
        stop.set()
        th.join(timeout=20)
    assert not th.is_alive()


def make(url, snapshots, step_s=5.0, **kw):
    """snapshots: danh sách snapshot trả lần lượt. Đồng hồ giả tiến step_s giây mỗi lần gọi."""
    calls = {"snap": 0}
    clock_t = [T0 / 1000.0]

    def clock():
        clock_t[0] += step_s
        return clock_t[0]

    def snapshot_fn(symbol):
        i = min(calls["snap"], len(snapshots) - 1)
        calls["snap"] += 1
        return snapshots[i]

    c = BookCollector("BTCUSDT", url=url, snapshot_fn=snapshot_fn, flush_seconds=0.0, recv_timeout=0.1,
                      max_backoff=0.2, clock=clock, **kw)
    c.min_snapshot_gap_s = 0.0
    return c, calls


BIDS = [(67000.0, 1.0), (66999.0, 2.0), (66990.0, 3.0)]
ASKS = [(67000.1, 1.5), (67001.0, 2.5), (67010.0, 3.5)]


def test_collector_syncs_samples_and_writes_rows(data_root):
    events = [ev(90, 95, 80), ev(99, 105, 95), ev(106, 110, 105, b=[(67000.0, 4.0)]), ev(111, 115, 110)]
    srv = FakeWs([(events, False)])
    try:
        c, calls = make(srv.url, [snap(100, BIDS, ASKS)])
        run(c, lambda: c.events >= 4 and c.written > 0)
    finally:
        srv.close()
    assert calls["snap"] == 1 and c.resyncs >= 1
    rows = store.read("book", "BTCUSDT")
    assert rows, "phải có dòng sổ lệnh"
    # tick 0,1 và bucket 1 USD = 10 tick. Bucket 670000 chứa 67000.0..67000.9: bid 67000.0 (đã cập nhật
    # lên 4.0 ở tin thứ ba) và ask 67000.1 (1.5). 66999.0 thuộc bucket 669990.
    last_ts = max(r[0] for r in rows)
    latest = {r[1]: (r[2], r[3]) for r in rows if r[0] == last_ts}
    assert latest[670000] == (pytest.approx(4.0), pytest.approx(1.5))
    assert latest[669990] == (pytest.approx(2.0), 0.0)
    assert all(r[0] % 5000 == 0 for r in rows)  # mẫu theo bội của 5 giây


def test_collector_resyncs_after_pu_break(data_root):
    ok1 = [ev(99, 105, 95), ev(106, 110, 105)]
    broken = [ev(120, 125, 119)]                        # pu sai: 119 != 110
    ok2 = [ev(300, 310, 299), ev(311, 320, 310)]        # tin quanh snapshot thứ hai (L=305)
    srv = FakeWs([(ok1 + broken + ok2, False)])
    try:
        c, calls = make(srv.url, [snap(100, BIDS, ASKS), snap(305, BIDS, ASKS)])
        run(c, lambda: c.events >= 5 and c.live is not None and c.live.last_u == 320)
    finally:
        srv.close()
    assert calls["snap"] == 2
    assert c.live.state == LocalBook.LIVE


def test_collector_periodic_resync_swaps_in_fresh_book(data_root):
    evs = [ev(99, 105, 95)] + [ev(106 + 10 * i, 115 + 10 * i, 105 + 10 * i - (0 if i == 0 else 0)) for i in range(0, 1)]
    # chuỗi liền mạch: mỗi tin có pu = u của tin trước
    seq, last_u = [], 105
    seq.append(ev(99, 105, 95))
    for _ in range(8):
        seq.append(ev(last_u + 1, last_u + 5, last_u))
        last_u += 5
    srv = FakeWs([(seq, False)])
    try:
        c, calls = make(srv.url, [snap(100, BIDS, ASKS), snap(120, BIDS, ASKS)])
        c.resync_s = 0.0  # luôn xin snapshot mới khi sổ hiện tại đã đồng bộ
        run(c, lambda: c.events >= len(seq))
    finally:
        srv.close()
    assert calls["snap"] >= 2 and c.resyncs >= 2
    assert c.live is not None and c.live.state == LocalBook.LIVE


def test_collector_reconnect_starts_fresh_and_keeps_collecting(data_root):
    s1 = ([ev(99, 105, 95), ev(106, 110, 105)], True)
    s2 = ([ev(200, 210, 199), ev(211, 220, 210)], False)
    srv = FakeWs([s1, s2])
    try:
        c, calls = make(srv.url, [snap(100, BIDS, ASKS), snap(205, BIDS, ASKS)])
        run(c, lambda: c.events >= 4 and c.live is not None and c.live.last_u == 220)
    finally:
        srv.close()
    assert srv.connections == 2 and calls["snap"] == 2


def test_snapshot_failure_does_not_crash(data_root):
    srv = FakeWs([([ev(99, 105, 95), ev(106, 110, 105), ev(111, 115, 110)], False)])

    def boom(symbol):
        raise RuntimeError("REST lỗi")

    try:
        c = BookCollector("BTCUSDT", url=srv.url, snapshot_fn=boom, flush_seconds=0.0, recv_timeout=0.1)
        c.min_snapshot_gap_s = 0.0
        run(c, lambda: c.events >= 3)
    finally:
        srv.close()
    assert c.live is None and c.written == 0


def test_bucket_must_be_multiple_of_tick(data_root, monkeypatch):
    monkeypatch.setattr(store, "symbol_config", lambda s: {"tick": 0.1, "book_window_pct": 0.1, "book_bucket": 0.25,
                                                           "book_interval_s": 5, "book_resync_s": 60})
    with pytest.raises(ValueError):
        BookCollector("BTCUSDT")


def test_ws_url_uses_public_path():
    assert live_book.ws_url("BTCUSDT") == "wss://fstream.binance.com/public/ws/btcusdt@depth@100ms"


@pytest.mark.live
def test_live_book_syncs_and_samples(data_root):
    c = BookCollector("BTCUSDT", flush_seconds=1)
    run(c, lambda: c.written > 0, timeout=90)
    assert c.live is not None and c.snapshot_bands
    lo, hi = c.snapshot_bands[0]
    assert lo < hi
