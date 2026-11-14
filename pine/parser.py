"""Parser cho tập con Pine Script v5. Sinh cây AST bằng các dataclass nhỏ; mỗi nút có `id` duy nhất để
bộ thông dịch gắn trạng thái (cửa sổ SMA, giá trị EMA trước đó, ...) theo vị trí gọi trong mã nguồn.

Hỗ trợ: khai báo (kể cả `var`, có hoặc không có kiểu), gán `=` `:=` `+=` ..., tuple `[a, b] = ...`, if/else if/else,
for ... to ... by, while, break/continue, hàm người dùng (một dòng `f(x) => expr` hoặc khối thụt lề),
toán tử ba ngôi, and/or/not, tham chiếu lịch sử `x[n]`, gọi hàm có tham số đặt tên, truy cập `a.b.c`.
Không hỗ trợ: switch, kiểu do người dùng định nghĩa (type/method), mảng, thư viện import.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from .lexer import PineSyntaxError, Tok, tokenize

_ids = itertools.count(1)
TYPES = {"int", "float", "bool", "string", "color", "series", "simple", "const"}


def _nid() -> int:
    return next(_ids)


@dataclass
class Num:
    value: float
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Str:
    value: str
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Bool:
    value: bool
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Color:
    value: str
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Name:
    name: str
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Attr:
    obj: object
    name: str
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Index:
    obj: object
    idx: object
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Call:
    func: object
    args: list            # [(tên hoặc None, biểu thức)]
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Unary:
    op: str
    operand: object
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Binary:
    op: str
    left: object
    right: object
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Ternary:
    cond: object
    a: object
    b: object
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class TupleLit:
    items: list
    line: int = 0
    id: int = field(default_factory=_nid)


# ---- câu lệnh ----
@dataclass
class Assign:
    target: object        # tên (str) hoặc list[str] cho tuple
    op: str               # "=" hoặc ":=" hoặc "+=" ...
    value: object
    var: bool = False
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class If:
    cond: object
    body: list
    orelse: list
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class For:
    var: str
    start: object
    stop: object
    step: object | None
    body: list
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class While:
    cond: object
    body: list
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class FuncDef:
    name: str
    params: list          # [(tên, mặc định hoặc None)]
    body: list
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class ExprStmt:
    expr: object
    line: int = 0
    id: int = field(default_factory=_nid)


@dataclass
class Jump:
    kind: str             # "break" | "continue"
    line: int = 0
    id: int = field(default_factory=_nid)


class Parser:
    def __init__(self, src: str):
        self.t = tokenize(src)
        self.p = 0

    # ---- tiện ích ----
    @property
    def cur(self) -> Tok:
        return self.t[self.p]

    def peek(self, k: int = 1) -> Tok:
        return self.t[min(self.p + k, len(self.t) - 1)]

    def err(self, msg: str) -> PineSyntaxError:
        return PineSyntaxError(msg, self.cur.line)

    def is_op(self, v: str, tok: Tok | None = None) -> bool:
        tok = tok or self.cur
        return tok.kind == "OP" and tok.value == v

    def is_kw(self, v: str) -> bool:
        return self.cur.kind == "KW" and self.cur.value == v

    def eat_op(self, v: str) -> Tok:
        if not self.is_op(v):
            raise self.err(f"cần '{v}', gặp {self.cur.value!r}")
        self.p += 1
        return self.t[self.p - 1]

    def skip_nl(self) -> None:
        while self.cur.kind == "NL":
            self.p += 1

    # ---- chương trình ----
    def program(self) -> list:
        out = []
        self.skip_nl()
        while self.cur.kind != "EOF":
            out.append(self.statement())
            self.skip_nl()
        return out

    def block(self) -> list:
        """Sau `if cond`, `for ...`, `=>`: một khối thụt lề."""
        if self.cur.kind != "NL":
            # khối một dòng không được Pine cho phép, nhưng `=>` cho phép biểu thức ngay sau
            return [self.statement()]
        self.skip_nl()
        if self.cur.kind != "INDENT":
            raise self.err("cần khối thụt lề")
        self.p += 1
        body = []
        self.skip_nl()
        while self.cur.kind not in ("DEDENT", "EOF"):
            body.append(self.statement())
            self.skip_nl()
        if self.cur.kind == "DEDENT":
            self.p += 1
        return body

    def end_stmt(self) -> None:
        if self.cur.kind == "NL":
            self.p += 1
        elif self.is_op(","):
            self.p += 1          # `a = 1, b = 2` trên một dòng: dấu phẩy ngăn cách các câu lệnh
        elif self.cur.kind not in ("EOF", "DEDENT"):
            raise self.err(f"không mong đợi {self.cur.value!r}")

    def statement(self):
        tok = self.cur
        line = tok.line
        if tok.kind == "KW":
            if tok.value in ("var", "varip"):
                self.p += 1
                if self.cur.kind == "ID" and self.cur.value in TYPES and self.peek().kind == "ID":
                    self.p += 1
                name = self.name()
                self.eat_op("=")
                v = self.expr()
                self.end_stmt()
                return Assign(name, "=", v, var=True, line=line)
            if tok.value == "if":
                return self.if_stmt()
            if tok.value == "for":
                return self.for_stmt()
            if tok.value == "while":
                self.p += 1
                c = self.expr()
                body = self.block()
                return While(c, body, line=line)
            if tok.value in ("break", "continue"):
                self.p += 1
                self.end_stmt()
                return Jump(tok.value, line=line)
        # tuple: [a, b] = expr
        if self.is_op("["):
            save = self.p
            names = self.try_tuple_target()
            if names is not None:
                v = self.expr()
                self.end_stmt()
                return Assign(names, "=", v, line=line)
            self.p = save
        # định nghĩa hàm: f(a, b) =>
        if tok.kind == "ID" and self.is_op("(", self.peek()) and self.is_func_def():
            return self.func_def()
        # khai báo có kiểu: float x = ...
        if tok.kind == "ID" and tok.value in TYPES and self.peek().kind == "ID" and self.is_op("=", self.peek(2)):
            self.p += 1
            tok = self.cur
        # gán
        if tok.kind == "ID" and self.peek().kind == "OP" and self.peek().value in ("=", ":=", "+=", "-=", "*=", "/=", "%="):
            name = tok.value
            op = self.peek().value
            self.p += 2
            v = self.expr()
            self.end_stmt()
            return Assign(name, op, v, line=line)
        e = self.expr()
        self.end_stmt()
        return ExprStmt(e, line=line)

    def name(self) -> str:
        if self.cur.kind != "ID":
            raise self.err(f"cần tên, gặp {self.cur.value!r}")
        self.p += 1
        return self.t[self.p - 1].value

    def try_tuple_target(self):
        self.p += 1
        names = []
        while True:
            if self.cur.kind != "ID":
                return None
            names.append(self.cur.value)
            self.p += 1
            if self.is_op(","):
                self.p += 1
                continue
            break
        if not self.is_op("]"):
            return None
        self.p += 1
        if not self.is_op("="):
            return None
        self.p += 1
        return names

    def is_func_def(self) -> bool:
        depth, i = 0, self.p + 1
        while i < len(self.t):
            tk = self.t[i]
            if tk.kind == "OP" and tk.value == "(":
                depth += 1
            elif tk.kind == "OP" and tk.value == ")":
                depth -= 1
                if depth == 0:
                    n = self.t[i + 1]
                    return n.kind == "OP" and n.value == "=>"
            elif tk.kind in ("NL", "EOF"):
                return False
            i += 1
        return False

    def func_def(self) -> FuncDef:
        line = self.cur.line
        name = self.name()
        self.eat_op("(")
        params = []
        while not self.is_op(")"):
            if self.cur.kind == "ID" and self.cur.value in TYPES and self.peek().kind == "ID":
                self.p += 1
            pn = self.name()
            default = None
            if self.is_op("="):
                self.p += 1
                default = self.expr()
            params.append((pn, default))
            if self.is_op(","):
                self.p += 1
        self.eat_op(")")
        self.eat_op("=>")
        if self.cur.kind == "NL":
            body = self.block()
        else:
            e = self.expr()
            self.end_stmt()
            body = [ExprStmt(e, line=line)]
        return FuncDef(name, params, body, line=line)

    def if_stmt(self) -> If:
        line = self.cur.line
        self.p += 1
        c = self.expr()
        body = self.block()
        orelse: list = []
        self.skip_nl()
        if self.is_kw("else"):
            self.p += 1
            if self.is_kw("if"):
                orelse = [self.if_stmt()]
            else:
                orelse = self.block()
        return If(c, body, orelse, line=line)

    def for_stmt(self) -> For:
        line = self.cur.line
        self.p += 1
        v = self.name()
        self.eat_op("=")
        a = self.expr()
        if not self.is_kw("to"):
            raise self.err("cần 'to'")
        self.p += 1
        b = self.expr()
        step = None
        if self.is_kw("by"):
            self.p += 1
            step = self.expr()
        return For(v, a, b, step, self.block(), line=line)

    # ---- biểu thức ----
    def expr(self):
        return self.ternary()

    def ternary(self):
        c = self.or_()
        if self.is_op("?"):
            line = self.cur.line
            self.p += 1
            a = self.ternary()
            self.eat_op(":")
            b = self.ternary()
            return Ternary(c, a, b, line=line)
        return c

    def or_(self):
        left = self.and_()
        while self.is_kw("or") or self.is_op("||"):
            line = self.cur.line
            self.p += 1
            left = Binary("or", left, self.and_(), line=line)
        return left

    def and_(self):
        left = self.not_()
        while self.is_kw("and") or self.is_op("&&"):
            line = self.cur.line
            self.p += 1
            left = Binary("and", left, self.not_(), line=line)
        return left

    def not_(self):
        if self.is_kw("not") or self.is_op("!"):
            line = self.cur.line
            self.p += 1
            return Unary("not", self.not_(), line=line)
        return self.compare()

    def compare(self):
        left = self.add()
        while self.cur.kind == "OP" and self.cur.value in ("==", "!=", "<", "<=", ">", ">="):
            op, line = self.cur.value, self.cur.line
            self.p += 1
            left = Binary(op, left, self.add(), line=line)
        return left

    def add(self):
        left = self.mul()
        while self.cur.kind == "OP" and self.cur.value in ("+", "-"):
            op, line = self.cur.value, self.cur.line
            self.p += 1
            left = Binary(op, left, self.mul(), line=line)
        return left

    def mul(self):
        left = self.unary()
        while self.cur.kind == "OP" and self.cur.value in ("*", "/", "%"):
            op, line = self.cur.value, self.cur.line
            self.p += 1
            left = Binary(op, left, self.unary(), line=line)
        return left

    def unary(self):
        if self.cur.kind == "OP" and self.cur.value in ("+", "-"):
            op, line = self.cur.value, self.cur.line
            self.p += 1
            return Unary(op, self.unary(), line=line)
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            line = self.cur.line
            if self.is_op("("):
                self.p += 1
                e = Call(e, self.call_args(), line=line)
            elif self.is_op("["):
                self.p += 1
                i = self.expr()
                self.eat_op("]")
                e = Index(e, i, line=line)
            elif self.is_op("."):
                self.p += 1
                e = Attr(e, self.name(), line=line)
            else:
                return e

    def call_args(self) -> list:
        args = []
        while not self.is_op(")"):
            if self.cur.kind == "ID" and self.is_op("=", self.peek()) and not self.is_op("==", self.peek()):
                nm = self.cur.value
                self.p += 2
                args.append((nm, self.expr()))
            else:
                args.append((None, self.expr()))
            if self.is_op(","):
                self.p += 1
            elif not self.is_op(")"):
                raise self.err("cần ',' hoặc ')'")
        self.eat_op(")")
        return args

    def primary(self):
        t = self.cur
        line = t.line
        if t.kind == "NUM":
            self.p += 1
            return Num(t.value, line=line)
        if t.kind == "STR":
            self.p += 1
            return Str(t.value, line=line)
        if t.kind == "COLOR":
            self.p += 1
            return Color(t.value, line=line)
        if t.kind == "KW" and t.value in ("true", "false"):
            self.p += 1
            return Bool(t.value == "true", line=line)
        if t.kind == "ID":
            self.p += 1
            return Name(t.value, line=line)
        if self.is_op("("):
            self.p += 1
            e = self.expr()
            self.eat_op(")")
            return e
        if self.is_op("["):
            self.p += 1
            items = []
            while not self.is_op("]"):
                items.append(self.expr())
                if self.is_op(","):
                    self.p += 1
            self.eat_op("]")
            return TupleLit(items, line=line)
        raise self.err(f"không mong đợi {t.value!r}")


def parse(src: str) -> list:
    return Parser(src).program()
