"""GET /api/footprint: khối lượng mua/bán theo từng mức giá trong mỗi nến.

Nguồn: tick của các ngày còn tick; ngày đã nén (tick bị xoá) dùng bảng `footprint_1m`.
Mỗi ngày chỉ dùng một nguồn nên không đếm trùng: compact chỉ xoá tick sau khi footprint ngày đó đã đủ.
Khung thời gian là bội của 1 phút. Mức giá gom theo `footprint_bucket` của symbol, nhân thêm `mult`
(zoom ra thì gom thô hơn). Phần đuôi chưa ghi xuống đĩa (tối đa ~60 giây) chưa có ở đây.
Mỗi dòng: [bar_ts, price, buy, sell]. Delta của nến = tổng (buy - sell) của các dòng trong nến, và
bằng delta của /api/bars (buy_v - sell_v) vì cả hai cùng đọc từ tick.
"""
from __future__ import annotations

import time

import duckdb
from fastapi import APIRouter, HTTPException, Query

from common import bars as tickbars
from common import store
from . import limits

router = APIRouter()

MAX_BARS = 2000
MAX_ROWS = 200_000
MINUTE = 60_000


def footprint_sql(symbol: str, tf_ms: int, start_ms: int, end_ms: int, mult: int) -> str | None:
    cfg = store.symbol_config(symbol)
    base = round(cfg["footprint_bucket"] / cfg["tick"])
    if base < 1:
        raise ValueError(f"footprint_bucket của {symbol} nhỏ hơn tick")
    bucket = base * mult
    ticks = store.range_select("ticks", symbol, start_ms, end_ms)
    fp = store.range_select("footprint_1m", symbol, start_ms, end_ms)
    parts = []
    if ticks:
        parts.append(
            f"SELECT (ts // 60000) * 60000 AS ts, (p // {bucket}) * {bucket} AS p, "
            f"sum(CASE WHEN m THEN 0 ELSE q::DOUBLE END) AS buy, "
            f"sum(CASE WHEN m THEN q::DOUBLE ELSE 0 END) AS sell FROM ({ticks}) GROUP BY 1, 2"
        )
    if fp:
        # chỉ lấy ngày UTC không có tick; footprint_1m cũng được tái gom theo bucket thô hơn
        day_has_ticks = f"(SELECT DISTINCT ts // 86400000 FROM ({ticks}))" if ticks else "(SELECT NULL::BIGINT WHERE false)"
        parts.append(
            f"SELECT ts, (p // {bucket}) * {bucket} AS p, sum(buy::DOUBLE) AS buy, sum(sell::DOUBLE) AS sell "
            f"FROM ({fp}) WHERE ts // 86400000 NOT IN {day_has_ticks} GROUP BY 1, 2"
        )
    if not parts:
        return None
    union = " UNION ALL ".join(parts)
    return (
        f"SELECT (ts // {tf_ms}) * {tf_ms} AS bar, p, sum(buy) AS buy, sum(sell) AS sell "
        f"FROM ({union}) GROUP BY 1, 2 ORDER BY 1, 2"
    )


def get_footprint(symbol: str, tf: str, start_ms: int | None, end_ms: int | None, limit: int, mult: int) -> dict:
    try:
        tf_ms = tickbars.tf_to_ms(tf)
        cfg = store.symbol_config(symbol)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    if tickbars.is_calendar(tf):
        raise HTTPException(400, "footprint không hỗ trợ khung tuần và tháng")
    if tf_ms < MINUTE or tf_ms % MINUTE:
        raise HTTPException(400, "footprint cần khung thời gian là bội của 1 phút")
    tick = cfg["tick"]
    if end_ms is None:
        end_ms = int(time.time() * 1000) // MINUTE * MINUTE + MINUTE
    if start_ms is None:
        start_ms = end_ms - limit * tf_ms
    if end_ms <= start_ms:
        raise HTTPException(400, "to phải lớn hơn from")
    if (end_ms - start_ms) // tf_ms > MAX_BARS:
        raise HTTPException(400, f"tối đa {MAX_BARS} nến mỗi yêu cầu")
    start_ms = start_ms // tf_ms * tf_ms
    sql = footprint_sql(symbol, tf_ms, start_ms, end_ms, mult)
    rows: list[list] = []
    if sql:
        con = store.query_conn()
        try:
            data = con.execute(sql + f" LIMIT {MAX_ROWS + 1}").fetchall()
        finally:
            con.close()
        if len(data) > MAX_ROWS:
            raise HTTPException(400, "quá nhiều dòng; thu hẹp khoảng thời gian hoặc tăng mult")
        rows = [[b, round(p * tick, 10), round(buy, 6), round(sell, 6)] for b, p, buy, sell in data]
    base = round(cfg["footprint_bucket"] / tick) * mult
    return {"symbol": symbol, "tf": tf, "tick": tick, "bucket": round(base * tick, 10),
            "from": start_ms, "to": end_ms, "rows": rows}


@router.get("/api/footprint")
def footprint_endpoint(
    symbol: str,
    tf: str = "1m",
    from_: int | None = Query(None, alias="from", description="ms, gồm"),
    to: int | None = Query(None, description="ms, không gồm"),
    limit: int = Query(100, ge=1, le=MAX_BARS, description="số nến khi không có from"),
    mult: int = Query(1, ge=1, le=1000, description="nhân bucket giá"),
) -> dict:
    with limits.heavy():
        return get_footprint(symbol.upper(), tf, from_, to, limit, mult)


def get_profile(symbol: str, start_ms: int, end_ms: int, mult: int) -> dict:
    """Volume profile của cả khoảng [start, end): mỗi mức giá một dòng [price, buy, sell]."""
    try:
        cfg = store.symbol_config(symbol)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    if end_ms <= start_ms:
        raise HTTPException(400, "to phải lớn hơn from")
    sql = footprint_sql(symbol, 10**12, start_ms, end_ms, mult)
    rows: list[list] = []
    if sql:
        con = store.query_conn()
        try:
            data = con.execute(f"SELECT p, sum(buy), sum(sell) FROM ({sql}) GROUP BY p ORDER BY p").fetchall()
        finally:
            con.close()
        rows = [[round(p * cfg["tick"], 10), round(b, 6), round(s, 6)] for p, b, s in data]
    bucket = round(round(cfg["footprint_bucket"] / cfg["tick"]) * mult * cfg["tick"], 10)
    return {"symbol": symbol, "from": start_ms, "to": end_ms, "bucket": bucket, "rows": rows}


@router.get("/api/profile")
def profile_endpoint(
    symbol: str,
    from_: int = Query(..., alias="from"),
    to: int = Query(...),
    mult: int = Query(1, ge=1, le=100000),
) -> dict:
    sym = symbol.upper()

    def run() -> dict:
        with limits.heavy():
            return get_profile(sym, from_, to, mult)
    return limits.coalesce(("profile", sym, from_, to, mult), limits.PROFILE_TTL, run)
