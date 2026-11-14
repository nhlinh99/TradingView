import random
from datetime import date
from pathlib import Path

import pytest

from common import appdb, store

DAY = date(2026, 11, 10)
BASE_TS = 1_794_000_000_000


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def make_ticks(n=1000, seed=1):
    rng = random.Random(seed)
    # q là bội của 0,5 nên float32 biểu diễn chính xác
    rows = [(BASE_TS + i, 670_000 + (i % 500), (i % 7) * 0.5, i % 2 == 0) for i in range(n)]
    rng.shuffle(rows)
    return rows


def test_roundtrip_1000_rows_match_and_sorted(data_root):
    rows = make_ticks()
    store.write_partition("ticks", "BTCUSDT", DAY, rows)
    back = store.read("ticks", "BTCUSDT")
    assert back == sorted(rows, key=lambda r: r[0])
    assert len(back) == 1000


def test_no_tmp_file_left_after_write(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(10))
    names = [p.name for p in (data_root / "ticks" / "BTCUSDT").iterdir()]
    assert names == ["date=2026-11-10.parquet"]


def test_failed_write_leaves_no_file(data_root):
    bad = [(BASE_TS, 1, 1.0)]  # thiếu cột m
    with pytest.raises(ValueError):
        store.write_partition("ticks", "BTCUSDT", DAY, bad)
    folder = data_root / "ticks" / "BTCUSDT"
    assert not folder.exists() or list(folder.iterdir()) == []


def test_failed_write_keeps_previous_file(data_root):
    good = make_ticks(5)
    store.write_partition("ticks", "BTCUSDT", DAY, good)
    with pytest.raises(ValueError):
        store.write_partition("ticks", "BTCUSDT", DAY, [(1, 2)])
    assert store.read("ticks", "BTCUSDT") == sorted(good, key=lambda r: r[0])


def test_rewrite_replaces_file(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(10))
    new = make_ticks(3, seed=2)
    store.write_partition("ticks", "BTCUSDT", DAY, new)
    assert len(store.read("ticks", "BTCUSDT")) == 3


def test_time_range_filter(data_root):
    rows = make_ticks(100)
    store.write_partition("ticks", "BTCUSDT", DAY, rows)
    got = store.read("ticks", "BTCUSDT", start_ms=BASE_TS + 10, end_ms=BASE_TS + 20)
    assert [r[0] for r in got] == list(range(BASE_TS + 10, BASE_TS + 20))


def test_parts_are_read_together(data_root):
    store.write_partition("ticks", "BTCUSDT", DAY, make_ticks(10), part=1)
    later = [(BASE_TS + 1000 + i, 1, 1.0, True) for i in range(5)]
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
    sql = "SELECT (1700000000000 + i)::BIGINT, 5::INTEGER, 1.5::FLOAT, true FROM range(50000) r(i)"
    store.write_partition("ticks", "BTCUSDT", DAY, sql)
    assert len(store.read("ticks", "BTCUSDT")) == 50_000


def test_symbol_path_traversal_rejected(data_root):
    with pytest.raises(ValueError):
        store.partition_path("ticks", "../evil", DAY)
    with pytest.raises(ValueError):
        store.partition_path("ticks", "a/b", DAY)


def test_unknown_kind_rejected(data_root):
    with pytest.raises(KeyError):
        store.partition_path("nope", "BTCUSDT", DAY)


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
    import os
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
