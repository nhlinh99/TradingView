import time
from datetime import date, datetime, timezone

import httpx

import pytest
from fastapi.testclient import TestClient

from collector import binance
from common import store
from server import bars_api
from server.main import app

client = TestClient(app)

T0 = 1_794_268_800_000  # 00:00 UTC ngày 10/11/2026
DAY = date(2026, 11, 10)
MIN = 60_000


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


REST_CALLS: list[dict] = []


def rest_serving(trades):
    """Client REST giả phục vụ /fapi/v1/aggTrades?fromId= từ danh sách (id, ts, giá, khối lượng, m)."""
    def handler(req):
        p = dict(req.url.params)
        REST_CALLS.append(p)
        from_id = int(p["fromId"])
        rows = [{"a": a, "p": f"{price:.1f}", "q": str(q), "f": a, "l": a, "T": ts, "m": m}
                for a, ts, price, q, m in trades if a >= from_id][: int(p["limit"])]
        return httpx.Response(200, json=rows)
    return lambda: binance.make_client(httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def no_network_rest(monkeypatch):
    """Mặc định REST giả không có lệnh khớp nào, để test không gọi mạng thật."""
    REST_CALLS.clear()
    monkeypatch.setattr(bars_api, "rest_client_factory", rest_serving([]))


def kline_rows(n, start=T0, base=670000):
    """n nến 1 phút liên tiếp. Nến i: o=base+i, h=base+i+5, l=base+i-5, c=base+i+1, v=2, buy=1."""
    return [(start + i * MIN, base + i, base + i + 5, base + i - 5, base + i + 1, 2.0, 1.0, 1.0) for i in range(n)]


def put_klines(rows):
    store.write_partition("bars", "BTCUSDT", DAY, rows)


def put_ticks(ticks):
    store.write_partition("ticks", "BTCUSDT", DAY, ticks, part="t")


def test_one_minute_bars_come_from_klines_with_float_prices(data_root):
    put_klines(kline_rows(10))
    r = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0, "to": T0 + 10 * MIN})
    assert r.status_code == 200
    j = r.json()
    assert j["tick"] == 0.1 and len(j["bars"]) == 10
    assert j["bars"][0] == [T0, 67000.0, 67000.5, 66999.5, 67000.1, 2.0, 1.0, 1.0]


def test_five_minute_aggregation(data_root):
    put_klines(kline_rows(10))
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "5m", "from": T0, "to": T0 + 10 * MIN}).json()
    b0, b1 = j["bars"]
    assert b0[0] == T0 and b1[0] == T0 + 5 * MIN
    # nến 5 phút đầu: mở của phút 0, đóng của phút 4, cao nhất của phút 4, thấp nhất của phút 0
    assert b0[1:5] == [67000.0, 67000.9, 66999.5, 67000.5]
    assert b0[5:] == [10.0, 5.0, 5.0]


def test_daily_aggregation_aligns_to_utc_midnight(data_root):
    put_klines(kline_rows(120))
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1d", "from": T0, "to": T0 + 86_400_000}).json()
    assert len(j["bars"]) == 1 and j["bars"][0][0] == T0 and j["bars"][0][5] == 240.0


def test_forming_bar_is_built_from_ticks_after_the_last_kline(data_root):
    put_klines(kline_rows(3))                                  # phút 0,1,2 đã đóng
    now = T0 + 3 * MIN + 20_000                                # 20 giây sau đầu phút 3
    put_ticks([(T0 + 3 * MIN + 1000, 1, 670100, 1.5, False), (T0 + 3 * MIN + 5000, 2, 670120, 0.5, True),
               (T0 + 3 * MIN + 9000, 3, 670090, 1.0, False)])
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0, "to": now}).json()
    assert [b[0] for b in j["bars"]] == [T0, T0 + MIN, T0 + 2 * MIN, T0 + 3 * MIN]
    forming = j["bars"][-1]
    assert forming == [T0 + 3 * MIN, 67010.0, 67012.0, 67009.0, 67009.0, 3.0, 2.5, 0.5]


def test_larger_timeframe_includes_forming_minute_in_current_bucket(data_root):
    put_klines(kline_rows(5))
    put_ticks([(T0 + 5 * MIN + 100, 1, 670200, 1.0, False)])
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "5m", "from": T0, "to": T0 + 5 * MIN + 30_000}).json()
    assert [b[0] for b in j["bars"]] == [T0, T0 + 5 * MIN]
    assert j["bars"][1][5] == 1.0 and j["bars"][1][4] == 67020.0


def test_klines_take_priority_over_ticks_for_closed_minutes(data_root):
    put_klines(kline_rows(2))
    put_ticks([(T0 + 100, 1, 999999, 50.0, False)])          # tick của phút 0 (đã có kline) không được đếm thêm
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0, "to": T0 + 2 * MIN}).json()
    assert j["bars"][0][5] == 2.0 and j["bars"][0][2] == 67000.5


