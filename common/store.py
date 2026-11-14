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
import json
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
    # chuỗi quyền chọn Deribit, mỗi 15 phút một snapshot. expiry = thời điểm hết hạn (ms), strike = giá thực hiện (USD),
    # cp = true nếu là call, oi = open interest (số hợp đồng, 1 hợp đồng = 1 BTC), iv = mark IV (%),
    # fwd = giá underlying của kỳ hạn đó, spot = giá chỉ số
    # sổ lệnh 3 mức của HOSE (VN100), ghi khi có thay đổi. Giá là đồng (số nguyên). last = giá khớp gần nhất,
    # tv = tổng khối lượng khớp trong phiên (cộng dồn), bu/sd = khối lượng "mua lên"/"bán xuống" cộng dồn
    "vn_book": [
        ("ts", "BIGINT"), ("b1p", "INTEGER"), ("b1v", "BIGINT"), ("b2p", "INTEGER"), ("b2v", "BIGINT"),
        ("b3p", "INTEGER"), ("b3v", "BIGINT"), ("a1p", "INTEGER"), ("a1v", "BIGINT"), ("a2p", "INTEGER"),
        ("a2v", "BIGINT"), ("a3p", "INTEGER"), ("a3v", "BIGINT"), ("last", "INTEGER"), ("tv", "BIGINT"),
        ("bu", "BIGINT"), ("sd", "BIGINT"),
    ],
    "options": [
        ("ts", "BIGINT"), ("expiry", "BIGINT"), ("strike", "INTEGER"), ("cp", "BOOLEAN"),
        ("oi", "FLOAT"), ("iv", "FLOAT"), ("fwd", "DOUBLE"), ("spot", "DOUBLE"),
    ],
}

# Khoá duy nhất của từng loại, dùng để loại trùng. Dòng trùng khoá: giữ dòng có ts nhỏ nhất.
KEYS: dict[str, list[str]] = {
    "ticks": ["id"], "bars": ["ts"], "book": ["ts", "p"], "bookdepth": ["ts", "pct"], "metrics": ["ts"],
    "footprint_1m": ["ts", "p"], "book_1m": ["ts", "p"], "options": ["ts", "expiry", "strike", "cp"], "vn_book": ["ts"],
}
# Thứ tự sắp xếp khi ghi và đọc (ổn định khi nhiều lệnh cùng mili giây).
ORDER: dict[str, str] = {
    "ticks": "ts, id", "bars": "ts", "book": "ts, p", "bookdepth": "ts, pct", "metrics": "ts",
    "footprint_1m": "ts, p", "book_1m": "ts, p", "options": "ts, expiry, strike, cp", "vn_book": "ts",
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

_SYMBOLS_FILE = ROOT / "config" / "symbols.toml"
VN100_FILE = ROOT / "config" / "vn100.json"
_symbols_cache: tuple[tuple[int, int], dict] | None = None   # ((mtime toml, mtime vn100), nội dung)

# Mã VN100 không cần khai từng mã trong symbols.toml: lấy từ vn100.json với cấu hình chung.
# Giá lưu theo nghìn đồng với tick 0.001 (1 đồng) vì lịch sử đã điều chỉnh có 3 chữ số thập phân.
VN_DEFAULTS = {"source": "vn", "market": "vn", "tick": 0.001, "qty_step": 1,
               "footprint_bucket": 0.01, "book_window_pct": 0.0, "book_bucket": 0.01}


def vn100_symbols() -> list[str]:
    try:
        with open(VN100_FILE, "rb") as f:
            return list(json.load(f)["symbols"])
    except (OSError, ValueError, KeyError):
        return []


def _load_symbols() -> dict:
    """Đọc config/symbols.toml và config/vn100.json, giữ bản nhớ đệm và chỉ đọc lại khi file đổi.

    to_int_price chạy cho từng tick, nên không được mở file mỗi lần. Nếu file đang bị khoá
    (OneDrive, trình soạn thảo) mà đã có bản nhớ đệm thì dùng bản đó thay vì làm sập luồng.
    """
    global _symbols_cache
    try:
        m1 = _SYMBOLS_FILE.stat().st_mtime_ns
        try:
            m2 = VN100_FILE.stat().st_mtime_ns
        except OSError:
            m2 = 0
        if _symbols_cache is not None and _symbols_cache[0] == (m1, m2):
            return _symbols_cache[1]
        with open(_SYMBOLS_FILE, "rb") as f:
            cfg = tomllib.load(f)
        for sym in vn100_symbols():
            cfg.setdefault(sym, dict(VN_DEFAULTS))
        _symbols_cache = ((m1, m2), cfg)
        return cfg
    except OSError:
        if _symbols_cache is not None:
            return _symbols_cache[1]
        raise


def symbol_config(symbol: str) -> dict:
    cfg = _load_symbols()
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
        # Điều kiện bắt buộc: file `date=D` chỉ chứa dữ liệu của ngày UTC D. range_select dựa vào đó để
        # chỉ đọc file của các ngày liên quan; nếu sai, truy vấn theo khoảng thời gian sẽ lặng lẽ thiếu dòng.
        lo, hi = con.execute("SELECT min(ts), max(ts) FROM t").fetchall()[0]
        if lo is not None:
            day_start = (day.toordinal() - _EPOCH.toordinal()) * 86_400_000
            if lo < day_start or hi >= day_start + 86_400_000:
                raise ValueError(
                    f"{kind} {symbol}: ts [{lo}, {hi}] nằm ngoài ngày UTC {day} [{day_start}, {day_start + 86_400_000})"
                )
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


_FILE_DATE_RE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})(\.p[A-Za-z0-9_-]+)?\.parquet$")
_EPOCH = date(1970, 1, 1)


