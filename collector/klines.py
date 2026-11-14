"""Đồng bộ nến 1 phút từ REST vào kho `bars`.

Chạy:  python -m collector.klines --symbol BTCUSDT --days 30
Chỉ ghi nến đã đóng. Mỗi ngày UTC một file chuẩn `date=YYYY-MM-DD.parquet`, ghi lại cả ngày mỗi lần
chạy (idempotent). Chạy lại sẽ tiếp từ đầu ngày của nến cuối cùng đã lưu.
"""
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from datetime import datetime, timezone

import httpx

from collector import binance
from common import store

DAY_MS = 86_400_000


def _day(ts_ms: int):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()


def last_bar_ts(symbol: str) -> int | None:
    rows = store.read("bars", symbol, columns=["ts"])
    return rows[-1][0] if rows else None


def sync(symbol: str, start_ms: int | None = None, now_ms: int | None = None,
         client: httpx.Client | None = None, days: int = 30) -> dict:
    """Lấy nến 1m đã đóng từ start_ms (mặc định: tiếp từ nến cuối đã lưu, hoặc `days` ngày trước).

    Trả về thống kê: số nến, số ngày đã ghi, khoảng thời gian.
    """
    own = client is None
    client = client or binance.make_client()
    try:
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        step = binance.INTERVAL_MS["1m"]
        end_ms = (now_ms // step) * step  # nến đang chạy có ts == end_ms, loại ra
        if start_ms is None:
            last = last_bar_ts(symbol)
            start_ms = last if last is not None else end_ms - days * DAY_MS
        start_ms = (start_ms // DAY_MS) * DAY_MS  # bắt đầu từ đầu ngày để ghi lại trọn ngày
        by_day: dict = defaultdict(list)
        for k in binance.iter_klines(client, symbol, "1m", start_ms, end_ms):
            by_day[_day(int(k[0]))].append(binance.kline_to_bar(symbol, k))
        for day, bars in by_day.items():
            # Ngày đã có dữ liệu cũ hơn start_ms không xảy ra: start_ms đã căn về đầu ngày.
            store.write_partition("bars", symbol, day, bars)
        n = sum(len(v) for v in by_day.values())
        return {"bars": n, "days": len(by_day), "from_ms": start_ms, "to_ms": end_ms}
    finally:
        if own:
            client.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=30, help="số ngày lấy nếu chưa có dữ liệu")
    a = ap.parse_args()
    s = sync(a.symbol, days=a.days)
    print(f"{a.symbol}: {s['bars']} nến 1m, {s['days']} ngày")


if __name__ == "__main__":
    main()
