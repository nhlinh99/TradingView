import os
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from common import appdb, store

DAY = date(2026, 11, 10)
BASE_TS = 1_794_268_800_000  # 00:00 UTC ngày DAY (10/11/2026)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def make_ticks(n=1000, seed=1, id0=0):
    rng = random.Random(seed)
    # q là bội của 0,5 nên float32 biểu diễn chính xác. Cột: ts, id, p, q, m
    rows = [(BASE_TS + i, id0 + i, 670_000 + (i % 500), (i % 7) * 0.5, i % 2 == 0) for i in range(n)]
    rng.shuffle(rows)
    return rows


def by_key(rows):
    return sorted(rows, key=lambda r: (r[0], r[1]))


def test_roundtrip_1000_rows_match_and_sorted(data_root):
    rows = make_ticks()
    store.write_partition("ticks", "BTCUSDT", DAY, rows)
    back = store.read("ticks", "BTCUSDT")
    assert back == by_key(rows)
    assert len(back) == 1000


def test_no_tmp_file_left_after_write(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(10))
    names = [p.name for p in (data_root / "ticks" / "BTCUSDT").iterdir()]
    assert names == ["date=2026-11-10.parquet"]


def test_failed_write_leaves_no_file(data_root):
    bad = [(BASE_TS, 1, 1, 1.0)]  # thiếu cột m
    with pytest.raises(ValueError):
        store.write_partition("ticks", "BTCUSDT", DAY, bad)
    folder = data_root / "ticks" / "BTCUSDT"
    assert not folder.exists() or list(folder.iterdir()) == []


def test_failed_write_keeps_previous_file(data_root):
    good = make_ticks(5)
    store.write_partition("ticks", "BTCUSDT", DAY, good)
    with pytest.raises(ValueError):
        store.write_partition("ticks", "BTCUSDT", DAY, [(1, 2)])
    assert store.read("ticks", "BTCUSDT") == by_key(good)


def test_rewrite_replaces_file(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(10))
    new = make_ticks(3, seed=2)
    store.write_partition("ticks", "BTCUSDT", DAY, new)
    assert len(store.read("ticks", "BTCUSDT")) == 3


def test_time_range_filter(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(100))
    got = store.read("ticks", "BTCUSDT", start_ms=BASE_TS + 10, end_ms=BASE_TS + 20)
    assert [r[0] for r in got] == list(range(BASE_TS + 10, BASE_TS + 20))


def test_parts_are_read_together(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(10), part=1)
    later = [(BASE_TS + 1000 + i, 1000 + i, 1, 1.0, True) for i in range(5)]
    store.write_partition("ticks", "BTCUSDT", DAY, later, part=2)
    got = store.read("ticks", "BTCUSDT")
    assert len(got) == 15
    assert [r[0] for r in got] == sorted(r[0] for r in got)


def test_read_missing_symbol_returns_empty(data_root):
    assert store.read("ticks", "ETHUSDT") == []


def test_read_selected_columns(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(5))
    got = store.read("ticks", "BTCUSDT", columns=["ts", "p"])
    assert all(len(r) == 2 for r in got)
    with pytest.raises(KeyError):
        store.read("ticks", "BTCUSDT", columns=["nope"])


def test_bulk_write_from_sql(data_root):
    sql = "SELECT (1794268800000 + i)::BIGINT, i::BIGINT, 5::INTEGER, 1.5::FLOAT, true FROM range(50000) r(i)"
    store.write_partition("ticks", "BTCUSDT", DAY, sql)
    assert len(store.read("ticks", "BTCUSDT")) == 50_000


def test_symbol_path_traversal_rejected(data_root):
    with pytest.raises(ValueError):
        store.partition_path("ticks", "../evil", DAY)
    with pytest.raises(ValueError):
        store.partition_path("ticks", "a/b", DAY)


def test_part_name_validated(data_root):
    with pytest.raises(ValueError):
        store.partition_path("ticks", "BTCUSDT", DAY, part="../x")
    assert store.partition_path("ticks", "BTCUSDT", DAY, part="123456").name == "date=2026-11-10.p123456.parquet"
    assert store.partition_path("ticks", "BTCUSDT", DAY, part=3).name == "date=2026-11-10.p0003.parquet"


def test_unknown_kind_rejected(data_root):
    with pytest.raises(KeyError):
        store.partition_path("nope", "BTCUSDT", DAY)


# ---------- trùng lặp và gộp ----------

def test_two_collector_runs_same_day_keep_all_rows(data_root):
    """Hai lần chạy collector cùng một ngày không ghi đè file của nhau (part theo id đầu tiên)."""
    run1 = make_ticks(100, id0=0)
    run2 = make_ticks(100, id0=1000)
    store.write_partition("ticks", "BTCUSDT", DAY, run1, part=str(min(r[1] for r in run1)))
    store.write_partition("ticks", "BTCUSDT", DAY, run2, part=str(min(r[1] for r in run2)))
    assert len(store.read("ticks", "BTCUSDT")) == 200


