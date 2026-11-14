"""POST /api/pine/run: chạy script Pine trên nến của một symbol; GET /api/pine/examples: 5 script mẫu.

Nến lấy từ cùng nguồn với /api/bars (kho Parquet cộng đuôi trực tiếp). `request.security` đọc nến của symbol hoặc
khung khác qua cùng hàm đó. Tên symbol dạng "BINANCE:BTCUSDT" hoặc "COMEX:GC1!" được bỏ tiền tố sàn; symbol không có dữ liệu
trong kho thì báo lỗi rõ ràng thay vì trả số liệu giả.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from common import store
from pine import runner
from pine.interp import Bars, PineRuntimeError, tf_to_ms
from pine.lexer import PineSyntaxError
from . import bars_api

router = APIRouter()

EXAMPLES = Path(__file__).resolve().parent.parent / "pine" / "examples"
MAX_BARS = 5000
VN_TZ_MS = 7 * 3_600_000


class RunBody(BaseModel):
    source: str
    symbol: str
    tf: str = "1m"
    limit: int = 1000
    inputs: dict = {}


def _norm_tf(tf: str) -> str:
    """Pine "60" hoặc "D" -> kiểu của /api/bars ("1h", "1d")."""
    ms = tf_to_ms(tf)
    for unit, size in (("d", 86_400_000), ("h", 3_600_000), ("m", 60_000)):
        if ms % size == 0:
            return f"{ms // size}{unit}"
    raise PineRuntimeError(f"timeframe không hỗ trợ: {tf}")


def load_bars(symbol: str, tf: str, limit: int, to_ms: int | None = None) -> Bars | None:
    sym = symbol.split(":")[-1].upper()
    try:
        store.symbol_config(sym)
    except KeyError:
        return None
    j = bars_api.get_bars(sym, _norm_tf(tf), None, to_ms, min(limit, MAX_BARS))
    rows = j["bars"]
    if not rows and to_ms is None:
        # collector tắt hoặc thị trường nghỉ lâu: dùng đoạn nến cuối cùng đang có thay vì trả rỗng
        from collector import vn as _last
        last = _last.last_bar_ts(sym)
        if last is not None:
            rows = bars_api.get_bars(sym, _norm_tf(tf), None, last + 1, min(limit, MAX_BARS))["bars"]
    if not rows:
        return None
    return Bars(time=[r[0] for r in rows], open=[r[1] for r in rows], high=[r[2] for r in rows], low=[r[3] for r in rows],
                close=[r[4] for r in rows], volume=[r[5] for r in rows], buy=[r[6] for r in rows], sell=[r[7] for r in rows])


def gex_levels() -> dict | None:
    try:
        from . import gex_api
        g = gex_api.get_gex(None, 0.3)
        return {"flip": g["flip"], "call_wall": g["call_wall"], "put_wall": g["put_wall"]}
    except Exception:  # noqa: BLE001 - không có snapshot thì request.external("gex_levels") trả NaN
        return None


def run_pine(body: RunBody) -> dict:
    sym = body.symbol.split(":")[-1].upper()
    try:
        cfg = store.symbol_config(sym)
    except KeyError:
        raise HTTPException(404, f"symbol không có trong config: {body.symbol}")
    try:
        bars = load_bars(sym, body.tf, body.limit)
        if bars is None:
            raise HTTPException(404, f"chưa có nến cho {sym} {body.tf}")
        is_vn = cfg.get("market") == "vn"
        # nến của symbol khác phải kết thúc không muộn hơn nến cuối của biểu đồ (không đưa dữ liệu tương lai vào)
        end = bars.time[-1] + tf_to_ms(body.tf)

        def provider(s: str, tf: str):
            return load_bars(s, tf, MAX_BARS, end)

        out = runner.run_script(
            body.source, bars, symbol=sym, tf=body.tf, tz_offset_ms=VN_TZ_MS if is_vn else 0, provider=provider,
            inputs=body.inputs, external={"gex_levels": gex_levels()} if "gex_levels" in body.source else None,
            syminfo_type="stock" if is_vn else ("cfd" if sym.startswith("XAU") else "crypto"))
    except PineSyntaxError as e:
        raise HTTPException(400, {"kind": "syntax", "message": str(e), "line": e.line})
    except PineRuntimeError as e:
        raise HTTPException(400, {"kind": "runtime", "message": str(e), "line": e.line})
    return {"symbol": sym, "tf": body.tf, **out}


@router.post("/api/pine/run")
def pine_run(body: RunBody) -> dict:
    return run_pine(body)


@router.get("/api/pine/examples")
def pine_examples() -> list[dict]:
    return [{"name": p.stem, "source": p.read_text(encoding="utf-8")} for p in sorted(EXAMPLES.glob("*.pine"))]
