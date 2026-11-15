"""Giám sát bộ nhớ của chính server: ghi log khi phình, và tự thoát khi vượt trần để dev.ps1 khởi động lại.

Lý do: ngày 2026-11-15 một server chạy nhiều giờ giữ 27,9 GB bộ nhớ cam kết (private bytes) dù RAM thật chỉ 2,5 GB,
đẩy commit của Windows lên 99%. Chưa tìm ra yêu cầu nào gây ra trong thử nghiệm ngắn (xem docs/plan/01-collector-storage.md), nên trần này
giới hạn thiệt hại bất kể nguyên nhân, và log bên dưới giúp truy ra nguyên nhân lần sau.

Cấu hình (biến môi trường): SERVER_MEM_LIMIT_MB (mặc định 3072, 0 = không giới hạn), SERVER_MEM_INTERVAL_S (mặc định 30).
SERVER_MEM_DIAG=1 bật chế độ chẩn đoán: bật `tracemalloc` ngay khi khởi động (làm chậm và tốn thêm bộ nhớ, chỉ dùng khi đang tìm nguyên nhân)
và khi bộ nhớ vượt SERVER_MEM_DIAG_MB (mặc định một nửa trần) thì ghi một báo cáo: nơi cấp phát nhiều nhất, loại đối tượng Python nhiều nhất, luồng.
Mã thoát 75 nghĩa là "vượt trần, hãy chạy lại".
"""
from __future__ import annotations

import gc
import logging
import os
import sys
import threading
import time
import tracemalloc
from collections import Counter

log = logging.getLogger("server.mem")

EXIT_CODE = 75
LIMIT_MB = int(os.environ.get("SERVER_MEM_LIMIT_MB", "3072"))
INTERVAL_S = float(os.environ.get("SERVER_MEM_INTERVAL_S", "30"))

DIAG = os.environ.get("SERVER_MEM_DIAG", "0") == "1"
DIAG_MB = int(os.environ.get("SERVER_MEM_DIAG_MB", str(LIMIT_MB // 2 if LIMIT_MB else 1536)))

hits: Counter = Counter()          # số yêu cầu theo đường dẫn từ lần ghi log trước
slow: dict[str, float] = {}        # yêu cầu chậm nhất theo đường dẫn từ lần ghi log trước (giây)
_started = False


def private_mb() -> int | None:
    """Bộ nhớ cam kết (private bytes) của tiến trình này, MB. Chỉ hỗ trợ Windows; nơi khác trả None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ps = ctypes.WinDLL("psapi", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    ps.GetProcessMemoryInfo.restype = wintypes.BOOL
    p = PMC()
    p.cb = ctypes.sizeof(p)
    ok = ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return int(p.PrivateUsage // 2**20) if ok else None


def diag_report(top: int = 15) -> str:
    """Báo cáo chẩn đoán bộ nhớ: nơi cấp phát nhiều nhất (cần tracemalloc), loại đối tượng Python nhiều nhất, các luồng."""
    lines = [f"BÁO CÁO CHẨN ĐOÁN: bộ nhớ cam kết {private_mb()} MB, {threading.active_count()} luồng"]
    if tracemalloc.is_tracing():
        cur, peak = tracemalloc.get_traced_memory()
        lines.append(f"tracemalloc: hiện {cur // 2**20} MB, đỉnh {peak // 2**20} MB (chỉ phần Python cấp phát, không gồm DuckDB và thư viện gốc)")
        for st in tracemalloc.take_snapshot().statistics("lineno")[:top]:
            lines.append(f"  {st.size // 1024:>8} KB  {st.count:>7} khối  {st.traceback[0]}")
    else:
        lines.append("tracemalloc chưa bật: đặt SERVER_MEM_DIAG=1 rồi chạy lại để có nơi cấp phát")
    kinds = Counter(type(o).__name__ for o in gc.get_objects())
    lines.append("đối tượng Python nhiều nhất: " + ", ".join(f"{k} x{n}" for k, n in kinds.most_common(8)))
    names = Counter(t.name.split("_")[0].split("-")[0] for t in threading.enumerate())
    lines.append("luồng theo loại: " + ", ".join(f"{k} x{n}" for k, n in names.most_common(6)))
    return "\n".join(lines)


def note_request(path: str, seconds: float) -> None:
    hits[path] += 1
    if seconds > slow.get(path, 0.0):
        slow[path] = seconds


def snapshot() -> dict:
    from server import limits
    return {"private_mb": private_mb(), "threads": threading.active_count(), "limit_mb": LIMIT_MB, "diag": DIAG, **limits.stats()}


def _loop() -> None:
    last = 0
    reported = False
    while True:
        time.sleep(INTERVAL_S)
        mb = private_mb()
        if mb is None:
            return
        top = ", ".join(f"{p} x{n} (max {slow.get(p, 0):.1f}s)" for p, n in hits.most_common(5)) or "không có yêu cầu"
        if abs(mb - last) >= 200 or (LIMIT_MB and mb > LIMIT_MB * 0.75):
            log.warning("bộ nhớ cam kết %d MB (trần %d), %d luồng; yêu cầu gần đây: %s", mb, LIMIT_MB, threading.active_count(), top)
            last = mb
        if DIAG and mb > DIAG_MB and not reported:
            reported = True
            log.warning("%s", diag_report())
        elif mb < DIAG_MB * 0.8:
            reported = False
        hits.clear()
        slow.clear()
        if LIMIT_MB and mb > LIMIT_MB:
            if DIAG:
                log.error("%s", diag_report())
            log.error("vượt trần bộ nhớ %d MB > %d MB, thoát với mã %d để dev.ps1 khởi động lại", mb, LIMIT_MB, EXIT_CODE)
            logging.shutdown()
            os._exit(EXIT_CODE)


def start() -> None:
    global _started
    if _started or sys.platform != "win32":
        return
    _started = True
    if DIAG and not tracemalloc.is_tracing():
        tracemalloc.start(8)
    threading.Thread(target=_loop, name="memguard", daemon=True).start()
