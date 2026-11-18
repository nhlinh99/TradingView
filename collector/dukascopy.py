"""Nến 1 phút XAUUSD cũ (trước khi có dữ liệu TVC) từ kho công khai của Dukascopy.

TradingView ẩn danh chỉ cho khoảng 5 ngày nến 1 phút, nên phần trước đó lấy ở đây: mỗi ngày một file
`BID_candles_min_1.bi5` (LZMA, mỗi nến 24 byte: giây từ 00:00 UTC, open, close, low, high là số nguyên giá×1000,
volume float32). Chỉ dùng được HTTP cổng 80; cổng 443 của host này bị chặn trên máy dự án.
Đây là endpoint công khai không có tài liệu chính thức; chỉ dùng cá nhân, gọi thưa.

Hai khác biệt với TVC, được hiệu chỉnh theo các ngày trùng nhau để chỗ nối liền mạch:
  - Giá là BID, thấp hơn TVC trung bình khoảng 0,13 USD: cộng thêm độ lệch trung bình đo được.
  - Volume là lot, TVC là số tick: nhân với hệ số tổng volume TVC / tổng volume Dukascopy trên các ngày trùng.
Nến không có giao dịch (volume 0, giá đứng yên) bị bỏ, giống TVC không phát nến giờ nghỉ.
Phần cũ này chỉ ghi các ngày TRƯỚC ngày TVC đầu tiên; không bao giờ ghi đè dữ liệu TVC.

Chạy:  python -m collector.dukascopy [--days 365]
"""
from __future__ import annotations

import argparse
import logging
import os
import lzma
import struct
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import httpx

from common import store

log = logging.getLogger("collector.dukascopy")

URL = "http://datafeed.dukascopy.com/datafeed/XAUUSD/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"   # tháng bắt đầu từ 0
SYMBOL = "XAUUSD"
ROW = 24


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=30.0, transport=transport, headers={"User-Agent": "Mozilla/5.0 tv-local/0.1"})


# Tên miền đôi khi trỏ vào CDN chỉ chạy HTTPS (301, rồi HTTPS bị 429); IP gốc vẫn phục vụ HTTP. Đo ngày 16/11/2026.
DIRECT_IP = os.environ.get("DUKASCOPY_IP", "194.8.15.180")
THROTTLE = (301, 403, 429)   # máy chủ chặn tạm thời sau khoảng 100 yêu cầu liên tiếp: 301 sang HTTPS (bị chặn), rồi 429
THROTTLE_WAIT = 300.0        # giây chờ khi bị chặn


class Throttled(RuntimeError):
    pass


def fetch_day(client: httpx.Client, day: date, tries: int = 4, sleep=time.sleep) -> list[tuple[int, float, float, float, float, float]]:
    """Nến của một ngày UTC: (ts_ms, open, high, low, close, volume). Ngày nghỉ (file rỗng hoặc 404) trả danh sách rỗng."""
    url = URL.format(y=day.year, m=day.month - 1, d=day.day)
    last: Exception | None = None
    direct = bool(DIRECT_IP)    # IP trực tiếp trước (không cần DNS, DNS ở đây chập chờn), tên miền khi IP lỗi
    for i in range(tries):
        try:
            if direct and DIRECT_IP:
                r = client.get(url.replace("datafeed.dukascopy.com", DIRECT_IP), headers={"Host": "datafeed.dukascopy.com"})
            else:
                r = client.get(url)
            if r.status_code == 404 or (r.status_code == 200 and not r.content):
                return []
            if r.status_code == 200:
                return parse_candles(r.content, day)
            if r.status_code in THROTTLE:
                if direct:                        # IP gốc cũng bị chuyển hướng: thử lại bằng tên miền trước khi coi là bị chặn
                    direct = False
                    continue
                raise Throttled(f"{url}: HTTP {r.status_code}")
            last = RuntimeError(f"HTTP {r.status_code}")
        except Throttled:
            raise
        except (httpx.HTTPError, lzma.LZMAError, ValueError) as e:
            last = e
            direct = False
        sleep(min(2 ** i, 10))
    raise RuntimeError(f"{url}: {last}")


