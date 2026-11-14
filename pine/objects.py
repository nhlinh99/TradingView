"""Mảng, chuỗi, đối tượng vẽ (line, label, box, table), alert() và các hàm phụ của engine Pine.

Đối tượng vẽ không được vẽ ngay mà ghi lại thành dữ liệu để giao diện vẽ: engine chạy xong, `Interp.objs` chứa mọi
line/label/box/table còn sống (chưa bị xoá). Toạ độ x là chỉ số nến (bar_index) và có thể vượt quá nến cuối.
"""
from __future__ import annotations

import math

from . import interp as I
from .ta import Cum, Dmi, isna

NAN = float("nan")
MAX_OBJECTS = 500          # như max_lines_count, max_labels_count, max_boxes_count mặc định của Pine

I.CONSTS.update({
    **{f"display.{k}": k for k in ("all", "none", "pane", "data_window", "price_scale", "status_line")},
    **{f"position.{k}": k for k in ("top_left", "top_center", "top_right", "middle_left", "middle_center", "middle_right",
                                    "bottom_left", "bottom_center", "bottom_right")},
    **{f"label.style_{k}": k for k in ("label_up", "label_down", "label_left", "label_right", "label_center", "label_lower_left",
                                       "label_lower_right", "label_upper_left", "label_upper_right", "none", "arrowup", "arrowdown",
                                       "circle", "square", "diamond", "triangleup", "triangledown", "cross", "xcross", "flag",
                                       "text_outline")},
    **{f"line.style_{k}": k for k in ("solid", "dashed", "dotted", "arrow_left", "arrow_right", "arrow_both")},
    **{f"text.align_{k}": k for k in ("left", "center", "right", "top", "bottom")},
    **{f"xloc.{k}": k for k in ("bar_index", "bar_time")},
    **{f"yloc.{k}": k for k in ("price", "abovebar", "belowbar")},
    **{f"alert.freq_{k}": k for k in ("all", "once_per_bar", "once_per_bar_close")},
    **{f"size.{k}": k for k in ("auto",)},
    "format.mintick": "mintick", "format.price": "price", "format.volume": "volume",
    "barstate.isrealtime": False, "barstate.ishistory": True, "barstate.isnew": True, "barstate.isconfirmed": True,
})


def A(args, kw, pos, name, default=None):
    if name in kw:
        return kw[name]
    return args[pos] if pos < len(args) else default


# ---------------- mảng ----------------

def _arr(x):
    if not isinstance(x, list):
        raise I.PineRuntimeError("cần một mảng")
    return x


def _new(default):
    def f(it, node, args, kw):
        n = int(A(args, kw, 0, "size", 0))
        v = A(args, kw, 1, "initial_value", default)
        return [v for _ in range(max(0, n))]
    return f


def _idx(a, i, node):
    i = int(i)
    if i < 0:
        i += len(a)
    if not 0 <= i < len(a):
        raise I.PineRuntimeError(f"chỉ số mảng {i} ngoài phạm vi 0..{len(a) - 1}", node.line)
    return i


def a_get(it, node, args, kw):
    a = _arr(args[0])
    return a[_idx(a, args[1], node)]


def a_set(it, node, args, kw):
    a = _arr(args[0])
    a[_idx(a, args[1], node)] = args[2]
    return NAN


def a_push(it, node, args, kw):
    _arr(args[0]).append(args[1])
    return NAN


def a_pop(it, node, args, kw):
    a = _arr(args[0])
    if not a:
        raise I.PineRuntimeError("array.pop trên mảng rỗng", node.line)
    return a.pop()


def a_remove(it, node, args, kw):
    a = _arr(args[0])
    return a.pop(_idx(a, args[1], node))


def a_insert(it, node, args, kw):
    a = _arr(args[0])
    a.insert(int(args[1]), args[2])
    return NAN


def a_clear(it, node, args, kw):
    _arr(args[0]).clear()
    return NAN


def _nums(a):
    return [float(x) for x in a if not isna(x)]


def _stat(fn):
    def f(it, node, args, kw):
        v = _nums(_arr(args[0]))
        return fn(v) if v else NAN
    return f


# ---------------- chuỗi ----------------

