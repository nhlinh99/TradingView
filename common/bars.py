"""Dựng nến mọi timeframe từ tick, tính lúc truy vấn bằng DuckDB (không lưu từng timeframe).

Nến 1 phút "chuẩn" lấy từ kline của Binance (kho `bars`). Hàm ở đây dùng khi cần timeframe khác
(1s ... 1d), cho nến đang chạy, hoặc kiểm tra chéo.
"""
from __future__ import annotations

import re
from typing import Iterable

import duckdb

from . import store

_TF_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


def tf_to_ms(tf: str | int) -> int:
    """'1s', '5m', '1h', '1d' -> mili giây. Số nguyên được coi là mili giây."""
    if isinstance(tf, int):
        if tf <= 0:
            raise ValueError("timeframe phải dương")
        return tf
    m = _TF_RE.match(tf)
    if not m or int(m.group(1)) <= 0:
        raise ValueError(f"timeframe không hợp lệ: {tf!r} (ví dụ 1s, 5m, 1h, 1d)")
    return int(m.group(1)) * _UNIT_MS[m.group(2)]


def bars_with_last_id(
    symbol: str, tf: str | int, start_ms: int | None = None, end_ms: int | None = None
) -> list[tuple]:
    """Như bars_from_ticks nhưng thêm cột cuối: id lớn nhất của các tick trong nến.

    Trả về [(ts, o, h, l, c, v, buy_v, sell_v, last_id)].
    """
    step = tf_to_ms(tf)
    # chỉ đọc file của các ngày liên quan và lọc ts trước khi loại trùng (xem store.range_select)
    src = store.range_select("ticks", symbol, start_ms, end_ms)
    if src is None:
        return []
    sql = f"""
        SELECT (ts // {step}) * {step} AS bar_ts,
               first(p ORDER BY ts, id) AS o, max(p) AS h, min(p) AS l, last(p ORDER BY ts, id) AS c,
               sum(q::DOUBLE) AS v,
               sum(CASE WHEN m THEN 0 ELSE q::DOUBLE END) AS buy_v,
               sum(CASE WHEN m THEN q::DOUBLE ELSE 0 END) AS sell_v,
               max(id) AS last_id
        FROM ({src})
        GROUP BY 1 ORDER BY 1
    """
    con = duckdb.connect()
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def bars_from_ticks(
    symbol: str, tf: str | int, start_ms: int | None = None, end_ms: int | None = None
) -> list[tuple]:
    """Trả về [(ts, o, h, l, c, v, buy_v, sell_v)], ts = đầu nến (UTC), giá theo tick.

    - Nến lấy theo ts từ [start_ms, end_ms). Nến đầu/cuối có thể thiếu nếu khoảng cắt giữa nến;
      truyền mốc đã căn theo timeframe để tránh.
    - Mở/đóng theo thứ tự (ts, id). Mua chủ động = isBuyerMaker false.
    - Tick trùng id (backfill chồng collector) chỉ tính một lần.
    """
    return [r[:8] for r in bars_with_last_id(symbol, tf, start_ms, end_ms)]


def bars_from_tick_rows(ticks: Iterable[tuple], tf: str | int) -> list[tuple]:
    """Như bars_from_ticks nhưng cho danh sách tick trong bộ nhớ (ts, id, p, q, m). Không loại trùng."""
    step = tf_to_ms(tf)
    out: dict[int, list] = {}
    for ts, _id, p, q, m in sorted(ticks, key=lambda t: (t[0], t[1])):
        t = ts // step * step
        b = out.get(t)
        buy, sell = (0.0, q) if m else (q, 0.0)
        if b is None:
            out[t] = [t, p, p, p, p, q, buy, sell]
        else:
            b[2] = max(b[2], p)
            b[3] = min(b[3], p)
            b[4] = p
            b[5] += q
            b[6] += buy
            b[7] += sell
    return [tuple(v) for _, v in sorted(out.items())]


def combine_bars(earlier: tuple, later: tuple) -> tuple:
    """Gộp hai nến cùng ts mà mọi tick của `later` xảy ra sau mọi tick của `earlier`."""
    return (earlier[0], earlier[1], max(earlier[2], later[2]), min(earlier[3], later[3]), later[4],
            earlier[5] + later[5], earlier[6] + later[6], earlier[7] + later[7])
