"""GET /api/heatmap: thanh khoản chờ trong sổ lệnh theo thời gian và giá.

Nguồn: `book` (cách 5 giây, bucket giá `book_bucket`) cho các ngày còn lưu; ngày đã nén dùng `book_1m`.
Mỗi ngày dùng một nguồn. Mỗi ô (thời gian, giá) lấy giá trị lớn nhất của bid và ask trong ô để một lệnh
chờ lớn tồn tại ngắn vẫn hiện ra. `scale` là phân vị 99 của (bid + ask): trình duyệt chia cho giá trị
này để chuẩn hoá màu, nên vài ô cực lớn không làm mờ cả bản đồ.
Cửa sổ giá chỉ rộng ±0.15% (BTC) và ±0.30% (vàng) quanh giá tại thời điểm đó; ngoài cửa sổ không có dữ liệu.
Mỗi dòng: [ts, price, bid, ask].
"""
from __future__ import annotations

import duckdb
from fastapi import APIRouter, HTTPException, Query

from common import store
from . import limits

router = APIRouter()

MAX_CELLS = 120_000
MIN_TBUCKET_MS = 5_000


def heatmap_sql(symbol: str, start_ms: int, end_ms: int, tbucket_ms: int, mult: int) -> str | None:
    cfg = store.symbol_config(symbol)
    base = round(cfg["book_bucket"] / cfg["tick"])
    if base < 1:
        raise ValueError(f"book_bucket của {symbol} nhỏ hơn tick")
    pm = base * mult
    book = store.range_select("book", symbol, start_ms, end_ms)
    b1m = store.range_select("book_1m", symbol, start_ms, end_ms)
    parts = []
    if book:
        parts.append(f"SELECT ts, p, bid, ask FROM ({book})")
    if b1m:
        has = f"(SELECT DISTINCT ts // 86400000 FROM ({book}))" if book else "(SELECT NULL::BIGINT WHERE false)"
        parts.append(f"SELECT ts, p, bid, ask FROM ({b1m}) WHERE ts // 86400000 NOT IN {has}")
    if not parts:
        return None
    union = " UNION ALL ".join(parts)
    return (
        f"SELECT (ts // {tbucket_ms}) * {tbucket_ms} AS t, (p // {pm}) * {pm} AS p, "
        f"max(bid::DOUBLE) AS bid, max(ask::DOUBLE) AS ask FROM ({union}) GROUP BY 1, 2"
    )


def get_heatmap(symbol: str, start_ms: int, end_ms: int, tbucket_ms: int, mult: int) -> dict:
    try:
        cfg = store.symbol_config(symbol)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    if end_ms <= start_ms:
        raise HTTPException(400, "to phải lớn hơn from")
    tbucket_ms = max(tbucket_ms, MIN_TBUCKET_MS) // MIN_TBUCKET_MS * MIN_TBUCKET_MS
    sql = heatmap_sql(symbol, start_ms, end_ms, tbucket_ms, mult)
    rows: list[list] = []
    scale = 0.0
    if sql:
        con = store.query_conn()
        try:
            con.execute(f"CREATE TEMP TABLE g AS {sql}")  # tính một lần, dùng cho cả dữ liệu và phân vị
            n = con.execute("SELECT count(*) FROM g").fetchone()[0]
            if n > MAX_CELLS:
                raise HTTPException(400, "quá nhiều ô; tăng tbucket hoặc mult")
            data = con.execute("SELECT t, p, bid, ask FROM g ORDER BY t, p").fetchall()
            if data:
                scale = con.execute("SELECT quantile_cont(bid + ask, 0.99) FROM g").fetchone()[0] or 0.0
        finally:
            con.close()
        tick = cfg["tick"]
        rows = [[t, round(p * tick, 10), round(b, 4), round(a, 4)] for t, p, b, a in data]
    bucket = round(round(cfg["book_bucket"] / cfg["tick"]) * mult * cfg["tick"], 10)
    return {"symbol": symbol, "from": start_ms, "to": end_ms, "tbucket": tbucket_ms, "bucket": bucket,
            "scale": round(float(scale), 4), "rows": rows}


