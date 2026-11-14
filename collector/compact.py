"""Gom nén và giữ dữ liệu theo config/retention.toml. Chạy mỗi đêm (Task Scheduler, xem README).

Chạy:  python -m collector.compact [--dry-run] [--symbol BTCUSDT]

Các bước cho mỗi symbol:
  1. Gộp file con của các ngày đã qua thành một file chuẩn mỗi ngày, loại dòng trùng khoá
     (backfill chồng collector trực tiếp). Không đụng ngày hôm nay và 15 phút đầu của ngày mới.
  2. ticks quá `ticks.full_days` ngày -> footprint_1m (bucket giá theo `footprint_bucket`).
     Chỉ xoá tick sau khi KIỂM TRA: tổng mua và tổng bán từng phút của footprint bằng của tick
     (sai số tương đối < 1e-5, chỉ do float32).
  3. book quá `book.raw_days` ngày -> book_1m (giá trị lớn nhất mỗi bucket trong phút). Kiểm tra rồi mới xoá.
  4. book_1m quá `book.agg_days` ngày: xoá.
  5. Nếu tổng dung lượng vượt `limits.max_data_gb`: xoá tầng cũ nhất theo thứ tự book_1m, options, ticks
     (tick chỉ bị xoá nếu ngày đó đã có footprint).

Mất độ phân giải: sau bước 2, footprint dưới 1 phút chỉ dựng lại được bằng cách tải lại file ngày đó
(collector.backfill --force). Nếu ngày đã gom lại có tick mới (ví dụ tải lại), job bỏ qua và cảnh báo
thay vì trộn hai nguồn.
"""
from __future__ import annotations

import argparse
import logging
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb

from common import store

log = logging.getLogger("collector.compact")

MERGE_KINDS = ("ticks", "bars", "book", "bookdepth", "metrics", "footprint_1m", "book_1m", "options")
MIN_AGE_S = 15 * 60          # không đụng ngày vừa kết thúc dưới 15 phút
REL_TOL = 1e-5               # sai số cho phép khi so tổng (float32)
LIMIT_ORDER = ("book_1m", "options", "ticks")


def load_retention() -> dict:
    with open(store.ROOT / "config" / "retention.toml", "rb") as f:
        return tomllib.load(f)


def _symbols(kind: str) -> list[str]:
    folder = store.data_dir() / kind
    return sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.exists() else []


def _size(files: list[Path]) -> int:
    return sum(f.stat().st_size for f in files if f.exists())


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= REL_TOL * max(abs(a), abs(b)) + 1e-9


def _eligible(day: date, now: datetime) -> bool:
    end_of_day = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)
    return (now - end_of_day).total_seconds() >= MIN_AGE_S


# ---------- bước 1: gộp ----------

def merge_old_days(symbol: str, now: datetime, dry: bool, stats: dict) -> None:
    for kind in MERGE_KINDS:
        for day in store.list_days(kind, symbol):
            if not _eligible(day, now):
                continue
            files = store.day_files(kind, symbol, day)
            canonical = store.partition_path(kind, symbol, day)
            if files == [canonical]:
                continue
            log.info("gộp %s %s %s: %d file", kind, symbol, day, len(files))
            stats["merged_files"] += len(files)
            if not dry:
                store.merge_day(kind, symbol, day)


# ---------- bước 2: ticks -> footprint_1m ----------

def _footprint_select(symbol: str, day: date) -> str:
    cfg = store.symbol_config(symbol)
    bucket = round(cfg["footprint_bucket"] / cfg["tick"])
    if bucket < 1 or abs(bucket * cfg["tick"] - cfg["footprint_bucket"]) > 1e-9:
        raise ValueError(f"footprint_bucket của {symbol} phải là bội của tick")
    raw = store.day_select("ticks", symbol, day)
    return (
        f"SELECT (ts // 60000) * 60000 AS ts, (p // {bucket}) * {bucket} AS p, "
        f"sum(CASE WHEN m THEN 0 ELSE q::DOUBLE END)::FLOAT AS buy, "
        f"sum(CASE WHEN m THEN q::DOUBLE ELSE 0 END)::FLOAT AS sell "
        f"FROM ({raw}) GROUP BY 1, 2"
    )