def test_sub_minute_timeframe_uses_ticks(data_root):
    put_ticks([(T0 + 100, 1, 670000, 1.0, False), (T0 + 600, 2, 670010, 2.0, True), (T0 + 1500, 3, 670020, 1.0, False)])
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1s", "from": T0, "to": T0 + 3000}).json()
    assert [b[0] for b in j["bars"]] == [T0, T0 + 1000]
    assert j["bars"][0][1:5] == [67000.0, 67001.0, 67000.0, 67001.0] and j["bars"][0][5:] == [3.0, 1.0, 2.0]


def test_limit_returns_the_most_recent_bars(data_root):
    put_klines(kline_rows(30))
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0, "to": T0 + 30 * MIN,
                                        "limit": 5}).json()
    assert [b[0] for b in j["bars"]] == [T0 + i * MIN for i in range(25, 30)]


def test_empty_range_and_unknown_data_return_empty_list(data_root):
    assert client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m"}).json()["bars"] == []
    assert client.get("/api/bars", params={"symbol": "XAUUSDT", "tf": "1h", "from": T0, "to": T0 + 3_600_000}).json()["bars"] == []


def test_errors(data_root):
    assert client.get("/api/bars", params={"symbol": "NOPE"}).status_code == 404
    assert client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "7x"}).status_code == 422
    assert client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "90s"}).status_code == 422
    assert client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": 10, "to": 5}).status_code == 422
    assert client.get("/api/bars", params={"symbol": "BTCUSDT", "limit": 0}).status_code == 422
    assert client.get("/api/bars", params={"symbol": "BTCUSDT", "limit": 99999}).status_code == 422
    assert client.get("/api/bars", params={"symbol": "../x"}).status_code in (404, 422)


def test_symbol_is_case_insensitive(data_root):
    put_klines(kline_rows(2))
    j = client.get("/api/bars", params={"symbol": "btcusdt", "tf": "1m", "from": T0, "to": T0 + 2 * MIN}).json()
    assert len(j["bars"]) == 2


def test_two_symbols_do_not_mix(data_root):
    put_klines(kline_rows(2))
    store.write_partition("bars", "XAUUSDT", DAY, kline_rows(2, base=388000))
    j = client.get("/api/bars", params={"symbol": "XAUUSDT", "tf": "1m", "from": T0, "to": T0 + 2 * MIN}).json()
    assert j["tick"] == 0.01 and j["bars"][0][1] == 3880.0


@pytest.mark.live
def test_live_real_data_directory_serves_recent_bars(monkeypatch):
    """Chạy trên kho dữ liệu thật trong .env: có nến, tăng dần, nến cuối là phút hiện tại hoặc gần đó."""
    from dotenv import dotenv_values
    monkeypatch.setenv("DATA_DIR", dotenv_values(store.ROOT / ".env")["DATA_DIR"])
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "limit": 120}).json()
    ts = [b[0] for b in j["bars"]]
    assert len(ts) > 100 and ts == sorted(ts) and len(set(ts)) == len(ts)
    assert time.time() * 1000 - ts[-1] < 5 * MIN


# ---------- đuôi lấy từ REST và last_trade_id ----------

def test_latest_request_adds_rest_trades_after_the_last_stored_tick(data_root, monkeypatch):
    put_klines(kline_rows(3))
    m3 = T0 + 3 * MIN
    put_ticks([(m3 + 1000, 10, 670100, 1.0, False), (m3 + 2000, 11, 670110, 2.0, True)])   # collector đã ghi tới id 11
    rest = [(12, m3 + 3000, 6712.0 * 10, 1.0, False), (13, m3 + 4000, 6705.0 * 10, 0.5, True)]
    monkeypatch.setattr(bars_api, "rest_client_factory", rest_serving(rest))
    monkeypatch.setattr(bars_api.time, "time", lambda: (m3 + 30_000) / 1000)
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0}).json()
    forming = j["bars"][-1]
    # mở 67010 (id 10), cao 67120 (REST id 12), thấp 67010... đóng 67050 (id 13)
    assert forming[0] == m3 and forming[1] == 67010.0 and forming[4] == 67050.0
    assert forming[2] == 67120.0 and forming[3] == 67010.0
    assert forming[5:] == [4.5, 2.0, 2.5]                            # v, mua chủ động, bán chủ động
    assert j["last_trade_id"] == 13
    assert REST_CALLS and REST_CALLS[0]["fromId"] == "12"          # chỉ xin phần sau tick đã lưu


def test_rest_trades_crossing_into_next_minute_open_a_new_bar(data_root, monkeypatch):
    put_klines(kline_rows(3))
    m3 = T0 + 3 * MIN
    put_ticks([(m3 + 59_000, 10, 670100, 1.0, False)])
    rest = [(11, m3 + 61_000, 6711.0 * 10, 2.0, True)]
    monkeypatch.setattr(bars_api, "rest_client_factory", rest_serving(rest))
    monkeypatch.setattr(bars_api.time, "time", lambda: (m3 + 62_000) / 1000)
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0}).json()
    assert [b[0] for b in j["bars"]][-2:] == [m3, m3 + MIN]
    assert j["bars"][-1][5] == 2.0 and j["last_trade_id"] == 11