def parse_candles(blob: bytes, day: date) -> list[tuple[int, float, float, float, float, float]]:
    raw = lzma.decompress(blob)
    if len(raw) % ROW:
        raise ValueError(f"độ dài {len(raw)} không chia hết cho {ROW}")
    base = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
    out = []
    for i in range(len(raw) // ROW):
        t, o, c, lo, hi, v = struct.unpack(">iiiiif", raw[i * ROW:(i + 1) * ROW])
        if v <= 0 and o == c == lo == hi:   # không có giao dịch: nến lấp chỗ trống
            continue
        out.append((base + t * 1000, o / 1000, hi / 1000, lo / 1000, c / 1000, float(v)))
    return out


def calibrate(duka: list[tuple], tvc_rows: list[tuple]) -> tuple[float, float]:
    """(độ lệch giá, hệ số volume) từ các nến trùng ts. Không đủ dữ liệu thì (0, 1)."""
    tv = {r[0]: r for r in tvc_rows}
    pairs = [(d, tv[d[0]]) for d in duka if d[0] in tv]
    if len(pairs) < 100:
        return 0.0, 1.0
    off = sum(store.from_int_price(SYMBOL, t[4]) - d[4] for d, t in pairs) / len(pairs)
    dv = sum(d[5] for d, _ in pairs)
    scale = sum(t[5] for _, t in pairs) / dv if dv > 0 else 1.0
    return off, scale


def to_bars(rows: list[tuple], offset: float, scale: float) -> list[tuple]:
    p = lambda x: store.to_int_price(SYMBOL, x + offset)   # noqa: E731
    return [(r[0], p(r[1]), p(r[2]), p(r[3]), p(r[4]), r[5] * scale, 0.0, 0.0) for r in rows]


def fetch_day_patient(client: httpx.Client, day: date, wait: float, sleep=time.sleep, tries: int = 6):
    """fetch_day, nhưng khi bị chặn tạm thời thì chờ `wait` giây rồi thử lại (tối đa `tries` lần)."""
    for i in range(tries):
        try:
            return fetch_day(client, day)
        except Throttled as e:
            log.warning("bị chặn tạm thời (%s); chờ %.0fs rồi thử lại (%d/%d)", e, wait, i + 1, tries)
            sleep(wait)
    raise Throttled(f"vẫn bị chặn sau {tries} lần chờ; chạy lại sau, các ngày đã nạp được giữ nguyên")


def sync(days: int = 365, client: httpx.Client | None = None, pause: float = 0.15, wait: float = THROTTLE_WAIT,
         force: bool = False) -> dict:
    """Ghi nến các ngày trước ngày TVC đầu tiên, lùi `days` ngày. Ngày đã có file thì bỏ qua (force: ghi lại)."""
    tvc_days = store.list_days("bars", SYMBOL)
    if not tvc_days:
        raise RuntimeError("chưa có dữ liệu TVC để làm mốc; chạy `python -m collector.tvc` trước")
    first_tvc = tvc_days[0]
    own = client is None
    client = client or make_client()
    try:
        # hiệu chỉnh trên các ngày TVC đầy đủ (bỏ ngày đầu, thường thiếu nến đầu ngày)
        cal_days = tvc_days[1:6] or tvc_days[:1]
        duka_cal: list[tuple] = []
        tvc_rows: list[tuple] = []
        for d in cal_days:
            duka_cal += fetch_day_patient(client, d, wait)
            start = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
            tvc_rows += store.read("bars", SYMBOL, start_ms=start, end_ms=start + 86_400_000)
            time.sleep(pause)
        offset, scale = calibrate(duka_cal, tvc_rows)
        log.info("hiệu chỉnh: giá %+.3f, volume ×%.1f (từ %d ngày trùng)", offset, scale, len(cal_days))

        written = bars_n = 0
        day = first_tvc - timedelta(days=1)
        while day >= first_tvc - timedelta(days=days):
            if not force and store.day_files("bars", SYMBOL, day):
                day -= timedelta(days=1)
                continue
            rows = fetch_day_patient(client, day, wait)
            if rows:
                by_day = defaultdict(list)
                for b in to_bars(rows, offset, scale):
                    by_day[datetime.fromtimestamp(b[0] / 1000, timezone.utc).date()].append(b)
                for dd, part in by_day.items():
                    if dd < first_tvc:   # không bao giờ ghi lên ngày của TVC
                        store.write_partition("bars", SYMBOL, dd, part)
                        written += 1
                        bars_n += len(part)
            day -= timedelta(days=1)
            time.sleep(pause)
        return {"days": written, "bars": bars_n, "price_offset": round(offset, 4), "volume_scale": round(scale, 2),
                "from": str(first_tvc - timedelta(days=days)), "to": str(first_tvc - timedelta(days=1))}
    finally:
        if own:
            client.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365, help="lùi bao nhiêu ngày trước ngày TVC đầu tiên")
    ap.add_argument("--pause", type=float, default=3.0, help="giây nghỉ giữa các ngày (máy chủ chặn nếu gọi dồn)")
    ap.add_argument("--force", action="store_true", help="ghi lại cả các ngày đã có")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("%s", sync(args.days, pause=args.pause, force=args.force))


if __name__ == "__main__":
    main()
