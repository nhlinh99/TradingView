"""Gamma exposure (GEX) của chuỗi quyền chọn BTC từ Deribit.

Công thức (đô-la mỗi 1% biến động giá): GEX = gamma x OI x kích thước hợp đồng x spot^2 x 0.01.
Call tính dương, put tính âm (giả định nhà tạo lập thị trường long call, short put của khách; đây là quy ước
phổ biến, không phải vị thế thật, vì Deribit không công bố ai nắm bên nào).
Gamma tính từ mark IV bằng Black-76 với lãi suất 0: gamma = phi(d1) / (F sigma sqrt(T)),
d1 = (ln(F/K) + sigma^2 T / 2) / (sigma sqrt(T)).
Kích thước hợp đồng BTC trên Deribit là 1 BTC.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

CONTRACT_SIZE = 1.0
YEAR_MS = 365 * 86_400_000
_MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}

# Một dòng của chuỗi quyền chọn: (expiry_ms, strike, is_call, oi, iv_percent, fwd)
Option = tuple[int, int, bool, float, float, float]


def bs_gamma(fwd: float, strike: float, iv_pct: float, years: float) -> float:
    if fwd <= 0 or strike <= 0 or iv_pct <= 0 or years <= 0:
        return 0.0
    sd = iv_pct / 100.0 * math.sqrt(years)
    d1 = (math.log(fwd / strike) + 0.5 * sd * sd) / sd
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return pdf / (fwd * sd)


def parse_instrument(name: str) -> tuple[int, int, bool] | None:
    """'BTC-29JAN27-72000-C' -> (expiry_ms lúc 08:00 UTC, strike, is_call). None nếu không đúng dạng."""
    try:
        _cur, exp, strike, cp = name.split("-")
        day = int(exp[:-5])
        month = _MONTHS[exp[-5:-2]]
        year = 2000 + int(exp[-2:])
        ms = int(datetime(year, month, day, 8, tzinfo=timezone.utc).timestamp() * 1000)
        if cp not in ("C", "P"):
            return None
        return ms, int(strike), cp == "C"
    except (ValueError, KeyError):
        return None


def option_rows(summary: Iterable[dict]) -> tuple[list[tuple], float | None]:
    """Đổi kết quả get_book_summary_by_currency thành các dòng (expiry, strike, cp, oi, iv, fwd) và giá chỉ số."""
    rows: list[tuple] = []
    spot = None
    for it in summary:
        p = parse_instrument(it.get("instrument_name", ""))
        if p is None or not it.get("underlying_price"):
            continue
        spot = it.get("estimated_delivery_price") or spot
        oi = float(it.get("open_interest") or 0.0)
        iv = it.get("mark_iv")
        rows.append((p[0], p[1], p[2], oi, float(iv) if iv else 0.0, float(it["underlying_price"])))
    return rows, (float(spot) if spot else None)


def gex_by_strike(options: Iterable[Option], now_ms: int, spot: float, shift: float = 1.0) -> dict[int, dict[str, float]]:
    """GEX từng strike: {strike: {'call': +, 'put': -, 'net': tổng}}.

    shift là hệ số dịch giá: dùng spot*shift làm spot và fwd*shift làm fwd (để tìm điểm gamma flip).
    Bỏ qua quyền chọn đã hết hạn hoặc không có IV.
    """
    s = spot * shift
    out: dict[int, dict[str, float]] = defaultdict(lambda: {"call": 0.0, "put": 0.0, "net": 0.0})
    for expiry, strike, is_call, oi, iv, fwd in options:
        years = (expiry - now_ms) / YEAR_MS
        g = bs_gamma(fwd * shift, strike, iv, years)
        if g == 0.0 or oi <= 0:
            continue
        v = g * oi * CONTRACT_SIZE * s * s * 0.01
        side = "call" if is_call else "put"
        sign = 1.0 if is_call else -1.0
        out[strike][side] += sign * v
        out[strike]["net"] += sign * v
    return dict(out)


def total_gex(options: list[Option], now_ms: int, spot: float, shift: float = 1.0) -> float:
    return sum(v["net"] for v in gex_by_strike(options, now_ms, spot, shift).values())


def levels(options: list[Option], now_ms: int, spot: float) -> dict:
    """Tổng GEX, gamma flip (giá mà tổng GEX đổi dấu, gần spot nhất), call wall và put wall."""
    per = gex_by_strike(options, now_ms, spot)
    if not per:
        return {"total": 0.0, "flip": None, "call_wall": None, "put_wall": None, "by_strike": []}
    call_wall = max(per, key=lambda k: per[k]["call"])
    put_wall = min(per, key=lambda k: per[k]["put"])
    grid = [0.7 + 0.01 * i for i in range(61)]          # 0.70 .. 1.30 lần spot
    vals = [total_gex(options, now_ms, spot, g) for g in grid]
    best = None
    for i in range(len(grid) - 1):
        a, b = vals[i], vals[i + 1]
        if a == 0 or (a < 0) != (b < 0):
            x = grid[i] if a == b else grid[i] + (grid[i + 1] - grid[i]) * (0 - a) / (b - a)
            price = x * spot
            if best is None or abs(price - spot) < abs(best - spot):
                best = price
    return {
        "total": sum(v["net"] for v in per.values()),
        "flip": round(best, 2) if best is not None else None,
        "call_wall": call_wall if per[call_wall]["call"] > 0 else None,
        "put_wall": put_wall if per[put_wall]["put"] < 0 else None,
        "by_strike": [{"strike": k, **{n: round(x, 2) for n, x in per[k].items()}} for k in sorted(per)],
    }
