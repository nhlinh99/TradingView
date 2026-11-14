import time
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from common import store
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
