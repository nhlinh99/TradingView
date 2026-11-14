"""Kho dữ liệu Parquet.

Một nơi duy nhất định nghĩa schema, đường dẫn và cách ghi/đọc.
Đường dẫn: DATA_DIR/<kind>/<symbol>/date=YYYY-MM-DD[.p<part>].parquet
  - `date=YYYY-MM-DD.parquet`  : file chuẩn của ngày (backfill hoặc kết quả gộp)
  - `date=YYYY-MM-DD.p<part>.parquet` : file con do collector ghi trong ngày
Đọc bằng DuckDB qua glob `date=*.parquet`. Dữ liệu trùng (backfill chồng collector) được loại
khi đọc và khi gộp, dựa vào khoá của từng loại (xem KEYS).
"""
from __future__ import annotations

import os
import re
import time
import tomllib
from datetime import date
from pathlib import Path
from typing import Callable, Sequence

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Cột `ts` (mili giây UTC) là cột sắp xếp chính của mọi schema.
SCHEMAS: dict[str, list[tuple[str, str]]] = {
    # lệnh khớp gộp. id = aggregate trade id của Binance (duy nhất theo symbol, tăng dần).
    # p = giá theo tick (số nguyên), q = khối lượng, m = isBuyerMaker (true: taker bán)
    "ticks": [("ts", "BIGINT"), ("id", "BIGINT"), ("p", "INTEGER"), ("q", "FLOAT"), ("m", "BOOLEAN")],
    # nến. o,h,l,c theo tick. buy_v/sell_v = khối lượng mua/bán chủ động
    "bars": [
        ("ts", "BIGINT"), ("o", "INTEGER"), ("h", "INTEGER"), ("l", "INTEGER"), ("c", "INTEGER"),
        ("v", "FLOAT"), ("buy_v", "FLOAT"), ("sell_v", "FLOAT"),
    ],
    # sổ lệnh đã gom bucket giá. p = bucket giá, bid/ask = tổng khối lượng chờ
    "book": [("ts", "BIGINT"), ("p", "INTEGER"), ("bid", "FLOAT"), ("ask", "FLOAT")],
    # bookDepth của Binance (kho lịch sử, cách 30 giây): độ sâu tích luỹ trong dải ±pct% quanh giá.
    # pct âm = phía mua, dương = phía bán. depth = khối lượng, notional = giá trị (USDT)
    "bookdepth": [("ts", "BIGINT"), ("pct", "FLOAT"), ("depth", "FLOAT"), ("notional", "DOUBLE")],
    # metrics của Binance (mỗi 5 phút): open interest và các tỉ lệ long/short
    "metrics": [
        ("ts", "BIGINT"), ("oi", "DOUBLE"), ("oi_value", "DOUBLE"), ("top_ls_count", "FLOAT"),
        ("top_ls_sum", "FLOAT"), ("ls_count", "FLOAT"), ("taker_ls", "FLOAT"),
    ],
    # footprint 1 phút: kết quả gom nén của ticks. p = cận dưới bucket giá (đơn vị tick),
    # buy/sell = khối lượng mua/bán chủ động trong bucket trong phút đó
    "footprint_1m": [("ts", "BIGINT"), ("p", "INTEGER"), ("buy", "FLOAT"), ("sell", "FLOAT")],
    # sổ lệnh 1 phút: kết quả gom nén của book (lấy giá trị lớn nhất mỗi bucket trong phút)
    "book_1m": [("ts", "BIGINT"), ("p", "INTEGER"), ("bid", "FLOAT"), ("ask", "FLOAT")],
}

# Khoá duy nhất của từng loại, dùng để loại trùng. Dòng trùng khoá: giữ dòng có ts nhỏ nhất.
KEYS: dict[str, list[str]] = {
    "ticks": ["id"], "bars": ["ts"], "book": ["ts", "p"], "bookdepth": ["ts", "pct"], "metrics": ["ts"],
    "footprint_1m": ["ts", "p"], "book_1m": ["ts", "p"],
}
# Thứ tự sắp xếp khi ghi và đọc (ổn định khi nhiều lệnh cùng mili giây).
ORDER: dict[str, str] = {
    "ticks": "ts, id", "bars": "ts", "book": "ts, p", "bookdepth": "ts, pct", "metrics": "ts",
    "footprint_1m": "ts, p", "book_1m": "ts, p",
}

