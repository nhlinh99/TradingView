"""Collector sổ lệnh: WebSocket depth (diff) + snapshot REST -> bảng `book` (heatmap thanh khoản).

Chạy:  python -m collector.live_book --symbols BTCUSDT,XAUUSDT

Quy tắc đồng bộ (tài liệu Binance "How to manage a local order book correctly", USDⓈ-M Futures):
  1. Nhận diff stream và đệm các tin.
  2. Lấy snapshot REST /fapi/v1/depth?limit=1000 (có lastUpdateId = L).
  3. Bỏ các tin có u < L.
  4. Tin đầu tiên được xử lý phải có U <= L và u >= L.
  5. Mỗi tin sau phải có pu bằng u của tin trước. Nếu không, bắt đầu lại từ bước 2.
  6. Số lượng là giá trị tuyệt đối tại mức giá. 0 nghĩa là xoá mức. Xoá mức không có trong sổ là bình thường.
Endpoint: wss://fstream.binance.com/public/ws/<symbol>@depth@100ms (đường dẫn /public mới của Binance).

Giới hạn quan trọng (đo thật): snapshot 1000 mức chỉ phủ khoảng ±0,2% quanh giá với BTC. Luồng diff gửi
cập nhật cho mọi mức giá, nhưng mức ngoài dải của snapshot chỉ được biết khi nó thay đổi. Vì vậy chỉ ghi
bucket trong cửa sổ nhỏ hơn dải đó (book_window_pct trong config/symbols.toml), và lấy snapshot mới mỗi
book_resync_s giây trong khi sổ cũ vẫn chạy, để dải bám theo giá.

Mỗi book_interval_s giây ghi các dòng (ts, p, bid, ask): p = cận dưới của bucket (đơn vị tick),
bid/ask = tổng khối lượng chờ trong bucket. Bucket rỗng không ghi. File con tên theo ts đầu tiên.
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Callable

import httpx
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import connect as ws_connect

from collector import binance
from common import store

log = logging.getLogger("collector.book")

WS_BASE = "wss://fstream.binance.com/public/ws"


def ws_url(symbol: str) -> str:
    return f"{WS_BASE}/{symbol.lower()}@depth@100ms"


# ---------- sổ lệnh cục bộ ----------

class LocalBook:
    """Sổ lệnh cục bộ theo đúng quy tắc đồng bộ của Binance.

    Giá khoá theo số nguyên tick. feed() trả False khi phải bắt đầu lại từ snapshot mới.
    """

    WAIT, SYNC, LIVE = "WAIT", "SYNC", "LIVE"

    def __init__(self, tick: float):
        self.tick = tick
        self.bids: dict[int, float] = {}
        self.asks: dict[int, float] = {}
        self.state = self.WAIT
        self.snapshot_id: int | None = None
        self.last_u: int | None = None
        self.synced_at: float | None = None
        self.snapshot_band: tuple[int, int] | None = None  # (giá bid thấp nhất, giá ask cao nhất), đơn vị tick

    def _k(self, price: str | float) -> int:
        return round(float(price) / self.tick)

    def load_snapshot(self, snap: dict, buffered: list[dict] | tuple = ()) -> bool:
        """Nạp snapshot rồi xử lý các tin đã đệm. False nếu đệm cho thấy phải lấy snapshot khác."""
        self.bids = {self._k(p): float(q) for p, q in snap["bids"] if float(q) > 0}
        self.asks = {self._k(p): float(q) for p, q in snap["asks"] if float(q) > 0}
        self.snapshot_id = int(snap["lastUpdateId"])
        self.last_u = None
        self.state = self.SYNC
        self.snapshot_band = (min(self.bids), max(self.asks)) if self.bids and self.asks else None
        for ev in buffered:
            if not self.feed(ev):
                return False
        return True

    def _apply(self, ev: dict) -> None:
        for side, book in (("b", self.bids), ("a", self.asks)):
            for p, q in ev.get(side, ()):
                k, qty = self._k(p), float(q)
                if qty == 0:
                    book.pop(k, None)  # xoá mức không có trong sổ là bình thường
                else:
                    book[k] = qty

    def feed(self, ev: dict, now: float | None = None) -> bool:
        U, u = int(ev["U"]), int(ev["u"])
        if self.state == self.SYNC:
            L = self.snapshot_id
            if u < L:
                return True  # tin cũ hơn snapshot: bỏ
            if U <= L <= u:
                self._apply(ev)
                self.last_u = u
                self.state = self.LIVE
                self.synced_at = time.monotonic() if now is None else now
                return True
            return False  # U > L: thiếu tin giữa snapshot và luồng
        if self.state == self.LIVE:
            if int(ev["pu"]) != self.last_u:
                return False
            self._apply(ev)
            self.last_u = u
            return True
        return True  # WAIT: chưa có snapshot, bỏ qua

    def mid(self) -> float | None:
        if not self.bids or not self.asks:
            return None
        return (max(self.bids) + min(self.asks)) / 2.0  # đơn vị tick


def bucket_rows(book: LocalBook, ts: int, window_pct: float, bucket_ticks: int) -> list[tuple]:
    """Gom sổ lệnh thành các bucket trong ±window_pct% quanh giá giữa. Trả về [(ts, p, bid, ask)]."""
    mid = book.mid()
    if mid is None:
        return []
    lo = mid * (1 - window_pct / 100.0)
    hi = mid * (1 + window_pct / 100.0)
    bid_b: dict[int, float] = defaultdict(float)
    ask_b: dict[int, float] = defaultdict(float)
    for k, q in book.bids.items():
        if lo <= k <= hi:
            bid_b[k // bucket_ticks * bucket_ticks] += q
    for k, q in book.asks.items():
        if lo <= k <= hi:
            ask_b[k // bucket_ticks * bucket_ticks] += q
    return [(ts, p, bid_b.get(p, 0.0), ask_b.get(p, 0.0)) for p in sorted(set(bid_b) | set(ask_b))]


def utc_day(ts_ms: int):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()


def write_book(symbol: str, rows: list[tuple]) -> int:
    by_day: dict = defaultdict(list)
    for r in rows:
        by_day[utc_day(r[0])].append(r)
    for day, rs in by_day.items():
        store.write_partition("book", symbol, day, rs, part=str(min(r[0] for r in rs)))
    return len(rows)


# ---------- collector ----------

def rest_snapshot(client: httpx.Client, symbol: str) -> dict:
    return binance.get_json(client, "/fapi/v1/depth", {"symbol": symbol, "limit": 1000})


class BookCollector:
    def __init__(self, symbol: str, *, url: str | None = None,
                 snapshot_fn: Callable[[str], dict] | None = None,
                 connect: Callable = ws_connect, flush_seconds: float = 60.0,
                 recv_timeout: float = 1.0, stale_seconds: float = 60.0, max_backoff: float = 30.0,
                 clock: Callable[[], float] = time.time):
        cfg = store.symbol_config(symbol)
        self.symbol = symbol
        self.tick = cfg["tick"]
        self.window_pct = cfg["book_window_pct"]
        self.bucket_ticks = round(cfg["book_bucket"] / self.tick)
        if self.bucket_ticks < 1 or abs(self.bucket_ticks * self.tick - cfg["book_bucket"]) > 1e-9:
            raise ValueError(f"book_bucket của {symbol} phải là bội của tick")
        self.interval_ms = int(cfg["book_interval_s"] * 1000)
        self.resync_s = cfg["book_resync_s"]
        self.url = url or ws_url(symbol)
        self.connect = connect
        self.flush_seconds, self.recv_timeout = flush_seconds, recv_timeout
        self.stale_seconds, self.max_backoff = stale_seconds, max_backoff
        self.clock = clock
        self._client: httpx.Client | None = None
        self.snapshot_fn = snapshot_fn or self._default_snapshot
        self.live: LocalBook | None = None
        self.candidate: LocalBook | None = None
        self.recent: deque[dict] = deque(maxlen=200)  # ~20 giây tin 100ms, để ghép với snapshot mới
        self.rows: list[tuple] = []
        self.last_flush = time.monotonic()
        self.next_sample_ms: int | None = None
        self.events = 0
        self.resyncs = 0
        self.written = 0
        self.snapshot_bands: list[tuple[int, int]] = []
        self.min_snapshot_gap_s = 2.0
        self._last_snapshot_try = float("-inf")

    # -- snapshot --
    def _default_snapshot(self, symbol: str) -> dict:
        if self._client is None:
            self._client = binance.make_client()
        return rest_snapshot(self._client, symbol)

    def _start_candidate(self) -> None:
        snap = self.snapshot_fn(self.symbol)
        cand = LocalBook(self.tick)
        if cand.load_snapshot(snap, list(self.recent)):
            self.candidate = cand
            if cand.snapshot_band:
                self.snapshot_bands.append(cand.snapshot_band)
        else:
            self.candidate = None
            log.info("%s snapshot không ghép được với tin đệm, thử lại ở tin sau", self.symbol)

    def _maybe_promote(self) -> None:
        c = self.candidate
        if c is not None and c.state == LocalBook.LIVE:
            self.live, self.candidate = c, None
            self.resyncs += 1

    # -- xử lý --
    def on_event(self, ev: dict) -> None:
        self.events += 1
        # live và candidate nhận cùng một tin
        if self.live is not None and not self.live.feed(ev):
            log.warning("%s sổ lệnh lệch (pu != u trước đó), đồng bộ lại", self.symbol)
            self.live = None
        if self.candidate is not None and not self.candidate.feed(ev):
            self.candidate = None
        self.recent.append(ev)
        self._maybe_promote()
        self._housekeeping()

    def _housekeeping(self) -> None:
        now_s = self.clock()
        need = self.live is None or (self.live.synced_at is not None and
                                     time.monotonic() - self.live.synced_at >= self.resync_s)
        # Giãn cách giữa các lần lấy snapshot (mỗi lần tốn trọng số 20 trên giới hạn 2400/phút)
        if (need and self.candidate is None and self.recent
                and time.monotonic() - self._last_snapshot_try >= self.min_snapshot_gap_s):
            self._last_snapshot_try = time.monotonic()
            try:
                self._start_candidate()
                self._maybe_promote()
            except Exception:
                log.exception("%s lấy snapshot lỗi", self.symbol)
        # lấy mẫu theo bội của interval
        now_ms = int(now_s * 1000)
        if self.next_sample_ms is None:
            self.next_sample_ms = (now_ms // self.interval_ms + 1) * self.interval_ms
        if now_ms >= self.next_sample_ms:
            ts = now_ms // self.interval_ms * self.interval_ms
            self.next_sample_ms = ts + self.interval_ms
            if self.live is not None and self.live.state == LocalBook.LIVE:
                self.rows.extend(bucket_rows(self.live, ts, self.window_pct, self.bucket_ticks))
        if self.rows and time.monotonic() - self.last_flush >= self.flush_seconds:
            self.flush()

    def flush(self) -> int:
        if not self.rows:
            self.last_flush = time.monotonic()
            return 0
        rows, self.rows = self.rows, []
        try:
            n = write_book(self.symbol, rows)
        except BaseException:
            self.rows = rows + self.rows
            raise
        self.last_flush = time.monotonic()
        self.written += n
        return n

    def _consume(self, ws, stop: threading.Event) -> None:
        last_msg = time.monotonic()
        while not stop.is_set():
            try:
                raw = ws.recv(timeout=self.recv_timeout)
            except TimeoutError:
                if time.monotonic() - last_msg > self.stale_seconds:
                    raise TimeoutError(f"không có tin nào trong {self.stale_seconds}s")
                self._housekeeping()
                continue
            last_msg = time.monotonic()
            ev = json.loads(raw)
            if ev.get("e") == "depthUpdate":
                self.on_event(ev)

    def run(self, stop: threading.Event) -> None:
        backoff = 1.0
        try:
            while not stop.is_set():
                # kết nối mới = luồng mới: sổ cũ không còn đáng tin
                self.live = self.candidate = None
                self.recent.clear()
                try:
                    with self.connect(self.url, open_timeout=10, max_size=2**22) as ws:
                        log.info("%s đã kết nối %s", self.symbol, self.url)
                        backoff = 1.0
                        self._consume(ws, stop)
                except (OSError, ConnectionClosed, TimeoutError, InvalidHandshake, InvalidURI) as e:
                    log.warning("%s mất kết nối: %s: %s", self.symbol, type(e).__name__, e)
                finally:
                    self.flush()
                if stop.is_set():
                    break
                stop.wait(backoff)
                backoff = min(backoff * 2, self.max_backoff)
        finally:
            self.flush()
            if self._client is not None:
                self._client.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="BTCUSDT")
    ap.add_argument("--flush-seconds", type=float, default=60.0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    cols = [BookCollector(s.strip().upper(), flush_seconds=a.flush_seconds) for s in a.symbols.split(",") if s.strip()]
    threads = [threading.Thread(target=c.run, args=(stop,), name=f"book-{c.symbol}") for c in cols]
    for t in threads:
        t.start()
    try:
        last_log = 0.0
        while any(t.is_alive() for t in threads):
            time.sleep(1)
            if time.time() - last_log >= 60:
                last_log = time.time()
                log.info("; ".join(f"{c.symbol}: tin {c.events}, dòng ghi {c.written}, đồng bộ {c.resyncs}" for c in cols))
    except KeyboardInterrupt:
        log.info("đang dừng, ghi nốt dữ liệu...")
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=60)


if __name__ == "__main__":
    main()
