"""Giới hạn yêu cầu nặng, trần DuckDB cho đường ghi, và báo cáo chẩn đoán bộ nhớ."""
import threading
import time

import pytest
from fastapi import HTTPException

from common import store
from server import limits, memguard


def test_heavy_chi_cho_toi_da_n_yeu_cau_cung_luc(monkeypatch):
    monkeypatch.setattr(limits, "_sem", threading.BoundedSemaphore(2))
    monkeypatch.setattr(limits, "_peak", 0)
    running = 0
    peak = 0
    lock = threading.Lock()

    def work():
        nonlocal running, peak
        with limits.heavy():
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with lock:
                running -= 1

    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak == 2
    assert limits.stats()["heavy_peak"] == 2
    assert limits.stats()["heavy_active"] == 0


def test_heavy_qua_thoi_gian_cho_thi_tra_503(monkeypatch):
    monkeypatch.setattr(limits, "_sem", threading.BoundedSemaphore(1))
    monkeypatch.setattr(limits, "WAIT_S", 0.05)
    with limits.heavy():
        with pytest.raises(HTTPException) as e:
            with limits.heavy():
                pass
    assert e.value.status_code == 503 and e.value.headers["Retry-After"] == "5"
    with limits.heavy():          # nhả lượt rồi thì vào lại được
        pass


def test_heavy_nha_luot_khi_loi(monkeypatch):
    monkeypatch.setattr(limits, "_sem", threading.BoundedSemaphore(1))
    with pytest.raises(ValueError):
        with limits.heavy():
            raise ValueError("x")
    assert limits.stats()["heavy_active"] == 0
    with limits.heavy():
        pass


def test_work_conn_co_tran_rieng(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))
    monkeypatch.setenv("DUCKDB_WORK_MEMORY_LIMIT", "256MB")
    monkeypatch.setenv("DUCKDB_WORK_THREADS", "1")
    a, b = store.work_conn(), store.work_conn()
    try:
        assert a.execute("SELECT current_setting('threads')").fetchall()[0][0] == 1
        num, unit = a.execute("SELECT current_setting('memory_limit')").fetchall()[0][0].split()
        assert unit == "MiB" and 200 < float(num) < 300          # 256MB, DuckDB báo theo MiB
        a.execute("CREATE TABLE t (x INT)")          # instance riêng: cùng tên bảng không va nhau
        b.execute("CREATE TABLE t (x INT)")
    finally:
        a.close()
        b.close()
    assert (tmp_path / "tv-data" / "tmp").is_dir()


def test_diag_report_co_cac_phan_can_thiet():
    out = memguard.diag_report(top=3)
    assert "BÁO CÁO CHẨN ĐOÁN" in out
    assert "đối tượng Python nhiều nhất" in out and "luồng theo loại" in out


def test_snapshot_co_thong_so_limits():
    snap = memguard.snapshot()
    assert {"heavy_active", "heavy_peak", "heavy_max", "diag"} <= set(snap)
