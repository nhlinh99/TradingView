import hashlib
import io
import zipfile
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from collector import backfill
from common import appdb, store

DAY = date(2026, 11, 10)
DAY_START = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp() * 1000)

AGG_HEADER = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def agg_csv(header=True, n=5, ts0=DAY_START + 1000, id0=100):
    rows = "".join(
        f"{id0 + i},{67000.1 + i * 0.1:.1f},{0.5 + i * 0.5},{id0 + i},{id0 + i},{ts0 + i},{'true' if i % 2 == 0 else 'false'}\n"
        for i in range(n)
    )
    return (AGG_HEADER if header else "") + rows


def make_zip(csv_text: str, name="x.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, csv_text)
    return buf.getvalue()


def server(files: dict[str, bytes], checksum_override=None):
    """files: đường dẫn zip -> nội dung. Phục vụ cả .CHECKSUM."""
    def handler(req: httpx.Request):
        path = req.url.path
        if path.endswith(".CHECKSUM"):
            z = files.get(path[: -len(".CHECKSUM")])
            if z is None:
                return httpx.Response(404)
            digest = checksum_override or hashlib.sha256(z).hexdigest()
            return httpx.Response(200, text=f"{digest}  {path.rsplit('/', 1)[-1][:-9]}\n")
        if path in files:
            return httpx.Response(200, content=files[path])
        return httpx.Response(404)
    return backfill.make_client(httpx.MockTransport(handler))


def agg_path(day=DAY, symbol="BTCUSDT"):
    return backfill.file_path("aggTrades", symbol, day)


def test_file_path_matches_binance_layout():
    assert agg_path() == "/data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-11-10.zip"


def test_ok_with_header_converts_to_ticks(data_root):
    c = server({agg_path(): make_zip(agg_csv())})
    assert backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY) == "ok"
    rows = store.read("ticks", "BTCUSDT")
    assert len(rows) == 5
    ts, id_, p, q, m = rows[0]
    assert (ts, id_, p, q, m) == (DAY_START + 1000, 100, 670001, 0.5, True)
    assert [r[1] for r in rows] == [100, 101, 102, 103, 104]


def test_ok_without_header(data_root):
    c = server({agg_path(): make_zip(agg_csv(header=False))})
    assert backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY) == "ok"
    assert len(store.read("ticks", "BTCUSDT")) == 5


def test_checksum_mismatch_raises_and_writes_nothing(data_root):
    c = server({agg_path(): make_zip(agg_csv())}, checksum_override="0" * 64)
    with pytest.raises(backfill.ChecksumError):
        backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY)
    assert store.read("ticks", "BTCUSDT") == []
    assert list((data_root / "cache").iterdir()) == []  # đã dọn file tạm


def test_malformed_checksum_file(data_root):
    c = server({agg_path(): make_zip(agg_csv())}, checksum_override="zz")
    with pytest.raises(backfill.ChecksumError):
        backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY)


def test_missing_file_reports_missing(data_root):
    assert backfill.backfill_day(server({}), "aggTrades", "BTCUSDT", DAY) == "missing"
    assert store.read("ticks", "BTCUSDT") == []


def test_rerun_is_skipped_and_force_reloads(data_root):
    c = server({agg_path(): make_zip(agg_csv())})
    assert backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY) == "ok"
    assert backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY) == "skipped"
    assert backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY, force=True) == "ok"
    assert len(store.read("ticks", "BTCUSDT")) == 5
    con = appdb.connect()
    try:
        assert con.execute("SELECT count(*) FROM backfill_log").fetchone()[0] == 1
    finally:
        con.close()


def test_timestamps_outside_day_are_rejected(data_root):
    # micro giây thay vì mili giây: Binance từng đổi đơn vị ở một số kho
    bad = agg_csv(ts0=(DAY_START + 1000) * 1000)
    c = server({agg_path(): make_zip(bad)})
    with pytest.raises(backfill.BackfillError, match="ngoài ngày UTC"):
        backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY)
    assert store.read("ticks", "BTCUSDT") == []