INT32_MAX = 2**31 - 1
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_PART_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


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


# ---------- thao tác file có thử lại (Windows khoá file đang mở) ----------

def _retry(fn: Callable[[], None], tries: int = 8) -> None:
    for i in range(tries):
        try:
            fn()
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.05 * (2 ** i))


def _replace(src: Path, dst: Path) -> None:
    _retry(lambda: os.replace(src, dst))


def _unlink(path: Path) -> None:
    _retry(lambda: path.unlink(missing_ok=True))


# ---------- ghi ----------

def partition_path(kind: str, symbol: str, day: date, part: int | str | None = None) -> Path:
    """part=None: file chuẩn của ngày. part=int hoặc str: file con của collector.

    Với collector, dùng giá trị không bao giờ lặp lại giữa các lần chạy (ví dụ id đầu tiên
    trong file, hoặc mốc thời gian), không dùng bộ đếm bắt đầu lại từ 1 sau mỗi lần khởi động.
    """
    _check(kind, symbol)
    if part is None:
        suffix = ""
    elif isinstance(part, int):
        suffix = f".p{part:04d}"
    else:
        if not _PART_RE.match(part):
            raise ValueError(f"part không hợp lệ: {part!r}")
        suffix = f".p{part}"
    return data_dir() / kind / symbol / f"date={day.isoformat()}{suffix}.parquet"


_COPY_OPTS = "(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9)"


