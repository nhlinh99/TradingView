"""Ghi sổ lệnh 3 mức của VN100 (HOSE) theo thời gian, từ bảng giá SSI iBoard (REST, không cần khoá).

Mỗi `INTERVAL_S` giây gọi một lần `stock/group/VN100` (một yêu cầu cho cả 100 mã). Chỉ ghi dòng khi có thay đổi
so với lần ghi trước của mã đó. Bảng giá chỉ có 3 mức mỗi phía và các bộ đếm cộng dồn trong phiên:
`tv` (tổng khối lượng khớp), `bu`/`sd` ("mua lên"/"bán xuống", hướng của lệnh khớp, không chắc là bên chủ động).
Vì lấy mẫu mỗi vài giây nên không phải từng lệnh khớp: delta lấy từ hiệu của bộ đếm giữa hai lần mẫu là xấp xỉ.

Chỉ chạy trong giờ giao dịch HOSE (thứ Hai đến thứ Sáu, 08:55-15:05 giờ Việt Nam).
Chạy:  python -m collector.vn_book [--interval 10] [--always]
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from collector import vn
from common import store

log = logging.getLogger("collector.vn_book")

INTERVAL_S = 10
FLUSH_S = 60
VN_TZ = timezone(timedelta(hours=7))
COLUMNS = ("b1p", "b1v", "b2p", "b2v", "b3p", "b3v", "a1p", "a1v", "a2p", "a2v", "a3p", "a3v", "last", "tv", "bu", "sd")
FIELDS = ("best1Bid", "best1BidVol", "best2Bid", "best2BidVol", "best3Bid", "best3BidVol",
          "best1Offer", "best1OfferVol", "best2Offer", "best2OfferVol", "best3Offer", "best3OfferVol",
          "matchedPrice", "nmTotalTradedQty", "stockBUVol", "stockSDVol")


def in_session(now: datetime) -> bool:
    t = now.astimezone(VN_TZ)
    return t.weekday() < 5 and (8, 55) <= (t.hour, t.minute) <= (15, 5)


def _int(v) -> int:
    """Giá có thể là 'ATO'/'ATC' hoặc rỗng ngoài phiên liên tục: ghi 0."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def row_values(rec: dict) -> tuple:
    return tuple(_int(rec.get(f)) for f in FIELDS)


class Recorder:
    def __init__(self) -> None:
        self.last: dict[str, tuple] = {}
        self.buf: dict[str, list[tuple]] = {}
        self.seq = 0

    def feed(self, records: list[dict], ts_ms: int) -> int:
        """Nhận một lần lấy mẫu; trả về số dòng mới (mã có thay đổi)."""
        n = 0
        for rec in records:
            sym = rec.get("stockSymbol")
            if not sym:
                continue
            vals = row_values(rec)
            if self.last.get(sym) == vals:
                continue
            self.last[sym] = vals
            self.buf.setdefault(sym, []).append((ts_ms, *vals))
            n += 1
        return n

    def flush(self) -> int:
        """Ghi mỗi mã một file part theo ngày UTC của dòng; trả về số dòng đã ghi."""
        total = 0
        self.seq += 1
        for sym, rows in list(self.buf.items()):
            by_day: dict = {}
            for r in rows:
                by_day.setdefault(datetime.fromtimestamp(r[0] / 1000, timezone.utc).date(), []).append(r)
            for day, rs in by_day.items():
                store.write_partition("vn_book", sym, day, rs, part=f"p{int(rs[0][0])}")
                total += len(rs)
        self.buf.clear()
        return total


def run(client: httpx.Client, interval: float, always: bool) -> None:
    rec = Recorder()
    next_flush = time.time() + FLUSH_S
    while True:
        now = datetime.now(timezone.utc)
        if always or in_session(now):
            try:
                n = rec.feed(vn.fetch_group(client), int(time.time() * 1000))
                log.debug("%d mã đổi", n)
            except Exception as e:  # noqa: BLE001 - lỗi mạng một lần không được làm chết vòng lặp
                log.warning("lấy bảng giá lỗi: %s", e)
        if time.time() >= next_flush:
            try:
                log.info("ghi %d dòng", rec.flush())
            except Exception:  # noqa: BLE001
                log.exception("ghi lỗi; giữ bộ đệm, thử lại lần sau")
            next_flush = time.time() + FLUSH_S
        time.sleep(max(0.5, interval - (time.time() % interval)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=INTERVAL_S)
    ap.add_argument("--always", action="store_true", help="bỏ qua kiểm tra giờ giao dịch (để thử)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with vn.make_client() as client:
        run(client, args.interval, args.always)


if __name__ == "__main__":
    main()