@router.get("/api/heatmap")
def heatmap_endpoint(
    symbol: str,
    from_: int = Query(..., alias="from"),
    to: int = Query(...),
    tbucket: int = Query(60_000, ge=1, description="độ rộng ô thời gian, ms (làm tròn lên bội của 5000)"),
    mult: int = Query(1, ge=1, le=100000, description="nhân bucket giá"),
) -> dict:
    sym = symbol.upper()

    def run() -> dict:
        with limits.heavy():
            return get_heatmap(sym, from_, to, tbucket, mult)
    return limits.coalesce(("heatmap", sym, from_, to, tbucket, mult), limits.CACHE_TTL, run)


def get_bubbles(symbol: str, start_ms: int, end_ms: int, tbucket_ms: int, top: int) -> dict:
    """Các cụm lệnh khớp lớn nhất (mua/bán chủ động) trong khoảng, gom theo ô thời gian và mức giá.

    Mỗi dòng: [ts, price, qty, side, n]. n là số lệnh khớp gộp (aggTrade) trong cụm: n = 1 là một lệnh lớn đơn lẻ, n > 1 là
    nhiều lệnh nhỏ cộng lại. Giao diện vẽ vòng đặc cho n = 1 và vòng rỗng cho n > 1 (kiểu Deep Trades của DeepCharts)."""
    try:
        cfg = store.symbol_config(symbol)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    if end_ms <= start_ms:
        raise HTTPException(400, "to phải lớn hơn from")
    tbucket_ms = max(tbucket_ms, 1000)
    base = round(cfg["book_bucket"] / cfg["tick"])
    ticks = store.range_select("ticks", symbol, start_ms, end_ms)
    rows: list[list] = []
    if ticks:
        con = store.query_conn()
        try:
            data = con.execute(
                f"SELECT (ts // {tbucket_ms}) * {tbucket_ms} AS t, (p // {base}) * {base} AS p, m, sum(q::DOUBLE) AS q, count(*) AS n "
                f"FROM ({ticks}) GROUP BY 1, 2, 3 ORDER BY q DESC LIMIT {int(top)}"
            ).fetchall()
        finally:
            con.close()
        rows = [[t, round(p * cfg["tick"], 10), round(q, 6), "sell" if m else "buy", n] for t, p, m, q, n in sorted(data)]
    return {"symbol": symbol, "from": start_ms, "to": end_ms, "tbucket": tbucket_ms,
            "bucket": round(base * cfg["tick"], 10), "rows": rows}


@router.get("/api/bubbles")
def bubbles_endpoint(
    symbol: str,
    from_: int = Query(..., alias="from"),
    to: int = Query(...),
    tbucket: int = Query(10_000, ge=1),
    top: int = Query(300, ge=1, le=5000),
) -> dict:
    sym = symbol.upper()

    def run() -> dict:
        with limits.heavy():
            return get_bubbles(sym, from_, to, tbucket, top)
    return limits.coalesce(("bubbles", sym, from_, to, tbucket, top), limits.CACHE_TTL, run)


