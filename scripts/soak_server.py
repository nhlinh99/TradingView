"""Chạy thử dài hơi để xem server có phình bộ nhớ theo thời gian không.

Gọi luân phiên các yêu cầu giống giao diện (nến, footprint, heatmap, bong bóng, profile, GEX, Pine, nối và ngắt WebSocket) rồi lấy mẫu
`private_mb` từ /health mỗi phút. Kết thúc in bảng và hệ số tăng (MB mỗi giờ, hồi quy tuyến tính trên nửa sau của phiên, để bỏ qua giai đoạn khởi động).

Dùng:  python scripts/soak_server.py --minutes 360 --url http://127.0.0.1:8000
Mã thoát 0 nếu tăng dưới --max-growth (mặc định 100 MB mỗi giờ), 2 nếu vượt, 3 nếu server không trả private_mb.
Server cần là bản có `server/memguard.py`. Ghi CSV vào --csv nếu có.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
H = 3_600_000


def requests_for(now_ms: int, src: dict[str, str]) -> list[tuple[str, str, str, dict | None]]:
    sym = ["BTCUSDT", "XAUUSDT"]
    out: list[tuple[str, str, str, dict | None]] = []
    for s in sym:
        for tf in ("1m", "5m", "15m", "1h", "1d", "1w"):
            out.append(("bars", "GET", f"/api/bars?symbol={s}&tf={tf}&limit=1000", None))
        out.append(("footprint", "GET", f"/api/footprint?symbol={s}&tf=5m&limit=200", None))
        out.append(("heatmap", "GET", f"/api/heatmap?symbol={s}&from={now_ms - 2 * H}&to={now_ms}&tbucket=60000", None))
        out.append(("bubbles", "GET", f"/api/bubbles?symbol={s}&from={now_ms - 2 * H}&to={now_ms}&tbucket=10000&top=300", None))
        out.append(("profile", "GET", f"/api/profile?symbol={s}&from={now_ms - 24 * H}&to={now_ms}", None))
    out.append(("gex", "GET", "/api/gex", None))
    for name, code in src.items():
        out.append((f"pine {name}", "POST", "/api/pine/run", {"source": code, "symbol": "BTCUSDT", "tf": random.choice(["5m", "15m"]), "limit": 1000, "inputs": {}}))
    return out


async def ws_cycle(base: str) -> None:
    import websockets
    url = base.replace("http", "ws", 1) + "/api/stream"
    try:
        async with websockets.connect(url, open_timeout=5) as w:
            await w.send('{"op": "subscribe", "symbol": "BTCUSDT"}')
            await asyncio.sleep(random.uniform(0.2, 1.5))
    except Exception:  # noqa: BLE001 - lỗi nối không phải mục tiêu của bài thử này
        pass


def slope_mb_per_hour(samples: list[tuple[float, int]]) -> float:
    pts = samples[len(samples) // 2:] if len(samples) >= 6 else samples
    if len(pts) < 2:
        return 0.0
    n = len(pts)
    mx = sum(t for t, _ in pts) / n
    my = sum(v for _, v in pts) / n
    den = sum((t - mx) ** 2 for t, _ in pts)
    return 0.0 if den == 0 else sum((t - mx) * (v - my) for t, v in pts) / den * 3600


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--sample-s", type=float, default=60)
    ap.add_argument("--max-growth", type=float, default=100.0, help="MB mỗi giờ")
    ap.add_argument("--csv")
    a = ap.parse_args()
    src = {p.stem: p.read_text(encoding="utf-8") for p in (ROOT / "pine" / "examples").glob("*.pine")
           if p.stem in ("ichimoku_future", "instituitional_level_indicator", "viprasol_liq_trail", "volume_profile_total")}
    c = httpx.Client(base_url=a.url, timeout=240)
    t0 = time.time()
    end = t0 + a.minutes * 60
    next_sample = t0
    samples: list[tuple[float, int]] = []
    rows: list[str] = ["giây,private_mb,luồng,yêu_cầu,lỗi"]
    n_req = n_err = 0
    print(f"{'phút':>6} {'Priv MB':>8} {'luồng':>6} {'yêu cầu':>8} {'lỗi':>5}")
    while time.time() < end:
        now_ms = int(time.time() * 1000)
        name, method, url, body = random.choice(requests_for(now_ms, src))
        try:
            r = c.get(url) if method == "GET" else c.post(url, json=body)
            n_req += 1
            if r.status_code >= 500 and r.status_code != 503:
                n_err += 1
        except Exception:  # noqa: BLE001
            n_err += 1
        if random.random() < 0.1:
            asyncio.run(ws_cycle(a.url))
        if time.time() >= next_sample:
            next_sample += a.sample_s
            h = c.get("/health").json()
            mb = h.get("private_mb")
            if mb is None:
                print("server không trả private_mb: cần bản có memguard", file=sys.stderr)
                return 3
            t = time.time() - t0
            samples.append((t, int(mb)))
            rows.append(f"{t:.0f},{mb},{h.get('threads')},{n_req},{n_err}")
            print(f"{t / 60:>6.1f} {mb:>8} {h.get('threads'):>6} {n_req:>8} {n_err:>5}", flush=True)
        time.sleep(random.uniform(0.05, 0.4))
    g = slope_mb_per_hour(samples)
    peak = max(v for _, v in samples) if samples else 0
    print(f"\nđỉnh {peak} MB; tăng {g:+.1f} MB mỗi giờ (nửa sau của phiên); {n_req} yêu cầu, {n_err} lỗi 5xx")
    if a.csv:
        Path(a.csv).write_text("\n".join(rows), encoding="utf-8")
    return 0 if g <= a.max_growth else 2


if __name__ == "__main__":
    raise SystemExit(main())
