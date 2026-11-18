"""GET /api/dom: bảng độ sâu (DOM) hiện tại của sổ lệnh, gom theo bucket giá, cho cột thanh khoản bên phải biểu đồ kiểu Bookmap.

Nguồn chính: snapshot REST `/fapi/v1/depth` của Binance Futures (công khai, 1000 mức mỗi phía, nhớ 1,5 giây để nhiều ô và nhiều người xem
dùng chung một yêu cầu). Khi REST lỗi thì lấy mẫu mới nhất đã ghi trong kho `book` (trễ tới vài phút) và ghi rõ `source` và `age_ms`.
Mỗi phía là danh sách [giá cận dưới của bucket, tổng khối lượng chờ], bid giảm dần và ask tăng dần theo giá.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import httpx
from fastapi import APIRouter, HTTPException, Query

from collector import binance
from common import store

log = logging.getLogger("server.dom")
router = APIRouter()

rest_client_factory: Callable[[], httpx.Client] = binance.make_client
CACHE_S = 1.5
LIMIT = 1000
MAX_ROWS = 1500

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def fetch_depth(symbol: str) -> dict:
    client = rest_client_factory()
    try:
        return binance.get_json(client, "/fapi/v1/depth", {"symbol": symbol, "limit": LIMIT}, tries=2)
    finally:
        client.close()


def bucketize(levels: list, bucket: float, descending: bool) -> list[list[float]]:
    """Gom [giá, khối lượng] vào bucket giá có độ rộng `bucket`."""
    acc: dict[int, float] = {}
    for p, q in levels:
        k = int(float(p) / bucket + 1e-9)
        acc[k] = acc.get(k, 0.0) + float(q)
    out = [[round(k * bucket, 10), round(v, 6)] for k, v in sorted(acc.items(), reverse=descending)]
    return out[:MAX_ROWS]


def from_book(symbol: str, cfg: dict, mult: int, now_ms: int) -> dict | None:
    """Mẫu sổ lệnh mới nhất đã ghi trong 10 phút gần nhất (dự phòng khi REST lỗi). Mỗi dòng book là (ts, p, bid, ask)."""
    sql = store.range_select("book", symbol, now_ms - 600_000, now_ms + 60_000)
    if not sql:
        return None
    con = store.query_conn()
    try:
        last = con.execute(f"SELECT max(ts) FROM ({sql})").fetchone()[0]
        if last is None:
            return None
        rows = con.execute(f"SELECT p, bid::DOUBLE, ask::DOUBLE FROM ({sql}) WHERE ts = {int(last)}").fetchall()
    finally:
        con.close()
    tick = cfg["tick"]
    bucket = round(round(cfg["book_bucket"] / tick) * mult * tick, 10)
    bids = [[p * tick, b] for p, b, _ in rows if b > 0]
    asks = [[p * tick, a] for p, _, a in rows if a > 0]
    return {"ts": int(last), "bids": bucketize(bids, bucket, True), "asks": bucketize(asks, bucket, False), "bucket": bucket}


def get_dom(symbol: str, mult: int, now_ms: int | None = None) -> dict:
    try:
        cfg = store.symbol_config(symbol)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    if cfg.get("source") != "binance_futures":
        raise HTTPException(400, f"{symbol} không có sổ lệnh sâu")
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    bucket = round(round(cfg["book_bucket"] / cfg["tick"]) * mult * cfg["tick"], 10)
    with _lock:
        hit = _cache.get(symbol)
        raw = hit[1] if hit is not None and time.monotonic() - hit[0] < CACHE_S else None
    if raw is None:
        try:
            raw = fetch_depth(symbol)
            with _lock:
                _cache[symbol] = (time.monotonic(), raw)
        except Exception as e:  # noqa: BLE001 - mạng lỗi: dùng mẫu đã ghi
            log.warning("%s: không lấy được depth REST (%s: %s), dùng sổ lệnh đã ghi", symbol, type(e).__name__, e)
            stored = from_book(symbol, cfg, mult, now)
            if stored is None:
                raise HTTPException(503, "Không lấy được sổ lệnh (Binance lỗi và chưa có mẫu đã ghi).") from e
            bids, asks = stored["bids"], stored["asks"]
            return {"symbol": symbol, "ts": stored["ts"], "age_ms": max(0, now - stored["ts"]), "source": "book", "bucket": stored["bucket"],
                    "best_bid": bids[0][0] if bids else None, "best_ask": asks[0][0] if asks else None, "bids": bids, "asks": asks}
    bids_raw = [(p, q) for p, q in raw.get("bids", []) if float(q) > 0]
    asks_raw = [(p, q) for p, q in raw.get("asks", []) if float(q) > 0]
    best_bid = max((float(p) for p, _ in bids_raw), default=None)
    best_ask = min((float(p) for p, _ in asks_raw), default=None)
    ts = int(raw.get("T") or raw.get("E") or now)
    return {"symbol": symbol, "ts": ts, "age_ms": max(0, now - ts), "source": "live", "bucket": bucket,
            "best_bid": best_bid, "best_ask": best_ask,
            "bids": bucketize(bids_raw, bucket, True), "asks": bucketize(asks_raw, bucket, False)}


@router.get("/api/dom")
def dom_endpoint(symbol: str, mult: int = Query(1, ge=1, le=100000)) -> dict:
    return get_dom(symbol.upper(), mult)
