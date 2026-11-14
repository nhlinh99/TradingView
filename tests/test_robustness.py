"""Hai lỗi thật gặp khi chạy collector nhiều giờ:
1. to_int_price đọc lại config/symbols.toml cho từng tick; file bị khoá tạm thời thì luồng lấp khoảng hở chết.
2. Luồng lấp khoảng hở không tự thử lại, gap nằm open cho tới lần khởi động sau.
"""
import threading
import time
import tomllib

import httpx
import pytest
from websockets.sync.server import serve

from collector import binance, live_trades
from collector.live_trades import TradeCollector
from common import appdb, store

T0 = 1_794_268_800_000


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


# ---------- nhớ đệm cấu hình ----------

def test_symbols_file_is_parsed_once_for_many_calls(monkeypatch):
    store._symbols_cache = None
    real = tomllib.load
    calls = {"n": 0}

    def counting(f):
        calls["n"] += 1
        return real(f)

    monkeypatch.setattr(store.tomllib, "load", counting)
    for i in range(1000):
        store.to_int_price("BTCUSDT", 67000.0 + i * 0.1)
    assert calls["n"] == 1


def test_locked_config_file_falls_back_to_cache(monkeypatch):
    store.symbol_config("BTCUSDT")  # nạp nhớ đệm

    class Locked:
        def stat(self):
            raise PermissionError("file đang bị khoá")

    monkeypatch.setattr(store, "_SYMBOLS_FILE", Locked())
    assert store.to_int_price("BTCUSDT", 67244.4) == 672444  # vẫn chạy nhờ bản nhớ đệm


def test_locked_config_file_without_cache_still_raises(monkeypatch):
    class Locked:
        def stat(self):
            raise PermissionError("file đang bị khoá")

    monkeypatch.setattr(store, "_symbols_cache", None)
    monkeypatch.setattr(store, "_SYMBOLS_FILE", Locked())
    with pytest.raises(PermissionError):
        store.symbol_config("BTCUSDT")


def test_config_is_reloaded_when_file_changes(tmp_path, monkeypatch):
    f = tmp_path / "symbols.toml"
    f.write_text('[AAA]\ntick = 0.5\n', encoding="utf-8")
    monkeypatch.setattr(store, "_SYMBOLS_FILE", f)
    monkeypatch.setattr(store, "_symbols_cache", None)
    assert store.symbol_config("AAA")["tick"] == 0.5
    time.sleep(0.02)
    f.write_text('[AAA]\ntick = 0.25\n', encoding="utf-8")
    import os
    os.utime(f, ns=(time.time_ns() + 10_000_000, time.time_ns() + 10_000_000))
    assert store.symbol_config("AAA")["tick"] == 0.25


# ---------- lấp khoảng hở có thử lại và tiếp tục ----------

def make_rest_client(trades_ids):
    ids = sorted(trades_ids)

    def handler(req):
        p = dict(req.url.params)
        from_id, limit = int(p["fromId"]), int(p["limit"])
        rows = [{"a": a, "p": "67000.1", "q": "0.5", "f": a, "l": a, "T": T0 + a * 10, "m": False}
                for a in ids if a >= from_id][:limit]
        return httpx.Response(200, json=rows)

    return binance.make_client(httpx.MockTransport(handler))


def stored_ids():
    return [r[0] for r in store.read("ticks", "BTCUSDT", columns=["id"])]


def test_fill_gap_resume_skips_already_written_ids(data_root, monkeypatch):
    """Dùng trang nhỏ để lỗi xảy ra giữa chừng: lần thử lại chỉ lấy phần còn thiếu."""
    appdb.init()
    live_trades.record_gap("BTCUSDT", 1, 60, "open")
    ids = list(range(1, 61))
    seen_from = []
    fail = {"done": False}

    def handler(req):
        p = dict(req.url.params)
        from_id, limit = int(p["fromId"]), int(p["limit"])
        seen_from.append(from_id)
        if from_id >= 21 and not fail["done"]:
            fail["done"] = True
            return httpx.Response(400, text="lỗi")
        rows = [{"a": a, "p": "67000.1", "q": "0.5", "f": a, "l": a, "T": T0 + a * 10, "m": False}
                for a in ids if a >= from_id][:min(limit, 10)]  # máy chủ giả trả tối đa 10 dòng một trang
        return httpx.Response(200, json=rows)

    client = binance.make_client(httpx.MockTransport(handler))
    # limit=10 khớp với số dòng mỗi trang để phân trang tiếp tục đúng
    orig = binance.iter_agg_trades
    monkeypatch.setattr(live_trades.binance, "iter_agg_trades",
                        lambda c, s, f, t=None, **kw: orig(c, s, f, t, limit=10, **{k: v for k, v in kw.items() if k != "limit"}))
    progress: dict = {}
    with pytest.raises(binance.BinanceError):
        live_trades.fill_gap("BTCUSDT", 1, 60, client, pause=0, chunk_rows=10, sleep=lambda s: None, progress=progress)
    assert progress["next"] == 21 and progress["rows"] == 20
    seen_from.clear()
    live_trades.fill_gap("BTCUSDT", 1, 60, client, pause=0, chunk_rows=10, sleep=lambda s: None, progress=progress)
    assert seen_from[0] == 21                       # không tải lại 1..20
    assert stored_ids() == ids


# ---------- collector tự thử lại ----------

class FakeServer:
    def __init__(self, msgs):
        self.msgs = msgs
        self.server = serve(self._handler, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/market/ws/btcusdt@aggTrade"

    def _handler(self, ws):
        import json
        for m in self.msgs:
            ws.send(json.dumps(m))
        try:
            while True:
                ws.recv()
        except Exception:
            return

    def close(self):
        self.server.shutdown()


def trade(a):
    return {"e": "aggTrade", "E": 1, "a": a, "s": "BTCUSDT", "p": "67000.1", "q": "0.5", "nq": "0.5",
            "f": a, "l": a, "T": T0 + a * 10, "m": False, "st": 1}


def test_collector_retries_a_failed_fill_on_its_own(data_root):
    made = []

    def factory():
        if not made:   # lần đầu: máy chủ lỗi 400 ngay; lần sau: bình thường
            made.append("bad")
            return binance.make_client(httpx.MockTransport(lambda req: httpx.Response(400, text="lỗi")))
        made.append("good")
        return make_rest_client(range(1, 20))

    srv = FakeServer([trade(1), trade(10)])
    try:
        c = TradeCollector("BTCUSDT", url=srv.url, client_factory=factory, flush_seconds=0.1, recv_timeout=0.1,
                           max_backoff=0.2, rest_pause=0.0)
        c.fill_retry_base = 0.05
        stop = threading.Event()
        th = threading.Thread(target=c.run, args=(stop,), daemon=True)
        th.start()
        t0 = time.time()
        while time.time() - t0 < 15:
            if live_trades.open_gaps("BTCUSDT") == [] and stored_ids() == list(range(1, 11)):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("khoảng hở không được tự lấp lại")
        stop.set()
        th.join(timeout=20)
    finally:
        srv.close()
    assert made[:2] == ["bad", "good"]
