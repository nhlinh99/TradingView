"""Hàm chỉ báo `ta.*` của engine Pine. Mỗi hàm là một lớp nhỏ giữ trạng thái giữa các nến và được gắn theo vị trí gọi
trong mã nguồn (xem Interp.state), giống cách Pine yêu cầu hàm ta.* chạy trên mọi nến.

Quy ước giá trị thiếu: NaN (Pine `na`). Cửa sổ có NaN cho kết quả NaN; EMA và RMA bắt đầu bằng SMA của n giá trị đầu
tiên (đúng cách Pine khởi tạo), nên các giá trị trước đó là NaN.
"""
from __future__ import annotations

import math
from collections import deque

NAN = float("nan")


def isna(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


class Sma:
    def __init__(self, n: int):
        self.n, self.w = n, deque(maxlen=n)

    def update(self, x: float) -> float:
        self.w.append(NAN if isna(x) else float(x))
        if len(self.w) < self.n or any(math.isnan(v) for v in self.w):
            return NAN
        return math.fsum(self.w) / self.n


class Ema:
    """EMA (alpha = 2/(n+1)) hoặc RMA (alpha = 1/n); khởi tạo bằng SMA của n giá trị đầu."""

    def __init__(self, n: int, alpha: float):
        self.n, self.alpha, self.seed, self.v = n, alpha, [], NAN

    def update(self, x: float) -> float:
        if isna(x):
            return NAN
        if math.isnan(self.v):
            self.seed.append(float(x))
            if len(self.seed) < self.n:
                return NAN
            self.v = math.fsum(self.seed) / self.n
            self.seed = []
            return self.v
        self.v = self.alpha * float(x) + (1 - self.alpha) * self.v
        return self.v


def make_ema(n: int) -> Ema:
    return Ema(n, 2.0 / (n + 1))


def make_rma(n: int) -> Ema:
    return Ema(n, 1.0 / n)


class Stdev:
    """Độ lệch chuẩn tổng thể (chia n), như ta.stdev của Pine."""

    def __init__(self, n: int):
        self.n, self.w = n, deque(maxlen=n)

    def update(self, x: float) -> float:
        self.w.append(NAN if isna(x) else float(x))
        if len(self.w) < self.n or any(math.isnan(v) for v in self.w):
            return NAN
        m = math.fsum(self.w) / self.n
        return math.sqrt(math.fsum((v - m) ** 2 for v in self.w) / self.n)


class Extreme:
    def __init__(self, n: int, hi: bool):
        self.n, self.hi, self.w = n, hi, deque(maxlen=n)

    def update(self, x: float) -> float:
        self.w.append(NAN if isna(x) else float(x))
        if len(self.w) < self.n or any(math.isnan(v) for v in self.w):
            return NAN
        return max(self.w) if self.hi else min(self.w)


class Change:
    def __init__(self, n: int):
        self.n, self.h = n, []

    def update(self, x: float) -> float:
        self.h.append(NAN if isna(x) else float(x))
        if len(self.h) <= self.n:
            return NAN
        return self.h[-1] - self.h[-1 - self.n]


class Cross:
    def __init__(self, up: bool):
        self.up, self.prev = up, None

    def update(self, a: float, b: float) -> bool:
        res = False
        if self.prev is not None and not any(isna(v) for v in (a, b, *self.prev)):
            pa, pb = self.prev
            res = (a > b and pa <= pb) if self.up else (a < b and pa >= pb)
        self.prev = (a, b)
        return res


class Rsi:
    def __init__(self, n: int):
        self.prev, self.up, self.dn = None, make_rma(n), make_rma(n)

    def update(self, x: float) -> float:
        if isna(x):
            return NAN
        if self.prev is None:
            self.prev = float(x)
            return NAN
        d = float(x) - self.prev
        self.prev = float(x)
        u, dn = self.up.update(max(d, 0.0)), self.dn.update(max(-d, 0.0))
        if math.isnan(u) or math.isnan(dn):
            return NAN
        if dn == 0:
            return 100.0
        if u == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + u / dn)


class Atr:
    def __init__(self, n: int):
        self.r, self.pc = make_rma(n), None

    def update(self, h: float, l: float, c: float) -> float:
        tr = h - l if self.pc is None else max(h - l, abs(h - self.pc), abs(l - self.pc))
        self.pc = c
        return self.r.update(tr)


def true_range(h: float, l: float, pc: float | None) -> float:
    return h - l if pc is None or isna(pc) else max(h - l, abs(h - pc), abs(l - pc))


class Vwap:
    """VWAP tích luỹ, về 0 khi `anchor` đúng. Dải = vwap ± mult × độ lệch chuẩn gia quyền theo khối lượng."""

    def __init__(self):
        self.pv = self.v = self.p2v = 0.0

    def update(self, src: float, vol: float, anchor: bool, mult: float) -> tuple[float, float, float]:
        if anchor:
            self.pv = self.v = self.p2v = 0.0
        if isna(src) or isna(vol):
            return NAN, NAN, NAN
        self.pv += src * vol
        self.v += vol
        self.p2v += src * src * vol
        if self.v == 0:
            return NAN, NAN, NAN
        vw = self.pv / self.v
        var = max(self.p2v / self.v - vw * vw, 0.0)
        sd = math.sqrt(var)
        return vw, vw + mult * sd, vw - mult * sd
