"""Dựng nến mọi timeframe từ tick, tính lúc truy vấn bằng DuckDB (không lưu từng timeframe).

Nến 1 phút "chuẩn" lấy từ kline của Binance (kho `bars`). Hàm ở đây dùng khi cần timeframe khác
(1s ... 1d) hoặc kiểm tra chéo.
"""
from __future__ import annotations

import re

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


def bars_from_ticks(
    symbol: str, tf: str | int, start_ms: int | None = None, end_ms: int | None = None
) -> list[tuple]:
    """Trả về [(ts, o, h, l, c, v, buy_v, sell_v)], ts = đầu nến (UTC), giá theo tick.

    - Nến lấy theo ts từ [start_ms, end_ms). Nến đầu/cuối có thể thiếu nếu khoảng cắt giữa nến;
      truyền mốc đã căn theo timeframe để tránh.
    - Mở/đóng theo thứ tự (ts, id). Mua chủ động = isBuyerMaker false.
    - Tick trùng id (backfill chồng collector) chỉ tính một lần.
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
               sum(CASE WHEN m THEN q::DOUBLE ELSE 0 END) AS sell_v
        FROM ({src})
        GROUP BY 1 ORDER BY 1
    """
    con = duckdb.connect()
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()
