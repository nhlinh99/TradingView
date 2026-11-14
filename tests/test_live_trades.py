import json
import threading
import time
from datetime import date

import httpx
import pytest
from websockets.sync.server import serve

from collector import binance, live_trades
from collector.live_trades import TickWriter, TradeCollector
from common import appdb, store

T0 = 1_794_268_800_000  # 00:00:00 UTC ngày 10/11/2026


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def trade(a, price="67000.1", qty="0.5", m=False, t=None):
    return {"e": "aggTrade", "E": 1, "a": a, "s": "BTCUSDT", "p": price, "q": qty, "nq": qty,
            "f": a, "l": a, "T": (T0 + a * 10) if t is None else t, "m": m, "st": 1}


class FakeServer:
    """Máy chủ WebSocket giả. scripts: danh sách kịch bản, mỗi kết nối dùng một kịch bản.
    Kịch bản: (danh sách tin, đóng_sau) - đóng_sau=True: đóng kết nối sau khi gửi hết."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.connections = 0
        self._lock = threading.Lock()
        self.server = serve(self._handler, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/market/ws/btcusdt@aggTrade"

    def _handler(self, ws):
        with self._lock:
            self.connections += 1
            msgs, close_after = self.scripts.pop(0) if self.scripts else ([], False)
        for m in msgs:
            ws.send(m if isinstance(m, str) else json.dumps(m))
        if close_after:
            return
        try:
            while True:
                ws.recv()
        except Exception:
            return

    def close(self):
        self.server.shutdown()


def rest_for(trades):
    """Client REST giả: phục vụ /fapi/v1/aggTrades?fromId=&limit= từ danh sách id."""
    ids = sorted(trades)
    calls = []

    def handler(req):
        p = dict(req.url.params)
        calls.append(p)
        from_id, limit = int(p["fromId"]), int(p["limit"])
        rows = [{"a": a, "p": "67000.1", "q": "0.5", "f": a, "l": a, "T": T0 + a * 10, "m": False}
                for a in ids if a >= from_id][:limit]
        return httpx.Response(200, json=rows)

    return (lambda: binance.make_client(httpx.MockTransport(handler))), calls


def run_collector(c, until, timeout=10.0):
    stop = threading.Event()
    th = threading.Thread(target=c.run, args=(stop,), daemon=True)
    th.start()
    t0 = time.time()
    try:
        while time.time() - t0 < timeout:
            if until():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("hết thời gian chờ điều kiện")
    finally:
        stop.set()
        th.join(timeout=20)
    assert not th.is_alive()


def stored_ids(symbol="BTCUSDT"):
    return [r[0] for r in store.read("ticks", symbol, columns=["id"])]


def make(url, **kw):
    kw.setdefault("flush_rows", 1000)
    kw.setdefault("flush_seconds", 0.1)
    kw.setdefault("recv_timeout", 0.1)
    kw.setdefault("max_backoff", 0.2)
    kw.setdefault("rest_pause", 0.0)
    return TradeCollector("BTCUSDT", url=url, **kw)


# ---------- TickWriter ----------

def test_writer_flush_by_rows_and_clock(data_root):
    now = [0.0]
    w = TickWriter("BTCUSDT", flush_rows=3, flush_seconds=10, clock=lambda: now[0])
    w.add((T0, 1, 1, 1.0, True)); w.add((T0, 2, 1, 1.0, True))
    assert not w.due()
    w.add((T0, 3, 1, 1.0, True))
    assert w.due()
    assert w.flush() == 3 and not w.due()
    w.add((T0, 4, 1, 1.0, True))
    now[0] = 11.0
    assert w.due()


def test_writer_splits_by_utc_day_and_names_parts_by_first_id(data_root):
    w = TickWriter("BTCUSDT")
    next_day = T0 + 86_400_000
    for tick in [(T0 + 1, 10, 1, 1.0, True), (next_day + 1, 11, 1, 1.0, True), (next_day + 2, 12, 1, 1.0, False)]:
        w.add(tick)
    w.flush()
    names = sorted(p.name for p in (data_root / "ticks" / "BTCUSDT").iterdir())
    assert names == ["date=2026-11-10.p10.parquet", "date=2026-11-11.p11.parquet"]
    assert stored_ids() == [10, 11, 12]


def test_writer_keeps_rows_when_write_fails(data_root, monkeypatch):
    w = TickWriter("BTCUSDT")
    w.add((T0, 1, 1, 1.0, True))
    monkeypatch.setattr(live_trades, "write_ticks", lambda *a: (_ for _ in ()).throw(OSError("đầy đĩa")))
    with pytest.raises(OSError):
        w.flush()
    assert len(w.rows) == 1
    monkeypatch.undo()
    monkeypatch.setenv("DATA_DIR", str(data_root))
    assert w.flush() == 1


# ---------- collector ----------

def test_basic_stream_is_written_and_stop_flushes(data_root):
    srv = FakeServer([([trade(a) for a in range(1, 11)], False)])
    try:
        c = make(srv.url, flush_seconds=60)  # không tự flush: chỉ flush khi dừng
        run_collector(c, lambda: c.received >= 10)
    finally:
        srv.close()
    assert stored_ids() == list(range(1, 11))
    row = store.read("ticks", "BTCUSDT")[0]
    assert row == (T0 + 10, 1, 670001, 0.5, False)


def test_duplicates_and_older_ids_are_ignored_and_other_messages_skipped(data_root):
    msgs = [{"result": None, "id": 1}, trade(5), trade(6), trade(6), trade(4), trade(7), "{\"e\":\"other\"}"]
    srv = FakeServer([(msgs, False)])
    try:
        c = make(srv.url)
        run_collector(c, lambda: c.received >= 5)
    finally:
        srv.close()
    assert stored_ids() == [5, 6, 7]


def test_gap_is_detected_logged_and_filled_via_rest(data_root):
    live = [trade(a) for a in (1, 2, 3, 4, 5, 10, 11, 12)]
    factory, calls = rest_for(range(1, 13))
    srv = FakeServer([(live, False)])
    try:
        c = make(srv.url, client_factory=factory)
        run_collector(c, lambda: c.received >= 8)
    finally:
        srv.close()
    assert stored_ids() == list(range(1, 13))
    con = appdb.connect()
    try:
        gaps = con.execute("SELECT from_id, to_id, status, rows FROM tick_gaps").fetchall()
    finally:
        con.close()
    assert gaps == [(6, 9, "filled", 4)]
    assert calls and calls[0]["fromId"] == "6"


def test_reconnect_after_server_closes(data_root):
    s1 = ([trade(a) for a in range(1, 6)], True)    # gửi 5 tin rồi đóng
    s2 = ([trade(a) for a in range(6, 11)], False)  # nối lại, tiếp tục liền mạch
    srv = FakeServer([s1, s2])
    try:
        c = make(srv.url)
        run_collector(c, lambda: c.received >= 10)
    finally:
        srv.close()
    assert stored_ids() == list(range(1, 11))
    assert srv.connections == 2 and c.reconnects >= 1
    con = appdb.connect()
    try:
        assert con.execute("SELECT count(*) FROM tick_gaps").fetchone()[0] == 0
    finally:
        con.close()


def test_reconnect_after_missed_messages_fills_the_hole(data_root):
    s1 = ([trade(a) for a in range(1, 6)], True)
    s2 = ([trade(a) for a in range(9, 12)], False)  # bỏ lỡ 6..8 trong lúc mất kết nối
    factory, _ = rest_for(range(1, 12))
    srv = FakeServer([s1, s2])
    try:
        c = make(srv.url, client_factory=factory)
        run_collector(c, lambda: c.received >= 8)
    finally:
        srv.close()
    assert stored_ids() == list(range(1, 12))


def test_restart_continues_from_stored_id_and_fills_hole(data_root):
    store.write_partition("ticks", "BTCUSDT", date(2026, 11, 10),
                          [(T0 + a * 10, a, 670001, 0.5, False) for a in range(1, 101)])
    factory, calls = rest_for(range(1, 120))
    srv = FakeServer([([trade(a) for a in (105, 106)], False)])
    try:
        c = make(srv.url, client_factory=factory)
        run_collector(c, lambda: c.received >= 2)
    finally:
        srv.close()
    assert stored_ids() == list(range(1, 101)) + [101, 102, 103, 104, 105, 106]


def test_open_gap_from_previous_run_is_resumed(data_root):
    appdb.init()
    store.write_partition("ticks", "BTCUSDT", date(2026, 11, 10),
                          [(T0 + a * 10, a, 670001, 0.5, False) for a in (1, 2, 3, 20, 21)])
    live_trades.record_gap("BTCUSDT", 4, 19, "open")  # lần chạy trước bị ngắt giữa chừng
    factory, _ = rest_for(range(1, 30))
    srv = FakeServer([([trade(22)], False)])
    try:
        c = make(srv.url, client_factory=factory)
        run_collector(c, lambda: c.received >= 1 and not live_trades.open_gaps("BTCUSDT"))
    finally:
        srv.close()
    assert stored_ids() == list(range(1, 23))


def test_huge_gap_is_skipped_not_filled(data_root):
    live = [trade(1), trade(1000)]
    factory, calls = rest_for(range(1, 1001))
    srv = FakeServer([(live, False)])
    try:
        c = make(srv.url, client_factory=factory, max_gap=100)
        run_collector(c, lambda: c.received >= 2)
    finally:
        srv.close()
    assert stored_ids() == [1, 1000] and calls == []
    con = appdb.connect()
    try:
        assert con.execute("SELECT status FROM tick_gaps").fetchall() == [("skipped",)]
    finally:
        con.close()


def test_failed_fill_stays_open_for_retry(data_root):
    def handler(req):
        return httpx.Response(400, text="bad")
    factory = lambda: binance.make_client(httpx.MockTransport(handler))  # noqa: E731
    srv = FakeServer([([trade(1), trade(5)], False)])
    try:
        c = make(srv.url, client_factory=factory)
        run_collector(c, lambda: c.received >= 2)
        time.sleep(0.3)
    finally:
        srv.close()
    assert live_trades.open_gaps("BTCUSDT") == [(2, 4)]


def test_stale_connection_is_dropped_and_reopened(data_root):
    srv = FakeServer([([trade(1)], False), ([trade(2)], False)])  # kết nối đầu im lặng sau tin đầu
    try:
        c = make(srv.url, stale_seconds=0.4)
        run_collector(c, lambda: c.received >= 2, timeout=15)
    finally:
        srv.close()
    assert stored_ids() == [1, 2] and srv.connections >= 2


def test_ws_url_uses_new_market_path():
    assert live_trades.ws_url("BTCUSDT") == "wss://fstream.binance.com/market/ws/btcusdt@aggTrade"


@pytest.mark.live
def test_live_stream_receives_trades(data_root):
    c = TradeCollector("BTCUSDT", flush_seconds=1, recv_timeout=1)
    run_collector(c, lambda: c.received >= 5, timeout=60)
    assert len(stored_ids()) >= 5
