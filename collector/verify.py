"""So khớp nến dựng từ tick với kline của Binance (nghiệm thu Phase 1).

Chạy:  python -m collector.verify --symbol BTCUSDT --days 3

So các nến 1 phút đã đóng có ở cả hai phía:
- Tổng volume và tổng khối lượng mua chủ động (buy_v so với taker buy base volume của kline)
  phải khớp dưới 0,1%.
- Chiều mua/bán: tổng buy_v dựng từ tick phải gần taker buy của kline hơn là gần sell của kline.
  Phép này chứng minh cờ isBuyerMaker được đọc đúng chiều.

Vì sao không so từng nến: Binance gộp các lệnh cùng giá trong 100ms thành một aggTrade và gán
thời điểm của lệnh đầu tiên, còn kline xếp từng lệnh riêng theo thời điểm của nó. Một aggTrade vắt
qua ranh giới phút làm khối lượng chuyển từ nến này sang nến kế, nên chênh lệch từng nến đi theo
cặp bù trừ nhau (ví dụ +55,8 BTC rồi -55,8 BTC) và tổng thì khớp. Báo cáo vẫn in lệch lớn nhất theo
nến 1 phút và theo giờ để thấy mức độ. Giá mở/đóng của nến sát ranh giới cũng bị ảnh hưởng.
"""
from __future__ import annotations

import argparse

from common import bars, store

TOL = 1e-3  # 0,1%
HOUR_MS = 3_600_000


def _hourly(rows: dict[int, tuple]) -> dict[int, list[float]]:
    out: dict[int, list[float]] = {}
    for ts, r in rows.items():
        h = ts // HOUR_MS * HOUR_MS
        acc = out.setdefault(h, [0.0, 0.0])
        acc[0] += r[5]
        acc[1] += r[6]
    return out


def compare(symbol: str, start_ms: int | None = None, end_ms: int | None = None) -> dict:
    ref = {r[0]: r for r in store.read("bars", symbol, start_ms, end_ms)}
    mine = {r[0]: r for r in bars.bars_from_ticks(symbol, "1m", start_ms, end_ms)}
    common = sorted(set(ref) & set(mine))
    if not common:
        raise RuntimeError("không có nến chung giữa kline và nến dựng từ tick")
    ref_c = {t: ref[t] for t in common}
    mine_c = {t: mine[t] for t in common}
    tot_ref = sum(r[5] for r in ref_c.values())
    tot_mine = sum(r[5] for r in mine_c.values())
    buy_ref = sum(r[6] for r in ref_c.values())
    buy_mine = sum(r[6] for r in mine_c.values())
    sell_ref = sum(r[7] for r in ref_c.values())

    worst_minute = max(abs(mine_c[t][5] - ref_c[t][5]) / max(ref_c[t][5], 1e-9) for t in common)
    hm, hr = _hourly(mine_c), _hourly(ref_c)
    worst_hour = max(abs(hm[h][0] - hr[h][0]) / max(hr[h][0], 1e-9) for h in hr)
    ohlc_bad = sum(1 for t in common if ref_c[t][1:5] != mine_c[t][1:5])
    return {
        "bars_compared": len(common),
        "only_in_klines": len(set(ref) - set(mine)),
        "only_in_ticks": len(set(mine) - set(ref)),
        "total_volume_rel_err": abs(tot_mine - tot_ref) / tot_ref,
        "buy_volume_rel_err": abs(buy_mine - buy_ref) / max(buy_ref, 1e-9),
        "buy_closer_to_taker_buy_than_sell": abs(buy_mine - buy_ref) < abs(buy_mine - sell_ref),
        "worst_minute_volume_rel_err": worst_minute,
        "worst_hour_volume_rel_err": worst_hour,
        "ohlc_mismatch_bars": ohlc_bad,
    }


def passes(r: dict, tol: float = TOL) -> bool:
    return (
        r["total_volume_rel_err"] < tol
        and r["buy_volume_rel_err"] < tol
        and r["buy_closer_to_taker_buy_than_sell"]
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=3, help="số ngày gần nhất có cả tick và kline")
    a = ap.parse_args()
    ticks = store.read("ticks", a.symbol, columns=["ts"])
    if not ticks:
        raise SystemExit("chưa có tick. Chạy collector.backfill trước.")
    end = ticks[-1][0] // 60_000 * 60_000  # bỏ nến cuối có thể thiếu
    start = max(ticks[0][0], end - a.days * 86_400_000)
    start = -(-start // 60_000) * 60_000  # làm tròn lên đầu phút
    r = compare(a.symbol, start, end)
    for k, v in r.items():
        print(f"{k:36s} {v:.3e}" if isinstance(v, float) else f"{k:36s} {v}")
    print("ĐẠT" if passes(r) else "KHÔNG ĐẠT")
    raise SystemExit(0 if passes(r) else 1)


if __name__ == "__main__":
    main()
