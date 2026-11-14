"""Bộ tách từ cho tập con Pine Script v5. Pine dùng thụt lề để chia khối, nên bộ tách từ sinh INDENT/DEDENT.

Quy tắc xuống dòng:
  - Bên trong ngoặc tròn hoặc vuông, xuống dòng không có nghĩa (biểu thức được phép trải nhiều dòng).
  - Dòng kết thúc bằng toán tử hoặc dấu phẩy thì dòng sau là phần tiếp theo.
  - Dòng trống và dòng chỉ có chú thích bị bỏ qua.
"""
from __future__ import annotations

from dataclasses import dataclass

KEYWORDS = {"if", "else", "for", "to", "by", "while", "var", "varip", "and", "or", "not", "true", "false", "break", "continue", "in", "switch"}
OPS3 = {"!==", "==="}
OPS2 = {"==", "!=", "<=", ">=", ":=", "+=", "-=", "*=", "/=", "%=", "=>", "&&", "||"}
OPS1 = set("+-*/%<>=?:()[],.!")
CONTINUE_AFTER = set("+-*/%<>=?:,(") | {"==", "!=", "<=", ">=", ":=", "+=", "-=", "*=", "/=", "%=", "and", "or", "&&", "||"}


class PineSyntaxError(Exception):
    def __init__(self, msg: str, line: int = 0):
        super().__init__(f"dòng {line}: {msg}" if line else msg)
        self.line = line


@dataclass
class Tok:
    kind: str     # NUM STR ID KW OP NL INDENT DEDENT EOF COLOR
    value: object
    line: int

    def __repr__(self) -> str:  # để debug
        return f"{self.kind}:{self.value!r}"


def tokenize(src: str) -> list[Tok]:
    toks: list[Tok] = []
    indents = [0]
    depth = 0
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for ln, raw in enumerate(lines, 1):
        line = raw.expandtabs(4)
        body = line.strip()
        if not body or body.startswith("//"):
            continue
        cont = depth > 0 or (toks and toks[-1].kind in ("OP", "KW") and toks[-1].value in CONTINUE_AFTER)
        if not cont:
            ind = len(line) - len(line.lstrip(" "))
            if ind > indents[-1]:
                indents.append(ind)
                toks.append(Tok("INDENT", ind, ln))
            else:
                while ind < indents[-1]:
                    indents.pop()
                    toks.append(Tok("DEDENT", 0, ln))
                if ind != indents[-1]:
                    raise PineSyntaxError("thụt lề không khớp với khối nào", ln)
        i, n = 0, len(line)
        # dòng tiếp theo của biểu thức dở dang: bỏ NL đã thêm ở cuối dòng trước (đã không thêm, xem dưới)
        while i < n:
            c = line[i]
            if c == " ":
                i += 1
            elif line.startswith("//", i):
                break
            elif c.isdigit() or (c == "." and i + 1 < n and line[i + 1].isdigit()):
                j = i
                while j < n and (line[j].isdigit() or line[j] == "."):
                    j += 1
                if j < n and line[j] in "eE" and j + 1 < n and (line[j + 1].isdigit() or line[j + 1] in "+-"):
                    j += 2
                    while j < n and line[j].isdigit():
                        j += 1
                toks.append(Tok("NUM", float(line[i:j]), ln))
                i = j
            elif c in "\"'":
                j = i + 1
                out = []
                while j < n and line[j] != c:
                    if line[j] == "\\" and j + 1 < n:
                        out.append({"n": "\n", "t": "\t"}.get(line[j + 1], line[j + 1]))
                        j += 2
                    else:
                        out.append(line[j])
                        j += 1
                if j >= n:
                    raise PineSyntaxError("chuỗi chưa đóng", ln)
                toks.append(Tok("STR", "".join(out), ln))
                i = j + 1
            elif c == "#":
                j = i + 1
                while j < n and line[j] in "0123456789abcdefABCDEF":
                    j += 1
                if j - i not in (7, 9):
                    raise PineSyntaxError("màu hex phải dạng #RRGGBB hoặc #RRGGBBAA", ln)
                toks.append(Tok("COLOR", line[i:j], ln))
                i = j
            elif c.isalpha() or c == "_":
                j = i
                while j < n and (line[j].isalnum() or line[j] == "_"):
                    j += 1
                w = line[i:j]
                toks.append(Tok("KW" if w in KEYWORDS else "ID", w, ln))
                i = j
            else:
                for op in (line[i:i + 3], line[i:i + 2], c):
                    if (len(op) == 3 and op in OPS3) or (len(op) == 2 and op in OPS2) or (len(op) == 1 and op in OPS1):
                        break
                else:
                    raise PineSyntaxError(f"ký tự không hợp lệ {c!r}", ln)
                if op in ("(", "["):
                    depth += 1
                elif op in (")", "]"):
                    depth -= 1
                toks.append(Tok("OP", op, ln))
                i += len(op)
        if depth == 0 and not (toks and toks[-1].kind in ("OP", "KW") and toks[-1].value in CONTINUE_AFTER):
            toks.append(Tok("NL", None, ln))
    while len(indents) > 1:
        indents.pop()
        toks.append(Tok("DEDENT", 0, len(lines)))
    toks.append(Tok("EOF", None, len(lines)))
    return toks
