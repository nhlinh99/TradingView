"""Quản lý cảnh báo: GET/POST/DELETE /api/alerts, PATCH bật tắt, GET /api/alerts/events.

Việc kiểm tra và gửi thông báo do tiến trình nền `python -m collector.alerts` làm, không phải server web,
nên đóng trình duyệt hay tắt server vẫn nhận được cảnh báo miễn là tiến trình nền còn chạy.
"""
from __future__ import annotations

import json
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from collector.alerts import describe
from common import appdb, store

router = APIRouter()


class AlertBody(BaseModel):
    symbol: str
    condition: dict
    message: str | None = None


class EnabledBody(BaseModel):
    enabled: bool


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_condition(c: dict) -> None:
    t = c.get("type")
    if t == "price":
        if c.get("op") not in (">=", "<=") or not _num(c.get("value")):
            raise HTTPException(422, 'price cần op ">=" hoặc "<=" và value là số')
    elif t == "cross":
        if not _num(c.get("level")) or c.get("dir", "any") not in ("up", "down", "any"):
            raise HTTPException(422, 'cross cần level là số và dir là "up", "down" hoặc "any"')
    elif t == "pine":
        if not isinstance(c.get("source"), str) or "alertcondition" not in c["source"]:
            raise HTTPException(422, "pine cần source có lời gọi alertcondition")
        if len(c["source"]) > 50_000:
            raise HTTPException(422, "script quá dài")
    else:
        raise HTTPException(422, 'type phải là "price", "cross" hoặc "pine"')


def _row(r) -> dict:
    c = json.loads(r[2])
    return {"id": r[0], "symbol": r[1], "condition": {k: v for k, v in c.items() if k != "source"}, "enabled": bool(r[3]),
            "created": r[4], "text": describe(r[1], c), "has_source": "source" in c}


@router.get("/api/alerts")
def list_alerts() -> list[dict]:
    appdb.init()
    con = appdb.connect()
    try:
        return [_row(r) for r in con.execute("SELECT id, symbol, condition, enabled, created FROM alerts ORDER BY id DESC")]
    finally:
        con.close()


@router.post("/api/alerts")
def create_alert(body: AlertBody) -> dict:
    sym = body.symbol.strip().upper()
    try:
        store.symbol_config(sym)
    except KeyError:
        raise HTTPException(404, f"symbol không có trong config: {sym}")
    _check_condition(body.condition)
    cond = dict(body.condition)
    if body.message:
        cond["message"] = body.message[:300]
    appdb.init()
    con = appdb.connect()
    try:
        cur = con.execute("INSERT INTO alerts(symbol, condition, enabled) VALUES (?, ?, 1)", (sym, json.dumps(cond)))
        con.commit()
        r = con.execute("SELECT id, symbol, condition, enabled, created FROM alerts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row(r)
    finally:
        con.close()


@router.patch("/api/alerts/{alert_id}")
def set_enabled(alert_id: int, body: EnabledBody) -> dict:
    appdb.init()
    con = appdb.connect()
    try:
        cur = con.execute("UPDATE alerts SET enabled = ? WHERE id = ?", (int(body.enabled), alert_id))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "không có cảnh báo này")
        return {"id": alert_id, "enabled": body.enabled}
    finally:
        con.close()


@router.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: int) -> dict:
    appdb.init()
    con = appdb.connect()
    try:
        cur = con.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "không có cảnh báo này")
        return {"deleted": alert_id}
    finally:
        con.close()


@router.get("/api/alerts/events")
def events(limit: int = 50) -> list[dict]:
    appdb.init()
    con = appdb.connect()
    try:
        return [{"id": r[0], "alert_id": r[1], "ts": r[2], "symbol": r[3], "message": r[4], "sent": r[5]}
                for r in con.execute("SELECT id, alert_id, ts, symbol, message, sent FROM alert_events ORDER BY id DESC LIMIT ?",
                                     (max(1, min(limit, 500)),))]
    finally:
        con.close()