def get_icebergs(symbol: str, start_ms: int, end_ms: int, tbucket_ms: int, factor: float, min_qty: float, top: int = 40) -> dict:
    """Ước lượng lệnh iceberg: ô (thời gian, giá) mà khối lượng khớp vượt `factor` lần thanh khoản đang hiển thị ở phía bị đánh.

    Mua chủ động đánh vào lệnh bán chờ (ask), bán chủ động đánh vào lệnh mua chờ (bid). Nếu đã khớp nhiều hơn nhiều so với
    thanh khoản hiển thị tại đúng mức giá đó mà vẫn còn lệnh chờ, phần dư được bổ sung ngầm, tức là dấu hiệu iceberg.
    Đây chỉ là ước lượng độ tin cậy thấp: sổ lệnh lấy mẫu mỗi 5 giây và gom theo bucket giá, sàn không công bố iceberg
    (Bookmap cũng suy luận theo cách tương tự và cảnh báo độ chính xác tuỳ nguồn dữ liệu).
    Chỉ giữ `top` ô có khối lượng khớp lớn nhất (trên dữ liệu thật hàng nghìn ô vượt ngưỡng tỉ lệ vì sổ lệnh chỉ lấy mẫu
    5 giây). Mỗi dòng: [ts, price, traded, displayed, side] với side = "buy" (mua chủ động) hoặc "sell".
    """
    try:
        cfg = store.symbol_config(symbol)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    if end_ms <= start_ms:
        raise HTTPException(400, "to phải lớn hơn from")
    tbucket_ms = max(tbucket_ms, MIN_TBUCKET_MS) // MIN_TBUCKET_MS * MIN_TBUCKET_MS
    base = round(cfg["book_bucket"] / cfg["tick"])
    book_sql = heatmap_sql(symbol, start_ms, end_ms, tbucket_ms, 1)
    ticks = store.range_select("ticks", symbol, start_ms, end_ms)
    rows: list[list] = []
    if book_sql and ticks:
        con = store.query_conn()
        try:
            data = con.execute(
                f"WITH b AS ({book_sql}), "
                f"t AS (SELECT (ts // {tbucket_ms}) * {tbucket_ms} AS t, (p // {base}) * {base} AS p, m, sum(q::DOUBLE) AS q "
                f"      FROM ({ticks}) GROUP BY 1, 2, 3) "
                f"SELECT t.t, t.p, t.q, CASE WHEN t.m THEN b.bid ELSE b.ask END AS shown, t.m "
                f"FROM t JOIN b ON b.t = t.t AND b.p = t.p "
                f"WHERE t.q >= {float(min_qty)} AND shown > 0 AND t.q > {float(factor)} * shown ORDER BY t.q DESC LIMIT {int(top)}"
            ).fetchall()
        finally:
            con.close()
        rows = sorted([[t, round(p * cfg["tick"], 10), round(q, 6), round(s, 6), "sell" if m else "buy"] for t, p, q, s, m in data])
    return {"symbol": symbol, "from": start_ms, "to": end_ms, "tbucket": tbucket_ms, "rows": rows}


@router.get("/api/icebergs")
def icebergs_endpoint(
    symbol: str,
    from_: int = Query(..., alias="from"),
    to: int = Query(...),
    tbucket: int = Query(30_000, ge=1),
    factor: float = Query(5.0, gt=0, description="khối lượng khớp phải lớn hơn factor lần thanh khoản hiển thị"),
    min_qty: float = Query(0.0, ge=0),
    top: int = Query(40, ge=1, le=500, description="chỉ giữ `top` ô có khối lượng khớp lớn nhất, vì dòng lệnh thường cũng vượt ngưỡng ở rất nhiều ô"),
) -> dict:
    sym = symbol.upper()

    def run() -> dict:
        with limits.heavy():
            return get_icebergs(sym, from_, to, tbucket, factor, min_qty, top)
    return limits.coalesce(("icebergs", sym, from_, to, tbucket, factor, min_qty, top), limits.CACHE_TTL, run)


# ---------- độ phủ dữ liệu sổ lệnh và dải độ sâu thô ----------

GAP_MS = 3 * 60_000          # hai mẫu sổ lệnh cách nhau quá 3 phút là một khoảng hở
MAX_DEPTH_ROWS = 60_000


