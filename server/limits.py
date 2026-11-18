"""Giới hạn số yêu cầu nặng chạy cùng lúc (Pine, footprint, profile, heatmap, bong bóng, iceberg).

Lý do: khi đổi symbol hoặc khung, giao diện bắn một yêu cầu Pine cho mỗi chỉ báo cùng lúc, cộng với các lớp orderflow. Mỗi yêu cầu giữ vài chục
đến vài trăm MB tạm thời, nên chạy hết cùng lúc làm đỉnh bộ nhớ cao hơn nhiều so với chạy lần lượt vài cái một. Yêu cầu thừa chờ lượt;
chờ quá `HEAVY_WAIT_S` giây thì trả 503 kèm `Retry-After`.

Cấu hình (biến môi trường): HEAVY_CONCURRENCY (mặc định 3), HEAVY_WAIT_S (mặc định 60).
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

from fastapi import HTTPException

MAX_CONCURRENT = max(1, int(os.environ.get("HEAVY_CONCURRENCY", "3")))
WAIT_S = float(os.environ.get("HEAVY_WAIT_S", "60"))

_sem = threading.BoundedSemaphore(MAX_CONCURRENT)
_lock = threading.Lock()
_active = 0
_peak = 0


@contextmanager
def heavy() -> Iterator[None]:
    """Xin một lượt chạy nặng. Dùng: `with limits.heavy(): ...`."""
    global _active, _peak
    if not _sem.acquire(timeout=WAIT_S):
        raise HTTPException(503, "Máy đang bận xử lý nhiều yêu cầu nặng, thử lại sau ít giây.", headers={"Retry-After": "5"})
    with _lock:
        _active += 1
        _peak = max(_peak, _active)
    try:
        yield
    finally:
        with _lock:
            _active -= 1
        _sem.release()


T = TypeVar("T")
_cache_lock = threading.Lock()
_cache: "OrderedDict[tuple, tuple[float, Future]]" = OrderedDict()
CACHE_MAX = int(os.environ.get("HEAVY_CACHE_ENTRIES", "24"))
PROFILE_TTL = float(os.environ.get("HEAVY_PROFILE_TTL_S", "5"))   # volume profile: ngắn hơn vì cột Khớp của DOM cần số liệu gần trực tiếp
CACHE_TTL = float(os.environ.get("HEAVY_CACHE_TTL_S", "20"))   # giây nhớ kết quả heatmap, bong bóng, iceberg; 0 = chỉ gộp các yêu cầu đang chạy


def coalesce(key: tuple, ttl: float, fn: Callable[[], T]) -> T:
    """Gộp các yêu cầu nặng giống hệt nhau: yêu cầu đầu chạy `fn`, các yêu cầu cùng `key` đến sau chờ kết quả đó thay vì chiếm thêm lượt chạy.

    Kết quả thành công được nhớ `ttl` giây. Lỗi không được nhớ. Giao diện huỷ yêu cầu khi kéo biểu đồ nhưng máy chủ vẫn chạy nốt,
    nên nếu không gộp thì mỗi lần kéo xếp thêm một truy vấn nặng vào hàng đợi.
    """
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and (not hit[1].done() or now - hit[0] < ttl):
            _cache.move_to_end(key)
            fut, owner = hit[1], False
        else:
            fut, owner = Future(), True
            _cache[key] = (now, fut)
            _cache.move_to_end(key)
            while len(_cache) > CACHE_MAX:
                _cache.popitem(last=False)
    if not owner:
        return fut.result(timeout=WAIT_S + 120)
    try:
        value = fn()
    except BaseException as e:   # noqa: BLE001 - báo lỗi cho cả những yêu cầu đang chờ rồi bỏ khỏi bộ nhớ
        with _cache_lock:
            if _cache.get(key, (0, None))[1] is fut:
                del _cache[key]
        fut.set_exception(e)
        raise
    fut.set_result(value)
    with _cache_lock:
        if key in _cache and _cache[key][1] is fut:
            _cache[key] = (time.monotonic(), fut)
    return value


def stats() -> dict:
    with _lock:
        return {"heavy_active": _active, "heavy_peak": _peak, "heavy_max": MAX_CONCURRENT}
