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


def _obj(o: dict) -> dict:
    return {k: _clean(v) for k, v in o.items() if k not in ("_k", "dead", "cells", "merges")}


def _objects(it: Interp) -> dict:
    live = lambda lst: [_obj(o) for o in lst if not o["dead"]][-500:]
    tables = []
    for t in it.objs["tables"]:
        if t["dead"]:
            continue
        tables.append({**_obj(t), "cells": [{"col": c, "row": r, **{k: _clean(v) for k, v in cell.items()}} for (c, r), cell in sorted(t["cells"].items())],
                       "merges": [list(m) for m in t["merges"]]})
    return {"lines": live(it.objs["lines"]), "labels": live(it.objs["labels"]), "boxes": live(it.objs["boxes"]), "tables": tables[-4:]}


def run_script(source: str, bars: Bars, *, symbol: str = "", tf: str = "1m", tz_offset_ms: int = 0, provider=None,
               inputs: dict | None = None, external: dict | None = None, syminfo_type: str = "crypto",
               strategy_opts: dict | None = None, tick: float = 0.01, chart_bg: str = "#131722") -> dict:
    """Ném PineSyntaxError hoặc PineRuntimeError khi script sai."""
    ast = parse(source)
    it = Interp(source, bars, symbol=symbol, tf=tf, tz_offset_ms=tz_offset_ms, provider=provider, inputs=inputs,
                external=external, syminfo_type=syminfo_type, ast=ast, strategy_opts=strategy_opts, tick=tick, chart_bg=chart_bg)
    it.run()
    strat = it.strategy.summary()
    total = len(bars) + it.future_bars               # plot(offset>0) có thể ghi tới các nến tương lai
    plot_ids = list(it.plots)
    # fill chỉ giữ lại nếu cả hai plot đều tồn tại; a, b là chỉ số trong danh sách plots; offset của fill = offset của plot a
    fills = [{"a": plot_ids.index(f["a"]), "b": plot_ids.index(f["b"]), "title": f["title"], "colors": f["colors"][:total]}
             for f in it.fills.values() if f["a"] in plot_ids and f["b"] in plot_ids]
    return {
        "future_bars": it.future_bars,
        "fills": fills,
        "meta": it.meta,
        "inputs": list(it.input_defs.values()),
        "times": list(bars.time),
        "plots": [{**p, "values": [_clean(x) for x in p["values"][:total]], "colors": p["colors"][:total]} for p in it.plots.values()],
        "shapes": list(it.shapes.values()),
        "bgcolors": list(it.bgcolors.values()),
        "hlines": [{**h, "price": _clean(h["price"])} for h in it.hlines.values()],
        "alerts": list(it.alerts.values()),
        "alert_events": it.alert_events[-200:],
        "objects": _objects(it),
        "barcolors": [it.barcolors.get(i) for i in range(len(bars))] if it.barcolors else [],
        "strategy": None if strat is None else {**strat, "equity": [_clean(x) for x in strat["equity"]]},
    }


__all__ = ["run_script", "Bars", "PineSyntaxError", "PineRuntimeError"]