def _decimals(tick: float) -> int:
    d = 0
    while d < 12 and abs(round(tick * 10 ** d) - tick * 10 ** d) > 1e-9:
        d += 1
    return d


def fmt_value(v, fmt, tick: float) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isna(v):
        return "NaN"
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "[" + ", ".join(fmt_value(x, None, tick) for x in v) + "]"
    x = float(v)
    if fmt in (None, "", "default"):
        return repr(round(x, 10)).rstrip("0").rstrip(".") if x != int(x) else str(int(x))
    if fmt == "mintick" or fmt == "price":
        return f"{x:.{_decimals(tick)}f}"
    if fmt == "volume":
        for lim, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(x) >= lim:
                return f"{x / lim:.3f}".rstrip("0").rstrip(".") + suf
        return f"{x:.0f}"
    if isinstance(fmt, str) and ("#" in fmt or "0" in fmt):
        dec = fmt.split(".", 1)[1] if "." in fmt else ""
        digits = len(dec)
        s = f"{x:.{digits}f}"
        if "." in s and "0" not in dec:        # "#.##": bỏ số 0 thừa ở cuối như Pine
            s = s.rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    return str(x)


def s_tostring(it, node, args, kw):
    return fmt_value(args[0], A(args, kw, 1, "format"), it.tick)


def s_length(it, node, args, kw):
    return float(len(str(args[0])))


def s_substring(it, node, args, kw):
    s = str(args[0])
    a = int(args[1])
    b = int(args[2]) if len(args) > 2 else len(s)
    return s[a:b]


def s_replace_all(it, node, args, kw):
    return str(args[0]).replace(str(args[1]), str(args[2]))


def s_contains(it, node, args, kw):
    return str(args[1]) in str(args[0])


def s_upper(it, node, args, kw):
    return str(args[0]).upper()


def s_lower(it, node, args, kw):
    return str(args[0]).lower()


def s_tonumber(it, node, args, kw):
    try:
        return float(str(args[0]))
    except ValueError:
        return NAN


def s_format(it, node, args, kw):
    s = str(args[0])
    for i, v in enumerate(args[1:]):
        s = s.replace("{" + str(i) + "}", fmt_value(v, None, it.tick))
    return s


# ---------------- màu ----------------

def _rgb(c):
    if c is None or isna(c):
        return (0, 0, 0, 0)
    h = str(c).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = int(h[6:8], 16) if len(h) >= 8 else 255
    return r, g, b, a


def c_r(it, node, args, kw):
    return float(_rgb(args[0])[0])


def c_g(it, node, args, kw):
    return float(_rgb(args[0])[1])


def c_b(it, node, args, kw):
    return float(_rgb(args[0])[2])


def c_t(it, node, args, kw):
    return float(round((255 - _rgb(args[0])[3]) * 100 / 255))


def c_gradient(it, node, args, kw):
    v, lo, hi = (I._num(args[i]) for i in range(3))
    if any(isna(x) for x in (v, lo, hi)) or args[3] is None or args[4] is None:
        return None
    f = 0.0 if hi == lo else min(1.0, max(0.0, (v - lo) / (hi - lo)))
    a, b = _rgb(args[3]), _rgb(args[4])
    c = [round(a[i] + (b[i] - a[i]) * f) for i in range(4)]
    return f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}{c[3]:02X}"


# ---------------- đối tượng vẽ ----------------

def _store(it, kind):
    lst = it.objs[kind]
    return lst


def _make(kind, fields):
    """fields: danh sách (tên tham số theo thứ tự vị trí, mặc định)."""
    def f(it, node, args, kw):
        o = {"_k": kind, "dead": False}
        for i, (name, default) in enumerate(fields):
            o[name] = A(args, kw, i, name, default)
        o["bar"] = it.i
        lst = it.objs[{"line": "lines", "label": "labels", "box": "boxes"}[kind]]
        lst.append(o)
        if len(lst) > MAX_OBJECTS * 4:           # giữ bộ nhớ có giới hạn: bỏ các đối tượng đã xoá lâu nhất
            lst[:] = [x for x in lst if not x["dead"]][-MAX_OBJECTS:]
        return o
    return f


def _setter(field):
    def f(it, node, args, kw):
        o = args[0]
        if not isinstance(o, dict):
            return NAN
        o[field] = args[1]
        return NAN
    return f


