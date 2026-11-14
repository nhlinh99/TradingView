"""Vòng lặp nền gộp file con của ngày đang chạy mỗi 30 phút (xem compact.merge_hot). Chạy:  python -m collector.hotmerge"""
from __future__ import annotations

import logging
import time

from collector import compact

log = logging.getLogger("collector.hotmerge")
INTERVAL_S = 30 * 60


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    while True:
        try:
            n = compact.merge_hot()
            if n:
                log.info("đã gộp %d file con", n)
        except Exception:  # noqa: BLE001 - lỗi một lượt không được làm chết vòng lặp
            log.exception("gộp nóng lỗi; thử lại ở lượt sau")
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