def _verify_footprint(symbol: str, day: date) -> None:
    raw = store.day_select("ticks", symbol, day)
    fp = store.partition_path("footprint_1m", symbol, day)
    con = duckdb.connect()
    try:
        rows = con.execute(f"""
            WITH r AS (SELECT (t.ts // 60000) * 60000 AS minute,
                              sum(CASE WHEN t.m THEN 0 ELSE t.q::DOUBLE END) AS buy,
                              sum(CASE WHEN t.m THEN t.q::DOUBLE ELSE 0 END) AS sell
                       FROM ({raw}) t GROUP BY 1),
                 f AS (SELECT ts AS minute, sum(buy::DOUBLE) AS buy, sum(sell::DOUBLE) AS sell
                       FROM read_parquet({store._sql_str(fp)}) GROUP BY 1)
            SELECT coalesce(r.minute, f.minute), r.buy, r.sell, f.buy, f.sell
            FROM r FULL OUTER JOIN f ON r.minute = f.minute
        """).fetchall()
    finally:
        con.close()
    if not rows:
        raise RuntimeError(f"footprint {symbol} {day} rỗng")
    for minute, rb, rs, fb, fs in rows:
        if rb is None or fb is None:
            raise RuntimeError(f"footprint {symbol} {day}: phút {minute} chỉ có ở một phía")
        if not (_close(rb, fb) and _close(rs, fs)):
            raise RuntimeError(
                f"footprint {symbol} {day}: phút {minute} lệch (mua {rb} vs {fb}, bán {rs} vs {fs}); giữ nguyên tick"
            )


def compact_ticks(symbol: str, now: datetime, full_days: int, dry: bool, stats: dict) -> None:
    today = now.date()
    for day in store.list_days("ticks", symbol):
        if (today - day).days <= full_days or not _eligible(day, now):
            continue
        fp_path = store.partition_path("footprint_1m", symbol, day)
        if fp_path.exists():
            log.warning("%s %s: đã có footprint nhưng lại có tick (tải lại?). Bỏ qua, xử lý tay.", symbol, day)
            stats["warnings"] += 1
            continue
        files = store.day_files("ticks", symbol, day)
        before = _size(files)
        log.info("gom tick -> footprint_1m %s %s (%.1f MB)", symbol, day, before / 1e6)
        if dry:
            continue
        store.write_partition("footprint_1m", symbol, day, _footprint_select(symbol, day))
        try:
            _verify_footprint(symbol, day)
        except BaseException:
            fp_path.unlink(missing_ok=True)  # bản footprint chưa được kiểm tra thì không giữ
            raise
        for f in files:
            store._unlink(f)
        stats["ticks_days_compacted"] += 1
        stats["bytes_freed"] += before - _size([fp_path])


# ---------- bước 3, 4: sổ lệnh ----------