def _setxy(fx, fy):
    def f(it, node, args, kw):
        o = args[0]
        if isinstance(o, dict):
            o[fx], o[fy] = args[1], args[2]
        return NAN
    return f


def _delete(it, node, args, kw):
    o = args[0]
    if isinstance(o, dict):
        o["dead"] = True
    return NAN


def t_new(it, node, args, kw):
    o = {"_k": "table", "dead": False, "cells": {}, "merges": []}
    for i, (name, default) in enumerate((("position", "top_right"), ("columns", 1), ("rows", 1), ("bgcolor", None), ("frame_color", None),
                                         ("frame_width", 0), ("border_color", None), ("border_width", 0))):
        o[name] = A(args, kw, i, name, default)
    it.objs["tables"].append(o)
    return o


def t_cell(it, node, args, kw):
    t = args[0]
    if not isinstance(t, dict):
        return NAN
    col, row = int(args[1]), int(args[2])
    cell = {"text": A(args, kw, 3, "text", "")}
    for name in ("text_color", "text_size", "bgcolor", "tooltip", "text_halign", "width", "height"):
        if name in kw:
            cell[name] = kw[name]
    t["cells"][(col, row)] = cell
    return NAN


def t_merge(it, node, args, kw):
    t = args[0]
    if isinstance(t, dict):
        t["merges"].append(tuple(int(x) for x in args[1:5]))
    return NAN


# ---------------- alert, fill, barcolor ----------------

def f_alert(it, node, args, kw):
    it.alert_events.append({"bar": it.i, "message": str(args[0])})
    return NAN


def f_fill(it, node, args, kw):
    a, b = args[0], args[1]
    key = node.id
    if not (isinstance(a, dict) and isinstance(b, dict) and "_plot" in a and "_plot" in b):
        return NAN                          # fill giữa hline hoặc đối số không phải plot: bỏ qua
    rec = it.fills.get(key)
    if rec is None:
        rec = it.fills[key] = {"a": a["_plot"], "b": b["_plot"], "title": kw.get("title", ""), "colors": [None] * (it.n + I.FUTURE_PAD)}
    j = it.i + int(a.get("offset", 0))              # màu gắn với vị trí đã dịch của hai plot
    if 0 <= j < len(rec["colors"]):
        rec["colors"][j] = I._col(A(args, kw, 2, "color", None))
    return NAN


def f_barcolor(it, node, args, kw):
    c = I._col(A(args, kw, 0, "color", None))
    it.barcolors[it.i] = c
    return NAN


# ---------------- ta bổ sung ----------------

def ta_cum(it, node, args, kw):
    return it.state(node, Cum).update(args[0])


def ta_dmi(it, node, args, kw):
    dl, sl = int(A(args, kw, 0, "diLength")), int(A(args, kw, 1, "adxSmoothing"))
    b, i = it.bars, it.i
    return it.state(node, lambda: Dmi(dl, sl)).update(b.high[i], b.low[i], b.close[i])


def _cast(fn):
    def f(it, node, args, kw):
        x = args[0]
        return NAN if isna(x) else fn(x)
    return f


