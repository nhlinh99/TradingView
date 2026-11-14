"""Collector lệnh khớp trực tiếp: WebSocket aggTrade của Binance Futures -> kho `ticks`.

Chạy:  python -m collector.live_trades --symbols BTCUSDT,XAUUSDT
Dừng:  Ctrl+C (ghi nốt dữ liệu còn trong bộ nhớ).

Thiết kế:
- Endpoint: wss://fstream.binance.com/market/ws/<symbol>@aggTrade. Binance đã đổi sang đường dẫn
  /public và /market và gỡ URL cũ ngày 2026-04-23 (xem changelog). URL cũ không còn gửi aggTrade.
- Mỗi tin có id gộp `a` liên tục. Nếu `a` nhảy cóc, ghi khoảng hở vào SQLite (tick_gaps) và lấp bằng
  REST /fapi/v1/aggTrades?fromId= ở luồng riêng, nên luồng chính không bị nghẽn. Khởi động lại sẽ
  tiếp tục các khoảng còn mở.
- Ghi file con `date=<ngày>.p<id đầu tiên>.parquet` mỗi 60 giây hoặc 5000 dòng. Tên theo id nên các lần
  chạy khác nhau không ghi đè nhau. Việc gộp thành file ngày do compact.py làm.
- Mất kết nối: tự nối lại với chờ luỹ thừa (tối đa 30 giây).
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

import duckdb
import httpx
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import connect as ws_connect

from collector import binance
from common import appdb, store

log = logging.getLogger("collector.trades")

WS_BASE = "wss://fstream.binance.com/market/ws"


def ws_url(symbol: str) -> str:
    return f"{WS_BASE}/{symbol.lower()}@aggTrade"


def utc_day(ts_ms: int):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()


def last_stored_id(symbol: str) -> int | None:
    folder = store.data_dir() / "ticks" / symbol
    if not folder.exists() or not any(folder.glob("date=*.parquet")):
        return None
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT max(id) FROM {store.scan_sql('ticks', symbol)}").fetchall()[0][0]
    finally:
        con.close()


def write_ticks(symbol: str, rows: list[tuple]) -> int:
    """Ghi các dòng tick, tách theo ngày UTC, mỗi ngày một file con đặt tên theo id nhỏ nhất."""
    by_day: dict = defaultdict(list)
    for r in rows:
        by_day[utc_day(r[0])].append(r)
    for day, rs in by_day.items():
        store.write_partition("ticks", symbol, day, rs, part=str(min(r[1] for r in rs)))
    return len(rows)


class TickWriter:
    """Bộ đệm tick. Ghi khi đủ số dòng hoặc đủ thời gian."""

    def __init__(self, symbol: str, flush_rows: int = 5000, flush_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self.symbol, self.flush_rows, self.flush_seconds, self.clock = symbol, flush_rows, flush_seconds, clock
        self.rows: list[tuple] = []
        self.last_flush = clock()
        self.total = 0

    def add(self, tick: tuple) -> None:
        self.rows.append(tick)

    def due(self) -> bool:
        return bool(self.rows) and (
            len(self.rows) >= self.flush_rows or self.clock() - self.last_flush >= self.flush_seconds
        )

    def flush(self) -> int:
        if not self.rows:
            self.last_flush = self.clock()
            return 0
        rows, self.rows = self.rows, []
        try:
            n = write_ticks(self.symbol, rows)
        except BaseException:
            self.rows = rows + self.rows  # không mất dữ liệu nếu ghi lỗi; thử lại lần sau
            raise
        self.last_flush = self.clock()
        self.total += n
        return n


# ---------- nhật ký khoảng hở ----------

def _gap_db():
    appdb.init()
    return appdb.connect()


def record_gap(symbol: str, from_id: int, to_id: int, status: str) -> None:
    con = _gap_db()
    try:
        con.execute("INSERT OR REPLACE INTO tick_gaps(symbol, from_id, to_id, status) VALUES (?,?,?,?)",
                    (symbol, from_id, to_id, status))
        con.commit()
    finally:
        con.close()


def finish_gap(symbol: str, from_id: int, rows: int) -> None:
    con = _gap_db()
    try:
        con.execute("UPDATE tick_gaps SET status='filled', rows=? WHERE symbol=? AND from_id=?", (rows, symbol, from_id))
        con.commit()
    finally:
        con.close()


def open_gaps(symbol: str) -> list[tuple[int, int]]:
    con = _gap_db()
    try:
        return [tuple(r) for r in con.execute(
            "SELECT from_id, to_id FROM tick_gaps WHERE symbol=? AND status='open' ORDER BY from_id", (symbol,))]
    finally:
        con.close()


def fill_gap(symbol: str, from_id: int, to_id: int, client: httpx.Client, pause: float = 0.6,
             chunk_rows: int = 100_000, sleep=time.sleep) -> int:
    """Lấp khoảng hở [from_id, to_id] bằng REST. Trả về số dòng đã ghi. Lỗi mạng: để gap ở trạng thái open."""
    buf: list[tuple] = []
    total = 0
    for t in binance.iter_agg_trades(client, symbol, from_id, to_id, pause=pause, sleep=sleep):
        buf.append(binance.agg_trade_to_tick(symbol, t))
        if len(buf) >= chunk_rows:
            total += write_ticks(symbol, buf)
            buf = []
    if buf:
        total += write_ticks(symbol, buf)
    finish_gap(symbol, from_id, total)
    return total


# ---------- collector ----------

class TradeCollector:
    def __init__(self, symbol: str, *, url: str | None = None,
                 client_factory: Callable[[], httpx.Client] = binance.make_client,
                 connect: Callable = ws_connect, flush_rows: int = 5000, flush_seconds: float = 60.0,
                 max_gap: int = 5_000_000, stale_seconds: float = 120.0, recv_timeout: float = 5.0,
                 rest_pause: float = 0.6, max_backoff: float = 30.0):
        self.symbol = symbol
        self.url = url or ws_url(symbol)
        self.client_factory = client_factory
        self.connect = connect
        self.writer = TickWriter(symbol, flush_rows, flush_seconds)
        self.max_gap, self.stale_seconds, self.recv_timeout = max_gap, stale_seconds, recv_timeout
        self.rest_pause, self.max_backoff = rest_pause, max_backoff
        self.last_id: int | None = None
        self.received = 0
        self.reconnects = 0
        self._fills: list[threading.Thread] = []

    # -- khoảng hở --
    def _start_fill(self, from_id: int, to_id: int) -> None:
        def work():
            client = self.client_factory()
            try:
                n = fill_gap(self.symbol, from_id, to_id, client, pause=self.rest_pause)
                log.info("%s lấp khoảng hở %d..%d: %d dòng", self.symbol, from_id, to_id, n)
            except Exception:
                log.exception("%s lấp khoảng hở %d..%d lỗi; để trạng thái open, sẽ thử lại khi khởi động", self.symbol, from_id, to_id)
            finally:
                client.close()
        t = threading.Thread(target=work, name=f"fill-{self.symbol}-{from_id}", daemon=True)
        t.start()
        self._fills.append(t)

    def _record_gap(self, from_id: int, to_id: int) -> None:
        size = to_id - from_id + 1
        if size > self.max_gap:
            log.warning("%s khoảng hở %d..%d (%d id) quá lớn, bỏ qua. Dùng collector.backfill cho ngày đã qua.",
                        self.symbol, from_id, to_id, size)
            record_gap(self.symbol, from_id, to_id, "skipped")
            return
        log.warning("%s phát hiện khoảng hở %d..%d (%d id)", self.symbol, from_id, to_id, size)
        record_gap(self.symbol, from_id, to_id, "open")
        self._start_fill(from_id, to_id)

    # -- xử lý tin --
    def on_message(self, raw: str | bytes) -> None:
        msg = json.loads(raw)
        if msg.get("e") != "aggTrade":
            return
        tick = binance.agg_trade_to_tick(self.symbol, msg)
        id_ = tick[1]
        self.received += 1
        if self.last_id is not None:
            if id_ <= self.last_id:
                return  # trùng hoặc cũ hơn dữ liệu đã có
            if id_ > self.last_id + 1:
                self._record_gap(self.last_id + 1, id_ - 1)
        self.last_id = id_
        self.writer.add(tick)
        if self.writer.due():
            self.writer.flush()

    def _consume(self, ws, stop: threading.Event) -> None:
        last_msg = time.monotonic()
        while not stop.is_set():
            try:
                raw = ws.recv(timeout=self.recv_timeout)
            except TimeoutError:
                if time.monotonic() - last_msg > self.stale_seconds:
                    raise TimeoutError(f"không có tin nào trong {self.stale_seconds}s")
                if self.writer.due():
                    self.writer.flush()
                continue
            last_msg = time.monotonic()
            self.on_message(raw)

    def run(self, stop: threading.Event) -> None:
        self.last_id = last_stored_id(self.symbol)
        for f, t in open_gaps(self.symbol):
            log.info("%s tiếp tục lấp khoảng hở %d..%d", self.symbol, f, t)
            self._start_fill(f, t)
        backoff = 1.0
        try:
            while not stop.is_set():
                try:
                    with self.connect(self.url, open_timeout=10, max_size=2**20) as ws:
                        log.info("%s đã kết nối %s", self.symbol, self.url)
                        backoff = 1.0
                        self._consume(ws, stop)
                except (OSError, ConnectionClosed, TimeoutError, InvalidHandshake, InvalidURI) as e:
                    log.warning("%s mất kết nối: %s: %s", self.symbol, type(e).__name__, e)
                finally:
                    self.writer.flush()
                if stop.is_set():
                    break
                self.reconnects += 1
                stop.wait(backoff)
                backoff = min(backoff * 2, self.max_backoff)
        finally:
            self.writer.flush()
            for t in self._fills:
                t.join(timeout=30)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="BTCUSDT", help="phân tách bằng dấu phẩy")
    ap.add_argument("--flush-seconds", type=float, default=60.0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    collectors = [TradeCollector(s.strip().upper(), flush_seconds=a.flush_seconds) for s in a.symbols.split(",") if s.strip()]
    threads = [threading.Thread(target=c.run, args=(stop,), name=f"trades-{c.symbol}") for c in collectors]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
            if int(time.time()) % 60 == 0:
                log.info("; ".join(f"{c.symbol}: nhận {c.received}, ghi {c.writer.total}, nối lại {c.reconnects}" for c in collectors))
    except KeyboardInterrupt:
        log.info("đang dừng, ghi nốt dữ liệu...")
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=60)


if __name__ == "__main__":
    main()
