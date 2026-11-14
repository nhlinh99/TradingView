"""Chạy một script Pine trên chuỗi nến và đóng gói kết quả thành dict JSON được.

Mọi mảng giá trị dài đúng bằng số nến, giá trị thiếu là null.
"""
from __future__ import annotations

import math

from .interp import Bars, Interp, PineRuntimeError
from .lexer import PineSyntaxError
from .parser import parse


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def run_script(source: str, bars: Bars, *, symbol: str = "", tf: str = "1m", tz_offset_ms: int = 0, provider=None,
               inputs: dict | None = None, external: dict | None = None, syminfo_type: str = "crypto") -> dict:
    """Ném PineSyntaxError hoặc PineRuntimeError khi script sai."""
    ast = parse(source)
    it = Interp(source, bars, symbol=symbol, tf=tf, tz_offset_ms=tz_offset_ms, provider=provider, inputs=inputs,
                external=external, syminfo_type=syminfo_type, ast=ast)
    it.run()
    strat = it.strategy.summary()
    return {
        "meta": it.meta,
        "inputs": list(it.input_defs.values()),
        "times": list(bars.time),
        "plots": [{**p, "values": [_clean(x) for x in p["values"]]} for p in it.plots.values()],
        "shapes": list(it.shapes.values()),
        "bgcolors": list(it.bgcolors.values()),
        "hlines": [{**h, "price": _clean(h["price"])} for h in it.hlines.values()],
        "alerts": list(it.alerts.values()),
        "strategy": None if strat is None else {**strat, "equity": [_clean(x) for x in strat["equity"]]},
    }


__all__ = ["run_script", "Bars", "PineSyntaxError", "PineRuntimeError"]