def register() -> None:
    B = I.BUILTINS
    for kind, d in (("float", NAN), ("int", NAN), ("string", ""), ("bool", False), ("color", None), ("line", NAN), ("label", NAN),
                    ("box", NAN), ("table", NAN), ("linefill", NAN)):
        B[f"array.new_{kind}"] = _new(d)
    B["array.new"] = _new(NAN)
    B.update({
        "array.get": a_get, "array.set": a_set, "array.push": a_push, "array.pop": a_pop, "array.remove": a_remove,
        "array.insert": a_insert, "array.clear": a_clear, "array.size": lambda it, n, a, k: float(len(_arr(a[0]))),
        "array.includes": lambda it, n, a, k: a[1] in _arr(a[0]),
        "array.sum": _stat(sum), "array.avg": _stat(lambda v: sum(v) / len(v)), "array.max": _stat(max), "array.min": _stat(min),
        "array.first": lambda it, n, a, k: _arr(a[0])[0], "array.last": lambda it, n, a, k: _arr(a[0])[-1],
        "str.tostring": s_tostring, "str.length": s_length, "str.substring": s_substring, "str.replace_all": s_replace_all,
        "str.contains": s_contains, "str.upper": s_upper, "str.lower": s_lower, "str.tonumber": s_tonumber, "str.format": s_format,
        "color.from_gradient": c_gradient, "color.r": c_r, "color.g": c_g, "color.b": c_b, "color.t": c_t,
        "line.new": _make("line", (("x1", NAN), ("y1", NAN), ("x2", NAN), ("y2", NAN), ("xloc", "bar_index"), ("extend", "none"),
                                   ("color", None), ("style", "solid"), ("width", 1))),
        "label.new": _make("label", (("x", NAN), ("y", NAN), ("text", ""), ("xloc", "bar_index"), ("yloc", "price"), ("color", None),
                                     ("style", "label_down"), ("textcolor", None), ("size", "normal"), ("textalign", "center"),
                                     ("tooltip", ""))),
        "box.new": _make("box", (("left", NAN), ("top", NAN), ("right", NAN), ("bottom", NAN), ("border_color", None),
                                 ("border_width", 1), ("border_style", "solid"), ("extend", "none"), ("xloc", "bar_index"),
                                 ("bgcolor", None), ("text", ""))),
        "table.new": t_new, "table.cell": t_cell, "table.merge_cells": t_merge, "table.delete": _delete,
        "line.delete": _delete, "label.delete": _delete, "box.delete": _delete,
        "alert": f_alert, "fill": f_fill, "barcolor": f_barcolor, "ta.cum": ta_cum, "ta.dmi": ta_dmi,
        "int": _cast(lambda x: float(int(x))), "float": _cast(float), "str": lambda it, n, a, k: fmt_value(a[0], None, it.tick),
        "bool": lambda it, n, a, k: I._truthy(a[0]),
    })
    for k, fields in (("line", ("x1", "y1", "x2", "y2", "color", "width", "style", "extend")),
                      ("label", ("x", "y", "text", "color", "textcolor", "style", "size", "tooltip")),
                      ("box", ("left", "top", "right", "bottom", "border_color", "border_width", "border_style", "bgcolor", "text"))):
        for f in fields:
            B[f"{k}.set_{f}"] = _setter(f)
    B["line.set_xy1"] = _setxy("x1", "y1")
    B["line.set_xy2"] = _setxy("x2", "y2")
    B["label.set_xy"] = _setxy("x", "y")
    B["box.set_lefttop"] = _setxy("left", "top")
    B["box.set_rightbottom"] = _setxy("right", "bottom")
    # tên hàm kiểu Pine v4 (không có namespace) và study()
    for v4, v6 in (("study", "indicator"), ("avg", "math.avg"), ("sma", "ta.sma"), ("ema", "ta.ema"), ("rma", "ta.rma"), ("rsi", "ta.rsi"),
                   ("atr", "ta.atr"), ("stdev", "ta.stdev"), ("change", "ta.change"), ("crossover", "ta.crossover"),
                   ("crossunder", "ta.crossunder"), ("cum", "ta.cum"), ("highest", "ta.highest"), ("lowest", "ta.lowest"),
                   ("sign", "math.sign"), ("abs", "math.abs"), ("max", "math.max"), ("min", "math.min"), ("round", "math.round"),
                   ("sqrt", "math.sqrt"), ("log", "math.log"), ("exp", "math.exp"), ("pow", "math.pow"), ("floor", "math.floor"),
                   ("ceil", "math.ceil"), ("tostring", "str.tostring"), ("tonumber", "str.tonumber")):
        if v6 in B and v4 not in B:
            B[v4] = B[v6]
    B["line.get_price"] = lambda it, n, a, k: NAN
    B["line.get_x1"] = lambda it, n, a, k: a[0]["x1"]
    B["line.get_x2"] = lambda it, n, a, k: a[0]["x2"]
    B["line.get_y1"] = lambda it, n, a, k: a[0]["y1"]
    B["line.get_y2"] = lambda it, n, a, k: a[0]["y2"]
    B["label.get_x"] = lambda it, n, a, k: a[0]["x"]
    B["label.get_y"] = lambda it, n, a, k: a[0]["y"]


register()
