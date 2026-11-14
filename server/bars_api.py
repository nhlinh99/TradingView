"""GET /api/bars: nến cho biểu đồ.

Nguồn:
  - tf là bội của 1 phút: gộp từ nến 1 phút. Các phút đã đóng lấy từ kline (kho `bars`). Các phút sau
    nến kline cuối cùng, kể cả phút đang chạy, dựng từ tick, nên nến đang hình thành luôn có.
  - tf dưới 1 phút (1s, 5s, ...): dựng thẳng từ tick.
  - Nến mới nhất (yêu cầu không có `to`): collector chỉ ghi tick mỗi 60 giây, nên server lấy thêm các
    lệnh khớp sau tick cuối cùng đã lưu từ REST của Binance và gộp vào, để nến đang chạy đủ tới từng giây.
Phản hồi có `last_trade_id`: id lệnh khớp mới nhất đã nằm trong nến. Trình duyệt chỉ áp dụng lệnh khớp
WebSocket có id lớn hơn, để không đếm trùng.
Giá trả về là số thực (đã đổi từ số nguyên tick). Mỗi nến: [ts, o, h, l, c, v, buy_v, sell_v].
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import duckdb
import httpx
from fastapi import APIRouter, HTTPException, Query

from collector import binance
from common import bars as tickbars
from common import store

log = logging.getLogger("server.bars")

router = APIRouter()

MAX_LIMIT = 5000
MINUTE = 60_000
REST_TAIL_MAX = 5000          # tối đa số lệnh khớp lấy từ REST cho phần đuôi

# Có thể thay trong test
rest_client_factory: Callable[[], httpx.Client] = binance.make_client


def _convert(rows: list[tuple], tick: float) -> list[list]:
    return [[r[0], round(r[1] * tick, 10), round(r[2] * tick, 10), round(r[3] * tick, 10),
             round(r[4] * tick, 10), round(r[5], 6), round(r[6], 6), round(r[7], 6)] for r in rows]


def fetch_rest_ticks(symbol: str, from_id: int) -> list[tuple]:
    """Lệnh khớp có id >= from_id từ REST. Lỗi mạng: trả những gì đã lấy được (có thể rỗng)."""
    rows: list[tuple] = []
    client = rest_client_factory()
    try:
        for t in binance.iter_agg_trades(client, symbol, from_id, pause=0.0):
            rows.append(binance.agg_trade_to_tick(symbol, t))
            if len(rows) >= REST_TAIL_MAX:
                break
    except Exception as e:  # noqa: BLE001
        log.warning("%s: không lấy được đuôi từ REST (%s: %s); dùng dữ liệu đã lưu", symbol, type(e).__name__, e)
    finally:
        client.close()
    return rows


def merge_tail(stored: list[tuple], extra: list[tuple]) -> list[tuple]:
    """Gộp nến dựng từ tick đã lưu với nến dựng từ lệnh khớp REST (mọi lệnh REST đến sau lệnh đã lưu)."""
    by_ts = {b[0]: b for b in stored}
    for b in extra:
        by_ts[b[0]] = tickbars.combine_bars(by_ts[b[0]], b) if b[0] in by_ts else b
    return [by_ts[k] for k in sorted(by_ts)]


def tick_bars(symbol: str, tf_ms: int, first_ms: int, end_ms: int, live: bool) -> tuple[list[tuple], int | None]:
    """Nến dựng từ tick trong [first_ms, end_ms), kèm id lệnh khớp mới nhất. live=True: thêm đuôi từ REST."""
    if first_ms >= end_ms:
        return [], None
    rows = tickbars.bars_with_last_id(symbol, tf_ms, first_ms, end_ms)
    bars = [r[:8] for r in rows]
    last_id = max((r[8] for r in rows), default=None)
    if live and last_id is not None:
        extra = fetch_rest_ticks(symbol, last_id + 1)
        if extra:
            bars = merge_tail(bars, tickbars.bars_from_tick_rows(extra, tf_ms))
            last_id = max(last_id, max(t[1] for t in extra))
    return bars, last_id


def aggregate_minutes(symbol: str, tf_ms: int, start_ms: int, end_ms: int, live: bool) -> tuple[list[tuple], int | None]:
    """Gộp nến 1 phút (kline + phần đuôi dựng từ tick) thành nến tf_ms."""
    src = store.range_select("bars", symbol, start_ms, end_ms)
    last_kline = None
    if src is not None:
        con = duckdb.connect()
        try:
            last_kline = con.execute(f"SELECT max(ts) FROM ({src})").fetchall()[0][0]
        finally:
            con.close()
    first = start_ms if last_kline is None else max(start_ms, last_kline + MINUTE)
    tail, last_id = tick_bars(symbol, MINUTE, first, end_ms, live)
    if src is None and not tail:
        return [], last_id
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
        return con.execute(sql).fetchall(), last_id
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
    live = end_ms is None          # chỉ yêu cầu nến mới nhất mới cần đuôi từ REST
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
        rows, last_id = tick_bars(symbol, tf_ms, start_ms, end_ms, live)
    elif tf_ms % MINUTE == 0:
        rows, last_id = aggregate_minutes(symbol, tf_ms, start_ms, end_ms, live)
    else:
        raise HTTPException(422, "timeframe từ 1 phút trở lên phải là bội của 1 phút")
    rows = rows[-limit:]
    return {"symbol": symbol, "tf": tf, "tf_ms": tf_ms, "tick": cfg["tick"], "last_trade_id": last_id,
            "bars": _convert(rows, cfg["tick"])}


@router.get("/api/bars")
def bars_endpoint(
    symbol: str,
    tf: str = "1m",
    from_: int | None = Query(None, alias="from", description="ms, gồm"),
    to: int | None = Query(None, description="ms, không gồm. Bỏ trống để lấy tới nến đang chạy"),
    limit: int = Query(1000, ge=1, le=MAX_LIMIT),
) -> dict:
    return get_bars(symbol.upper(), tf, from_, to, limit)
