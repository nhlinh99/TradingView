"""Danh sách symbol và watchlist (lưu trong SQLite).

GET /api/symbols     mọi symbol trong config/symbols.toml kèm tick size
GET /api/watchlist   danh sách theo dõi theo thứ tự. Lần đầu tự khởi tạo bằng mọi symbol trong config
PUT /api/watchlist   thay cả danh sách (và thứ tự). Chỉ nhận symbol có trong config
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from common import appdb, store

router = APIRouter()


class WatchlistBody(BaseModel):
    symbols: list[str]


def seed_symbols() -> list[str]:
    """Watchlist ban đầu: các mã khai trong symbols.toml. Mã VN100 thêm tay từ danh sách."""
    return [s for s, c in configured().items() if c.get("market") != "vn"]


def configured() -> dict[str, dict]:
    return store._load_symbols()   # symbols.toml cộng các mã trong vn100.json


def _read(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT symbol FROM watchlist ORDER BY position, symbol")]


@router.get("/api/symbols")
def symbols() -> list[dict]:
    return [{"symbol": s, "tick": c["tick"], "source": c.get("source")} for s, c in configured().items()]


@router.get("/api/watchlist")
def get_watchlist() -> dict:
    appdb.init()
    con = appdb.connect()
    try:
        syms = _read(con)
        if not syms:  # lần đầu: bắt đầu bằng mọi symbol đã cấu hình
            con.executemany("INSERT INTO watchlist(symbol, position) VALUES (?, ?)",
                            [(s, i) for i, s in enumerate(seed_symbols())])
            con.commit()
            syms = _read(con)
        return {"symbols": syms}
    finally:
        con.close()


@router.put("/api/watchlist")
def put_watchlist(body: WatchlistBody) -> dict:
    known = configured()
    seen: list[str] = []
    for s in body.symbols:
        s = s.strip().upper()
        if s not in known:
            raise HTTPException(422, f"symbol không có trong config/symbols.toml: {s}")
        if s not in seen:
            seen.append(s)
    appdb.init()
    con = appdb.connect()
    try:
        con.execute("DELETE FROM watchlist")
        con.executemany("INSERT INTO watchlist(symbol, position) VALUES (?, ?)", [(s, i) for i, s in enumerate(seen)])
        con.commit()
    finally:
        con.close()
    return {"symbols": seen}