def test_rest_failure_falls_back_to_stored_ticks(data_root, monkeypatch):
    put_klines(kline_rows(3))
    put_ticks([(T0 + 3 * MIN + 1000, 10, 670100, 1.0, False)])
    monkeypatch.setattr(bars_api, "rest_client_factory",
                        lambda: binance.make_client(httpx.MockTransport(lambda req: httpx.Response(400, text="lỗi"))))
    monkeypatch.setattr(bars_api.time, "time", lambda: (T0 + 3 * MIN + 30_000) / 1000)
    r = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0})
    assert r.status_code == 200 and r.json()["last_trade_id"] == 10 and r.json()["bars"][-1][5] == 1.0


def test_historical_request_never_calls_rest(data_root):
    put_klines(kline_rows(3))
    put_ticks([(T0 + 3 * MIN + 1000, 10, 670100, 1.0, False)])
    client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0, "to": T0 + 4 * MIN})
    assert REST_CALLS == []


def test_larger_timeframe_also_gets_the_rest_tail(data_root, monkeypatch):
    put_klines(kline_rows(5))
    put_ticks([(T0 + 5 * MIN + 1000, 10, 670100, 1.0, False)])
    monkeypatch.setattr(bars_api, "rest_client_factory", rest_serving([(11, T0 + 5 * MIN + 2000, 6720.0 * 10, 3.0, False)]))
    monkeypatch.setattr(bars_api.time, "time", lambda: (T0 + 5 * MIN + 30_000) / 1000)
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "5m", "from": T0}).json()
    assert j["bars"][-1][0] == T0 + 5 * MIN and j["bars"][-1][5] == 4.0 and j["bars"][-1][4] == 67200.0


def test_sub_minute_latest_gets_rest_tail_and_last_id(data_root, monkeypatch):
    put_ticks([(T0 + 100, 1, 670000, 1.0, False)])
    monkeypatch.setattr(bars_api, "rest_client_factory", rest_serving([(2, T0 + 400, 670010, 2.0, True)]))
    monkeypatch.setattr(bars_api.time, "time", lambda: (T0 + 900) / 1000)
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1s", "from": T0}).json()
    assert j["bars"][-1][5] == 3.0 and j["last_trade_id"] == 2


def test_no_stored_ticks_means_no_rest_call_and_null_last_id(data_root):
    put_klines(kline_rows(3))
    j = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1m", "from": T0}).json()
    assert j["last_trade_id"] is None and REST_CALLS == []


def test_merge_tail_helpers():
    from common import bars
    ticks = [(T0 + 10, 2, 105, 1.0, True), (T0 + 5, 1, 100, 2.0, False)]
    b = bars.bars_from_tick_rows(ticks, "1m")
    assert b == [(T0, 100, 105, 100, 105, 3.0, 2.0, 1.0)]
    assert bars.combine_bars((T0, 100, 110, 99, 105, 1.0, 1.0, 0.0), (T0, 106, 120, 104, 118, 2.0, 0.0, 2.0)) ==         (T0, 100, 120, 99, 118, 3.0, 1.0, 2.0)


def test_week_and_month_timeframes_use_calendar_boundaries(data_root):
    from datetime import datetime, timezone

    def ms(y, m, d, h=12):
        return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)
    # một nến 1 phút mỗi ngày từ 2026-10-26 (thứ Hai) tới 2026-11-10; giá = số ngày kể từ đầu
    days = []
    d0 = date(2026, 10, 26)
    for k in range(16):
        d = date.fromordinal(d0.toordinal() + k)
        t = ms(d.year, d.month, d.day)
        store.write_partition("bars", "BTCUSDT", d, [(t, 1000 + k * 10, 1005 + k * 10, 995 + k * 10, 1001 + k * 10, 2.0, 1.0, 1.0)])
        days.append(t)
    w = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1w", "from": ms(2026, 10, 26, 0), "to": ms(2026, 11, 11, 0)}).json()
    opens = [b[0] for b in w["bars"]]
    assert opens == [ms(2026, 10, 26, 0), ms(2026, 11, 2, 0), ms(2026, 11, 9, 0)]       # thứ Hai mỗi tuần
    first = w["bars"][0]
    assert first[5] == 14.0 and first[1] == 100.0 and first[4] == pytest.approx(100.0 + 6 * 1.0 + 0.1)   # 7 ngày: open ngày đầu, close ngày cuối
    mth = client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "1M", "from": ms(2026, 10, 1, 0), "to": ms(2026, 11, 11, 0)}).json()
    assert [b[0] for b in mth["bars"]] == [ms(2026, 10, 1, 0), ms(2026, 11, 1, 0)]
    assert mth["bars"][0][5] == 12.0 and mth["bars"][1][5] == 20.0          # 26-31/10 = 6 ngày, 1-10/11 = 10 ngày, mỗi ngày volume 2
    assert client.get("/api/bars", params={"symbol": "BTCUSDT", "tf": "2M"}).status_code == 422
    assert client.get("/api/footprint", params={"symbol": "BTCUSDT", "tf": "1w"}).status_code == 400
