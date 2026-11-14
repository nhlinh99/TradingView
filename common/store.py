"""Kho dữ liệu Parquet.

Một nơi duy nhất định nghĩa schema, đường dẫn và cách ghi/đọc.
Đường dẫn: DATA_DIR/<kind>/<symbol>/date=YYYY-MM-DD[.pNNNN].parquet
Đọc bằng DuckDB qua glob `date=*.parquet`.
"""
from __future__ import annotations

import os
import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Sequence

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Cột đầu tiên của mọi schema phải là `ts` (mili giây UTC). Việc sắp xếp dựa vào nó.
SCHEMAS: dict[str, list[tuple[str, str]]] = {
    # lệnh khớp. p = giá theo tick (số nguyên), q = khối lượng, m = isBuyerMaker (true: taker bán)
    "ticks": [("ts", "BIGINT"), ("p", "INTEGER"), ("q", "FLOAT"), ("m", "BOOLEAN")],
    # nến. o,h,l,c theo tick. buy_v/sell_v = khối lượng mua/bán chủ động
    "bars": [
        ("ts", "BIGINT"), ("o", "INTEGER"), ("h", "INTEGER"), ("l", "INTEGER"), ("c", "INTEGER"),
        ("v", "FLOAT"), ("buy_v", "FLOAT"), ("sell_v", "FLOAT"),
    ],
    # sổ lệnh đã gom bucket giá. p = bucket giá, bid/ask = tổng khối lượng chờ
    "book": [("ts", "BIGINT"), ("p", "INTEGER"), ("bid", "FLOAT"), ("ask", "FLOAT")],
}

INT32_MAX = 2**31 - 1
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class DataDirError(ValueError):
    """DATA_DIR thiếu, sai dạng, hoặc nằm trong OneDrive."""


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def data_dir() -> Path:
    raw = os.environ.get("DATA_DIR")
    if not raw:
        raise DataDirError("DATA_DIR chưa đặt. Thêm DATA_DIR=C:\\tv-data vào .env")
    p = Path(raw)
    if not p.is_absolute():
        raise DataDirError(f"DATA_DIR phải là đường dẫn tuyệt đối: {raw}")
    resolved = p.resolve()
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(var)
        if base and _is_within(resolved, Path(base).resolve()):
            raise DataDirError(f"DATA_DIR không được nằm trong OneDrive: {resolved}")
    if any("onedrive" in part.lower() for part in resolved.parts):
        raise DataDirError(f"DATA_DIR không được nằm trong OneDrive: {resolved}")
    return resolved


def _sql_str(value: object) -> str:
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def _check(kind: str, symbol: str) -> None:
    if kind not in SCHEMAS:
        raise KeyError(f"kind không có schema: {kind!r}. Đã có: {sorted(SCHEMAS)}")
    if not _SYMBOL_RE.match(symbol):
        raise ValueError(f"symbol không hợp lệ: {symbol!r}")


# ---------- giá dạng số nguyên ----------

def symbol_config(symbol: str) -> dict:
    with open(ROOT / "config" / "symbols.toml", "rb") as f:
        cfg = tomllib.load(f)
    if symbol not in cfg:
        raise KeyError(f"{symbol} chưa có trong config/symbols.toml")
    return cfg[symbol]


def to_int_price(symbol: str, price: float) -> int:
    tick = symbol_config(symbol)["tick"]
    n = round(price / tick)
    if abs(n) > INT32_MAX:
        raise OverflowError(f"giá {price} của {symbol} vượt int32 với tick {tick}")
    return n


def from_int_price(symbol: str, p: int) -> float:
    tick = symbol_config(symbol)["tick"]
    return round(p * tick, 10)


# ---------- ghi / đọc ----------

def partition_path(kind: str, symbol: str, day: date, part: int | None = None) -> Path:
    _check(kind, symbol)
    suffix = "" if part is None else f".p{part:04d}"
    return data_dir() / kind / symbol / f"date={day.isoformat()}{suffix}.parquet"


def write_partition(
    kind: str, symbol: str, day: date, data: Sequence[tuple] | str, part: int | None = None
) -> Path:
    """Ghi một file Parquet (zstd mức 9), sắp xếp theo ts.

    data: danh sách tuple theo thứ tự cột của SCHEMAS[kind], hoặc một câu SELECT của DuckDB
    (dùng cho khối lượng lớn; chỉ truyền chuỗi do chính code của dự án tạo ra).
    Ghi ra file `.tmp` rồi đổi tên, nên không bao giờ để lại file nửa vời.
    Ghi lại cùng (kind, symbol, day, part) sẽ thay thế file cũ.
    """
    cols = SCHEMAS[kind]
    final = partition_path(kind, symbol, day, part)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(final.name + ".tmp")
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (" + ", ".join(f"{n} {t}" for n, t in cols) + ")")
        if isinstance(data, str):
            con.execute(f"INSERT INTO t {data}")
        else:
            rows = [tuple(r) for r in data]
            bad = [r for r in rows if len(r) != len(cols)]
            if bad:
                raise ValueError(f"mỗi dòng cần {len(cols)} cột {[c for c, _ in cols]}, gặp {bad[0]!r}")
            if rows:
                con.executemany(f"INSERT INTO t VALUES ({','.join('?' * len(cols))})", rows)
        con.execute(
            f"COPY (SELECT * FROM t ORDER BY ts) TO {_sql_str(tmp)} "
            "(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9)"
        )
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        con.close()
    return final


def scan_sql(kind: str, symbol: str) -> str:
    """Biểu thức FROM cho SQL tuỳ ý: SELECT ... FROM <scan_sql> WHERE ..."""
    _check(kind, symbol)
    return f"read_parquet({_sql_str(data_dir() / kind / symbol / 'date=*.parquet')})"


def read(
    kind: str, symbol: str, start_ms: int | None = None, end_ms: int | None = None,
    columns: Sequence[str] | None = None,
) -> list[tuple]:
    """Đọc mọi file của (kind, symbol), lọc ts trong [start_ms, end_ms), sắp theo ts.

    Chưa loại trùng nếu hai file chồng thời gian. Job gom nén chịu trách nhiệm việc đó.
    """
    _check(kind, symbol)
    names = [n for n, _ in SCHEMAS[kind]]
    if columns is not None:
        unknown = [c for c in columns if c not in names]
        if unknown:
            raise KeyError(f"cột không có trong schema {kind}: {unknown}")
    folder = data_dir() / kind / symbol
    if not folder.exists() or not any(folder.glob("date=*.parquet")):
        return []
    where, params = [], []
    if start_ms is not None:
        where.append("ts >= ?"); params.append(start_ms)
    if end_ms is not None:
        where.append("ts < ?"); params.append(end_ms)
    sel = ", ".join(columns) if columns else "*"
    sql = f"SELECT {sel} FROM {scan_sql(kind, symbol)}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts"
    con = duckdb.connect()
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()