def compact_book(symbol: str, now: datetime, raw_days: int, agg_days: int, dry: bool, stats: dict) -> None:
    today = now.date()
    for day in store.list_days("book", symbol):
        if (today - day).days <= raw_days or not _eligible(day, now):
            continue
        out = store.partition_path("book_1m", symbol, day)
        if out.exists():
            log.warning("%s %s: đã có book_1m nhưng lại có book thô. Bỏ qua, xử lý tay.", symbol, day)
            stats["warnings"] += 1
            continue
        files = store.day_files("book", symbol, day)
        before = _size(files)
        log.info("gom book -> book_1m %s %s (%.1f MB)", symbol, day, before / 1e6)
        if dry:
            continue
        raw = store.day_select("book", symbol, day)
        sel = (f"SELECT (ts // 60000) * 60000 AS ts, p, max(bid)::FLOAT AS bid, max(ask)::FLOAT AS ask "
               f"FROM ({raw}) GROUP BY 1, 2")
        store.write_partition("book_1m", symbol, day, sel)
        con = duckdb.connect()
        try:
            n_out, mb, ma = con.execute(
                f"SELECT count(*), max(bid), max(ask) FROM read_parquet({store._sql_str(out)})").fetchall()[0]
            n_exp, rb, ra = con.execute(
                f"SELECT count(*), max(bid), max(ask) FROM (SELECT (ts // 60000) AS m, p, max(bid) AS bid, max(ask) AS ask "
                f"FROM ({raw}) GROUP BY 1, 2)").fetchall()[0]
        finally:
            con.close()
        if n_out != n_exp or mb != rb or ma != ra or n_out == 0:
            out.unlink(missing_ok=True)
            raise RuntimeError(f"book_1m {symbol} {day} không khớp bản thô; giữ nguyên")
        for f in files:
            store._unlink(f)
        stats["book_days_compacted"] += 1
        stats["bytes_freed"] += before - _size([out])

    for day in store.list_days("book_1m", symbol):
        if (today - day).days > agg_days:
            log.info("xoá book_1m %s %s (quá %d ngày)", symbol, day, agg_days)
            if not dry:
                for f in store.day_files("book_1m", symbol, day):
                    store._unlink(f)
                stats["old_book_1m_deleted"] += 1


# ---------- bước 5: trần dung lượng ----------

def data_bytes() -> int:
    root = store.data_dir()
    total = 0
    for kind in (*MERGE_KINDS, "vn_book"):
        d = root / kind
        if d.exists():
            total += sum(f.stat().st_size for f in d.rglob("*.parquet"))
    return total


def enforce_limit(max_gb: float, dry: bool, stats: dict) -> None:
    limit = int(max_gb * 1e9)
    used = data_bytes()
    if used <= limit:
        return
    log.warning("dung lượng %.2f GB vượt trần %.2f GB, xoá tầng cũ nhất", used / 1e9, max_gb)
    root = store.data_dir()
    for kind in LIMIT_ORDER:
        base = root / kind
        if not base.exists():
            continue
        files = sorted(base.rglob("date=*.parquet"), key=lambda p: p.name.split(".")[0])  # theo ngày tăng dần
        for f in files:
            if used <= limit:
                return
            symbol = f.parent.name
            if kind == "ticks":
                day = date.fromisoformat(f.name[len("date="):len("date=") + 10])
                if not store.partition_path("footprint_1m", symbol, day).exists():
                    continue  # chưa có footprint thì không xoá tick
            size = f.stat().st_size
            log.warning("xoá %s", f)
            if not dry:
                store._unlink(f)
            used -= size
            stats["limit_deleted_files"] += 1
    if used > limit:
        log.warning("vẫn vượt trần (%.2f GB). Không còn gì xoá an toàn được.", used / 1e9)
        stats["warnings"] += 1


# ---------- chạy ----------

def compact_all(now: datetime | None = None, dry_run: bool = False, only_symbol: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cfg = load_retention()
    stats = {"merged_files": 0, "ticks_days_compacted": 0, "book_days_compacted": 0,
             "old_book_1m_deleted": 0, "limit_deleted_files": 0, "bytes_freed": 0, "warnings": 0}
    symbols = sorted({s for k in MERGE_KINDS for s in _symbols(k)})
    if only_symbol:
        symbols = [s for s in symbols if s == only_symbol]
    for symbol in symbols:
        merge_old_days(symbol, now, dry_run, stats)
        if symbol in {s for s in _symbols("ticks")}:
            compact_ticks(symbol, now, cfg["ticks"]["full_days"], dry_run, stats)
        if symbol in {s for s in _symbols("book")} | {s for s in _symbols("book_1m")}:
            compact_book(symbol, now, cfg["book"]["raw_days"], cfg["book"]["agg_days"], dry_run, stats)
    enforce_limit(cfg["limits"]["max_data_gb"], dry_run, stats)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="chỉ in việc sẽ làm")
    ap.add_argument("--symbol")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = compact_all(dry_run=a.dry_run, only_symbol=a.symbol)
    log.info("xong: %s", s)


if __name__ == "__main__":
    main()
