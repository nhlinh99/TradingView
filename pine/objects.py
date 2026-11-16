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
    "display.none": 0, "display.pane": 1, "display.data_window": 2, "display.price_scale": 4, "display.status_line": 8, "display.all": 15,
    "display.pine_screener": 16,
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
    **{f"earnings.{k}": k for k in ("actual", "estimate", "standardized")}, **{f"dividends.{k}": k for k in ("gross", "net")},
    **{f"splits.{k}": k for k in ("numerator", "denominator")}, "barmerge.lookahead_off": False,
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


def time_to_index(it, t) -> float:
    """Chỉ số nến (có thể thập phân, âm hoặc vượt nến cuối) ứng với thời điểm t (ms)."""
    import bisect
    if isna(t):
        return NAN
    ts = it.bars.time
    if not ts:
        return NAN
    if t >= ts[-1]:
        return (len(ts) - 1) + (t - ts[-1]) / it.tf_ms
    if t <= ts[0]:
        return (t - ts[0]) / it.tf_ms
    j = bisect.bisect_right(ts, t) - 1
    return j + (t - ts[j]) / (ts[j + 1] - ts[j])


def _is_point(x) -> bool:
    return isinstance(x, dict) and x.get("_k") == "point"


def point_xy(it, p: dict, xloc: str = "bar_index"):
    """(x theo chỉ số nến, giá) của một chart.point; ưu tiên `index`, không có thì đổi từ `time`."""
    x = p.get("index")
    if x is None or isna(x):
        x = time_to_index(it, p.get("time"))
    return x, p.get("price")


XFIELDS = {"line": ("x1", "x2"), "label": ("x",), "box": ("left", "right")}


def _make(kind, fields):
    """fields: danh sách (tên tham số theo thứ tự vị trí, mặc định). Nhận cả dạng toạ độ lẻ lẫn dạng chart.point."""
    def f(it, node, args, kw):
        args = list(args)
        npts = {"line": 2, "box": 2, "label": 1}[kind]
        if args and _is_point(args[0]):
            coords = []
            for p in args[:npts]:
                coords.extend(point_xy(it, p))
            args = coords + args[npts:]
        for nm in ("first_point", "top_left", "point"):          # tên tham số của dạng chart.point khi truyền theo tên
            if nm in kw and _is_point(kw[nm]):
                kw = dict(kw)
                args = list(point_xy(it, kw.pop(nm))) + args
        o = {"_k": kind, "dead": False}
        for i, (name, default) in enumerate(fields):
            o[name] = A(args, kw, i, name, default)
        if o.get("xloc") == "bar_time":
            for xf in XFIELDS[kind]:
                o[xf] = time_to_index(it, o[xf])
        o["bar"] = it.i
        lst = it.objs[{"line": "lines", "label": "labels", "box": "boxes"}[kind]]
        lst.append(o)
        if len(lst) > MAX_OBJECTS * 4:           # giữ bộ nhớ có giới hạn: bỏ các đối tượng đã xoá lâu nhất
            lst[:] = [x for x in lst if not x["dead"]][-MAX_OBJECTS:]
        return o
    return f


def _point_setter(*fields):
    """set_first_point(p) -> ghi (x, y) của chart.point vào hai trường."""
    def f(it, node, args, kw):
        o, p = args[0], args[1]
        if isinstance(o, dict) and _is_point(p):
            x, y = point_xy(it, p)
            o[fields[0]], o[fields[1]] = x, y
        return NAN
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


