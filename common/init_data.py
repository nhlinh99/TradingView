"""Tạo cây thư mục dữ liệu và app.sqlite. Chạy: python -m common.init_data"""
from __future__ import annotations

from . import appdb, store

SUBDIRS = ("ticks", "bars", "book", "options", "vn_book", "cache")


def main() -> None:
    root = store.data_dir()
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    db = appdb.init()
    print(f"DATA_DIR = {root}")
    print(f"thư mục: {', '.join(SUBDIRS)}")
    print(f"sqlite:  {db}")


if __name__ == "__main__":
    main()
