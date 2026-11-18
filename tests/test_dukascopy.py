import lzma
import struct
from datetime import date, datetime, timezone

import httpx
import pytest

from collector import dukascopy
from common import store

DAY = 86_400_000


def blob(rows):
    return lzma.compress(b"".join(struct.pack(">iiiiif", t, round(o * 1000), round(c * 1000), round(lo * 1000), round(h * 1000), v)
                                   for t, o, h, lo, c, v in rows))


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))
    return tmp_path


def test_parse_maps_field_order_and_skips_filler(data_root):
    # file: giây, open, close, low, high, volume; nến 2 không có giao dịch
    b = blob([(0, 100.0, 101.0, 99.5, 100.5, 3.0), (60, 100.5, 100.5, 100.5, 100.5, 0.0), (120, 100.5, 102.0, 100.0, 101.0, 1.5)])
    rows = dukascopy.parse_candles(b, date(2026, 10, 21))
    base = int(datetime(2026, 10, 21, tzinfo=timezone.utc).timestamp() * 1000)
    assert rows == [(base, 100.0, 101.0, 99.5, 100.5, 3.0), (base + 120_000, 100.5, 102.0, 100.0, 101.0, 1.5)]


def test_empty_and_404_days_are_skipped(data_root):
    for resp in (httpx.Response(200, content=b""), httpx.Response(404)):
        c = dukascopy.make_client(httpx.MockTransport(lambda r, resp=resp: resp))
        assert dukascopy.fetch_day(c, date(2026, 10, 24)) == []


def test_url_month_is_zero_based(data_root):
    seen = []
    c = dukascopy.make_client(httpx.MockTransport(lambda r: seen.append(str(r.url)) or httpx.Response(404)))
    dukascopy.fetch_day(c, date(2026, 10, 21))
    assert seen[0].endswith("/XAUUSD/2026/09/21/BID_candles_min_1.bi5") and seen[0].startswith("http://")


def test_calibrate_matches_price_and_volume(data_root):
    base = 1_000_000 * 60_000
    duka = [(base + i * 60_000, 100.0, 101.0, 99.0, 100.0, 2.0) for i in range(150)]
    tv = [(base + i * 60_000, store.to_int_price("XAUUSD", 100.2), 0, 0, store.to_int_price("XAUUSD", 100.2), 200.0, 0.0, 0.0) for i in range(150)]
    off, scale = dukascopy.calibrate(duka, tv)
    assert off == pytest.approx(0.2, abs=1e-9) and scale == pytest.approx(100.0)
    assert dukascopy.calibrate(duka[:10], tv[:10]) == (0.0, 1.0)


def test_sync_writes_only_days_before_tvc(data_root):
    first = date(2026, 11, 9)
    t0 = int(datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp() * 1000)
    p = lambda x: store.to_int_price("XAUUSD", x)   # noqa: E731
    store.write_partition("bars", "XAUUSD", first, [(t0 + i * 60_000, p(100), p(101), p(99), p(100), 1.0, 0.0, 0.0) for i in range(5)])

    def handler(req):
        return httpx.Response(200, content=blob([(0, 90.0, 91.0, 89.0, 90.5, 1.0), (60, 90.5, 92.0, 90.0, 91.0, 2.0)]))
    c = dukascopy.make_client(httpx.MockTransport(handler))
    r = dukascopy.sync(days=2, client=c, pause=0)
    assert r["days"] == 2 and r["to"] == "2026-11-08"
    days = store.list_days("bars", "XAUUSD")
    assert days[-1] == first and all(d <= first for d in days)
    assert len(store.read("bars", "XAUUSD", start_ms=t0, end_ms=t0 + DAY)) == 5      # ngày TVC không bị đụng


def test_throttle_waits_then_retries(data_root):
    calls, waits = [], []

    def handler(req):
        calls.append(1)
        return httpx.Response(301) if len(calls) < 3 else httpx.Response(200, content=blob([(0, 90.0, 91.0, 89.0, 90.5, 1.0)]))
    c = dukascopy.make_client(httpx.MockTransport(handler))
    rows = dukascopy.fetch_day_patient(c, date(2026, 10, 21), wait=5, sleep=waits.append)
    assert len(rows) == 1 and waits == [5]   # 301 đầu: IP gốc rồi tên miền; 301 thứ hai mới tính là bị chặn
    c2 = dukascopy.make_client(httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(dukascopy.Throttled):
        dukascopy.fetch_day_patient(c2, date(2026, 10, 21), wait=0, sleep=lambda s: None, tries=2)
