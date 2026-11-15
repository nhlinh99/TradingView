"""Cảnh báo khi collector im lặng: không có file mới của `ticks` hoặc `book` trong hơn 5 phút.

Chạy bên trong tiến trình `collector.alerts` (kiểm mỗi 60 giây) và gửi qua cùng kênh với cảnh báo giá (toast Windows, Telegram).
Mốc ghi cuối là thời điểm sửa (mtime) của file con mới nhất của hôm nay hoặc hôm qua theo UTC. Collector ghi một file con mỗi 60 giây
nên 5 phút im lặng nghĩa là tiến trình đã dừng, kẹt hoặc mất mạng.

Quy tắc:
  - Chỉ theo dõi cặp (loại, symbol) từng có file trong 7 ngày gần đây, để không báo nhầm symbol không dùng.
  - Báo một lần khi bắt đầu im lặng, nhắc lại mỗi 30 phút nếu vẫn im, và báo một lần khi phục hồi.
  - Chỉ theo dõi symbol crypto. Cổ phiếu VN chỉ ghi trong giờ giao dịch nên không theo dõi ở đây.
  - Hạn chế đã biết: `hotmerge` ghi lại file ngày khi gộp (mỗi 30 phút), nên khi chỉ còn file đã gộp thì mốc ghi cuối là lần gộp đó.
    Vì vậy chỉ tính file con (`.pNNN`); nếu không còn file con nào thì mới dùng file chuẩn.

Cấu hình (biến môi trường): WATCHDOG_SILENCE_S (mặc định 300), WATCHDOG_REMIND_S (mặc định 1800), WATCHDOG_ENABLED=0 để tắt.
"""
from __future__ import annotations

import logging
import os
import re
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from common import store

log = logging.getLogger("collector.watchdog")

KINDS = ("ticks", "book")
SILENCE_S = float(os.environ.get("WATCHDOG_SILENCE_S", "300"))
REMIND_S = float(os.environ.get("WATCHDOG_REMIND_S", "1800"))
RECENT_DAYS = 7
_NAME = re.compile(r"^date=(\d{4}-\d{2}-\d{2})(\.p\w+)?\.parquet$")


def last_write(kind: str, symbol: str, now: float) -> tuple[float | None, bool]:
    """(mtime của file con mới nhất hôm nay hoặc hôm qua, từng có dữ liệu trong 7 ngày gần đây?). mtime None nghĩa là không thấy file."""
    d = store.data_dir() / kind / symbol
    if not d.is_dir():
        return None, False
    today = datetime.fromtimestamp(now, timezone.utc).date()
    recent = {(today - timedelta(days=i)).isoformat() for i in range(RECENT_DAYS)}
    near = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
    parts: list[float] = []
    canon: list[float] = []
    seen_recent = False
    with os.scandir(d) as it:
        for e in it:
            m = _NAME.match(e.name)
            if not m:
                continue
            day = m.group(1)
            if day in recent:
                seen_recent = True
            if day in near:
                (parts if m.group(2) else canon).append(e.stat().st_mtime)
    newest = max(parts) if parts else (max(canon) if canon else None)
    return newest, seen_recent


def _configured_symbols() -> list[str]:
    with open(store.ROOT / "config" / "symbols.toml", "rb") as f:
        return list(tomllib.load(f))


def targets(now: float, symbols: list[str] | None = None) -> dict[tuple[str, str], float | None]:
    """Mốc ghi cuối của mọi cặp (loại, symbol) đang được ghi. Cặp không có dữ liệu gần đây thì bỏ qua."""
    if symbols is None:
        symbols = [s for s in _configured_symbols() if store.symbol_config(s).get("market") != "vn"]
    out: dict[tuple[str, str], float | None] = {}
    for s in symbols:
        for k in KINDS:
            t, recent = last_write(k, s, now)
            if recent:
                out[(k, s)] = t
    return out


@dataclass
class Watchdog:
    silence_s: float = SILENCE_S
    remind_s: float = REMIND_S
    state: dict = field(default_factory=dict)     # (kind, symbol) -> {"since": mốc bắt đầu im, "told": lần báo cuối}

    def evaluate(self, last: dict[tuple[str, str], float | None], now: float) -> list[str]:
        """Trả về các tin cần gửi cho lượt kiểm này."""
        msgs: list[str] = []
        for key, t in last.items():
            kind, sym = key
            quiet = float("inf") if t is None else now - t
            st = self.state.get(key)
            if quiet > self.silence_s:
                if st is None:
                    self.state[key] = {"since": t if t is not None else now, "told": now}
                    msgs.append(f"Collector im lặng: {kind} {sym} không ghi mới {self._fmt(quiet)} (lần cuối {self._clock(t)}). "
                                "Kiểm tra scripts\\run-collectors.ps1.")
                elif now - st["told"] >= self.remind_s:
                    st["told"] = now
                    msgs.append(f"Vẫn im lặng: {kind} {sym} đã {self._fmt(quiet)} không ghi mới (lần cuối {self._clock(t)}).")
            elif st is not None:
                del self.state[key]
                msgs.append(f"Đã phục hồi: {kind} {sym} ghi dữ liệu lại sau {self._fmt(now - st['since'])} im lặng.")
        for key in [k for k in self.state if k not in last]:
            del self.state[key]          # cặp không còn được theo dõi (hết dữ liệu gần đây)
        return msgs

    @staticmethod
    def _fmt(sec: float) -> str:
        if sec == float("inf"):
            return "từ đầu ngày"
        m = int(sec // 60)
        return f"{m // 60} giờ {m % 60} phút" if m >= 60 else f"{m} phút"

    @staticmethod
    def _clock(t: float | None) -> str:
        return "không rõ" if t is None else datetime.fromtimestamp(t).strftime("%H:%M")


def run_once(dog: Watchdog, notifier: Callable[[str], str], now: float | None = None,
             target_fn: Callable[[float], dict[tuple[str, str], float | None]] = targets) -> list[str]:
    """Một lượt kiểm: đọc mốc ghi cuối, gửi tin cần gửi. Lỗi đọc đĩa chỉ ghi log, không làm dừng tiến trình cảnh báo."""
    now = now if now is not None else time.time()
    try:
        msgs = dog.evaluate(target_fn(now), now)
    except Exception:  # noqa: BLE001
        log.exception("không đọc được mốc ghi cuối của collector")
        return []
    for m in msgs:
        log.warning("%s", m)
        notifier(m)
    return msgs
