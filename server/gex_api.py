"""GET /api/gex: GEX của BTC từ snapshot quyền chọn Deribit mới nhất (hoặc snapshot ngay trước `ts`).

Trả về GEX từng strike (đô-la mỗi 1% giá), tổng, gamma flip, call wall và put wall.
`oi_note` nhắc rằng open interest của Deribit cập nhật trễ, nên GEX phản ánh vị thế cũ hơn giá hiện tại.
"""
from __future__ import annotations

import time

import duckdb
from fastapi import APIRouter, HTTPException, Query

from common import gex, store

router = APIRouter()

SYMBOL = "BTCUSDT"
LOOKBACK_MS = 3 * 86_400_000
OI_NOTE = "OI của Deribit cập nhật trễ (khoảng 8 giờ); GEX tính theo OI này, không phải vị thế tức thời."


def get_gex(ts: int | None, band: float) -> dict:
    end = (ts if ts is not None else int(time.time() * 1000)) + 1
    sql = store.range_select("options", SYMBOL, end - LOOKBACK_MS, end)
    if not sql:
        raise HTTPException(404, "chưa có snapshot quyền chọn; chạy python -m collector.deribit")
    con = store.query_conn()
    try:
        snap = con.execute(f"SELECT max(ts) FROM ({sql})").fetchone()[0]
        if snap is None:
            raise HTTPException(404, "chưa có snapshot quyền chọn trong 3 ngày qua")
        data = con.execute(
            f"SELECT expiry, strike, cp, oi, iv, fwd, spot FROM ({sql}) WHERE ts = {int(snap)}"
        ).fetchall()
    finally:
        con.close()
    spot = float(data[0][6])
    options: list[gex.Option] = [(e, k, bool(cp), float(oi), float(iv), float(fwd)) for e, k, cp, oi, iv, fwd, _s in data]
    lv = gex.levels(options, int(snap), spot)
    lo, hi = spot * (1 - band), spot * (1 + band)
    return {
        "symbol": SYMBOL, "ts": int(snap), "spot": spot, "total": round(lv["total"], 2), "flip": lv["flip"],
        "call_wall": lv["call_wall"], "put_wall": lv["put_wall"],
        "by_strike": [r for r in lv["by_strike"] if lo <= r["strike"] <= hi],
        "age_s": round((time.time() * 1000 - snap) / 1000), "oi_note": OI_NOTE,
    }


@router.get("/api/gex")
def gex_endpoint(
    ts: int | None = Query(None, description="ms; lấy snapshot ngay trước thời điểm này"),
    band: float = Query(0.3, gt=0, le=1, description="chỉ trả các strike trong spot x (1 +- band)"),
) -> dict:
    return get_gex(ts, band)
