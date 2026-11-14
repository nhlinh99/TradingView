"""GET /api/bars: nến cho biểu đồ.

Nguồn:
  - tf là bội của 1 phút: gộp từ nến 1 phút. Các phút đã đóng lấy từ kline (kho `bars`). Các phút sau
    nến kline cuối cùng, kể cả phút đang chạy, dựng từ tick, nên nến đang hình thành luôn có.
  - tf dưới 1 phút (1s, 5s, ...): dựng thẳng từ tick.
Giá trả về là số thực (đã đổi từ số nguyên tick). Mỗi nến: [ts, o, h, l, c, v, buy_v, sell_v].
"""
from __future__ import annotations

import time

import duckdb
from fastapi import APIRouter, HTTPException, Query

from common import bars as tickbars
from common import store

router = APIRouter()

MAX_LIMIT = 5000
MINUTE = 60_000


def _convert(rows: list[tuple], tick: float) -> list[list]:
    return [[r[0], round(r[1] * tick, 10), round(r[2] * tick, 10), round(r[3] * tick, 10),
             round(r[4] * tick, 10), round(r[5], 6), round(r[6], 6), round(r[7], 6)] for r in rows]


def minute_tail(symbol: str, after_ms: int | None, start_ms: int, end_ms: int) -> list[tuple]:
    """Nến 1 phút dựng từ tick cho các phút sau `after_ms` (ts của nến kline cuối cùng)."""
    first = start_ms if after_ms is None else max(start_ms, after_ms + MINUTE)
    if first >= end_ms:
        return []
    return tickbars.bars_from_ticks(symbol, "1m", first, end_ms)


def aggregate_minutes(symbol: str, tf_ms: int, start_ms: int, end_ms: int) -> list[tuple]:
    """Gộp nến 1 phút (kline + phần đuôi dựng từ tick) thành nến tf_ms."""
    src = store.range_select("bars", symbol, start_ms, end_ms)
    last_kline = None
    if src is not None:
        con = duckdb.connect()
        try:
            last_kline = con.execute(f"SELECT max(ts) FROM ({src})").fetchall()[0][0]
        finally:
            con.close()
    tail = minute_tail(symbol, last_kline, start_ms, end_ms)
    if src is None and not tail:
        return []
    con = duckdb.connect()
    try:
        con.execute("CREATE TEMP TABLE tail (ts BIGINT, o INTEGER, h INTEGER, l INTEGER, c INTEGER, "
                    "v DOUBLE, buy_v DOUBLE, sell_v DOUBLE)")
        if tail:
            con.executemany("INSERT INTO tail VALUES (?,?,?,?,?,?,?,?)", tail)
        parts = []
        if src is not None:
            parts.append(f"SELECT ts, o, h, l, c, v::DOUBLE v, buy_v::DOUBLE buy_v, sell_v::DOUBLE sell_v FROM ({src})")
        parts.append("SELECT * FROM tail")
        sql = f"""
            SELECT (ts // {tf_ms}) * {tf_ms} AS t,
                   first(o ORDER BY ts) AS o, max(h) AS h, min(l) AS l, last(c ORDER BY ts) AS c,
                   sum(v) AS v, sum(buy_v) AS buy_v, sum(sell_v) AS sell_v
            FROM ({' UNION ALL '.join(parts)})
            GROUP BY 1 ORDER BY 1
        """
        return con.execute(sql).fetchall()
    finally:
        con.close()


def get_bars(symbol: str, tf: str, start_ms: int | None, end_ms: int | None, limit: int) -> dict:
    try:
        cfg = store.symbol_config(symbol)
    except KeyError:
        raise HTTPException(404, f"symbol không có trong config/symbols.toml: {symbol}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    try:
        tf_ms = tickbars.tf_to_ms(tf)
    except ValueError as e:
        raise HTTPException(422, str(e))
    now_ms = int(time.time() * 1000)
    if end_ms is None:
        end_ms = now_ms + 1  # gồm cả nến đang chạy
    if start_ms is None:
        start_ms = end_ms - limit * tf_ms
    if start_ms >= end_ms:
        raise HTTPException(422, "from phải nhỏ hơn to")
    if (end_ms - start_ms) // tf_ms > MAX_LIMIT * 4:
        raise HTTPException(422, f"khoảng thời gian quá lớn cho timeframe {tf}")
    start_ms = start_ms // tf_ms * tf_ms          # căn đầu nến để nến đầu tiên đủ dữ liệu

    if tf_ms < MINUTE:
        rows = tickbars.bars_from_ticks(symbol, tf_ms, start_ms, end_ms)
    elif tf_ms % MINUTE == 0:
        rows = aggregate_minutes(symbol, tf_ms, start_ms, end_ms)
    else:
        raise HTTPException(422, "timeframe từ 1 phút trở lên phải là bội của 1 phút")
    rows = rows[-limit:]
    return {"symbol": symbol, "tf": tf, "tf_ms": tf_ms, "tick": cfg["tick"], "bars": _convert(rows, cfg["tick"])}


@router.get("/api/bars")
def bars_endpoint(
    symbol: str,
    tf: str = "1m",
    from_: int | None = Query(None, alias="from", description="ms, gồm"),
    to: int | None = Query(None, description="ms, không gồm"),
    limit: int = Query(1000, ge=1, le=MAX_LIMIT),
) -> dict:
    return get_bars(symbol.upper(), tf, from_, to, limit)
