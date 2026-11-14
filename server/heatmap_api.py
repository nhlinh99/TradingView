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
        con = duckdb.connect()
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
    return get_heatmap(symbol.upper(), from_, to, tbucket, mult)
