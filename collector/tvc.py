"""XAUUSD (vàng giao ngay) lấy từ TradingView, nguồn TVC. Chỉ có nến, không có tick và không có sổ lệnh.

Dùng websocket công khai của biểu đồ TradingView với tài khoản ẩn danh (`unauthorized_user_token`).
Đây là endpoint không có tài liệu chính thức; TradingView có thể đổi hoặc chặn bất cứ lúc nào, và điều khoản
của họ không cho phép dùng lại dữ liệu ngoài cá nhân. Chỉ dùng cá nhân, gọi thưa.
`TVC:XAUUSD` bị từ chối với tài khoản ẩn danh ("invalid symbol"); `TVC:GOLD` (CFD vàng, USD/oz) là mã TVC
cho cùng sản phẩm và chạy được, nên dùng nó. Volume là số tick của nhà cung cấp, không phải khối lượng khớp thật.

Chạy:  python -m collector.tvc [--days 30]     (nạp nến 1 phút vào kho `bars`, mã XAUUSD)
       python -m collector.tvc --history        (nạp lịch sử dài của các khung 5m, 15m, 1h, 4h, 1d, 1w, 1M)

Nến 1 phút ẩn danh chỉ sâu khoảng 5 ngày, còn khung lớn sâu hơn nhiều (5m ~1 tháng, 1h ~10 tháng, 4h ~4 năm, 1d hàng
chục năm). Các khung lớn lưu riêng ở DATA_DIR/tvc/XAUUSD/<khung>.json và được server trả đúng khung đó.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import string
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

import websockets

from common import store

log = logging.getLogger("collector.tvc")

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
TV_SYMBOL = "TVC:GOLD"
SYMBOL = "XAUUSD"
DAY_MS = 86_400_000
CHUNK = 5000          # số nến mỗi lần xin
MAX_CHUNKS = 200      # chặn vòng lặp vô hạn


def _frame(method: str, params: list) -> str:
    s = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(s)}~m~{s}"


def _sid(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def parse_frames(raw: str) -> list[str]:
    return [p for p in re.split(r"~m~\d+~m~", raw) if p]


def series_rows(msg: dict, name: str = "sds_1") -> list[list[float]]:
    """Các dòng [t, o, h, l, c, v] trong một thông điệp timescale_update. Nến có thể thiếu volume."""
    out = []
    for item in msg["p"][1].get(name, {}).get("s", []):
        v = item["v"]
        out.append(list(v) + [0.0] * (6 - len(v)))
    return out


def to_bars(rows: list[list[float]]) -> list[tuple]:
    return [(int(r[0]) * 1000, store.to_int_price(SYMBOL, r[1]), store.to_int_price(SYMBOL, r[2]),
             store.to_int_price(SYMBOL, r[3]), store.to_int_price(SYMBOL, r[4]), float(r[5]), 0.0, 0.0)
            for r in rows]


async def fetch_minutes(start_s: int, timeout: float = 20.0, connect=websockets.connect, count: int = CHUNK, res: str = "1") -> list[list[float]]:
    """Nến 1 phút mới nhất lùi tới start_s (giây), cũ trước. Dừng khi đủ hoặc nguồn hết lịch sử (ẩn danh: khoảng 5 ngày)."""
    got: dict[int, list[float]] = {}
    async with connect(WS_URL, origin="https://www.tradingview.com", max_size=None) as ws:
        cs = _sid("cs_")
        sym = "=" + json.dumps({"symbol": TV_SYMBOL, "adjustment": "splits", "session": "regular"})
        for m, p in [("set_auth_token", ["unauthorized_user_token"]), ("chart_create_session", [cs, ""]),
                     ("resolve_symbol", [cs, "sym", sym]),
                     ("create_series", [cs, "sds_1", "s1", "sym", res, count, ""])]:
            await ws.send(_frame(m, p))
        chunks = 0
        last_new = 0
        deadline = time.monotonic() + timeout   # hạn chờ dữ liệu; heartbeat không làm mới hạn này
        while chunks < MAX_CHUNKS:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"TradingView không trả nến trong {timeout:.0f}s")
            raw = await asyncio.wait_for(ws.recv(), left)
            done = False
            for part in parse_frames(raw):
                if part.startswith("~h~"):
                    await ws.send(f"~m~{len(part)}~m~{part}")
                    continue
                d = json.loads(part)
                m = d.get("m")
                if m in ("symbol_error", "series_error", "critical_error"):
                    raise RuntimeError(f"TradingView: {m} {d.get('p')}")
                if m == "timescale_update":
                    rows = series_rows(d)
                    new = [r for r in rows if int(r[0]) not in got]
                    for r in rows:
                        got[int(r[0])] = r
                    chunks += 1
                    deadline = time.monotonic() + timeout
                    log.info("đợt %d: %d nến mới, cũ nhất %s", chunks, len(new), datetime.fromtimestamp(min(got), timezone.utc))
                    last_new = len(new)
                elif m == "series_completed":
                    # nguồn ẩn danh chỉ cho khoảng 7.800 nến 1 phút, rồi báo data_completed (thường là "limit")
                    info = d["p"][-1] if isinstance(d.get("p", [None])[-1], dict) else {}
                    if info.get("data_completed") or not last_new or (got and min(got) <= start_s):
                        done = True
                    else:
                        await ws.send(_frame("request_more_data", [cs, "sds_1", CHUNK]))
            if done:
                break
    return [got[k] for k in sorted(got) if k >= start_s]


def sync(days: int = 30, now_ms: int | None = None, fetch=fetch_minutes) -> dict:
    from collector import vn   # last_bar_ts đọc kho `bars`, không phụ thuộc nguồn
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    last = vn.last_bar_ts(SYMBOL)
    start_ms = (last if last is not None else now_ms - days * DAY_MS) // DAY_MS * DAY_MS   # về đầu ngày UTC
    need = min(CHUNK, (now_ms - start_ms) // 60_000 + 10)   # chỉ xin đủ số nến cần, để lần làm mới đuôi nhanh
    rows = asyncio.run(fetch(start_ms // 1000, count=need)) if fetch is fetch_minutes else asyncio.run(fetch(start_ms // 1000))
    bars = to_bars(rows)
    by_day = defaultdict(list)
    for b in bars:
        by_day[datetime.fromtimestamp(b[0] / 1000, timezone.utc).date()].append(b)
    for day, day_rows in by_day.items():
        store.write_partition("bars", SYMBOL, day, day_rows)
    return {"bars": len(bars), "days": len(by_day), "from_ms": start_ms}


COARSE = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "1D", "1w": "1W", "1M": "1M"}
FULL_CAP = 10_000     # số nến tối đa khi nạp lịch sử một khung


def coarse_path(tf: str):
    return store.data_dir() / "tvc" / SYMBOL / f"{tf}.json"


def load_coarse(tf: str) -> list[list[float]]:
    try:
        return json.loads(coarse_path(tf).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def sync_coarse(tf: str, full: bool = False, fetch=fetch_minutes) -> dict:
    """Nạp nến khung `tf` (full: toàn bộ lịch sử nguồn cho; không thì chỉ phần mới), gộp vào tệp JSON theo ts."""
    old = load_coarse(tf)
    start_s = 0 if full or not old else int(old[-1][0])
    count = FULL_CAP if full else 100
    rows = asyncio.run(fetch(start_s, res=COARSE[tf], count=min(count, 5000)))
    merged = {int(r[0]): r for r in old}
    for r in rows:
        merged[int(r[0])] = r
    out = [merged[k] for k in sorted(merged)]
    p = coarse_path(tf)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)
    return {"tf": tf, "bars": len(out), "new": len(out) - len(old)}


_last_coarse: dict[str, float] = {}


def refresh_coarse(tf: str, min_interval: float = 30.0) -> bool:
    """Làm mới đuôi của khung lớn khi có người xem, gọi thưa. Lỗi chỉ ghi log."""
    if time.monotonic() - _last_coarse.get(tf, -1e9) < min_interval or not _refresh_lock.acquire(blocking=False):
        return False
    try:
        _last_coarse[tf] = time.monotonic()
        sync_coarse(tf)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("không làm mới được XAUUSD %s: %s: %s", tf, type(e).__name__, e)
        return False
    finally:
        _refresh_lock.release()


_last_refresh = 0.0
_refresh_lock = threading.Lock()


def refresh_tail(min_interval: float = 20.0) -> bool:
    """Làm mới đuôi nến cho server khi có người xem. Gọi thưa (mặc định 20 giây một lần); lỗi mạng chỉ ghi log."""
    global _last_refresh
    if time.monotonic() - _last_refresh < min_interval or not _refresh_lock.acquire(blocking=False):
        return False
    try:
        _last_refresh = time.monotonic()
        sync()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("không làm mới được XAUUSD từ TradingView: %s: %s", type(e).__name__, e)
        return False
    finally:
        _refresh_lock.release()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--history", action="store_true", help="nạp toàn bộ lịch sử các khung lớn")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.history:
        for tf in COARSE:
            log.info("%s", sync_coarse(tf, full=True))
        return
    log.info("%s %s", SYMBOL, sync(args.days))


if __name__ == "__main__":
    main()
