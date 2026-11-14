"""Client REST công khai của Binance USDⓈ-M Futures (không cần key).

Chỉ dùng cho dữ liệu thị trường. Có thử lại khi gặp 429/418/5xx và tôn trọng Retry-After.
"""
from __future__ import annotations

import time
from typing import Iterator

import httpx

from common import store

BASE_URL = "https://fapi.binance.com"
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class BinanceError(RuntimeError):
    pass


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=20.0, transport=transport,
                        headers={"User-Agent": "tv-local/0.1"})


def get_json(client: httpx.Client, path: str, params: dict | None = None, tries: int = 5,
             sleep=time.sleep):
    """GET có thử lại. 429/418: chờ theo Retry-After. 5xx và lỗi mạng: chờ luỹ thừa."""
    last: Exception | None = None
    for i in range(tries):
        try:
            r = client.get(path, params=params)
        except httpx.TransportError as e:
            last = e
            sleep(min(0.5 * 2 ** i, 8))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 418) or r.status_code >= 500:
            retry_after = r.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else min(0.5 * 2 ** i, 8)
            last = BinanceError(f"HTTP {r.status_code} {path}")
            if r.status_code == 418 and i == tries - 1:
                break  # bị cấm IP tạm thời: không nên cố thêm
            sleep(wait)
            continue
        raise BinanceError(f"HTTP {r.status_code} {path}: {r.text[:200]}")
    raise BinanceError(f"hết lần thử cho {path}: {last}")


# ---------- nến ----------

def kline_to_bar(symbol: str, k: list) -> tuple:
    """Dòng kline của Binance -> dòng của kho `bars`: (ts, o, h, l, c, v, buy_v, sell_v).

    k[9] là taker buy base volume, nên buy_v là khối lượng mua chủ động (chính xác, không suy đoán).
    """
    v = float(k[5])
    buy = float(k[9])
    return (
        int(k[0]),
        store.to_int_price(symbol, float(k[1])),
        store.to_int_price(symbol, float(k[2])),
        store.to_int_price(symbol, float(k[3])),
        store.to_int_price(symbol, float(k[4])),
        v,
        buy,
        max(v - buy, 0.0),
    )


def iter_klines(client: httpx.Client, symbol: str, interval: str, start_ms: int, end_ms: int,
                limit: int = 1500, sleep=time.sleep) -> Iterator[list]:
    """Phát từng kline trong [start_ms, end_ms). Tự phân trang."""
    step = INTERVAL_MS[interval]
    cursor = start_ms
    while cursor < end_ms:
        rows = get_json(client, "/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "startTime": cursor,
            "endTime": end_ms - 1, "limit": limit,
        }, sleep=sleep)
        if not rows:
            return
        for k in rows:
            if int(k[0]) >= end_ms:
                return
            yield k
        last_open = int(rows[-1][0])
        if len(rows) < limit:
            return
        cursor = last_open + step


# ---------- lệnh khớp gộp (dùng để lấp khoảng hở) ----------

def agg_trade_to_tick(symbol: str, t: dict) -> tuple:
    """Dòng aggTrades REST -> dòng của kho `ticks`: (ts, id, p, q, m)."""
    return (int(t["T"]), int(t["a"]), store.to_int_price(symbol, float(t["p"])), float(t["q"]), bool(t["m"]))


def iter_agg_trades(client: httpx.Client, symbol: str, from_id: int, to_id: int | None = None,
                    limit: int = 1000, sleep=time.sleep) -> Iterator[dict]:
    """Phát các aggTrade có id >= from_id (và <= to_id nếu có), tăng dần theo id."""
    cursor = from_id
    while True:
        rows = get_json(client, "/fapi/v1/aggTrades", {"symbol": symbol, "fromId": cursor, "limit": limit}, sleep=sleep)
        if not rows:
            return
        for t in rows:
            if to_id is not None and int(t["a"]) > to_id:
                return
            yield t
        if len(rows) < limit:
            return
        cursor = int(rows[-1]["a"]) + 1
