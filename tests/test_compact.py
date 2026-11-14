import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import pytest

from collector import compact
from common import store

NOW = datetime(2026, 12, 25, 12, 0, tzinfo=timezone.utc)
OLD = date(2026, 10, 20)       # 66 ngày trước NOW: quá full_days=30 và raw_days=7
RECENT = date(2026, 12, 20)    # 5 ngày trước NOW: chưa tới hạn gom
BUCKET_TICKS = 10              # footprint_bucket 1.0 / tick 0.1


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def day_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def make_ticks(d: date, n=600, seed=3, id0=0):
    rng = random.Random(seed)
    base = day_ms(d) + 3_600_000
    rows = []
    for i in range(n):
        rows.append((base + i * 700 + rng.randint(0, 5), id0 + i, 670000 + rng.randint(0, 60),
                     rng.randint(1, 8) * 0.5, rng.random() < 0.5))
    return rows


def expected_footprint(rows):
    acc = defaultdict(lambda: [0.0, 0.0])
    for ts, _id, p, q, m in rows:
        key = (ts // 60000 * 60000, p // BUCKET_TICKS * BUCKET_TICKS)
        acc[key][1 if m else 0] += q
    return {k: tuple(v) for k, v in acc.items()}


def put_ticks(d, rows, part=None):
    store.write_partition("ticks", "BTCUSDT", d, rows, part=part)


def fp_rows():
    return {(r[0], r[1]): (r[2], r[3]) for r in store.read("footprint_1m", "BTCUSDT")}


def names(kind):
    f = store.data_dir() / kind / "BTCUSDT"
    return sorted(p.name for p in f.iterdir()) if f.exists() else []


# ---------- gộp ----------

def test_merge_old_days_only_and_dedupes(data_root):
    rows = make_ticks(RECENT)
    put_ticks(RECENT, rows[:400], part="a")
    put_ticks(RECENT, rows[300:], part="b")                       # trùng id 300..399
    today = NOW.date()
    put_ticks(today, make_ticks(today, 50), part="x")              # hôm nay: không đụng
    s = compact.compact_all(NOW)
    assert names("ticks") == [f"date={RECENT}.parquet", f"date={today}.px.parquet"]
    assert len(store.read("ticks", "BTCUSDT", start_ms=day_ms(RECENT), end_ms=day_ms(RECENT) + 86_400_000,
                          dedupe=False)) == len(rows)
    assert s["merged_files"] == 2


def test_day_that_just_ended_is_not_touched(data_root):
    yesterday = NOW.date() - timedelta(days=1)
    put_ticks(yesterday, make_ticks(yesterday, 20), part="a")
    put_ticks(yesterday, make_ticks(yesterday, 20, id0=100), part="b")
    just_after_midnight = datetime(NOW.year, NOW.month, NOW.day, 0, 5, tzinfo=timezone.utc)
    compact.compact_all(just_after_midnight)
    assert len(names("ticks")) == 2           # mới 5 phút sau nửa đêm
    compact.compact_all(datetime(NOW.year, NOW.month, NOW.day, 0, 16, tzinfo=timezone.utc))
    assert len(names("ticks")) == 1


# ---------- ticks -> footprint ----------

def test_old_ticks_become_footprint_with_matching_sums_and_ticks_deleted(data_root):
    rows = make_ticks(OLD)
    put_ticks(OLD, rows[:350], part="a")
    put_ticks(OLD, rows[350:], part="b")
    s = compact.compact_all(NOW)
    assert s["ticks_days_compacted"] == 1
    assert names("ticks") == []
    got, want = fp_rows(), expected_footprint(rows)
    assert got.keys() == want.keys()
    for k in want:
        assert got[k] == (pytest.approx(want[k][0], rel=1e-6), pytest.approx(want[k][1], rel=1e-6))
    # delta từng phút được giữ nguyên
    per_min = defaultdict(float)
    for (m, _p), (b, sl) in want.items():
        per_min[m] += b - sl
    got_min = defaultdict(float)
    for (m, _p), (b, sl) in got.items():
        got_min[m] += b - sl
    assert all(got_min[m] == pytest.approx(per_min[m], abs=1e-4) for m in per_min)
    assert all(p % BUCKET_TICKS == 0 for (_m, p) in got)


def test_recent_ticks_are_kept(data_root):
    put_ticks(RECENT, make_ticks(RECENT))
    compact.compact_all(NOW)
    assert names("ticks") == [f"date={RECENT}.parquet"] and names("footprint_1m") == []


def test_footprint_verification_failure_keeps_ticks(data_root, monkeypatch):
    put_ticks(OLD, make_ticks(OLD))
    real = compact._footprint_select

    def wrong(symbol, day):
        return real(symbol, day).replace("::FLOAT AS buy", " * 2 ::FLOAT AS buy")  # nhân đôi tổng mua

    monkeypatch.setattr(compact, "_footprint_select", wrong)
    with pytest.raises(RuntimeError, match="lệch"):
        compact.compact_all(NOW)
    assert names("ticks") == [f"date={OLD}.parquet"]
    assert names("footprint_1m") == []          # bản chưa kiểm tra không được giữ lại


def test_existing_footprint_with_new_ticks_is_skipped_with_warning(data_root):
    put_ticks(OLD, make_ticks(OLD))
    compact.compact_all(NOW)
    put_ticks(OLD, make_ticks(OLD, 10, seed=9, id0=5000), part="late")   # tick muộn cho ngày đã gom
    s = compact.compact_all(NOW)
    assert s["warnings"] == 1 and s["ticks_days_compacted"] == 0
    assert len(names("ticks")) == 1


def test_dry_run_changes_nothing(data_root):
    put_ticks(OLD, make_ticks(OLD, 100), part="a")
    put_ticks(OLD, make_ticks(OLD, 100, id0=500), part="b")
    before = names("ticks")
    compact.compact_all(NOW, dry_run=True)
    assert names("ticks") == before and names("footprint_1m") == []


def test_footprint_much_smaller_than_ticks(data_root):
    rows = make_ticks(OLD, n=20_000)
    put_ticks(OLD, rows)
    tick_bytes = sum(p.stat().st_size for p in (data_root / "ticks" / "BTCUSDT").iterdir())
    compact.compact_all(NOW)
    fp_bytes = sum(p.stat().st_size for p in (data_root / "footprint_1m" / "BTCUSDT").iterdir())
    assert fp_bytes < 0.5 * tick_bytes


# ---------- sổ lệnh ----------

def book_rows(d):
    base = day_ms(d) + 7_200_000
    rows = []
    for s in range(0, 180, 5):                  # 3 phút, mỗi 5 giây
        for p in (670000, 670010):
            rows.append((base + s * 1000, p, float(s + 1), float(200 - s)))
    return rows


def test_book_older_than_raw_days_becomes_1m_max(data_root):
    rows = book_rows(OLD)
    store.write_partition("book", "BTCUSDT", OLD, rows, part="a")
    s = compact.compact_all(NOW)
    assert s["book_days_compacted"] == 1 and names("book") == []
    out = {(r[0], r[1]): (r[2], r[3]) for r in store.read("book_1m", "BTCUSDT")}
    want = {}
    for ts, p, bid, ask in rows:
        k = (ts // 60000 * 60000, p)
        b, a = want.get(k, (0.0, 0.0))
        want[k] = (max(b, bid), max(a, ask))
    assert out == want


def test_recent_book_is_kept(data_root):
    store.write_partition("book", "BTCUSDT", RECENT, book_rows(RECENT))
    compact.compact_all(NOW)
    assert names("book") == [f"date={RECENT}.parquet"] and names("book_1m") == []


def test_book_1m_older_than_agg_days_is_deleted(data_root):
    ancient = NOW.date() - timedelta(days=200)
    store.write_partition("book_1m", "BTCUSDT", ancient, [(day_ms(ancient), 1, 1.0, 1.0)])
    keep = NOW.date() - timedelta(days=100)
    store.write_partition("book_1m", "BTCUSDT", keep, [(day_ms(keep), 1, 1.0, 1.0)])
    s = compact.compact_all(NOW)
    assert s["old_book_1m_deleted"] == 1
    assert names("book_1m") == [f"date={keep}.parquet"]


# ---------- trần dung lượng ----------

def test_limit_deletes_book_1m_first_then_ticks_with_footprint_only(data_root, monkeypatch):
    d1, d2 = date(2026, 12, 1), date(2026, 12, 2)
    store.write_partition("book_1m", "BTCUSDT", d1, [(day_ms(d1) + i, i, 1.0, 1.0) for i in range(20_000)])
    put_ticks(d1, make_ticks(d1, 5000))
    store.write_partition("footprint_1m", "BTCUSDT", d1, [(day_ms(d1), 670000, 1.0, 1.0)])   # d1 đã có footprint
    put_ticks(d2, make_ticks(d2, 5000, id0=10_000))                                           # d2 chưa có
    cfg = compact.load_retention()
    cfg["limits"]["max_data_gb"] = 1e-9                                                       # ~1 byte
    monkeypatch.setattr(compact, "load_retention", lambda: cfg)
    s = compact.compact_all(NOW)
    assert names("book_1m") == []
    assert names("ticks") == [f"date={d2}.parquet"]     # tick d1 bị xoá, d2 được giữ vì chưa có footprint
    assert s["limit_deleted_files"] == 2 and s["warnings"] == 1


def test_under_limit_deletes_nothing(data_root):
    put_ticks(RECENT, make_ticks(RECENT))
    s = compact.compact_all(NOW)
    assert s["limit_deleted_files"] == 0


def test_merge_hot_merges_todays_parts_and_keeps_new_ones(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from collector import compact
    from common import store
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    day = now.date()
    t0 = int(datetime(2026, 11, 14, tzinfo=timezone.utc).timestamp() * 1000)
    for i in range(45):
        store.write_partition("ticks", "BTCUSDT", day, [(t0 + i * 1000, 100 + i, 670000 + i, 1.0, False)], part=f"p{100 + i}")
    store.write_partition("ticks", "XAUUSDT", day, [(t0, 1, 38000, 1.0, True)], part="p1")      # ít file: không động tới
    before = store.read("ticks", "BTCUSDT")
    assert compact.merge_hot(now, min_files=40) == 45
    files = store.day_files("ticks", "BTCUSDT", day)
    assert files == [store.partition_path("ticks", "BTCUSDT", day)]
    assert store.read("ticks", "BTCUSDT") == before                                              # dữ liệu y nguyên
    assert len(store.day_files("ticks", "XAUUSDT", day)) == 1 and not store.day_files("ticks", "XAUUSDT", day)[0].name.endswith("date=2026-11-14.parquet")
    # collector ghi thêm file con sau khi gộp: lần sau gộp tiếp, không mất dòng nào
    store.write_partition("ticks", "BTCUSDT", day, [(t0 + 99_000, 999, 670999, 2.0, True)], part="p999")
    assert compact.merge_hot(now, min_files=2) == 2
    assert len(store.read("ticks", "BTCUSDT")) == 46
