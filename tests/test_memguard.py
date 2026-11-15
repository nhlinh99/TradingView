"""Instance DuckDB dùng chung (có trần) và bộ giám sát bộ nhớ của server."""
import sys

import pytest

from common import store
from server import memguard


def test_query_conn_dung_chung_instance_co_tran():
    a, b = store.query_conn(), store.query_conn()
    try:
        limit, threads = a.execute("SELECT current_setting('memory_limit'), current_setting('threads')").fetchall()[0]
        assert threads == 4
        assert limit.endswith("GiB") or limit.endswith("MiB")
        # cùng một instance: bảng thường thấy được ở cả hai con trỏ; bảng tạm thì riêng
        a.execute("CREATE TEMP TABLE t_riêng (x INTEGER)")
        a.execute("INSERT INTO t_riêng VALUES (1)")
        with pytest.raises(Exception):
            b.execute("SELECT * FROM t_riêng")
    finally:
        a.close()
    # đóng một con trỏ không làm hỏng con trỏ khác
    assert b.execute("SELECT 41 + 1").fetchall() == [(42,)]
    b.close()


def test_query_conn_nhieu_luong():
    import threading

    out: list[int] = []

    def work(n: int) -> None:
        c = store.query_conn()
        try:
            c.execute("CREATE TEMP TABLE tail (v INTEGER)")
            c.executemany("INSERT INTO tail VALUES (?)", [(i,) for i in range(n)])
            out.append(c.execute("SELECT count(*) FROM tail").fetchall()[0][0])
        finally:
            c.close()

    ts = [threading.Thread(target=work, args=(100 + i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == [100 + i for i in range(8)]


@pytest.mark.skipif(sys.platform != "win32", reason="chỉ đo bộ nhớ cam kết trên Windows")
def test_private_mb_la_so_duong():
    mb = memguard.private_mb()
    assert mb is not None and 10 < mb < 100_000


def test_snapshot_va_dem_yeu_cau():
    memguard.hits.clear()
    memguard.note_request("/api/bars", 0.4)
    memguard.note_request("/api/bars", 1.2)
    assert memguard.hits["/api/bars"] == 2
    assert memguard.slow["/api/bars"] == 1.2
    snap = memguard.snapshot()
    assert {"private_mb", "threads", "limit_mb"} <= set(snap)
    memguard.hits.clear()
    memguard.slow.clear()