def _ms_to_day(ms: int) -> date:
    return date.fromordinal(_EPOCH.toordinal() + ms // 86_400_000)


def range_select(
    kind: str, symbol: str, start_ms: int | None = None, end_ms: int | None = None, dedupe: bool = True
) -> str | None:
    """Câu SELECT trả về các dòng có ts trong [start_ms, end_ms), hoặc None nếu không có file nào.

    Nhanh hơn dedupe_sql cho khoảng thời gian ngắn vì:
      - chỉ đọc file của các ngày UTC có thể chứa khoảng đó (tên file mang ngày), và
      - lọc ts ngay bên trong, trước khi loại trùng. Cửa sổ row_number() không đẩy được bộ lọc không
        phải khoá phân vùng xuống dưới, nên lọc sau sẽ phải quét và sắp xếp mọi file.
    Lọc trước khi loại trùng là an toàn: các bản sao của cùng một dòng có cùng ts, nên cả hai
    cùng nằm trong hoặc cùng nằm ngoài khoảng.
    """
    _check(kind, symbol)
    folder = data_dir() / kind / symbol
    if not folder.exists():
        return None
    d0 = _ms_to_day(start_ms) if start_ms is not None else None
    d1 = _ms_to_day(end_ms - 1) if end_ms is not None else None
    files = []
    for p in sorted(folder.glob("date=*.parquet")):
        m = _FILE_DATE_RE.match(p.name)
        if not m:
            continue
        d = date.fromisoformat(m.group(1))
        if (d0 is None or d >= d0) and (d1 is None or d <= d1):
            files.append(p)
    if not files:
        return None
    flist = "[" + ", ".join(_sql_str(f) for f in files) + "]"
    conds = []
    if start_ms is not None:
        conds.append(f"ts >= {int(start_ms)}")
    if end_ms is not None:
        conds.append(f"ts < {int(end_ms)}")
    inner = f"SELECT * FROM read_parquet({flist}, union_by_name=true)"
    if conds:
        inner += " WHERE " + " AND ".join(conds)
    if not dedupe:
        return inner
    return _dedupe_from(kind, f"({inner})")


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
    base = range_select(kind, symbol, start_ms, end_ms, dedupe=dedupe)
    if base is None:
        return []
    sel = ", ".join(columns) if columns else "*"
    sql = f"SELECT {sel} FROM ({base}) ORDER BY {ORDER[kind]}"
    con = duckdb.connect()
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()