def test_wrong_day_file_is_rejected(data_root):
    prev = agg_csv(ts0=DAY_START - 5000)  # dữ liệu của ngày hôm trước đặt nhầm vào file ngày này
    c = server({agg_path(): make_zip(prev)})
    with pytest.raises(backfill.BackfillError):
        backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY)


def test_empty_file_rejected(data_root):
    c = server({agg_path(): make_zip(AGG_HEADER)})
    with pytest.raises(backfill.BackfillError, match="rỗng"):
        backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY)


def test_zip_must_contain_one_csv(data_root):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", agg_csv())
        z.writestr("b.csv", agg_csv())
    c = server({agg_path(): buf.getvalue()})
    with pytest.raises(backfill.BackfillError, match="đúng 1"):
        backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY)


def test_bookdepth_conversion(data_root):
    csv = (
        "timestamp,percentage,depth,notional\n"
        "2026-11-10 00:00:01,-5.00,8864.407,654377433.3077\n"
        "2026-11-10 00:00:01,5.00,6546.67,499469325.7057\n"
        "2026-11-10 00:00:31,-0.20,690.167,51920669.1835\n"
    )
    p = backfill.file_path("bookDepth", "BTCUSDT", DAY)
    c = server({p: make_zip(csv)})
    assert backfill.backfill_day(c, "bookDepth", "BTCUSDT", DAY) == "ok"
    rows = store.read("bookdepth", "BTCUSDT")
    assert len(rows) == 3
    assert rows[0][0] == DAY_START + 1000 and rows[0][1] == -5.0
    assert rows[-1][0] == DAY_START + 31_000


def test_metrics_conversion_with_missing_values(data_root):
    csv = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
        "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
        "2026-11-10 00:05:00,BTCUSDT,98691.693,7389698420.08,3.15,2.34,2.80,1.57\n"
        "2026-11-10 00:10:00,BTCUSDT,98700.0,7390000000.0,,,,\n"
    )
    p = backfill.file_path("metrics", "BTCUSDT", DAY)
    c = server({p: make_zip(csv)})
    assert backfill.backfill_day(c, "metrics", "BTCUSDT", DAY) == "ok"
    rows = store.read("metrics", "BTCUSDT")
    assert len(rows) == 2 and rows[0][1] == pytest.approx(98691.693)
    assert rows[1][3] is None


def test_backfill_range_skips_today_and_future(data_root):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=2)
    files = {}
    for i in range(2, 0, -1):
        d = today - timedelta(days=i)
        ds = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
        files[agg_path(d)] = make_zip(agg_csv(ts0=ds + 1000, id0=i * 1000))
    stats = backfill.backfill("BTCUSDT", "aggTrades", start, today + timedelta(days=5), client=server(files))
    assert stats["ok"] == 2 and stats["missing"] == 0
    assert [d for d, _ in stats["days"]] == [(today - timedelta(days=2)).isoformat(), (today - timedelta(days=1)).isoformat()]


def test_download_error_other_than_404(data_root):
    def handler(req):
        return httpx.Response(500)
    c = backfill.make_client(httpx.MockTransport(handler))
    with pytest.raises(backfill.BackfillError):
        backfill.backfill_day(c, "aggTrades", "BTCUSDT", DAY)


@pytest.mark.live
def test_live_three_days_btc_and_checksums(data_root):
    """Nghiệm thu: tải thật 3 ngày, checksum khớp, đủ số dòng."""
    end = datetime.now(timezone.utc).date() - timedelta(days=2)
    stats = backfill.backfill("BTCUSDT", "aggTrades", end - timedelta(days=2), end)
    assert stats["ok"] == 3, stats
    rows = store.read("ticks", "BTCUSDT", columns=["id"])
    assert len(rows) > 1_000_000
    ids = [r[0] for r in rows]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
