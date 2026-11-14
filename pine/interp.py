"""Bộ thông dịch Pine Script (tập con). Chạy toàn bộ chương trình trên từng nến theo thứ tự thời gian.

Ngữ nghĩa chính:
  - Giá trị thiếu là NaN (Pine `na`). Phép toán với NaN cho NaN; so sánh với NaN cho False.
  - Biến thường được tính lại mỗi nến; biến `var` chỉ khởi tạo một lần và giữ giá trị giữa các nến.
  - `x[n]` đọc giá trị của biến (hoặc của biểu thức bất kỳ) cách đây n nến.
  - Hàm `ta.*` giữ trạng thái theo vị trí gọi (nút AST + ngăn xếp lời gọi hàm người dùng) và phải chạy trên mọi nến,
    đúng như Pine yêu cầu. Gọi chúng trong nhánh `if` sẽ cho kết quả sai, giống Pine.
  - `request.security` tính biểu thức trên chuỗi nến khác rồi ánh xạ về nến hiện tại KHÔNG nhìn trước: chỉ dùng nến
    của khung/ symbol kia đã đóng tại thời điểm đóng của nến hiện tại (lookahead_off).
  - `request.external` là phần mở rộng riêng: "delta", "cvd", "gex_levels".
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Callable

from . import ta as T
from .lexer import PineSyntaxError
from .parser import (Assign, Attr, Binary, Bool, Call, Color, ExprStmt, For, ForIn, FuncDef, If, Index, Jump, Name, Num, Str,
                     Switch, Ternary, TupleLit, Unary, While, parse)

NAN = float("nan")
isna = T.isna


class PineRuntimeError(Exception):
    def __init__(self, msg: str, line: int = 0):
        super().__init__(f"dòng {line}: {msg}" if line else msg)
        self.line = line


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


@dataclass
class Bars:
    time: list            # ms, thời điểm mở nến
    open: list
    high: list
    low: list
    close: list
    volume: list
    buy: list = field(default_factory=list)    # khối lượng mua chủ động (có thể rỗng)
    sell: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.time)


TF_MS = {"s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 7 * 86_400_000}


def tf_to_ms(tf: str) -> int:
    """Chấp nhận kiểu Pine ("1", "60", "D", "W") và kiểu của dự án ("1m", "4h", "1d")."""
    t = str(tf).strip()
    if not t:
        raise PineRuntimeError("timeframe rỗng")
    if t.isdigit():
        return int(t) * 60_000
    unit = t[-1].lower()
    num = t[:-1] or "1"
    if t[-1] == "M" and num.isdigit():          # chữ M hoa là tháng, m thường là phút
        return int(num) * 30 * 86_400_000
    if unit in TF_MS and num.isdigit():
        return int(num) * TF_MS[unit]
    raise PineRuntimeError(f"timeframe không hợp lệ: {tf!r}")


COLORS = {
    "red": "#F23645", "green": "#4CAF50", "teal": "#089981", "blue": "#2962FF", "orange": "#FF9800", "lime": "#00E676",
    "gray": "#787B86", "white": "#FFFFFF", "black": "#363A45", "yellow": "#FDD835", "purple": "#9C27B0",
    "aqua": "#00BCD4", "fuchsia": "#E040FB", "maroon": "#880E4F", "navy": "#311B92", "olive": "#808000", "silver": "#B2B5BE",
}


def color_new(c: str | None, transp: float) -> str | None:
    if c is None:
        return None
    base = c[:7]
    a = 0 if isna(transp) else max(0, min(255, round(255 * (100 - transp) / 100)))
    return f"{base}{a:02X}"


CONSTS: dict[str, object] = {
    **{f"color.{k}": v for k, v in COLORS.items()},
    "plot.style_line": "line", "plot.style_columns": "columns", "plot.style_histogram": "histogram",
    "plot.style_circles": "circles", "plot.style_stepline": "stepline", "plot.style_area": "area",
    "plot.style_linebr": "line", "plot.style_cross": "cross",
    "shape.triangleup": "triangleup", "shape.triangledown": "triangledown", "shape.circle": "circle",
    "shape.diamond": "diamond", "shape.square": "square", "shape.xcross": "xcross", "shape.cross": "cross",
    "shape.arrowup": "arrowup", "shape.arrowdown": "arrowdown", "shape.flag": "flag", "shape.labelup": "labelup",
    "shape.labeldown": "labeldown",
    "location.abovebar": "abovebar", "location.belowbar": "belowbar", "location.top": "top",
    "location.bottom": "bottom", "location.absolute": "absolute",
    "size.tiny": "tiny", "size.small": "small", "size.normal": "normal", "size.large": "large", "size.huge": "huge",
    "format.volume": "volume", "format.price": "price", "format.percent": "percent", "format.inherit": "inherit",
    "barmerge.lookahead_off": False, "barmerge.lookahead_on": True,
    "barmerge.gaps_off": False, "barmerge.gaps_on": True,
    "hline.style_solid": "solid", "hline.style_dashed": "dashed", "hline.style_dotted": "dotted",
    "strategy.long": "long", "strategy.short": "short",
    "strategy.percent_of_equity": "percent_of_equity", "strategy.fixed": "fixed", "strategy.cash": "cash",
    "strategy.commission.percent": "percent", "strategy.commission.cash_per_order": "cash_per_order",
    "math.pi": math.pi, "math.e": math.e,
    "extend.none": "none", "extend.right": "right", "extend.left": "left", "extend.both": "both",
}


def _num(x) -> float:
    if x is None:
        return NAN
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    if isinstance(x, (int, float)):
        return float(x)
    raise PineRuntimeError(f"cần số, gặp {x!r}")


def _truthy(x) -> bool:
    if x is None:
        return False
    if isinstance(x, float):
        return not math.isnan(x) and x != 0.0
    return bool(x)


@dataclass
class Func:
    node: FuncDef


class Interp:
    def __init__(self, src: str | list, bars: Bars, *, symbol: str = "", tf: str = "1m", tz_offset_ms: int = 0,
                 provider: Callable[[str, str], Bars | None] | None = None, inputs: dict | None = None,
                 external: dict | None = None, syminfo_type: str = "crypto", ast: list | None = None,
                 strategy_opts: dict | None = None, tick: float = 0.01, chart_bg: str = "#131722"):
        self.ast = ast if ast is not None else (parse(src) if isinstance(src, str) else src)
        self.bars, self.n = bars, len(bars)
        self.symbol, self.tf, self.tz = symbol, tf, tz_offset_ms
        self.tf_ms = tf_to_ms(tf) if tf else 60_000
        self.provider, self.input_overrides, self.external = provider, inputs or {}, external or {}
        self.syminfo_type = syminfo_type
        self.i = -1
        self.vars: dict[str, object] = {}
        self.persist: set[str] = set()
        self.hist: dict[str, list] = {}
        self.funcs: dict[str, Func] = {}
        self.locals: list[dict] = []
        self.stack: tuple = ()
        self.states: dict = {}
        self.node_hist: dict = {}
        self.sec_cache: dict = {}
        # đầu ra
        self.meta: dict = {"kind": "indicator", "title": "", "overlay": False}
        self.plots: dict[int, dict] = {}
        self.shapes: dict[int, dict] = {}
        self.bgcolors: dict[int, dict] = {}
        self.hlines: dict[int, dict] = {}
        self.alerts: dict[int, dict] = {}
        self.input_defs: dict[int, dict] = {}
        self.strategy = Strategy(self)
        self.strategy.overrides = strategy_opts or {}
        self.strategy.apply_overrides()
        self.input_count = 0
        self.objs = {"lines": [], "labels": [], "boxes": [], "tables": []}
        self.alert_events: list = []
        self.fills: dict = {}
        self.barcolors: dict = {}
        self.tick = tick
        self.chart_bg = chart_bg

    # ---------- vòng lặp nến ----------
    def run(self) -> None:
        for stmt in self.ast:
            if isinstance(stmt, FuncDef):
                self.funcs[stmt.name] = Func(stmt)
        body = [s for s in self.ast if not isinstance(s, FuncDef)]
        for i in range(self.n):
            self.i = i
            self.strategy.begin_bar(i)
            self.exec_block(body)
            self.commit(i)
            self.strategy.end_bar(i)
        self.strategy.finish()

    def run_expr(self, node) -> list:
        """Tính một biểu thức trên từng nến (dùng cho request.security) và trả về danh sách giá trị."""
        out = []
        for i in range(self.n):
            self.i = i
            out.append(self.eval(node))
            self.commit(i)
        return out

    def commit(self, i: int) -> None:
        for name, v in list(self.vars.items()):
            self.hist.setdefault(name, [NAN] * i).append(v)
        for name, h in self.hist.items():
            if len(h) < i + 1:
                h.append(NAN)
        for name in [k for k in self.vars if k not in self.persist]:
            del self.vars[name]

    def state(self, node, factory):
        k = (node.id, self.stack)
        s = self.states.get(k)
        if s is None:
            s = self.states[k] = factory()
        return s

    # ---------- câu lệnh ----------
    def exec_block(self, stmts: list):
        result = NAN
        for s in stmts:
            result = self.exec(s)
        return result

    def scope(self) -> dict:
        return self.locals[-1] if self.locals else self.vars

    def exec(self, s):
        if isinstance(s, ExprStmt):
            return self.eval(s.expr)
        if isinstance(s, Assign):
            return self.assign(s)
        if isinstance(s, If):
            if _truthy(self.eval(s.cond)):
                return self.exec_block(s.body)
            return self.exec_block(s.orelse)
        if isinstance(s, For):
            a, b = _num(self.eval(s.start)), _num(self.eval(s.stop))
            step = _num(self.eval(s.step)) if s.step is not None else (1.0 if b >= a else -1.0)
            if step == 0 or math.isnan(a) or math.isnan(b):
                raise PineRuntimeError("for: cận hoặc bước không hợp lệ", s.line)
            x, out = a, NAN
            sc = self.scope()
            while (step > 0 and x <= b) or (step < 0 and x >= b):
                sc[s.var] = x
                try:
                    out = self.exec_block(s.body)
                except _Break:
                    break
                except _Continue:
                    pass
                x += step
            return out
        if isinstance(s, ForIn):
            seq = self.eval(s.iterable)
            if not isinstance(seq, list):
                raise PineRuntimeError("for ... in cần một mảng", s.line)
            sc = self.scope()
            out = NAN
            for item in list(seq):
                sc[s.var] = item
                try:
                    out = self.exec_block(s.body)
                except _Break:
                    break
                except _Continue:
                    pass
            return out
        if isinstance(s, While):
            guard = 0
            out = NAN
            while _truthy(self.eval(s.cond)):
                guard += 1
                if guard > 100_000:
                    raise PineRuntimeError("while chạy quá 100000 vòng", s.line)
                try:
                    out = self.exec_block(s.body)
                except _Break:
                    break
                except _Continue:
                    pass
            return out
        if isinstance(s, Jump):
            raise _Break() if s.kind == "break" else _Continue()
        if isinstance(s, FuncDef):
            self.funcs[s.name] = Func(s)
            return NAN
        raise PineRuntimeError(f"câu lệnh không hỗ trợ: {type(s).__name__}", getattr(s, "line", 0))

    def assign(self, s: Assign):
        sc = self.scope()
        if isinstance(s.target, list):
            vals = self.eval(s.value)
            if not isinstance(vals, (list, tuple)) or len(vals) != len(s.target):
                raise PineRuntimeError(f"cần tuple {len(s.target)} phần tử", s.line)
            for nm, v in zip(s.target, vals):
                sc[nm] = v
            return vals
        name = s.target
        if s.var:
            if name in self.persist and not self.locals:
                return sc.get(name, NAN)
            v = self.eval(s.value)
            sc[name] = v
            if not self.locals:
                self.persist.add(name)
            return v
        if s.op == "=":
            v = self.eval(s.value)
        elif s.op == ":=":
            if name not in sc and name not in self.vars:
                raise PineRuntimeError(f"{name} chưa được khai báo trước khi gán :=", s.line)
            v = self.eval(s.value)
        else:
            cur = sc.get(name, self.vars.get(name))
            if cur is None and name not in sc and name not in self.vars:
                raise PineRuntimeError(f"{name} chưa được khai báo", s.line)
            v = self.binop(s.op[0], cur, self.eval(s.value))
        if s.op == ":=" and name not in sc and name in self.vars:
            self.vars[name] = v
        else:
            sc[name] = v
        return v

    # ---------- biểu thức ----------
    def eval(self, n):
        t = type(n)
        if t is Num:
            return n.value
        if t is Name:
            return self.lookup(n.name, n.line)
        if t is Binary:
            if n.op == "and":
                return _truthy(self.eval(n.left)) and _truthy(self.eval(n.right))
            if n.op == "or":
                return _truthy(self.eval(n.left)) or _truthy(self.eval(n.right))
            return self.binop(n.op, self.eval(n.left), self.eval(n.right), n.line)
        if t is Call:
            return self.call(n)
        if t is Index:
            return self.index(n)
        if t is Attr:
            return self.attr(n)
        if t is Switch:
            return self.switch(n)
        if t is Ternary:
            return self.eval(n.a) if _truthy(self.eval(n.cond)) else self.eval(n.b)
        if t is Unary:
            v = self.eval(n.operand)
            if n.op == "not":
                return not _truthy(v)
            if n.op == "-":
                return -_num(v)
            return _num(v)
        if t is Bool:
            return n.value
        if t is Str:
            return n.value
        if t is Color:
            v = n.value
            return v.upper()
        if t is TupleLit:
            return [self.eval(x) for x in n.items]
        raise PineRuntimeError(f"biểu thức không hỗ trợ: {t.__name__}", getattr(n, "line", 0))

    def switch(self, n: Switch):
        subj = self.eval(n.subject) if n.subject is not None else None
        for match, body in n.cases:
            if match is None:
                return self.exec_block(body)
            v = self.eval(match)
            hit = self.binop("==", subj, v, n.line) if n.subject is not None else _truthy(v)
            if hit:
                return self.exec_block(body)
        return NAN

    def binop(self, op: str, a, b, line: int = 0):
        if op == "+" and (isinstance(a, str) or isinstance(b, str)):
            return f"{a}{b}"
        if op in ("==", "!="):
            if isinstance(a, str) or isinstance(b, str):
                return (a == b) if op == "==" else (a != b)
            x, y = _num(a), _num(b)
            if math.isnan(x) or math.isnan(y):
                return False
            return (x == y) if op == "==" else (x != y)
        x, y = _num(a), _num(b)
        if op in ("<", "<=", ">", ">="):
            if math.isnan(x) or math.isnan(y):
                return False
            return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
        if math.isnan(x) or math.isnan(y):
            return NAN
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            return x / y if y != 0 else NAN
        if op == "%":
            return math.fmod(x, y) if y != 0 else NAN
        raise PineRuntimeError(f"toán tử không hỗ trợ {op}", line)

    # ---------- tên, thuộc tính, lịch sử ----------
    def builtin_series(self, name: str):
        b, i = self.bars, self.i
        if name == "open":
            return b.open[i]
        if name == "high":
            return b.high[i]
        if name == "low":
            return b.low[i]
        if name == "close":
            return b.close[i]
        if name == "volume":
            return b.volume[i]
        if name == "time":
            return float(b.time[i])
        if name == "bar_index":
            return float(i)
        if name == "hl2":
            return (b.high[i] + b.low[i]) / 2
        if name == "hlc3":
            return (b.high[i] + b.low[i] + b.close[i]) / 3
        if name == "ohlc4":
            return (b.open[i] + b.high[i] + b.low[i] + b.close[i]) / 4
        if name == "hlcc4":
            return (b.high[i] + b.low[i] + 2 * b.close[i]) / 4
        raise KeyError(name)

    SERIES = {"open", "high", "low", "close", "volume", "time", "bar_index", "hl2", "hlc3", "ohlc4", "hlcc4"}

    def lookup(self, name: str, line: int = 0):
        if self.locals and name in self.locals[-1]:
            return self.locals[-1][name]
        if name in self.vars:
            return self.vars[name]
        if name in self.SERIES:
            return self.builtin_series(name)
        if name == "na":
            return NAN
        if name in CONSTS:
            return CONSTS[name]
        raise PineRuntimeError(f"biến chưa được định nghĩa: {name}", line)

    def dotted(self, n) -> str | None:
        parts = []
        while isinstance(n, Attr):
            parts.append(n.name)
            n = n.obj
        if isinstance(n, Name):
            parts.append(n.name)
            return ".".join(reversed(parts))
        return None

    def attr(self, n: Attr):
        d = self.dotted(n)
        if d is None:
            raise PineRuntimeError("truy cập thuộc tính không hỗ trợ", n.line)
        if d in CONSTS:
            return CONSTS[d]
        if d == "ta.tr":
            b, i = self.bars, self.i
            return T.true_range(b.high[i], b.low[i], b.close[i - 1] if i > 0 else None)
        if d == "timeframe.period":
            return self.tf
        if d == "timeframe.multiplier":
            return float(self.tf_ms // 60_000)
        if d == "chart.bg_color":
            return self.chart_bg
        if d == "syminfo.mintick":
            return self.tick
        if d == "syminfo.type":
            return self.syminfo_type
        if d in ("syminfo.ticker", "syminfo.tickerid"):
            return self.symbol
        if d == "syminfo.timezone":
            return f"UTC{self.tz // 3_600_000:+d}"
        if d == "strategy.position_size":
            return self.strategy.position_size
        if d == "strategy.equity":
            return self.strategy.equity_now()
        if d == "barstate.islast":
            return self.i == self.n - 1
        if d == "barstate.isfirst":
            return self.i == 0
        if d.startswith("color.") or d.startswith("plot.") or d.startswith("shape."):
            raise PineRuntimeError(f"hằng không có: {d}", n.line)
        raise PineRuntimeError(f"không hỗ trợ: {d}", n.line)

    def index(self, n: Index):
        k = int(_num(self.eval(n.idx)))
        if k < 0:
            raise PineRuntimeError("chỉ số lịch sử không được âm", n.line)
        base = n.obj
        i = self.i
        if isinstance(base, Name):
            name = base.name
            local = bool(self.locals) and name in self.locals[-1]
            if not local and name not in self.vars and name in self.SERIES:
                if k == 0:
                    return self.builtin_series(name)
                if i - k < 0:
                    return NAN
                save, self.i = self.i, i - k
                try:
                    return self.builtin_series(name)
                finally:
                    self.i = save
            if not local and (name in self.vars or name in self.hist):
                if k == 0:
                    return self.vars.get(name, NAN)
                h = self.hist.get(name, [])
                return h[i - k] if 0 <= i - k < len(h) else NAN
        # biểu thức bất kỳ: giữ lịch sử riêng theo nút
        cur = self.eval(base)
        key = (n.id, self.stack)
        h = self.node_hist.setdefault(key, {})
        h[i] = cur
        return h.get(i - k, NAN) if k else cur

    # ---------- gọi hàm ----------
    def call(self, n: Call):
        d = self.dotted(n.func)
        if d is not None and d in self.funcs and not (self.locals and d in self.locals[-1]):
            return self.call_user(self.funcs[d], n)
        if d is None:
            raise PineRuntimeError("gọi hàm không hỗ trợ", n.line)
        fn = LAZY.get(d)
        if fn is not None:
            return fn(self, n)
        fn = BUILTINS.get(d)
        if fn is None:
            raise PineRuntimeError(f"hàm không được hỗ trợ: {d}", n.line)
        args = [self.eval(e) for nm, e in n.args if nm is None]
        kw = {nm: self.eval(e) for nm, e in n.args if nm is not None}
        try:
            return fn(self, n, args, kw)
        except PineRuntimeError:
            raise
        except (TypeError, ValueError, IndexError) as e:
            raise PineRuntimeError(f"{d}: tham số không hợp lệ ({e})", n.line) from e

    def call_user(self, f: Func, n: Call):
        node = f.node
        scope: dict = {}
        pos = [self.eval(e) for nm, e in n.args if nm is None]
        kw = {nm: self.eval(e) for nm, e in n.args if nm is not None}
        for idx, (pn, default) in enumerate(node.params):
            if idx < len(pos):
                scope[pn] = pos[idx]
            elif pn in kw:
                scope[pn] = kw[pn]
            elif default is not None:
                scope[pn] = self.eval(default)
            else:
                raise PineRuntimeError(f"{node.name}: thiếu tham số {pn}", n.line)
        if len(self.locals) > 50:
            raise PineRuntimeError("đệ quy quá sâu", n.line)
        self.locals.append(scope)
        saved = self.stack
        self.stack = saved + (n.id,)
        try:
            return self.exec_block(node.body)
        finally:
            self.stack = saved
            self.locals.pop()


# ======================= thư viện hàm =======================

def A(args, kw, pos, name, default=None):
    if name in kw:
        return kw[name]
    return args[pos] if pos < len(args) else default


def _ta_window(factory, nm_n="length", src_pos=0, n_pos=1):
    def f(it, node, args, kw):
        src = A(args, kw, src_pos, "source")
        n = int(A(args, kw, n_pos, nm_n))
        if n < 1:
            raise PineRuntimeError("length phải >= 1", node.line)
        return it.state(node, lambda: factory(n)).update(src)
    return f


def ta_macd(it, node, args, kw):
    src, fast, slow, sig = A(args, kw, 0, "source"), int(A(args, kw, 1, "fast_length")), int(A(args, kw, 2, "slow_length")), int(A(args, kw, 3, "signal_length"))
    st = it.state(node, lambda: (T.make_ema(fast), T.make_ema(slow), T.make_ema(sig)))
    ef, es = st[0].update(src), st[1].update(src)
    m = ef - es if not (isna(ef) or isna(es)) else NAN
    s = st[2].update(m)
    return [m, s, m - s if not (isna(m) or isna(s)) else NAN]


def ta_bb(it, node, args, kw):
    src, n, mult = A(args, kw, 0, "series"), int(A(args, kw, 1, "length")), _num(A(args, kw, 2, "mult"))
    st = it.state(node, lambda: (T.Sma(n), T.Stdev(n)))
    basis, dev = st[0].update(src), st[1].update(src)
    if isna(basis) or isna(dev):
        return [NAN, NAN, NAN]
    return [basis, basis + mult * dev, basis - mult * dev]


def ta_atr(it, node, args, kw):
    n = int(A(args, kw, 0, "length"))
    b, i = it.bars, it.i
    return it.state(node, lambda: T.Atr(n)).update(b.high[i], b.low[i], b.close[i])


def _day_index(it, ms: float) -> int:
    return int((ms + it.tz) // 86_400_000)


def ta_vwap(it, node, args, kw):
    src = A(args, kw, 0, "source", it.builtin_series("hlc3"))
    anchor = A(args, kw, 1, "anchor", None)
    mult = A(args, kw, 2, "stdev_mult", None)
    st = it.state(node, lambda: {"v": T.Vwap(), "day": None})
    day = _day_index(it, it.bars.time[it.i])
    if anchor is None:
        anchor = st["day"] != day
    st["day"] = day
    res = st["v"].update(src, it.bars.volume[it.i], _truthy(anchor), _num(mult) if mult is not None else 1.0)
    return list(res) if (len(args) >= 3 or "stdev_mult" in kw) else res[0]


def in_session(spec: str, local_ms: float) -> bool:
    """spec dạng "0930-1600" hoặc "0000-2400" (có thể kèm ":23456" ngày trong tuần, bỏ qua phần ngày); giờ theo múi giờ sàn."""
    rng = str(spec).split(":")[0]
    try:
        a, b = rng.split("-")
        start, end = int(a[:2]) * 60 + int(a[2:]), int(b[:2]) * 60 + int(b[2:])
    except ValueError:
        return True
    m = int(local_ms // 60_000) % 1440
    if start == end or (start == 0 and end >= 1440):
        return True
    return start <= m < end if start < end else (m >= start or m < end)     # phiên qua nửa đêm


def f_time(it, node, args, kw):
    tf = A(args, kw, 0, "timeframe", it.tf)
    t = float(it.bars.time[it.i])
    sess = A(args, kw, 1, "session", None)
    if sess is not None and not in_session(sess, t + it.tz):
        return NAN
    tfs = str(tf).upper()
    local = t + it.tz
    if tfs in ("D", "1D"):
        return (local // 86_400_000) * 86_400_000 - it.tz
    if tfs in ("W", "1W"):
        day = local // 86_400_000
        monday = day - ((day + 3) % 7)       # 1970-01-01 là thứ Năm
        return monday * 86_400_000 - it.tz
    if tfs in ("M", "1M"):
        import datetime as dt
        d = dt.datetime.fromtimestamp(local / 1000, dt.timezone.utc)
        return dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc).timestamp() * 1000 - it.tz
    step = tf_to_ms(tf)
    return (local // step) * step - it.tz


def f_na(it, node, args, kw):
    return isna(args[0])


def f_nz(it, node, args, kw):
    x = args[0]
    return _num(A(args, kw, 1, "replacement", 0.0)) if isna(x) else x


def _m1(fn):
    def f(it, node, args, kw):
        x = _num(args[0])
        return NAN if math.isnan(x) else fn(x)
    return f


def _round(it, node, args, kw):
    x = _num(args[0])
    if math.isnan(x):
        return NAN
    p = int(A(args, kw, 1, "precision", 0))
    return float(math.floor(x * 10 ** p + 0.5) / 10 ** p)


def _minmax(fn):
    def f(it, node, args, kw):
        v = [_num(a) for a in args]
        return NAN if any(math.isnan(x) for x in v) else fn(v)
    return f


def _pow(it, node, args, kw):
    a, b = _num(args[0]), _num(args[1])
    try:
        return a ** b if not (math.isnan(a) or math.isnan(b)) else NAN
    except (OverflowError, ZeroDivisionError, ValueError):
        return NAN


def _sign(x: float) -> float:
    return float((x > 0) - (x < 0))


# ---- input ----
def make_input(kind: str):
    def f(it, node, args, kw):
        default = A(args, kw, 0, "defval", None)
        title = A(args, kw, 1, "title", None) or A(args, kw, 1, "name", None) or f"Input {len(it.input_defs) + 1}"
        key = node.id
        if key not in it.input_defs:
            d = {"title": title, "type": kind, "default": default}
            for opt in ("minval", "maxval", "step", "options"):
                if opt in kw:
                    d[opt] = kw[opt]
            it.input_defs[key] = d
        val = it.input_overrides.get(title, default)
        if kind in ("int", "float") and val is not None:
            val = float(val)
            if kind == "int":
                val = float(int(val))
        if kind == "source" and isinstance(default, float) is False and default is not None:
            return default
        return val
    return f


def input_generic(it, node, args, kw):
    return make_input("float")(it, node, args, kw)


# ---- đầu ra ----
def f_indicator(it, node, args, kw):
    it.meta.update(kind="indicator", title=A(args, kw, 0, "title", ""), overlay=bool(kw.get("overlay", False)),
                   format=kw.get("format"))
    return NAN


def f_strategy(it, node, args, kw):
    it.meta.update(kind="strategy", title=A(args, kw, 0, "title", ""), overlay=bool(kw.get("overlay", False)))
    s = it.strategy
    s.initial = _num(kw.get("initial_capital", 10000.0))
    s.qty_type = kw.get("default_qty_type", "fixed")
    s.qty_value = _num(kw.get("default_qty_value", 1.0))
    s.commission = _num(kw.get("commission_value", 0.0)) if kw.get("commission_type", "percent") == "percent" else 0.0
    s.pyramiding = int(_num(kw.get("pyramiding", 0)))
    s.apply_overrides()         # tham số của giao diện backtest thắng giá trị ghi trong script
    return NAN


def _col(c):
    return None if isna(c) else c


def f_plot(it, node, args, kw):
    v = A(args, kw, 0, "series")
    p = it.plots.get(node.id)
    if p is None:
        p = it.plots[node.id] = {
            "title": A(args, kw, 1, "title", None) or f"Plot {len(it.plots)}", "style": kw.get("style", "line"),
            "linewidth": int(_num(kw.get("linewidth", 1))), "values": [NAN] * it.n, "colors": [None] * it.n,
        }
    p["values"][it.i] = _num(v)
    p["colors"][it.i] = _col(A(args, kw, 2, "color", None))
    return NAN


def f_plotshape(it, node, args, kw):
    v = A(args, kw, 0, "series")
    p = it.shapes.get(node.id)
    if p is None:
        p = it.shapes[node.id] = {
            "title": A(args, kw, 1, "title", None) or f"Shape {len(it.shapes)}", "shape": A(args, kw, 2, "style", "xcross"),
            "location": A(args, kw, 3, "location", "abovebar"), "size": kw.get("size", "small"), "text": kw.get("text", ""),
            "values": [False] * it.n, "colors": [None] * it.n,
        }
    p["values"][it.i] = _truthy(v)
    p["colors"][it.i] = _col(A(args, kw, 4, "color", None))
    return NAN


def f_bgcolor(it, node, args, kw):
    c = _col(A(args, kw, 0, "color", None))
    p = it.bgcolors.get(node.id)
    if p is None:
        p = it.bgcolors[node.id] = {"colors": [None] * it.n}
    p["colors"][it.i] = c
    return NAN


def f_hline(it, node, args, kw):
    price = _num(A(args, kw, 0, "price"))
    it.hlines.setdefault(node.id, {"price": price, "title": A(args, kw, 1, "title", ""), "color": A(args, kw, 2, "color", None),
                                    "style": kw.get("linestyle", "dashed")})
    return price


def f_alertcondition(it, node, args, kw):
    cond = A(args, kw, 0, "condition")
    a = it.alerts.get(node.id)
    if a is None:
        a = it.alerts[node.id] = {"title": A(args, kw, 1, "title", "Alert"), "message": A(args, kw, 2, "message", ""), "bars": []}
    if _truthy(cond):
        a["bars"].append(it.i)
    return NAN


def f_color_new(it, node, args, kw):
    return color_new(args[0], _num(A(args, kw, 1, "transp", 0.0)))


def f_color_rgb(it, node, args, kw):
    r, g, b = (int(_num(x)) for x in args[:3])
    return color_new(f"#{r:02X}{g:02X}{b:02X}", _num(A(args, kw, 3, "transp", 0.0)))


# ---- request ----
def _sec_series(it, n: Call, sym, tf, expr_node, lookahead: bool):
    """Tính (và nhớ) biểu thức trên nến của (symbol, tf), rồi ánh xạ về từng nến của biểu đồ."""
    key = (n.id, it.stack)
    c = it.sec_cache.get(key)
    if c is None:
        same = (not sym or sym == it.symbol) and (not tf or tf_to_ms(tf) == it.tf_ms)
        if same:
            other = it.bars
        else:
            if it.provider is None:
                raise PineRuntimeError("request.security cần nguồn dữ liệu (provider)", n.line)
            other = it.provider(sym or it.symbol, tf or it.tf)
            if other is None or len(other) == 0:
                raise PineRuntimeError(f"không có dữ liệu cho {sym} {tf}", n.line)
        d_ms = tf_to_ms(tf) if tf else it.tf_ms
        sub = Interp(it.ast, other, symbol=sym or it.symbol, tf=tf or it.tf, tz_offset_ms=it.tz, provider=it.provider,
                     inputs=it.input_overrides, external=it.external, syminfo_type=it.syminfo_type, ast=it.ast)
        sub.funcs = it.funcs
        sub.vars = {k: v for k, v in it.vars.items() if not isinstance(v, (list,))}
        sub.persist = set(sub.vars)   # hằng của chương trình chính (ví dụ độ dài từ input) phải sống qua mọi nến
        vals = sub.run_expr(expr_node)
        opens = list(other.time)
        closes = [t + d_ms for t in opens]
        c = it.sec_cache[key] = (vals, opens, closes)
    vals, opens, closes = c
    i = it.i
    if lookahead:
        j = bisect.bisect_right(opens, it.bars.time[i]) - 1
    else:
        # nến chỉ được dùng khi đã đóng tại thời điểm đóng của nến hiện tại: không nhìn trước
        j = bisect.bisect_right(closes, it.bars.time[i] + it.tf_ms) - 1
    return vals[j] if j >= 0 else NAN


def lazy_security(it, n: Call):
    pos = [e for nm, e in n.args if nm is None]
    kw = {nm: e for nm, e in n.args if nm is not None}
    sym_n = pos[0] if pos else kw.get("symbol")
    tf_n = pos[1] if len(pos) > 1 else kw.get("timeframe")
    expr_n = pos[2] if len(pos) > 2 else kw.get("expression")
    la = it.eval(kw["lookahead"]) if "lookahead" in kw else (it.eval(pos[3]) if len(pos) > 3 else False)
    sym = it.eval(sym_n) if sym_n is not None else ""
    tf = it.eval(tf_n) if tf_n is not None else ""
    if expr_n is None:
        raise PineRuntimeError("request.security cần biểu thức", n.line)
    return _sec_series(it, n, str(sym), str(tf), expr_n, bool(la))


def f_external(it, node, args, kw):
    name = str(args[0])
    b, i = it.bars, it.i
    if name == "delta":
        return (b.buy[i] - b.sell[i]) if b.buy else NAN
    if name == "cvd":
        st = it.state(node, lambda: {"day": None, "sum": 0.0})
        day = _day_index(it, b.time[i])
        if st["day"] != day:
            st["day"], st["sum"] = day, 0.0
        st["sum"] += (b.buy[i] - b.sell[i]) if b.buy else 0.0
        return st["sum"]
    if name == "gex_levels":
        g = it.external.get("gex_levels") or {}
        return [_num(g.get("flip")), _num(g.get("call_wall")), _num(g.get("put_wall"))]
    raise PineRuntimeError(f"request.external không có nguồn {name!r}", node.line)


# ---- strategy ----
def f_entry(it, node, args, kw):
    it.strategy.order("entry", str(A(args, kw, 0, "id")), A(args, kw, 1, "direction"), kw.get("qty"),
                      when=kw.get("when", True))
    return NAN


def f_close(it, node, args, kw):
    it.strategy.order("close", str(A(args, kw, 0, "id")), None, None, when=kw.get("when", True))
    return NAN


def f_close_all(it, node, args, kw):
    it.strategy.order("close_all", "", None, None, when=kw.get("when", True))
    return NAN


class Strategy:
    """Backtest tối giản: lệnh đặt ở nến i khớp ở giá mở cửa của nến i+1. Một vị thế ròng, không pyramiding."""

    def __init__(self, it: Interp):
        self.it = it
        self.initial = 10000.0
        self.qty_type, self.qty_value, self.commission, self.pyramiding = "fixed", 1.0, 0.0, 0
        self.overrides: dict = {}      # initial_capital, commission_pct, slippage (đơn vị giá) từ giao diện backtest
        self.slippage = 0.0
        self.pending: list = []
        self.position_size = 0.0
        self.avg = 0.0
        self.realized = 0.0
        self.open_trade: dict | None = None
        self.trades: list[dict] = []
        self.equity: list[float] = []
        self.active = False

    def order(self, kind, oid, direction, qty, when=True):
        self.active = True
        if _truthy(when):
            self.pending.append((kind, oid, direction, qty))

    def equity_now(self) -> float:
        i = max(self.it.i, 0)
        px = self.it.bars.close[i] if self.it.n else 0.0
        return self.initial + self.realized + self.position_size * (px - self.avg)

    def apply_overrides(self) -> None:
        o = self.overrides
        if o.get("initial_capital") is not None:
            self.initial = float(o["initial_capital"])
        if o.get("commission_pct") is not None:
            self.commission = float(o["commission_pct"])
        self.slippage = float(o.get("slippage") or 0.0)

    def _fill(self, i: int, px: float, delta: float, oid: str) -> None:
        """Đổi vị thế một lượng delta (có dấu) ở giá px. Trượt giá làm giá khớp xấu đi: mua cao hơn, bán thấp hơn."""
        px = px + self.slippage if delta > 0 else px - self.slippage
        fee = abs(delta) * px * self.commission / 100.0
        self.realized -= fee
        old = self.position_size
        new = old + delta
        t = self.it.bars.time[i]
        if old != 0 and (new == 0 or (old > 0) != (new > 0) or abs(new) < abs(old)):
            closed = min(abs(delta), abs(old)) * (1 if old > 0 else -1)
            pnl = closed * (px - self.avg)
            self.realized += pnl
            if self.open_trade is not None and (new == 0 or (old > 0) != (new > 0)):
                tr = self.open_trade
                tr.update(exit_time=t, exit_price=px, pnl=pnl - fee - tr.get("fee", 0.0))
                tr["pnl_pct"] = tr["pnl"] / (abs(tr["qty"]) * tr["entry_price"]) * 100 if tr["qty"] else 0.0
                self.trades.append(tr)
                self.open_trade = None
        if new != 0 and (old == 0 or (old > 0) != (new > 0)):
            self.avg = px
            self.open_trade = {"id": oid, "dir": "long" if new > 0 else "short", "entry_time": t, "entry_price": px,
                               "qty": abs(new), "fee": fee}
        elif new != 0 and abs(new) > abs(old):
            self.avg = (self.avg * abs(old) + px * abs(delta)) / abs(new)
        self.position_size = new

    def begin_bar(self, i: int) -> None:
        if not self.pending:
            return
        px = self.it.bars.open[i]
        orders, self.pending = self.pending, []
        for kind, oid, direction, qty in orders:
            if kind == "entry":
                sign = 1.0 if direction == "long" else -1.0
                if self.position_size != 0 and (self.position_size > 0) == (sign > 0):
                    continue          # cùng hướng, không pyramiding
                if qty is None or isna(qty):
                    eq = self.initial + self.realized
                    if self.qty_type == "percent_of_equity":
                        q = eq * self.qty_value / 100.0 / px
                    elif self.qty_type == "cash":
                        q = self.qty_value / px
                    else:
                        q = self.qty_value
                else:
                    q = float(qty)
                if q <= 0:
                    continue
                self._fill(i, px, sign * q - self.position_size, oid)
            elif kind == "close":
                if self.position_size != 0 and self.open_trade and self.open_trade["id"] == oid:
                    self._fill(i, px, -self.position_size, oid)
            elif kind == "close_all" and self.position_size != 0:
                self._fill(i, px, -self.position_size, oid)

    def end_bar(self, i: int) -> None:
        self.equity.append(self.equity_now())

    def finish(self) -> None:
        pass

    def summary(self) -> dict | None:
        if not self.active and not self.trades:
            return None
        wins = [t for t in self.trades if t["pnl"] > 0]
        peak, mdd = -math.inf, 0.0
        for e in self.equity:
            peak = max(peak, e)
            mdd = max(mdd, (peak - e) / peak if peak > 0 else 0.0)
        net = sum(t["pnl"] for t in self.trades)
        return {"initial_capital": self.initial, "net_profit": net, "closed_trades": len(self.trades),
                "win_rate": len(wins) / len(self.trades) if self.trades else 0.0, "max_drawdown": mdd,
                "open_position": self.position_size, "equity": self.equity, "trades": self.trades}


BUILTINS: dict[str, Callable] = {
    "indicator": f_indicator, "strategy": f_strategy, "plot": f_plot, "plotshape": f_plotshape, "bgcolor": f_bgcolor,
    "hline": f_hline, "alertcondition": f_alertcondition, "time": f_time, "na": f_na, "nz": f_nz,
    "color.new": f_color_new, "color.rgb": f_color_rgb,
    "input": input_generic, "input.int": make_input("int"), "input.float": make_input("float"), "input.bool": make_input("bool"),
    "input.string": make_input("string"), "input.symbol": make_input("symbol"), "input.timeframe": make_input("timeframe"),
    "input.source": make_input("source"), "input.color": make_input("color"), "input.session": make_input("session"),
    "ta.sma": _ta_window(T.Sma), "ta.ema": _ta_window(T.make_ema), "ta.rma": _ta_window(T.make_rma),
    "ta.rsi": _ta_window(T.Rsi), "ta.stdev": _ta_window(T.Stdev),
    "ta.highest": _ta_window(lambda n: T.Extreme(n, True)), "ta.lowest": _ta_window(lambda n: T.Extreme(n, False)),
    "ta.change": lambda it, node, args, kw: it.state(node, lambda: T.Change(int(A(args, kw, 1, "length", 1)))).update(args[0]),
    "ta.crossover": lambda it, node, args, kw: it.state(node, lambda: T.Cross(True)).update(_num(args[0]), _num(args[1])),
    "ta.crossunder": lambda it, node, args, kw: it.state(node, lambda: T.Cross(False)).update(_num(args[0]), _num(args[1])),
    "ta.macd": ta_macd, "ta.bb": ta_bb, "ta.atr": ta_atr, "ta.vwap": ta_vwap,
    "math.abs": _m1(abs), "math.sqrt": _m1(lambda x: math.sqrt(x) if x >= 0 else NAN),
    "math.log": _m1(lambda x: math.log(x) if x > 0 else NAN), "math.exp": _m1(math.exp), "math.floor": _m1(lambda x: float(math.floor(x))),
    "math.ceil": _m1(lambda x: float(math.ceil(x))), "math.sign": _m1(_sign), "math.round": _round,
    "math.max": _minmax(max), "math.min": _minmax(min), "math.pow": _pow, "math.avg": _minmax(lambda v: sum(v) / len(v)),
    "request.external": f_external,
    "strategy.entry": f_entry, "strategy.close": f_close, "strategy.close_all": f_close_all,
}
LAZY: dict[str, Callable] = {"request.security": lazy_security}

from . import objects as _objects  # noqa: E402,F401  (đăng ký mảng, chuỗi, đối tượng vẽ vào BUILTINS)