def test_read_dedupes_overlap_between_backfill_and_parts(data_root):
    full = make_ticks(100)                      # backfill cả ngày: id 0..99
    store.write_partition("ticks", "BTCUSDT", DAY, full)
    live = [r for r in make_ticks(100) if r[1] >= 90]  # collector trùng id 90..99
    store.write_partition("ticks", "BTCUSDT", DAY, live, part="90")
    assert len(store.read("ticks", "BTCUSDT")) == 100
    assert len(store.read("ticks", "BTCUSDT", dedupe=False)) == 110


def test_merge_day_dedupes_and_removes_parts(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(100))
    live = [r for r in make_ticks(100) if r[1] >= 90] + [(BASE_TS + 500, 500, 1, 1.0, True)]
    store.write_partition("ticks", "BTCUSDT", DAY, live, part="90")
    out = store.merge_day("ticks", "BTCUSDT", DAY)
    assert out == store.partition_path("ticks", "BTCUSDT", DAY)
    names = sorted(p.name for p in (data_root / "ticks" / "BTCUSDT").iterdir())
    assert names == ["date=2026-11-10.parquet"]
    rows = store.read("ticks", "BTCUSDT", dedupe=False)
    assert len(rows) == 101 and len({r[1] for r in rows}) == 101


def test_merge_day_without_canonical_file(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(10, id0=0), part="0")
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(10, id0=10), part="10")
    store.merge_day("ticks", "BTCUSDT", DAY)
    assert [p.name for p in (data_root / "ticks" / "BTCUSDT").iterdir()] == ["date=2026-11-10.parquet"]
    assert len(store.read("ticks", "BTCUSDT", dedupe=False)) == 20


def test_merge_day_noop_cases(data_root):
    assert store.merge_day("ticks", "BTCUSDT", DAY) is None
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(5))
    before = (data_root / "ticks" / "BTCUSDT" / "date=2026-11-10.parquet").stat().st_mtime_ns
    store.merge_day("ticks", "BTCUSDT", DAY)
    assert (data_root / "ticks" / "BTCUSDT" / "date=2026-11-10.parquet").stat().st_mtime_ns == before


def test_merge_does_not_touch_other_days(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(5), part="a")
    other = date(2026, 11, 11)
    next_day_rows = [(BASE_TS + 86_400_000 + i, 100 + i, 1, 1.0, True) for i in range(5)]
    store.write_partition("ticks", "BTCUSDT", other, next_day_rows, part="b")
    store.merge_day("ticks", "BTCUSDT", DAY)
    names = sorted(p.name for p in (data_root / "ticks" / "BTCUSDT").iterdir())
    assert names == ["date=2026-11-10.parquet", "date=2026-11-11.pb.parquet"]


def test_bars_dedupe_by_ts_and_book_by_ts_and_price(data_root):
    bar = (BASE_TS, 1, 2, 1, 2, 3.0, 1.0, 2.0)
    store.write_partition("bars", "BTCUSDT", DAY, [bar], part="a")
    store.write_partition("bars", "BTCUSDT", DAY, [bar, (BASE_TS + 60000, 2, 3, 2, 3, 1.0, 1.0, 0.0)], part="b")
    assert len(store.read("bars", "BTCUSDT")) == 2
    b1 = (BASE_TS, 100, 1.0, 2.0)
    b2 = (BASE_TS, 101, 1.0, 2.0)
    store.write_partition("book", "BTCUSDT", DAY, [b1, b2], part="a")
    store.write_partition("book", "BTCUSDT", DAY, [b1], part="b")
    assert len(store.read("book", "BTCUSDT")) == 2


# ---------- Windows khoá file ----------

def test_replace_retries_on_permission_error(data_root, monkeypatch):
    calls = {"n": 0}
    real = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("file đang được mở")
        return real(src, dst)

    monkeypatch.setattr(store.os, "replace", flaky)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(5))
    assert calls["n"] == 3
    assert len(store.read("ticks", "BTCUSDT")) == 5


def test_replace_gives_up_after_many_failures(data_root, monkeypatch):
    def always(src, dst):
        raise PermissionError("khoá")

    monkeypatch.setattr(store.os, "replace", always)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(5))
    assert [p for p in (data_root / "ticks" / "BTCUSDT").iterdir()] == []  # không còn file tạm


# ---------- DATA_DIR ----------

def test_data_dir_rejects_onedrive_path(monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(Path.home() / "OneDrive" / "Desktop" / "x"))
    with pytest.raises(store.DataDirError):
        store.data_dir()


def test_data_dir_rejects_onedrive_env_var(monkeypatch, tmp_path):
    fake = tmp_path / "OD"
    monkeypatch.setenv("OneDrive", str(fake))
    monkeypatch.setenv("DATA_DIR", str(fake / "data"))
    with pytest.raises(store.DataDirError):
        store.data_dir()


def test_data_dir_rejects_relative_and_missing(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "relative/path")
    with pytest.raises(store.DataDirError):
        store.data_dir()
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(store, "load_dotenv", lambda *a, **k: None)
    with pytest.raises(store.DataDirError):
        store.data_dir()


