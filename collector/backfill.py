"""Tải lịch sử từ kho công khai data.binance.vision (USDⓈ-M Futures, file theo ngày).

Chạy:
  python -m collector.backfill --symbol BTCUSDT --dataset aggTrades --days 30
  python -m collector.backfill --symbol BTCUSDT --dataset bookDepth --days 30
  python -m collector.backfill --symbol BTCUSDT --dataset metrics --from 2026-10-01 --to 2026-10-31

Mỗi ngày: tải zip -> kiểm sha256 với file .CHECKSUM -> kiểm dấu thời gian nằm trong ngày UTC ->
chuyển sang Parquet bằng DuckDB (không nạp CSV vào bộ nhớ Python) -> ghi nhật ký. Chạy lại không
tải trùng (trừ khi --force). Chỉ tải ngày đã kết thúc (đến hôm qua theo UTC); hôm nay do collector lo.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import httpx

from common import appdb, store

BASE_URL = "https://data.binance.vision"
DAY_MS = 86_400_000

AGG_COLS = {
    "agg_trade_id": "BIGINT", "price": "DOUBLE", "quantity": "DOUBLE", "first_trade_id": "BIGINT",
    "last_trade_id": "BIGINT", "transact_time": "BIGINT", "is_buyer_maker": "BOOLEAN",
}
DEPTH_COLS = {"timestamp": "TIMESTAMP", "percentage": "DOUBLE", "depth": "DOUBLE", "notional": "DOUBLE"}
METRIC_COLS = {
    "create_time": "TIMESTAMP", "symbol": "VARCHAR", "sum_open_interest": "DOUBLE",
    "sum_open_interest_value": "DOUBLE", "count_toptrader_long_short_ratio": "DOUBLE",
    "sum_toptrader_long_short_ratio": "DOUBLE", "count_long_short_ratio": "DOUBLE",
    "sum_taker_long_short_vol_ratio": "DOUBLE",
}


class BackfillError(RuntimeError):
    pass


class NotPublished(BackfillError):
    """File của ngày này chưa có trên kho (404)."""


class ChecksumError(BackfillError):
    pass


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(60.0, connect=15.0), transport=transport,
                        follow_redirects=True, headers={"User-Agent": "tv-local/0.1"})


def file_path(dataset: str, symbol: str, day: date) -> str:
    return f"/data/futures/um/daily/{dataset}/{symbol}/{symbol}-{dataset}-{day.isoformat()}.zip"


KINDS = {"aggTrades": "ticks", "bookDepth": "bookdepth", "metrics": "metrics"}


# ---------- tải và kiểm ----------

def download(client: httpx.Client, path: str, dest: Path) -> str:
    """Tải về `dest` theo luồng, trả về sha256. 404 -> NotPublished."""
    h = hashlib.sha256()
    with client.stream("GET", path) as r:
        if r.status_code == 404:
            raise NotPublished(path)
        if r.status_code != 200:
            raise BackfillError(f"HTTP {r.status_code} khi tải {path}")
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                h.update(chunk)
                f.write(chunk)
    return h.hexdigest()


def expected_checksum(client: httpx.Client, path: str) -> str:
    r = client.get(path + ".CHECKSUM")
    if r.status_code == 404:
        raise NotPublished(path + ".CHECKSUM")
    if r.status_code != 200:
        raise BackfillError(f"HTTP {r.status_code} khi tải checksum {path}")
    token = r.text.split()[0].strip().lower() if r.text.strip() else ""
    if len(token) != 64:
        raise ChecksumError(f"file checksum không đúng dạng: {r.text[:80]!r}")
    return token


# ---------- chuyển đổi ----------

def _has_header(csv_path: Path) -> bool:
    with open(csv_path, "r", encoding="utf-8") as f:
        first = f.readline().lstrip()
    return not (first[:1].isdigit() or first[:1] == "-")


def _read_csv_expr(csv_path: Path, cols: dict[str, str]) -> str:
    colspec = ", ".join(f"'{k}': '{v}'" for k, v in cols.items())
    header = "true" if _has_header(csv_path) else "false"
    return f"read_csv({store._sql_str(csv_path)}, header={header}, columns={{{colspec}}}, auto_detect=false)"


def build_select(dataset: str, symbol: str, day: date, csv_path: Path) -> tuple[str, int]:
    """Kiểm tra dữ liệu và trả về (câu SELECT theo schema kho, số dòng).

    Nếu dấu thời gian không nằm trong ngày UTC (ví dụ Binance đổi đơn vị mili giây/micro giây),
    ném lỗi thay vì ghi sai.
    """
    day_start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
    day_end = day_start + DAY_MS
    con = duckdb.connect()
    try:
        if dataset == "aggTrades":
            src = _read_csv_expr(csv_path, AGG_COLS)
            n, lo, hi = con.execute(f"SELECT count(*), min(transact_time), max(transact_time) FROM {src}").fetchall()[0]
            tick = store.symbol_config(symbol)["tick"]
            sel = (
                f"SELECT transact_time AS ts, agg_trade_id AS id, round(price / {tick!r})::INTEGER AS p, "
                f"quantity::FLOAT AS q, is_buyer_maker AS m FROM {src}"
            )
        elif dataset == "bookDepth":
            src = _read_csv_expr(csv_path, DEPTH_COLS)
            n, lo, hi = con.execute(f"SELECT count(*), min(epoch_ms(timestamp)), max(epoch_ms(timestamp)) FROM {src}").fetchall()[0]
            sel = (
                f"SELECT epoch_ms(timestamp)::BIGINT AS ts, percentage::FLOAT AS pct, depth::FLOAT AS depth, "
                f"notional AS notional FROM {src}"
            )
        elif dataset == "metrics":
            src = _read_csv_expr(csv_path, METRIC_COLS)
            n, lo, hi = con.execute(f"SELECT count(*), min(epoch_ms(create_time)), max(epoch_ms(create_time)) FROM {src}").fetchall()[0]
            sel = (
                f"SELECT epoch_ms(create_time)::BIGINT AS ts, sum_open_interest AS oi, sum_open_interest_value AS oi_value, "
                f"count_toptrader_long_short_ratio::FLOAT AS top_ls_count, sum_toptrader_long_short_ratio::FLOAT AS top_ls_sum, "
                f"count_long_short_ratio::FLOAT AS ls_count, sum_taker_long_short_vol_ratio::FLOAT AS taker_ls FROM {src}"
            )
        else:
            raise BackfillError(f"dataset chưa hỗ trợ: {dataset}")
    finally:
        con.close()
    if n == 0:
        raise BackfillError(f"{dataset} {symbol} {day}: file rỗng")
    if not (day_start <= lo and hi < day_end):
        raise BackfillError(
            f"{dataset} {symbol} {day}: dấu thời gian [{lo}, {hi}] nằm ngoài ngày UTC [{day_start}, {day_end}). "
            "Có thể Binance đã đổi đơn vị thời gian. Dừng, không ghi."
        )
    return sel, int(n)


# ---------- một ngày ----------

def backfill_day(client: httpx.Client, dataset: str, symbol: str, day: date, force: bool = False) -> str:
    """Trả về 'ok', 'skipped' (đã có trong nhật ký) hoặc 'missing' (chưa có trên kho)."""
    kind = KINDS[dataset]
    appdb.init()
    con = appdb.connect()
    try:
        row = con.execute(
            "SELECT rows FROM backfill_log WHERE dataset=? AND symbol=? AND day=?", (dataset, symbol, day.isoformat())
        ).fetchone()
    finally:
        con.close()
    if row and not force:
        return "skipped"

    cache = store.data_dir() / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    stem = f"{symbol}-{dataset}-{day.isoformat()}"
    zip_path, csv_path = cache / f"{stem}.zip", cache / f"{stem}.csv"
    try:
        path = file_path(dataset, symbol, day)
        try:
            actual = download(client, path, zip_path)
            expected = expected_checksum(client, path)
        except NotPublished:
            return "missing"
        if actual != expected:
            raise ChecksumError(f"{stem}: sha256 {actual} khác checksum công bố {expected}")
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise BackfillError(f"{stem}.zip có {len(names)} file CSV, cần đúng 1")
            with z.open(names[0]) as src, open(csv_path, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
        select_sql, n = build_select(dataset, symbol, day, csv_path)
        store.write_partition(kind, symbol, day, select_sql)
        con = appdb.connect()
        try:
            con.execute(
                "INSERT OR REPLACE INTO backfill_log(dataset, symbol, day, rows, sha256) VALUES (?,?,?,?,?)",
                (dataset, symbol, day.isoformat(), n, actual),
            )
            con.commit()
        except sqlite3.Error:
            con.rollback()
            raise
        finally:
            con.close()
        return "ok"
    finally:
        for p in (zip_path, csv_path):
            try:
                p.unlink(missing_ok=True)
            except PermissionError:
                pass


def backfill(symbol: str, dataset: str, start: date, end: date, force: bool = False,
             client: httpx.Client | None = None) -> dict:
    """Tải các ngày trong [start, end] (gồm cả hai đầu), chỉ ngày đã kết thúc theo UTC."""
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    end = min(end, yesterday)
    own = client is None
    client = client or make_client()
    stats = {"ok": 0, "skipped": 0, "missing": 0, "days": []}
    try:
        d = start
        while d <= end:
            status = backfill_day(client, dataset, symbol, d, force=force)
            stats[status] += 1
            stats["days"].append((d.isoformat(), status))
            d += timedelta(days=1)
    finally:
        if own:
            client.close()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--dataset", choices=sorted(KINDS), default="aggTrades")
    ap.add_argument("--days", type=int, default=30, help="số ngày gần nhất (mặc định 30)")
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    ap.add_argument("--force", action="store_true", help="tải lại cả ngày đã có trong nhật ký")
    ap.add_argument("--yes", action="store_true", help="xác nhận tải hơn 366 ngày")
    a = ap.parse_args()
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    end = a.end or yesterday
    start = a.start or end - timedelta(days=a.days - 1)
    n_days = (min(end, yesterday) - start).days + 1
    if n_days > 366 and not a.yes:
        raise SystemExit(f"Sẽ tải {n_days} ngày. Thêm --yes để xác nhận (BTC aggTrades khoảng 2,4 GB Parquet mỗi năm).")
    s = backfill(a.symbol, a.dataset, start, end, force=a.force)
    print(f"{a.symbol} {a.dataset}: ok={s['ok']} bỏ qua={s['skipped']} chưa có trên kho={s['missing']}")


if __name__ == "__main__":
    main()
