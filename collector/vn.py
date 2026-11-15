"""Cổ phiếu Việt Nam, chỉ rổ VN100 (HOSE). Hai nguồn công khai, không cần khoá:

  - Danh sách VN100 và bảng giá 3 mức: SSI iBoard (`iboard-query.ssi.com.vn/stock/group/VN100`).
  - Nến lịch sử (1 phút trở lên, khoảng 1 năm): VNDirect dchart (`dchart-api.vndirect.com.vn/dchart/history`).
Cả hai là endpoint không có tài liệu chính thức, phục vụ web của nhà cung cấp. Có thể đổi hoặc chặn bất cứ lúc nào;
chỉ dùng cho mục đích cá nhân, gọi thưa (xem docs/plan/07-vn100.md). Giá nến là nghìn đồng, đã điều chỉnh theo sự kiện doanh nghiệp.

Lệnh:
  python -m collector.vn refresh-vn100              # ghi config/vn100.json từ SSI
  python -m collector.vn bars [--symbols VNM,FPT] [--days 400]   # nạp nến 1 phút vào kho `bars`
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

import httpx

from common import store

log = logging.getLogger("collector.vn")

SSI_URL = "https://iboard-query.ssi.com.vn/stock/group/VN100"
DCHART_URL = "https://dchart-api.vndirect.com.vn/dchart/history"
DAY_MS = 86_400_000
UA = {"User-Agent": "Mozilla/5.0 tv-local/0.1", "Origin": "https://iboard.ssi.com.vn"}


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=30.0, transport=transport, headers=UA)


def _get(client: httpx.Client, url: str, params: dict | None = None, tries: int = 5, sleep=time.sleep):
    last: Exception | None = None
    for i in range(tries):
        try:
            r = client.get(url, params=params)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}")
            if r.status_code not in (403, 429, 500, 502, 503, 504):
                break
        except (httpx.HTTPError, ValueError) as e:
            last = e
        sleep(min(2 ** i, 30))
    raise RuntimeError(f"{url}: {last}")


# ---------- danh sách VN100 ----------

def fetch_group(client: httpx.Client) -> list[dict]:
    d = _get(client, SSI_URL)
    if d.get("code") != "SUCCESS":
        raise RuntimeError(f"SSI trả về mã {d.get('code')!r}")
    return d["data"]


def refresh_vn100(client: httpx.Client, path=None) -> list[str]:
    """Ghi config/vn100.json. Từ chối nếu danh sách không đúng 100 mã hoặc có mã ngoài HOSE."""
    rows = fetch_group(client)
    syms = sorted({r["stockSymbol"] for r in rows if r.get("stockType") == "s" or r.get("stockType") is None})
    bad = [r["stockSymbol"] for r in rows if r.get("exchange") != "hose"]
    if len(syms) != 100 or bad:
        raise RuntimeError(f"VN100 không hợp lệ: {len(syms)} mã, ngoài HOSE: {bad}")
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": SSI_URL, "symbols": syms}
    (path or store.VN100_FILE).write_text(json.dumps(out, indent=1), encoding="utf-8")
    log.info("VN100: %d mã", len(syms))
    return syms


# ---------- nến ----------

def fetch_history(client: httpx.Client, symbol: str, resolution: str, start_s: int, end_s: int) -> dict:
    d = _get(client, DCHART_URL, {"resolution": resolution, "symbol": symbol, "from": start_s, "to": end_s})
    if d.get("s") not in ("ok", "no_data"):
        raise RuntimeError(f"dchart {symbol}: trạng thái {d.get('s')!r}")
    return d


def history_to_bars(symbol: str, d: dict) -> list[tuple]:
    """Đổi phản hồi dchart sang các dòng (ts, o, h, l, c, v, buy_v, sell_v). Không có phía mua/bán nên để 0."""
    out = []
    for t, o, h, l, c, v in zip(d.get("t", []), d.get("o", []), d.get("h", []), d.get("l", []), d.get("c", []), d.get("v", [])):
        out.append((int(t) * 1000, store.to_int_price(symbol, o), store.to_int_price(symbol, h),
                    store.to_int_price(symbol, l), store.to_int_price(symbol, c), float(v), 0.0, 0.0))
    return out


def last_bar_ts(symbol: str) -> int | None:
    days = store.list_days("bars", symbol)
    if not days:
        return None
    rows = store.read("bars", symbol, start_ms=int(datetime(days[-1].year, days[-1].month, days[-1].day,
                                                              tzinfo=timezone.utc).timestamp() * 1000))
    return max((r[0] for r in rows), default=None)


def sync_bars(client: httpx.Client, symbol: str, days: int = 400, now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    last = last_bar_ts(symbol)
    start_ms = (last if last is not None else now_ms - days * DAY_MS) // DAY_MS * DAY_MS   # về đầu ngày UTC
    d = fetch_history(client, symbol, "1", start_ms // 1000, now_ms // 1000)
    bars = history_to_bars(symbol, d)
    by_day = defaultdict(list)
    for b in bars:
        by_day[datetime.fromtimestamp(b[0] / 1000, timezone.utc).date()].append(b)
    for day, rows in by_day.items():
        store.write_partition("bars", symbol, day, rows)
    return {"bars": len(bars), "days": len(by_day)}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh-vn100")
    b = sub.add_parser("bars")
    b.add_argument("--symbols")
    b.add_argument("--days", type=int, default=400)
    b.add_argument("--pause", type=float, default=0.5, help="giây nghỉ giữa các mã")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with make_client() as client:
        if args.cmd == "refresh-vn100":
            refresh_vn100(client)
            return
        syms = args.symbols.split(",") if args.symbols else store.vn100_symbols()
        if not syms:
            raise SystemExit("chưa có config/vn100.json; chạy refresh-vn100 trước")
        fail = []
        for i, s in enumerate(syms, 1):
            try:
                log.info("[%d/%d] %s %s", i, len(syms), s, sync_bars(client, s, args.days))
            except Exception as e:  # noqa: BLE001 - một mã lỗi không dừng cả lượt
                log.warning("%s lỗi: %s", s, e)
                fail.append(s)
            time.sleep(args.pause)
        if fail:
            log.warning("mã lỗi: %s", ",".join(fail))


if __name__ == "__main__":
    main()