def write_partition(
    kind: str, symbol: str, day: date, data: Sequence[tuple] | str, part: int | str | None = None
) -> Path:
    """Ghi một file Parquet (zstd mức 9), sắp xếp theo ORDER[kind].

    data: danh sách tuple theo thứ tự cột của SCHEMAS[kind], hoặc một câu SELECT của DuckDB
    (dùng cho khối lượng lớn; chỉ truyền chuỗi do chính code của dự án tạo ra).
    Ghi ra file `.tmp` rồi đổi tên, nên không bao giờ để lại file nửa vời. Nếu file đích đang bị
    tiến trình khác mở, thử lại vài lần.
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
        con.execute(f"COPY (SELECT * FROM t ORDER BY {ORDER[kind]}) TO {_sql_str(tmp)} {_COPY_OPTS}")
        _replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        con.close()
    return final


def day_files(kind: str, symbol: str, day: date) -> list[Path]:
    """Mọi file của một ngày: file chuẩn và các file con."""
    _check(kind, symbol)
    folder = data_dir() / kind / symbol
    if not folder.exists():
        return []
    d = day.isoformat()
    return sorted(p for p in folder.glob(f"date={d}*.parquet") if p.name == f"date={d}.parquet" or p.name.startswith(f"date={d}.p"))


def list_days(kind: str, symbol: str) -> list[date]:
    """Các ngày có dữ liệu của (kind, symbol), tăng dần."""
    _check(kind, symbol)
    folder = data_dir() / kind / symbol
    if not folder.exists():
        return []
    days = set()
    for p in folder.glob("date=*.parquet"):
        m = re.match(r"^date=(\d{4}-\d{2}-\d{2})(\.p[A-Za-z0-9_-]+)?\.parquet$", p.name)
        if m:
            days.add(date.fromisoformat(m.group(1)))
    return sorted(days)


def day_select(kind: str, symbol: str, day: date) -> str:
    """Câu SELECT trả về mọi dòng của một ngày, đã loại trùng khoá. Dùng làm bảng con: FROM (<câu này>)."""
    files = day_files(kind, symbol, day)
    if not files:
        raise FileNotFoundError(f"không có file {kind} {symbol} {day}")
    flist = "[" + ", ".join(_sql_str(f) for f in files) + "]"
    return _dedupe_from(kind, f"read_parquet({flist}, union_by_name=true)")


def _dedupe_from(kind: str, from_expr: str) -> str:
    keys = KEYS.get(kind)
    if not keys:
        return f"SELECT * FROM {from_expr}"
    part = ", ".join(keys)
    return (
        f"SELECT * EXCLUDE (_rn) FROM (SELECT *, row_number() OVER (PARTITION BY {part} ORDER BY ts) AS _rn "
        f"FROM {from_expr}) WHERE _rn = 1"
    )


def merge_day(kind: str, symbol: str, day: date) -> Path | None:
    """Gộp mọi file của ngày thành một file chuẩn, loại dòng trùng khoá.

    Việc cần thiết vì backfill (cả ngày) và collector (nhiều file con) có thể chồng nhau.
    Thứ tự an toàn: ghi bản gộp ra file tạm, kiểm tra số dòng, thay file chuẩn, rồi mới xoá
    file con. Nếu bị ngắt giữa chừng, dữ liệu vẫn đủ và đọc có loại trùng vẫn đúng.
    Trả về None nếu ngày không có file. Không làm gì nếu chỉ có đúng file chuẩn.
    """
    files = day_files(kind, symbol, day)
    if not files:
        return None
    canonical = partition_path(kind, symbol, day)
    if files == [canonical]:
        return canonical
    flist = "[" + ", ".join(_sql_str(f) for f in files) + "]"
    src = f"read_parquet({flist}, union_by_name=true)"
    tmp = canonical.with_name(canonical.name + ".tmp")
    try:
        con = duckdb.connect()
        try:
            merged_sql = _dedupe_from(kind, src)
            con.execute(f"COPY ({merged_sql} ORDER BY {ORDER[kind]}) TO {_sql_str(tmp)} {_COPY_OPTS}")
            n_out = con.execute(f"SELECT count(*) FROM read_parquet({_sql_str(tmp)})").fetchall()[0][0]
            keys = KEYS.get(kind)
            if keys:
                n_expected = con.execute(
                    f"SELECT count(*) FROM (SELECT DISTINCT {', '.join(keys)} FROM {src})"
                ).fetchall()[0][0]
                if n_out != n_expected:
                    raise RuntimeError(f"gộp sai số dòng: {n_out} != {n_expected} ({kind} {symbol} {day})")
        finally:
            con.close()  # đóng trước khi thay file, để Windows không giữ khoá
        _replace(tmp, canonical)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    for f in files:
        if f != canonical:
            _unlink(f)
    return canonical


# ---------- đọc ----------

def scan_sql(kind: str, symbol: str) -> str:
    """Biểu thức FROM cho SQL tuỳ ý: SELECT ... FROM <scan_sql> WHERE ...

    Không loại trùng. Dùng read() hoặc dedupe_sql() khi cần dữ liệu sạch.
    """
    _check(kind, symbol)
    return f"read_parquet({_sql_str(data_dir() / kind / symbol / 'date=*.parquet')}, union_by_name=true)"


def dedupe_sql(kind: str, symbol: str) -> str:
    """Câu SELECT trả về mọi dòng đã loại trùng khoá. Dùng làm bảng con: FROM (<dedupe_sql>)."""
    return _dedupe_from(kind, scan_sql(kind, symbol))


def read(
    kind: str, symbol: str, start_ms: int | None = None, end_ms: int | None = None,
    columns: Sequence[str] | None = None, dedupe: bool = True,
) -> list[tuple]:
    """Đọc mọi file của (kind, symbol), lọc ts trong [start_ms, end_ms), sắp theo ORDER[kind].

    dedupe=True loại dòng trùng khoá (an toàn khi backfill chồng collector chưa được gộp).
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
    base = dedupe_sql(kind, symbol) if dedupe else f"SELECT * FROM {scan_sql(kind, symbol)}"
    sql = f"SELECT {sel} FROM ({base})"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {ORDER[kind]}"
    con = duckdb.connect()
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()