def f_timestamp(it, node, args, kw):
    """timestamp("2024-01-01 00:00") hoặc timestamp(năm, tháng, ngày, giờ, phút, giây); trả về mili giây UTC (múi giờ sàn bỏ qua)."""
    import datetime as dt
    if args and isinstance(args[0], str):
        s = args[0].strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return float(dt.datetime.strptime(s[:19], fmt).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
            except ValueError:
                continue
        return NAN
    vals = [int(I._num(x)) for x in args[:6]] + [0] * (6 - len(args[:6]))
    y, m, d = vals[0], max(1, vals[1] or 1), max(1, vals[2] or 1)
    try:
        return float(dt.datetime(y, m, d, vals[3], vals[4], vals[5], tzinfo=dt.timezone.utc).timestamp() * 1000)
    except ValueError:
        return NAN


def tf_in_seconds(it, node, args, kw):
    tf = args[0] if args else it.tf
    return float(I.tf_to_ms(tf) // 1000)


def tf_change(it, node, args, kw):
    """timeframe.change(tf): đúng ở nến đầu của mỗi kỳ hạn tf (theo lịch cho D/W/M, theo bội chia đều cho còn lại)."""
    tf = args[0] if args else it.tf
    t = float(it.bars.time[it.i] + it.tz)
    prev = float(it.bars.time[it.i - 1] + it.tz) if it.i > 0 else None
    if prev is None:
        return True
    tfs = str(tf).upper()
    if tfs in ("D", "1D"):
        return t // 86_400_000 != prev // 86_400_000
    if tfs in ("W", "1W"):
        return ((t // 86_400_000 + 3) // 7) != ((prev // 86_400_000 + 3) // 7)
    if tfs in ("M", "1M"):
        import datetime as dt
        a, b = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc), dt.datetime.fromtimestamp(prev / 1000, dt.timezone.utc)
        return (a.year, a.month) != (b.year, b.month)
    step = I.tf_to_ms(tf)
    return t // step != prev // step


def cp_new(it, node, args, kw):
    return {"_k": "point", "time": A(args, kw, 0, "time", NAN), "index": A(args, kw, 1, "index", NAN), "price": A(args, kw, 2, "price", NAN)}


def cp_from_index(it, node, args, kw):
    return {"_k": "point", "time": NAN, "index": A(args, kw, 0, "index", NAN), "price": A(args, kw, 1, "price", NAN)}


def cp_from_time(it, node, args, kw):
    return {"_k": "point", "time": A(args, kw, 0, "time", NAN), "index": NAN, "price": A(args, kw, 1, "price", NAN)}


def cp_now(it, node, args, kw):
    return {"_k": "point", "time": float(it.bars.time[it.i]), "index": float(it.i), "price": A(args, kw, 0, "price", NAN)}


def poly_new(it, node, args, kw):
    pts = [p for p in _arr(A(args, kw, 0, "points", [])) if isinstance(p, dict)]
    o = {"_k": "polyline", "dead": False, "points": [{"index": p.get("index"), "time": p.get("time"), "price": p.get("price")} for p in pts],
         "curved": bool(kw.get("curved", False)), "closed": bool(kw.get("closed", False)), "line_color": kw.get("line_color"),
         "fill_color": kw.get("fill_color"), "line_style": kw.get("line_style", "solid"), "line_width": kw.get("line_width", 1)}
    it.objs.setdefault("polylines", []).append(o)
    return o


def f_plotcandle(it, node, args, kw):
    """plotcandle/plotbar: vẽ nến riêng (thường để tô lại màu nến của biểu đồ)."""
    rec = it.candles.get(node.id)
    if rec is None:
        rec = it.candles[node.id] = {"title": kw.get("title", ""), "ohlc": [None] * it.n, "color": [None] * it.n,
                                     "wick": [None] * it.n, "border": [None] * it.n, "bar": node.id}
    vals = [I._num(A(args, kw, k, nm)) for k, nm in enumerate(("open", "high", "low", "close"))]
    if not any(isna(v) for v in vals):
        rec["ohlc"][it.i] = vals
        rec["color"][it.i] = I._col(kw.get("color"))
        rec["wick"][it.i] = I._col(kw.get("wickcolor", kw.get("color")))
        rec["border"][it.i] = I._col(kw.get("bordercolor", kw.get("color")))
    return NAN


def f_plotchar(it, node, args, kw):
    """plotchar(series, char=..., location=...): ghi thành marker có chữ."""
    v = A(args, kw, 0, "series")
    p = it.shapes.get(node.id)
    if p is None:
        p = it.shapes[node.id] = {"title": A(args, kw, 1, "title", None) or f"Char {len(it.shapes)}", "shape": "circle",
                                  "location": A(args, kw, 3, "location", "abovebar"), "size": kw.get("size", "small"),
                                  "text": str(A(args, kw, 2, "char", kw.get("text", ""))), "values": [False] * it.n, "colors": [None] * it.n}
    p["values"][it.i] = I._truthy(v) and not isna(v)
    p["colors"][it.i] = I._col(kw.get("color"))
    return NAN


def f_plotarrow(it, node, args, kw):
    v = I._num(A(args, kw, 0, "series"))
    up = I._truthy(v) and v > 0
    dn = I._truthy(v) and v < 0
    for suffix, on, shape, loc, key in (("up", up, "arrowup", "belowbar", "colorup"), ("down", dn, "arrowdown", "abovebar", "colordown")):
        k = (node.id, suffix)
        p = it.shapes.get(k)
        if p is None:
            p = it.shapes[k] = {"title": f"Arrow {suffix}", "shape": shape, "location": loc, "size": "small", "text": "",
                                "values": [False] * it.n, "colors": [None] * it.n}
        p["values"][it.i] = on
        p["colors"][it.i] = I._col(kw.get(key))
    return NAN


def a_indexof(it, node, args, kw):
    a = _arr(args[0])
    try:
        return float(a.index(args[1]))
    except ValueError:
        return -1.0


def a_lastindexof(it, node, args, kw):
    a = _arr(args[0])
    for i in range(len(a) - 1, -1, -1):
        if a[i] == args[1]:
            return float(i)
    return -1.0


def a_slice(it, node, args, kw):
    a = _arr(args[0])
    return a[int(args[1]):int(args[2])]          # Pine: chỉ số cuối không gồm


def a_sort(it, node, args, kw):
    a = _arr(args[0])
    desc = str(A(args, kw, 1, "order", "ascending")) == "descending"
    a.sort(key=lambda x: (isna(x), x), reverse=desc)
    return NAN


def a_median(it, node, args, kw):
    v = sorted(_nums(_arr(args[0])))
    if not v:
        return NAN
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def a_stdev(it, node, args, kw):
    v = _nums(_arr(args[0]))
    if not v:
        return NAN
    mu = sum(v) / len(v)
    return math.sqrt(sum((x - mu) ** 2 for x in v) / len(v))


def a_fill(it, node, args, kw):
    a = _arr(args[0])
    lo = int(A(args, kw, 2, "index_from", 0))
    hi = int(A(args, kw, 3, "index_to", len(a)))
    for i in range(lo, hi):
        a[i] = args[1]
    return NAN


# ---------------- chỉ báo bổ sung ----------------

class Supertrend:
    """ta.supertrend(factor, atrPeriod) -> [giá trị, hướng]; hướng -1 là xu hướng tăng, 1 là xu hướng giảm (như Pine)."""

    def __init__(self, factor: float, n: int):
        from .ta import make_rma, true_range
        self.f, self.r, self.tr = factor, make_rma(n), true_range
        self.pc = self.pl = self.pu = self.pst = None

    def update(self, h: float, l: float, c: float):
        trv = self.tr(h, l, self.pc)
        atr = self.r.update(trv)
        src = (h + l) / 2
        if isna(atr):
            self.pc = c
            return [NAN, NAN]
        lower, upper = src - self.f * atr, src + self.f * atr
        if self.pl is not None:
            lower = lower if (lower > self.pl or self.pc < self.pl) else self.pl
            upper = upper if (upper < self.pu or self.pc > self.pu) else self.pu
        if self.pst is None:
            direction = 1
        elif self.pst == self.pu:
            direction = -1 if c > upper else 1
        else:
            direction = 1 if c < lower else -1
        st = lower if direction == -1 else upper
        self.pl, self.pu, self.pst, self.pc = lower, upper, st, c
        return [st, float(direction)]


class Sar:
    def __init__(self, start: float, inc: float, mx: float):
        self.start, self.inc, self.mx = start, inc, mx
        self.prev = None
        self.sar = self.ep = self.af = None
        self.up = True

    def update(self, h: float, l: float):
        if self.prev is None:
            self.prev = (h, l)
            return NAN
        ph, pl = self.prev
        if self.sar is None:
            self.up = h >= ph
            self.sar = pl if self.up else ph
            self.ep = h if self.up else l
            self.af = self.start
        else:
            self.sar = self.sar + self.af * (self.ep - self.sar)
            if self.up:
                self.sar = min(self.sar, pl, self.prev[1])
                if l < self.sar:
                    self.up, self.sar, self.ep, self.af = False, self.ep, l, self.start
                elif h > self.ep:
                    self.ep, self.af = h, min(self.af + self.inc, self.mx)
            else:
                self.sar = max(self.sar, ph, self.prev[0])
                if h > self.sar:
                    self.up, self.sar, self.ep, self.af = True, self.ep, h, self.start
                elif l < self.ep:
                    self.ep, self.af = l, min(self.af + self.inc, self.mx)
        self.prev = (h, l)
        return self.sar


def ta_supertrend(it, node, args, kw):
    f, n = I._num(A(args, kw, 0, "factor")), int(A(args, kw, 1, "atrPeriod"))
    b, i = it.bars, it.i
    return it.state(node, lambda: Supertrend(f, n)).update(b.high[i], b.low[i], b.close[i])


def ta_sar(it, node, args, kw):
    s, inc, mx = (I._num(A(args, kw, k, nm)) for k, nm in enumerate(("start", "inc", "max")))
    return it.state(node, lambda: Sar(s, inc, mx)).update(it.bars.high[it.i], it.bars.low[it.i])


def _extreme_bars(hi: bool):
    def f(it, node, args, kw):
        if len(args) == 1 and "length" not in kw and "source" not in kw:      # ta.highestbars(length): nguồn mặc định là high/low
            args = [it.builtin_series("high" if hi else "low"), args[0]]
        elif "length" in kw and "source" not in kw and not args:
            args = [it.builtin_series("high" if hi else "low")]
        src = A(args, kw, 0, "source")
        n = int(A(args, kw, 1, "length"))
        from collections import deque
        st = it.state(node, lambda: deque(maxlen=n))
        st.append(NAN if isna(src) else float(src))
        if len(st) < n or any(isna(v) for v in st):
            return NAN
        vals = list(st)
        best = max(vals) if hi else min(vals)
        k = max(i for i, v in enumerate(vals) if v == best)       # lần gần nhất
        return float(k - (n - 1))
    return f


def tv_aroon(it, node, args, kw):
    n = int(A(args, kw, 0, "length"))
    b, i = it.bars, it.i
    if i < n:
        return [NAN, NAN]
    hs, ls = b.high[i - n:i + 1], b.low[i - n:i + 1]
    hi_off = max(k for k, v in enumerate(hs) if v == max(hs)) - n      # <= 0
    lo_off = max(k for k, v in enumerate(ls) if v == min(ls)) - n
    return [100.0 * (n + hi_off) / n, 100.0 * (n + lo_off) / n]


def ta_cross(it, node, args, kw):
    a, b = I._num(args[0]), I._num(args[1])
    st = it.state(node, lambda: [None])
    prev = st[0]
    st[0] = (a, b)
    if prev is None or any(isna(v) for v in (a, b, *prev)):
        return False
    return (a > b) != (prev[0] > prev[1]) and a != b


def runtime_error(it, node, args, kw):
    raise I.PineRuntimeError(str(args[0]) if args else "runtime.error", node.line)


def pc_ltf(it, node, args, kw):
    """PineCoders lower_tf.ltf: chọn khung thấp hơn khung biểu đồ để lấy dữ liệu trong nến. Chế độ tự động: khoảng 1/15 khung biểu đồ, tối thiểu 1 phút."""
    ms = it.tf_ms
    if ms <= 60_000:
        raise I.PineRuntimeError("Không có dữ liệu trong nến ở khung nhỏ hơn 1 phút (nguồn chỉ có nến 1 phút trở lên)", node.line)
    target = ms / 15
    for m in (1, 3, 5, 15, 30, 60, 240):
        if m * 60_000 >= target:
            return str(m)
    return "240"


def pc_formatted(it, node, args, kw):
    ms = I._num(args[0])
    for lim, name in ((86_400_000, "day"), (3_600_000, "hour"), (60_000, "minute"), (1000, "second")):
        if ms >= lim:
            n = ms / lim
            n = int(n) if float(n).is_integer() else round(n, 1)
            return f"{n} {name}{'' if n == 1 else 's'}"
    return f"{int(ms)} ms"


def sec_lower(it, node_call, sym, tf, expr_node):
    """request.security_lower_tf: giá trị của biểu thức ở từng nến khung thấp nằm trong nến hiện tại (mảng, hoặc tuple các mảng)."""
    import bisect
    key = (node_call.id, it.stack)
    c = it.sec_cache.get(key)
    if c is None:
        if it.provider is None:
            raise I.PineRuntimeError("request.security_lower_tf cần nguồn dữ liệu (provider)", node_call.line)
        other = it.provider(sym or it.symbol, tf)
        if other is None or len(other) == 0:
            raise I.PineRuntimeError(f"không có dữ liệu khung {tf} cho {sym}", node_call.line)
        sub = I.Interp(it.ast, other, symbol=sym or it.symbol, tf=tf, tz_offset_ms=it.tz, provider=it.provider, inputs=it.input_overrides,
                       external=it.external, syminfo_type=it.syminfo_type, ast=it.ast, tick=it.tick, chart_bg=it.chart_bg)
        sub.funcs, sub.types, sub.aliases = it.funcs, it.types, it.aliases
        sub.vars = {k: v for k, v in it.vars.items() if not isinstance(v, list)}
        sub.persist = set(sub.vars)
        c = it.sec_cache[key] = (sub.run_expr(expr_node), list(other.time))
    vals, times = c
    t0 = it.bars.time[it.i]
    lo, hi = bisect.bisect_left(times, t0), bisect.bisect_left(times, t0 + it.tf_ms)
    seg = vals[lo:hi]
    if seg and isinstance(seg[0], list):
        return [[row[k] for row in seg] for k in range(len(seg[0]))]
    if not seg:
        tup = next((v for v in vals if isinstance(v, list)), None)
        if tup is not None:                 # biểu thức trả về tuple nhưng nến này chưa có dữ liệu khung thấp: mỗi phần tử là mảng rỗng
            return [[] for _ in tup]
    return list(seg)


def lazy_security_lower(it, n):
    pos = [e for nm, e in n.args if nm is None]
    kw = {nm: e for nm, e in n.args if nm is not None}
    sym = it.eval(pos[0] if pos else kw["symbol"])
    tf = it.eval(pos[1] if len(pos) > 1 else kw["timeframe"])
    expr = pos[2] if len(pos) > 2 else kw["expression"]
    return sec_lower(it, n, str(sym), str(tf), expr)


def register() -> None:
    B = I.BUILTINS
    for kind, d in (("float", NAN), ("int", NAN), ("string", ""), ("bool", False), ("color", None), ("line", NAN), ("label", NAN),
                    ("box", NAN), ("table", NAN), ("linefill", NAN)):
        B[f"array.new_{kind}"] = _new(d)
    B["array.new"] = _new(NAN)
    B.update({
        "array.get": a_get, "array.set": a_set, "array.push": a_push, "array.pop": a_pop, "array.remove": a_remove,
        "array.insert": a_insert, "array.clear": a_clear, "array.indexof": a_indexof, "array.lastindexof": a_lastindexof, "array.copy": lambda it, n, a, k: list(_arr(a[0])),
        "array.slice": a_slice, "array.sort": a_sort, "array.reverse": lambda it, n, a, k: (_arr(a[0]).reverse(), NAN)[1],
        "array.concat": lambda it, n, a, k: (_arr(a[0]).extend(_arr(a[1])), a[0])[1], "array.median": a_median, "array.stdev": a_stdev,
        "array.fill": a_fill, "array.abs": lambda it, n, a, k: [abs(x) if not isna(x) else x for x in _arr(a[0])], "array.range": _stat(lambda v: max(v) - min(v)), "color": lambda it, n, a, k: a[0], "array.shift": lambda it, n, a, k: _arr(a[0]).pop(0) if _arr(a[0]) else NAN, "array.unshift": lambda it, n, a, k: (_arr(a[0]).insert(0, a[1]), NAN)[1], "array.size": lambda it, n, a, k: float(len(_arr(a[0]))),
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
                                 ("bgcolor", None), ("text", ""), ("text_size", "normal"), ("text_color", None),
                                 ("text_halign", "center"), ("text_valign", "center"))),
        "table.new": t_new, "table.cell": t_cell, "table.merge_cells": t_merge, "table.delete": _delete,
        "line.delete": _delete, "label.delete": _delete, "box.delete": _delete,
        "request.earnings": lambda it, n, a, k: NAN, "request.dividends": lambda it, n, a, k: NAN, "request.splits": lambda it, n, a, k: NAN,
        "request.economic": lambda it, n, a, k: NAN, "request.quandl": lambda it, n, a, k: NAN,
        "timeframe.in_seconds": tf_in_seconds, "timeframe.change": tf_change, "chart.point.new": cp_new, "chart.point.from_index": cp_from_index, "chart.point.from_time": cp_from_time, "chart.point.now": cp_now,
        "polyline.new": poly_new, "polyline.delete": _delete, "array.from": lambda it, n, a, k: list(a),
        "plotcandle": f_plotcandle, "plotbar": f_plotcandle, "plotchar": f_plotchar, "plotarrow": f_plotarrow,
        "ta.supertrend": ta_supertrend, "ta.sar": ta_sar, "ta.highestbars": _extreme_bars(True), "ta.lowestbars": _extreme_bars(False),
        "ta.cross": ta_cross, "runtime.error": runtime_error,
        "PineCoders/lower_tf.ltf": pc_ltf, "PineCoders/Time.formattedNoOfPeriods": pc_formatted, "TradingView/ta.aroon": tv_aroon,
        "PineCoders/VisibleChart.leftBarIndex": lambda it, n, a, k: 0.0,
        "PineCoders/VisibleChart.rightBarIndex": lambda it, n, a, k: float(it.n - 1),
        "PineCoders/VisibleChart.barIsVisible": lambda it, n, a, k: True,
        "PineCoders/VisibleChart.isLastVisibleBar": lambda it, n, a, k: it.i == it.n - 1,
        "PineCoders/VisibleChart.bars": lambda it, n, a, k: float(it.n),
        "timestamp": f_timestamp, "alert": f_alert, "fill": f_fill, "barcolor": f_barcolor, "ta.cum": ta_cum, "ta.dmi": ta_dmi,
        "int": _cast(lambda x: float(int(x))), "float": _cast(float), "str": lambda it, n, a, k: fmt_value(a[0], None, it.tick),
        "bool": lambda it, n, a, k: I._truthy(a[0]),
    })
    for k, fields in (("line", ("x1", "y1", "x2", "y2", "color", "width", "style", "extend")),
                      ("label", ("x", "y", "text", "color", "textcolor", "style", "size", "tooltip")),
                      ("box", ("left", "top", "right", "bottom", "border_color", "border_width", "border_style", "bgcolor", "text",
                                  "text_size", "text_color", "text_halign", "text_valign"))):
        for f in fields:
            B[f"{k}.set_{f}"] = _setter(f)
    B["line.set_first_point"] = _point_setter("x1", "y1")
    B["line.set_second_point"] = _point_setter("x2", "y2")
    B["label.set_point"] = _point_setter("x", "y")
    B["box.set_top_left_point"] = _point_setter("left", "top")
    B["box.set_bottom_right_point"] = _point_setter("right", "bottom")
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
I.LAZY["request.security_lower_tf"] = lazy_security_lower
