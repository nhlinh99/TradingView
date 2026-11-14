"""Thu snapshot chuỗi quyền chọn BTC từ Deribit (API công khai, không cần khoá).

Một lần gọi `public/get_book_summary_by_currency?currency=BTC&kind=option` trả về OI, mark IV và giá underlying
của mọi hợp đồng đang niêm yết (khoảng 1000). Gamma không có trong endpoint này nên tính từ IV (common/gex.py).
Ghi vào kho kind `options` mỗi 15 phút. Deribit ghi trong changelog rằng OI cập nhật trễ (khoảng 8 giờ một lần);
UI hiện nhãn này.

Chạy:  python -m collector.deribit            # lặp mỗi 15 phút
       python -m collector.deribit --once     # một snapshot rồi thoát
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

import httpx

from common import gex, store

log = logging.getLogger("collector.deribit")

BASE = "https://www.deribit.com/api/v2"
SYMBOL = "BTCUSDT"           # chỗ lưu trong kho; GEX này dùng cho BTC
INTERVAL_S = 15 * 60


def fetch_summary(client: httpx.Client, currency: str = "BTC", tries: int = 5) -> list[dict]:
    last: Exception | None = None
    for i in range(tries):
        try:
            r = client.get(f"{BASE}/public/get_book_summary_by_currency", params={"currency": currency, "kind": "option"})
            if r.status_code == 200:
                return r.json()["result"]
            last = RuntimeError(f"HTTP {r.status_code}")
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except (httpx.HTTPError, KeyError, ValueError) as e:
            last = e
        time.sleep(min(2 ** i, 30))
    raise RuntimeError(f"Deribit không trả về dữ liệu: {last}")


def snapshot_to_store(summary: list[dict], now_ms: int) -> int:
    """Ghi một snapshot. Trả về số dòng đã ghi (0 nếu không có dữ liệu dùng được)."""
    rows, spot = gex.option_rows(summary)
    if not rows or spot is None:
        return 0
    ts = now_ms // 1000 * 1000
    day = datetime.fromtimestamp(ts / 1000, timezone.utc).date()
    out = [(ts, e, k, cp, oi, iv, fwd, spot) for e, k, cp, oi, iv, fwd in rows]
    store.write_partition("options", SYMBOL, day, out, part=f"s{ts}")
    return len(out)


def run_once(client: httpx.Client) -> int:
    n = snapshot_to_store(fetch_summary(client), int(time.time() * 1000))
    log.info("Deribit: đã ghi %d hợp đồng", n)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with httpx.Client(timeout=30) as client:
        while True:
            try:
                run_once(client)
            except Exception:  # noqa: BLE001 - vòng lặp không được chết vì một lần lỗi
                log.exception("snapshot lỗi; thử lại ở chu kỳ sau")
            if args.once:
                return
            time.sleep(INTERVAL_S - time.time() % INTERVAL_S)   # căn theo mốc 15 phút


if __name__ == "__main__":
    main()
