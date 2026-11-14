import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from websockets.sync.server import serve

from server import live_hub
from server.main import app


def agg(a, p="67000.5", q="0.5", m=False, t=1_794_268_800_000):
    return {"e": "aggTrade", "E": 1, "a": a, "s": "BTCUSDT", "p": p, "q": q, "nq": q, "f": a, "l": a,
            "T": t + a, "m": m, "st": 1}


class Upstream:
    """Máy chủ aggTrade giả. scripts: mỗi kết nối một (danh sách tin, đóng_sau)."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.connections = 0
        self.closed = threading.Event()   # đặt khi một kết nối bị phía server đóng
        self.paths = []
        self.server = serve(self._handler, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url_for(self, symbol):
        return f"ws://127.0.0.1:{self.port}/market/ws/{symbol.lower()}@aggTrade"

    def _handler(self, ws):
        self.connections += 1
        self.paths.append(ws.request.path)
        msgs, close_after = self.scripts.pop(0) if self.scripts else ([], False)
        for m in msgs:
            ws.send(json.dumps(m))
        if close_after:
            return
        try:
            while True:
                ws.recv()
        except Exception:
            self.closed.set()

    def close(self):
        self.server.shutdown()


@pytest.fixture()
def hub_env(monkeypatch):
    def make(scripts):
        up = Upstream(scripts)
        h = live_hub.LiveHub(url_for=up.url_for, backoff_start=0.05)
        monkeypatch.setattr(live_hub, "hub", h)
        return up, h
    return make


def recv_until(ws, pred, limit=50):
    out = []
    for _ in range(limit):
        m = ws.receive_json()
        out.append(m)
        if pred(m):
            return out
    raise AssertionError(f"không thấy tin mong đợi, đã nhận: {out[-5:]}")


def test_subscribe_receives_status_then_trades_in_order_and_dedupes(hub_env):
    up, _ = hub_env([([agg(1), agg(2), agg(2), agg(3, m=True)], False)])
    try:
        with TestClient(app).websocket_connect("/api/stream") as ws:
            ws.send_json({"op": "subscribe", "symbol": "btcusdt"})
            msgs = recv_until(ws, lambda m: m.get("t") == "trade" and m["id"] == 3)
    finally:
        up.close()
    assert msgs[0]["t"] == "status" and msgs[0]["s"] == "BTCUSDT"              # tin đầu luôn là trạng thái
    trades = [m for m in msgs if m["t"] == "trade"]
    assert [t["id"] for t in trades] == [1, 2, 3]                      # id 2 trùng đã bị bỏ
    assert trades[0] == {"t": "trade", "s": "BTCUSDT", "ts": 1_794_268_800_001, "id": 1, "p": 67000.5, "q": 0.5, "m": False}
    assert trades[2]["m"] is True
    assert up.paths[0] == "/market/ws/btcusdt@aggTrade"


def test_two_clients_share_one_upstream_connection(hub_env):
    up, h = hub_env([([agg(1), agg(2)], False)])
    try:
        c = TestClient(app)
        with c.websocket_connect("/api/stream") as a, c.websocket_connect("/api/stream") as b:
            a.send_json({"op": "subscribe", "symbol": "BTCUSDT"})
            b.send_json({"op": "subscribe", "symbol": "BTCUSDT"})
            ra = recv_until(a, lambda m: m.get("t") == "trade" and m["id"] == 2)
            rb = recv_until(b, lambda m: m.get("t") == "trade" and m["id"] == 2)
            assert up.connections == 1 and len(h.feeds) == 1
    finally:
        up.close()
    # người vào sau có thể bỏ lỡ id 1 (nguồn đã chạy), nhưng cả hai đều phải nhận id 2 đúng một lần
    for r in (ra, rb):
        ids = [m["id"] for m in r if m["t"] == "trade"]
        assert ids.count(2) == 1 and ids == sorted(ids)


def test_upstream_closes_when_last_subscriber_leaves(hub_env):
    up, h = hub_env([([agg(1)], False)])
    try:
        with TestClient(app).websocket_connect("/api/stream") as ws:
            ws.send_json({"op": "subscribe", "symbol": "BTCUSDT"})
            recv_until(ws, lambda m: m.get("t") == "trade")
            assert len(h.feeds) == 1
        assert up.closed.wait(5), "kết nối nguồn phải được đóng khi không còn người xem"
    finally:
        up.close()
    assert h.feeds == {}


def test_unsubscribe_stops_updates_for_that_symbol(hub_env):
    up, h = hub_env([([agg(1)], False)])
    try:
        with TestClient(app).websocket_connect("/api/stream") as ws:
            ws.send_json({"op": "subscribe", "symbol": "BTCUSDT"})
            recv_until(ws, lambda m: m.get("t") == "trade")
            ws.send_json({"op": "unsubscribe", "symbol": "BTCUSDT"})
            assert up.closed.wait(5)
            assert h.feeds == {}
    finally:
        up.close()


def test_reconnects_upstream_and_reports_status(hub_env):
    s1 = ([agg(1), agg(2)], True)                 # gửi 2 tin rồi đóng
    s2 = ([agg(2), agg(3), agg(4)], False)        # nối lại, lặp lại id 2 (phải bị bỏ)
    up, _ = hub_env([s1, s2])
    try:
        with TestClient(app).websocket_connect("/api/stream") as ws:
            ws.send_json({"op": "subscribe", "symbol": "BTCUSDT"})
            msgs = recv_until(ws, lambda m: m.get("t") == "trade" and m["id"] == 4)
    finally:
        up.close()
    states = [m["state"] for m in msgs if m["t"] == "status"]
    assert "reconnecting" in states and states[-1] == "connected"
    assert [m["id"] for m in msgs if m["t"] == "trade"] == [1, 2, 3, 4]
    assert up.connections == 2


def test_errors_for_bad_requests_keep_connection_open(hub_env):
    up, _ = hub_env([([agg(1)], False)])
    try:
        with TestClient(app).websocket_connect("/api/stream") as ws:
            ws.send_json({"op": "subscribe", "symbol": "NOPE"})
            assert ws.receive_json()["t"] == "error"
            ws.send_json({"op": "dance", "symbol": "BTCUSDT"})
            assert ws.receive_json()["t"] == "error"
            ws.send_text("không phải json")
            assert ws.receive_json()["t"] == "error"
            ws.send_json([1, 2])
            assert ws.receive_json()["t"] == "error"
            ws.send_json({"op": "subscribe", "symbol": "BTCUSDT"})          # vẫn dùng được sau các lỗi
            recv_until(ws, lambda m: m.get("t") == "trade")
    finally:
        up.close()


def test_subscribe_twice_is_idempotent(hub_env):
    up, h = hub_env([([agg(1)], False)])
    try:
        with TestClient(app).websocket_connect("/api/stream") as ws:
            ws.send_json({"op": "subscribe", "symbol": "BTCUSDT"})
            ws.send_json({"op": "subscribe", "symbol": "BTCUSDT"})
            recv_until(ws, lambda m: m.get("t") == "trade")
            assert len(h.feeds["BTCUSDT"].subs) == 1
    finally:
        up.close()


def test_slow_consumer_drops_oldest_instead_of_blocking():
    import asyncio
    q: asyncio.Queue = asyncio.Queue(maxsize=3)
    for i in range(10):
        live_hub._put_drop_oldest(q, {"i": i})
    assert [q.get_nowait()["i"] for _ in range(3)] == [7, 8, 9]


def test_garbage_from_upstream_is_ignored():
    f = live_hub.Feed(live_hub.LiveHub(), "BTCUSDT")
    q = __import__("asyncio").Queue()
    f.subs.add(q)
    f._on_raw("không phải json")
    f._on_raw(json.dumps({"e": "other"}))
    f._on_raw(json.dumps(agg(5)))
    assert q.qsize() == 1


@pytest.mark.live
def test_live_real_binance_stream_through_the_server():
    with TestClient(app).websocket_connect("/api/stream") as ws:
        ws.send_json({"op": "subscribe", "symbol": "BTCUSDT"})
        msgs = recv_until(ws, lambda m: m.get("t") == "trade", limit=200)
    t = msgs[-1]
    assert t["s"] == "BTCUSDT" and t["p"] > 1000 and abs(time.time() * 1000 - t["ts"]) < 60_000
