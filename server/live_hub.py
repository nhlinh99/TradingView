"""WebSocket /api/stream: đẩy lệnh khớp trực tiếp cho trình duyệt.

Giao thức (JSON):
  client -> server  {"op": "subscribe", "symbol": "BTCUSDT"}   /  {"op": "unsubscribe", "symbol": "BTCUSDT"}
  server -> client  {"t": "status", "s": "BTCUSDT", "state": "connected" | "reconnecting"}
                    {"t": "trade", "s": "BTCUSDT", "ts": ms, "id": aggId, "p": giá, "q": khối lượng, "m": isBuyerMaker}
                    {"t": "error", "detail": "..."}

Server giữ một kết nối aggTrade tới Binance cho mỗi symbol, dùng chung cho mọi người đăng ký, và đóng
khi không còn ai đăng ký. Mất kết nối thì tự nối lại (chờ luỹ thừa). Trình duyệt tự gộp lệnh khớp thành
nến theo timeframe đang xem, nên server không cần biết timeframe.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from collector.live_trades import ws_url
from common import store

log = logging.getLogger("server.live")

router = APIRouter()
MAX_SUBSCRIPTIONS = 8
QUEUE_SIZE = 2000


def _put_drop_oldest(q: asyncio.Queue, msg: dict) -> None:
    """Người xem chậm thì bỏ tin cũ nhất, không làm nghẽn nguồn."""
    while True:
        try:
            q.put_nowait(msg)
            return
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass


class Feed:
    def __init__(self, hub: "LiveHub", symbol: str):
        self.hub, self.symbol = hub, symbol
        self.subs: set[asyncio.Queue] = set()
        self.last_id: int | None = None
        self.state = "reconnecting"
        self.task: asyncio.Task | None = None

    def _broadcast(self, msg: dict) -> None:
        for q in self.subs:
            _put_drop_oldest(q, msg)

    def _status(self, state: str) -> None:
        self.state = state
        self._broadcast({"t": "status", "s": self.symbol, "state": state})

    def _on_raw(self, raw: str | bytes) -> None:
        try:
            m = json.loads(raw)
        except ValueError:
            return
        if m.get("e") != "aggTrade":
            return
        id_ = int(m["a"])
        if self.last_id is not None and id_ <= self.last_id:
            return  # trùng hoặc cũ hơn (ví dụ sau khi nối lại)
        self.last_id = id_
        self._broadcast({"t": "trade", "s": self.symbol, "ts": int(m["T"]), "id": id_,
                         "p": float(m["p"]), "q": float(m["q"]), "m": bool(m["m"])})

    async def run(self) -> None:
        backoff = self.hub.backoff_start
        while True:
            try:
                async with connect(self.hub.url_for(self.symbol), open_timeout=10, max_size=2**20) as ws:
                    self._status("connected")
                    backoff = self.hub.backoff_start
                    async for raw in ws:
                        self._on_raw(raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("%s mất kết nối nguồn: %s: %s", self.symbol, type(e).__name__, e)
            self._status("reconnecting")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


class LiveHub:
    def __init__(self, url_for: Callable[[str], str] = ws_url, backoff_start: float = 1.0):
        self.url_for, self.backoff_start = url_for, backoff_start
        self.feeds: dict[str, Feed] = {}

    def subscribe(self, symbol: str) -> asyncio.Queue:
        feed = self.feeds.get(symbol)
        if feed is None:
            feed = self.feeds[symbol] = Feed(self, symbol)
            if store.symbol_config(symbol).get("market") in ("vn", "tvc"):
                feed.state = "connected"   # cổ phiếu VN: không có luồng lệnh khớp; nến cập nhật theo lần tải lại
            else:
                feed.task = asyncio.get_running_loop().create_task(feed.run(), name=f"feed-{symbol}")
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        feed.subs.add(q)
        q.put_nowait({"t": "status", "s": symbol, "state": feed.state})
        return q

    def unsubscribe(self, symbol: str, q: asyncio.Queue) -> None:
        feed = self.feeds.get(symbol)
        if feed is None:
            return
        feed.subs.discard(q)
        if not feed.subs:
            del self.feeds[symbol]
            if feed.task is not None:
                feed.task.cancel()


hub = LiveHub()


def _valid_symbol(symbol: str) -> bool:
    try:
        store.symbol_config(symbol)
        return True
    except (KeyError, ValueError):
        return False


@router.websocket("/api/stream")
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    queues: dict[str, asyncio.Queue] = {}
    pumps: dict[str, asyncio.Task] = {}

    async def pump(q: asyncio.Queue) -> None:
        while True:
            await ws.send_json(await q.get())

    try:
        while True:
            try:
                data = await ws.receive_json()
            except ValueError:
                await ws.send_json({"t": "error", "detail": "tin nhắn không phải JSON"})
                continue
            if not isinstance(data, dict):
                await ws.send_json({"t": "error", "detail": "tin nhắn phải là đối tượng JSON"})
                continue
            op, symbol = data.get("op"), str(data.get("symbol", "")).upper()
            if op not in ("subscribe", "unsubscribe"):
                await ws.send_json({"t": "error", "detail": f"op không hợp lệ: {op!r}"})
            elif not _valid_symbol(symbol):
                await ws.send_json({"t": "error", "detail": f"symbol không có trong config: {symbol}"})
            elif op == "subscribe":
                if symbol in queues:
                    continue
                if len(queues) >= MAX_SUBSCRIPTIONS:
                    await ws.send_json({"t": "error", "detail": f"tối đa {MAX_SUBSCRIPTIONS} symbol mỗi kết nối"})
                    continue
                queues[symbol] = hub.subscribe(symbol)
                pumps[symbol] = asyncio.create_task(pump(queues[symbol]))
            elif symbol in queues:
                pumps.pop(symbol).cancel()
                hub.unsubscribe(symbol, queues.pop(symbol))
    except WebSocketDisconnect:
        pass
    finally:
        for t in pumps.values():
            t.cancel()
        for symbol, q in queues.items():
            hub.unsubscribe(symbol, q)