def get_coverage(symbol: str, start_ms: int, end_ms: int) -> dict:
    """Các đoạn thời gian đã ghi sổ lệnh chi tiết (heatmap) trong [start_ms, end_ms): [[bắt đầu, kết thúc], ...] (ms).

    Gộp hai mẫu liền nhau nếu cách nhau không quá 3 phút. Dùng để giao diện đánh dấu đoạn không có heatmap.
    """
    try:
        store.symbol_config(symbol)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    if end_ms <= start_ms:
        raise HTTPException(400, "to phải lớn hơn from")
    parts = [f"SELECT ts FROM ({s})" for s in (store.range_select("book", symbol, start_ms, end_ms),
                                                   store.range_select("book_1m", symbol, start_ms, end_ms)) if s]
    segs: list[list[int]] = []
    first = last = None
    if parts:
        con = store.query_conn()
        try:
            minutes = [r[0] for r in con.execute(
                f"SELECT DISTINCT ts // 60000 AS m FROM ({' UNION ALL '.join(parts)}) ORDER BY m").fetchall()]
        finally:
            con.close()
        for m in minutes:
            t0, t1 = m * 60_000, (m + 1) * 60_000
            if segs and t0 - segs[-1][1] <= GAP_MS:
                segs[-1][1] = t1
            else:
                segs.append([t0, t1])
        if segs:
            first, last = segs[0][0], segs[-1][1]
    covered = sum(b - a for a, b in segs)
    return {"symbol": symbol, "from": start_ms, "to": end_ms, "segments": segs, "first": first, "last": last, "covered_ms": covered}


@router.get("/api/heatmap/coverage")
def coverage_endpoint(symbol: str, from_: int = Query(..., alias="from"), to: int = Query(...)) -> dict:
    sym = symbol.upper()
    return limits.coalesce(("coverage", sym, from_, to), limits.CACHE_TTL, lambda: get_coverage(sym, from_, to))


def get_depthbands(symbol: str, start_ms: int, end_ms: int, tbucket_ms: int) -> dict:
    """Độ sâu thô từ kho Binance `bookDepth` (độ sâu cộng dồn tới ±0,2%, 1%...5% quanh giá, 30 giây/mẫu): không có từng mức giá.

    Mỗi dòng: [t, lo_pct, hi_pct, mật_độ]. Dải nằm giữa hai mốc liền nhau của cùng một phía (lo, hi theo % so với giá giữa; âm là phía mua),
    mật_độ là giá trị lệnh chờ (USD) trên mỗi 1% khoảng cách. `scale` là phân vị 99 để chuẩn hoá màu.
    """
    try:
        store.symbol_config(symbol)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    if end_ms <= start_ms:
        raise HTTPException(400, "to phải lớn hơn from")
    tb = max(tbucket_ms, 60_000)
    src = store.range_select("bookdepth", symbol, start_ms, end_ms)
    rows: list[list] = []
    scale = 0.0
    if src:
        con = store.query_conn()
        try:
            data = con.execute(
                f"SELECT (ts // {tb}) * {tb} AS t, round(pct::DOUBLE, 3) AS p, avg(notional) AS n FROM ({src}) "
                f"GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
        finally:
            con.close()
        by_t: dict[int, dict[float, float]] = {}
        for t, p, n in data:
            by_t.setdefault(t, {})[p] = n
        for t in sorted(by_t):
            lv = by_t[t]
            for sign in (-1, 1):
                prev_p, prev_n = 0.0, 0.0
                for p in sorted((q for q in lv if q * sign > 0), key=abs):
                    width = abs(p) - prev_p
                    dens = (lv[p] - prev_n) / width if width > 0 else 0.0
                    if dens > 0:
                        lo, hi = (-abs(p), -prev_p) if sign < 0 else (prev_p, abs(p))
                        rows.append([t, round(lo, 3), round(hi, 3), round(dens, 1)])
                    prev_p, prev_n = abs(p), lv[p]
        if len(rows) > MAX_DEPTH_ROWS:
            raise HTTPException(400, "quá nhiều dòng; tăng tbucket")
        if rows:
            dens = sorted(r[3] for r in rows)
            scale = dens[min(len(dens) - 1, int(len(dens) * 0.99))]   # phân vị 99
    return {"symbol": symbol, "from": start_ms, "to": end_ms, "tbucket": tb, "scale": round(float(scale), 1), "rows": rows}


@router.get("/api/depthbands")
def depthbands_endpoint(
    symbol: str, from_: int = Query(..., alias="from"), to: int = Query(...), tbucket: int = Query(900_000, ge=1),
) -> dict:
    sym = symbol.upper()

    def run() -> dict:
        with limits.heavy():
            return get_depthbands(sym, from_, to, tbucket)
    return limits.coalesce(("depthbands", sym, from_, to, tbucket), limits.CACHE_TTL, run)