def test_real_env_data_dir_is_outside_onedrive():
    """Cấu hình thật trong .env phải hợp lệ (nghiệm thu Phase 0)."""
    from dotenv import dotenv_values

    values = dotenv_values(store.ROOT / ".env")
    assert "DATA_DIR" in values, ".env thiếu DATA_DIR"
    old = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = values["DATA_DIR"]
    try:
        root = store.data_dir()
    finally:
        if old is None:
            os.environ.pop("DATA_DIR")
        else:
            os.environ["DATA_DIR"] = old
    assert "onedrive" not in str(root).lower()


# ---------- giá số nguyên ----------

def test_price_roundtrip_btc_and_xau():
    assert store.to_int_price("BTCUSDT", 67244.4) == 672444
    assert store.from_int_price("BTCUSDT", 672444) == 67244.4
    assert store.to_int_price("XAUUSDT", 3885.56) == 388556
    assert store.from_int_price("XAUUSDT", 388556) == 3885.56


def test_price_overflow_detected():
    with pytest.raises(OverflowError):
        store.to_int_price("XAUUSDT", 50_000_000.0)


def test_unknown_symbol_config():
    with pytest.raises(KeyError):
        store.to_int_price("NOPE", 1.0)


# ---------- SQLite ----------

def test_appdb_init_creates_tables(data_root):
    path = appdb.init()
    assert path.exists()
    con = appdb.connect()
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    assert {"watchlist", "layouts", "drawings", "alerts"} <= tables
    appdb.init()  # chạy lại không lỗi


# ---------- ts phải nằm trong ngày của file ----------

def test_write_rejects_rows_outside_the_files_day(data_root):
    inside = (BASE_TS + 5, 1, 1, 1.0, True)
    next_day = (BASE_TS + 86_400_000, 2, 1, 1.0, True)
    before = (BASE_TS - 1, 3, 1, 1.0, True)
    for bad in (next_day, before):
        with pytest.raises(ValueError, match="ngoài ngày UTC"):
            store.write_partition("ticks", "BTCUSDT", DAY, [inside, bad])
    assert not (data_root / "ticks" / "BTCUSDT").exists() or list((data_root / "ticks" / "BTCUSDT").iterdir()) == []
    store.write_partition("ticks", "BTCUSDT", DAY, [inside, (BASE_TS + 86_400_000 - 1, 4, 1, 1.0, True)])  # đúng biên


def test_range_read_only_touches_days_in_range(data_root):
    d1, d2, d3 = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)
    day = 86_400_000
    # mỗi ngày 5 tick ở đầu ngày, ngày 10 có thêm 3 tick cuối ngày
    store.write_partition("ticks", "BTCUSDT", d1, [(BASE_TS - day + k, k, 1, 1.0, True) for k in range(5)])
    store.write_partition("ticks", "BTCUSDT", d2, [(BASE_TS + k, 100 + k, 1, 1.0, True) for k in range(5)]
                          + [(BASE_TS + day - 3 + k, 150 + k, 1, 1.0, True) for k in range(3)])
    store.write_partition("ticks", "BTCUSDT", d3, [(BASE_TS + day + k, 200 + k, 1, 1.0, True) for k in range(5)])
    # trong một ngày
    assert [r[1] for r in store.read("ticks", "BTCUSDT", BASE_TS, BASE_TS + 3)] == [100, 101, 102]
    # bắc qua nửa đêm: lấy từ hai file
    got = store.read("ticks", "BTCUSDT", BASE_TS + day - 2, BASE_TS + day + 2)
    assert [r[1] for r in got] == [151, 152, 200, 201]
    # ngoài mọi file
    assert store.read("ticks", "BTCUSDT", BASE_TS + 10 * day, BASE_TS + 11 * day) == []
    # không giới hạn: đọc hết
    assert len(store.read("ticks", "BTCUSDT")) == 5 + 8 + 5


def test_range_read_dedupes_within_range(data_root):
    rows = [(BASE_TS + i, i, 1, 1.0, True) for i in range(10)]
    store.write_partition("ticks", "BTCUSDT", DAY, rows)
    store.write_partition("ticks", "BTCUSDT", DAY, rows[4:], part="live")
    assert len(store.read("ticks", "BTCUSDT", BASE_TS + 2, BASE_TS + 8)) == 6


def test_range_select_dedupes_only_days_with_parts(data_root):
    """Ngày chỉ có file chuẩn đọc thẳng (không tốn cửa sổ loại trùng); ngày còn file con vẫn được loại trùng."""
    day = 86_400_000
    old = [(BASE_TS - day + i, i, 1, 1.0, True) for i in range(5)]
    new = [(BASE_TS + i, 100 + i, 1, 1.0, True) for i in range(10)]
    store.write_partition("ticks", "BTCUSDT", DAY - timedelta(days=1), old)
    assert "row_number" not in store.range_select("ticks", "BTCUSDT")
    store.write_partition("ticks", "BTCUSDT", DAY, new)
    store.write_partition("ticks", "BTCUSDT", DAY, new[4:], part="live")
    assert len(store.read("ticks", "BTCUSDT")) == 5 + 10