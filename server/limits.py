"""Giới hạn số yêu cầu nặng chạy cùng lúc (Pine, footprint, profile, heatmap, bong bóng, iceberg).

Lý do: khi đổi symbol hoặc khung, giao diện bắn một yêu cầu Pine cho mỗi chỉ báo cùng lúc, cộng với các lớp orderflow. Mỗi yêu cầu giữ vài chục
đến vài trăm MB tạm thời, nên chạy hết cùng lúc làm đỉnh bộ nhớ cao hơn nhiều so với chạy lần lượt vài cái một. Yêu cầu thừa chờ lượt;
chờ quá `HEAVY_WAIT_S` giây thì trả 503 kèm `Retry-After`.

Cấu hình (biến môi trường): HEAVY_CONCURRENCY (mặc định 3), HEAVY_WAIT_S (mặc định 60).
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator

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


def stats() -> dict:
    with _lock:
        return {"heavy_active": _active, "heavy_peak": _peak, "heavy_max": MAX_CONCURRENT}
