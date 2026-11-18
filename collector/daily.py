"""Job hằng ngày: giữ dữ liệu cập nhật và sửa các khoảng thiếu. Đăng ký bằng Task Scheduler (xem README).

Chạy:  python -m collector.daily [--symbols BTCUSDT,XAUUSDT] [--backfill-days 3] [--skip-compact]

Với mỗi symbol, theo thứ tự:
  1. klines.sync        nến 1 phút đã đóng (kho `bars`, nguồn chuẩn của nến 1 phút). Không có bước này,
                        `bars` dừng ở lần chạy tay cuối cùng.
  2. backfill           aggTrades, bookDepth, metrics của vài ngày gần nhất (đến hôm qua theo UTC), từ kho
                        data.binance.vision. Đây là chỗ sửa mọi khoảng thiếu của collector trực tiếp (máy
                        tắt, khoảng hở bị bỏ qua hoặc lấp hỏng). File đủ ngày được ghi làm file chuẩn;
                        bước gộp sau đó loại trùng với các file con của collector. File chưa công bố
                        ("missing") sẽ được thử lại ở đêm sau. Ngày đã tải được ghi nhật ký nên không tải lại.
  3. compact            gộp file con, gom tick cũ thành footprint, áp dụng giữ dữ liệu.

Thứ tự này an toàn: backfill ghi trọn ngày, rồi gộp mới loại trùng với dữ liệu trực tiếp.
Mỗi bước bọc riêng: một bước lỗi không chặn các bước khác. Mã thoát khác 0 nếu có bước lỗi.
"""
from __future__ import annotations

import argparse
import logging
import tomllib
from datetime import datetime, timedelta, timezone

from collector import backfill, compact, klines, tvc, vn
from common import store

log = logging.getLogger("collector.daily")

BACKFILL_DATASETS = ("aggTrades", "bookDepth", "metrics")


def configured_symbols() -> list[str]:
    with open(store.ROOT / "config" / "symbols.toml", "rb") as f:
        return list(tomllib.load(f))


def run(symbols: list[str], backfill_days: int = 3, do_compact: bool = True, vn_bars: bool = False) -> dict:
    """Trả về {"failures": [...], "steps": [(bước, symbol, kết quả)]}."""
    report: dict = {"failures": [], "steps": []}
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = yesterday - timedelta(days=backfill_days - 1)

    def step(name: str, symbol: str, fn):
        try:
            result = fn()
            log.info("%s %s: %s", name, symbol, result)
            report["steps"].append((name, symbol, result))
        except Exception as e:  # noqa: BLE001 - cố ý bắt rộng: mỗi bước độc lập
            log.exception("%s %s lỗi", name, symbol)
            report["failures"].append(f"{name} {symbol}: {type(e).__name__}: {e}")

    for symbol in symbols:
        if store.symbol_config(symbol).get("market") == "tvc":   # vàng TVC: chỉ nến 1 phút, không tick, không compact
            step("tvc-bars", symbol, lambda: tvc.sync())
            for tf in tvc.COARSE:
                step(f"tvc-{tf}", symbol, lambda t=tf: tvc.sync_coarse(t))
            continue
        step("klines", symbol, lambda s=symbol: klines.sync(s))
        for dataset in BACKFILL_DATASETS:
            step(f"backfill-{dataset}", symbol,
                 lambda s=symbol, d=dataset: {k: v for k, v in backfill.backfill(s, d, start, yesterday).items() if k != "days"})
    if vn_bars:
        with vn.make_client() as client:
            for symbol in store.vn100_symbols():
                step("vn-bars", symbol, lambda s=symbol: vn.sync_bars(client, s))
                step("vn-daily", symbol, lambda s=symbol: vn.sync_daily(client, s))
    if do_compact:
        step("compact", "*", lambda: compact.compact_all())
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", help="phân tách bằng dấu phẩy. Mặc định: mọi symbol trong config/symbols.toml")
    ap.add_argument("--backfill-days", type=int, default=3)
    ap.add_argument("--skip-compact", action="store_true")
    ap.add_argument("--vn", action="store_true", help="nạp thêm nến 1 phút của VN100 (cần config/vn100.json)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    symbols = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else configured_symbols()
    report = run(symbols, a.backfill_days, not a.skip_compact, a.vn)
    if report["failures"]:
        log.error("có %d bước lỗi:\n  %s", len(report["failures"]), "\n  ".join(report["failures"]))
        raise SystemExit(1)
    log.info("xong, %d bước", len(report["steps"]))


if __name__ == "__main__":
    main()
