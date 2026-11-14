import json
from datetime import date

import httpx
import pytest

from collector import binance, klines
from common import store

DAY0 = 1_794_000_000_000 // 86_400_000 * 86_400_000  # 00:00 UTC của một ngày


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def kline(open_ms, o="67000.0", h="67010.0", l="66990.0", c="67005.0", v="10.0", buy="4.0"):
    # định dạng Binance: [open, o, h, l, c, vol, close, quote, trades, takerBuyBase, takerBuyQuote, ignore]
    return [open_ms, o, h, l, c, v, open_ms + 59_999, "0", 5, buy, "0", "0"]


def make_client(handler):
    return binance.make_client(httpx.MockTransport(handler))


def test_kline_to_bar_uses_taker_buy_for_buy_volume():
    bar = binance.kline_to_bar("BTCUSDT", kline(DAY0, v="10.0", buy="4.0"))
    assert bar == (DAY0, 670000, 670100, 669900, 670050, 10.0, 4.0, 6.0)


def test_pagination_and_end_exclusive():
    seen = []

    def handler(req):
        p = dict(req.url.params)
        seen.append((int(p["startTime"]), int(p["endTime"]), int(p["limit"])))
        start = int(p["startTime"])
        n = min(int(p["limit"]), (int(p["endTime"]) - start) // 60_000 + 1)
        return httpx.Response(200, json=[kline(start + i * 60_000) for i in range(n)])

    c = make_client(handler)
    got = list(binance.iter_klines(c, "BTCUSDT", "1m", DAY0, DAY0 + 10 * 60_000, limit=4))
    assert [int(k[0]) for k in got] == [DAY0 + i * 60_000 for i in range(10)]
    assert len(seen) == 3 and seen[1][0] == DAY0 + 4 * 60_000


def test_retry_on_429_honours_retry_after():
    waits, calls = [], {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=[])

    c = make_client(handler)
    assert binance.get_json(c, "/x", sleep=waits.append) == []
    assert waits == [2.0, 2.0]


def test_http_400_raises_without_retry():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(400, text='{"code":-1121,"msg":"Invalid symbol."}')

    with pytest.raises(binance.BinanceError):
        binance.get_json(make_client(handler), "/x", sleep=lambda s: None)
    assert calls["n"] == 1


def test_gives_up_after_tries():
    def handler(req):
        return httpx.Response(503)

    with pytest.raises(binance.BinanceError):
        binance.get_json(make_client(handler), "/x", tries=3, sleep=lambda s: None)


def test_sync_writes_closed_bars_only_one_file_per_day(data_root):
    now = DAY0 + 86_400_000 + 5 * 60_000 + 30_000  # 00:05:30 của ngày hôm sau: nến 00:05 chưa đóng

    def handler(req):
        p = dict(req.url.params)
        start, end = int(p["startTime"]), int(p["endTime"])
        ts = range(start, end + 1, 60_000)
        return httpx.Response(200, json=[kline(t) for t in ts])

    s = klines.sync("BTCUSDT", start_ms=DAY0, now_ms=now, client=make_client(handler))
    assert s["days"] == 2
    rows = store.read("bars", "BTCUSDT")
    assert rows[0][0] == DAY0
    assert rows[-1][0] == DAY0 + 86_400_000 + 4 * 60_000  # nến 00:04 là nến đóng cuối cùng
    assert len(rows) == 1440 + 5
    names = sorted(p.name for p in (data_root / "bars" / "BTCUSDT").iterdir())
    assert len(names) == 2 and all(n.endswith(".parquet") for n in names)


def test_sync_resumes_from_last_bar_day_and_is_idempotent(data_root):
    def handler(req):
        p = dict(req.url.params)
        return httpx.Response(200, json=[kline(t) for t in range(int(p["startTime"]), int(p["endTime"]) + 1, 60_000)])

    now1 = DAY0 + 3_600_000
    klines.sync("BTCUSDT", start_ms=DAY0, now_ms=now1, client=make_client(handler))
    assert len(store.read("bars", "BTCUSDT")) == 60
    now2 = DAY0 + 7_200_000
    klines.sync("BTCUSDT", now_ms=now2, client=make_client(handler))  # tiếp tục, không start_ms
    rows = store.read("bars", "BTCUSDT")
    assert len(rows) == 120 and len({r[0] for r in rows}) == 120


def test_agg_trade_to_tick_and_paging():
    def handler(req):
        p = dict(req.url.params)
        start = int(p["fromId"])
        n = min(int(p["limit"]), 7 - start)
        rows = [{"a": start + i, "p": "67000.1", "q": "0.5", "f": 1, "l": 1, "T": 1_794_000_000_000 + start + i, "m": i % 2 == 0}
                for i in range(max(n, 0))]
        return httpx.Response(200, json=rows)

    got = list(binance.iter_agg_trades(make_client(handler), "BTCUSDT", 0, limit=3))
    assert [t["a"] for t in got] == list(range(7))
    assert binance.agg_trade_to_tick("BTCUSDT", got[0]) == (1_794_000_000_000, 0, 670001, 0.5, True)
    to = list(binance.iter_agg_trades(make_client(handler), "BTCUSDT", 2, to_id=4, limit=3))
    assert [t["a"] for t in to] == [2, 3, 4]


@pytest.mark.live
def test_live_klines_shape_and_taker_buy():
    c = binance.make_client()
    now = int(__import__("time").time() * 1000)
    end = now // 60_000 * 60_000
    ks = list(binance.iter_klines(c, "BTCUSDT", "1m", end - 5 * 60_000, end))
    assert len(ks) == 5
    for k in ks:
        bar = binance.kline_to_bar("BTCUSDT", k)
        assert 0 <= bar[6] <= bar[5] + 1e-6 and bar[3] <= bar[1] <= bar[2]
