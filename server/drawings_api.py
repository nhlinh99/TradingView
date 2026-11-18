"""Công cụ vẽ: lưu trong SQLite (bảng `drawings`), theo symbol.

Mỗi hình có `kind` (trend, hline, rect, fib, fibx, ruler, xline, text) và `payload` JSON chứa các điểm neo. Điểm neo dùng thời gian
(giây UTC) và giá thật, không dùng toạ độ màn hình hay chỉ số nến, nên hình đúng ở mọi khung thời gian.
`layout_id` bỏ trống nghĩa là layout mặc định (một chart); layout nhiều ô dùng chung bản vẽ theo symbol.
"""
from __future__ import annotations

import json
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from common import appdb, store

router = APIRouter()

# số điểm neo cho phép (tối thiểu, tối đa); brush là nét vẽ tự do nên có nhiều điểm
KINDS = {
    "trend": (2, 2), "ray": (2, 2), "hray": (1, 1), "xline": (2, 2), "hline": (1, 1), "vline": (1, 1), "cross": (1, 1),
    "info": (2, 2), "angle": (2, 2), "arrow": (2, 2), "channel": (3, 3), "regression": (2, 2),
    "rect": (2, 2), "brush": (2, 400), "fib": (2, 2), "fibx": (3, 3), "ruler": (2, 2), "daterange": (2, 2),
    "pricerange": (2, 2), "text": (1, 1),
    "long": (3, 3), "short": (3, 3), "circle": (2, 2), "ellipse": (2, 2), "triangle": (3, 3), "polyline": (2, 50),
    "note": (1, 1), "callout": (2, 2), "pricelabel": (1, 1), "flag": (1, 1),
}
MAX_PAYLOAD = 40_000


class DrawingBody(BaseModel):
    symbol: str
    kind: str
    payload: dict
    id: int | None = None   # khi hoàn tác một lần xoá: tạo lại đúng id cũ


def _validate(kind: str, payload: dict) -> None:
    if kind not in KINDS:
        raise HTTPException(422, f"loại hình không hợp lệ: {kind}; có: {sorted(KINDS)}")
    pts = payload.get("points")
    lo, hi = KINDS[kind]
    if not isinstance(pts, list) or not lo <= len(pts) <= hi:
        raise HTTPException(422, f"{kind} cần " + (f"đúng {lo}" if lo == hi else f"từ {lo} đến {hi}") + " điểm neo")
    for p in pts:
        if not (isinstance(p, dict) and all(isinstance(p.get(k), (int, float)) and math.isfinite(p[k]) for k in ("time", "price"))):
            raise HTTPException(422, "mỗi điểm neo cần time (giây) và price là số hữu hạn")
    if len(json.dumps(payload)) > MAX_PAYLOAD:
        raise HTTPException(422, "payload quá lớn")


def _row(r) -> dict:
    return {"id": r[0], "symbol": r[1], "kind": r[2], "payload": json.loads(r[3])}


def _symbol(s: str) -> str:
    s = s.strip().upper()
    try:
        store.symbol_config(s)
    except KeyError:
        raise HTTPException(404, f"symbol không có trong config: {s}")
    return s


@router.get("/api/drawings")
def list_drawings(symbol: str) -> list[dict]:
    sym = _symbol(symbol)
    appdb.init()
    con = appdb.connect()
    try:
        return [_row(r) for r in con.execute(
            "SELECT id, symbol, kind, payload FROM drawings WHERE symbol = ? AND layout_id IS NULL ORDER BY id", (sym,))]
    finally:
        con.close()


@router.post("/api/drawings")
def create_drawing(body: DrawingBody) -> dict:
    sym = _symbol(body.symbol)
    _validate(body.kind, body.payload)
    appdb.init()
    con = appdb.connect()
    try:
        if body.id is not None:
            if con.execute("SELECT 1 FROM drawings WHERE id = ?", (body.id,)).fetchone():
                raise HTTPException(409, "id đã tồn tại")
            cur = con.execute("INSERT INTO drawings(id, layout_id, symbol, kind, payload) VALUES (?, NULL, ?, ?, ?)",
                              (body.id, sym, body.kind, json.dumps(body.payload)))
        else:
            cur = con.execute("INSERT INTO drawings(layout_id, symbol, kind, payload) VALUES (NULL, ?, ?, ?)",
                              (sym, body.kind, json.dumps(body.payload)))
        con.commit()
        return {"id": cur.lastrowid, "symbol": sym, "kind": body.kind, "payload": body.payload}
    finally:
        con.close()


@router.put("/api/drawings/{drawing_id}")
def update_drawing(drawing_id: int, body: DrawingBody) -> dict:
    sym = _symbol(body.symbol)
    _validate(body.kind, body.payload)
    appdb.init()
    con = appdb.connect()
    try:
        cur = con.execute("UPDATE drawings SET symbol = ?, kind = ?, payload = ? WHERE id = ?",
                          (sym, body.kind, json.dumps(body.payload), drawing_id))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "không có hình này")
        return {"id": drawing_id, "symbol": sym, "kind": body.kind, "payload": body.payload}
    finally:
        con.close()


@router.delete("/api/drawings/{drawing_id}")
def delete_drawing(drawing_id: int) -> dict:
    appdb.init()
    con = appdb.connect()
    try:
        cur = con.execute("DELETE FROM drawings WHERE id = ?", (drawing_id,))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "không có hình này")
        return {"deleted": drawing_id}
    finally:
        con.close()


@router.delete("/api/drawings")
def clear_drawings(symbol: str) -> dict:
    sym = _symbol(symbol)
    appdb.init()
    con = appdb.connect()
    try:
        cur = con.execute("DELETE FROM drawings WHERE symbol = ? AND layout_id IS NULL", (sym,))
        con.commit()
        return {"deleted": cur.rowcount}
    finally:
        con.close()
