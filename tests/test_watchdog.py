"""Cảnh báo khi collector im lặng hơn 5 phút."""
import os
from datetime import datetime, timezone

import pytest

from collector import watchdog
from collector.watchdog import Watchdog

NOW = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))
    return tmp_path / "tv-data"


def touch(root, kind, sym, name, age_s):
    d = root / kind / sym
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_bytes(b"x")
    os.utime(f, (NOW - age_s, NOW - age_s))


# ---------- logic thuần ----------

def test_im_lang_bao_mot_lan_roi_nhac_va_phuc_hoi():
    dog = Watchdog(silence_s=300, remind_s=1800)
    key = ("ticks", "BTCUSDT")
    assert dog.evaluate({key: NOW - 60}, NOW) == []                      # ghi gần đây: yên
    m1 = dog.evaluate({key: NOW - 400}, NOW)                              # 6 phút 40 giây
    assert len(m1) == 1 and "im lặng" in m1[0] and "ticks BTCUSDT" in m1[0] and "6 phút" in m1[0]
    assert dog.evaluate({key: NOW - 460}, NOW + 60) == []                 # vẫn im, chưa tới lúc nhắc
    m2 = dog.evaluate({key: NOW - 2300}, NOW + 1900)                      # sau 31 phút: nhắc
    assert len(m2) == 1 and "Vẫn im lặng" in m2[0]
    m3 = dog.evaluate({key: NOW + 1900 - 5}, NOW + 1900 + 30)             # ghi lại: báo phục hồi một lần
    assert len(m3) == 1 and "Đã phục hồi" in m3[0]
    assert dog.evaluate({key: NOW + 1900 + 20}, NOW + 1900 + 60) == []


def test_ranh_gioi_dung_5_phut_chua_bao():
    dog = Watchdog(silence_s=300)
    assert dog.evaluate({("book", "XAUUSDT"): NOW - 300}, NOW) == []
    assert len(dog.evaluate({("book", "XAUUSDT"): NOW - 301}, NOW)) == 1


def test_khong_co_file_hom_nay_thi_bao_tu_dau_ngay():
    dog = Watchdog()
    m = dog.evaluate({("ticks", "BTCUSDT"): None}, NOW)
    assert len(m) == 1 and "từ đầu ngày" in m[0]


def test_hai_cap_doc_lap():
    dog = Watchdog()
    m = dog.evaluate({("ticks", "BTCUSDT"): NOW - 10, ("book", "BTCUSDT"): NOW - 900}, NOW)
    assert len(m) == 1 and "book BTCUSDT" in m[0]


# ---------- đọc mốc ghi cuối trên đĩa ----------

def test_last_write_dung_file_con_moi_nhat_va_bo_qua_file_da_gop(root):
    touch(root, "ticks", "BTCUSDT", "date=2026-11-15.p100.parquet", 900)
    touch(root, "ticks", "BTCUSDT", "date=2026-11-15.p200.parquet", 100)
    touch(root, "ticks", "BTCUSDT", "date=2026-11-15.parquet", 5)            # hotmerge vừa gộp: không tính là collector còn sống
    t, recent = watchdog.last_write("ticks", "BTCUSDT", NOW)
    assert recent and t == NOW - 100


def test_last_write_chi_co_file_chuan_thi_dung_file_chuan(root):
    touch(root, "ticks", "BTCUSDT", "date=2026-11-15.parquet", 1000)
    t, recent = watchdog.last_write("ticks", "BTCUSDT", NOW)
    assert recent and t == NOW - 1000


def test_last_write_bo_qua_file_tmp_va_ngay_cu(root):
    touch(root, "book", "BTCUSDT", "date=2026-11-15.p9.parquet.tmp", 1)
    touch(root, "book", "BTCUSDT", "date=2026-11-01.p9.parquet", 1)         # 14 ngày trước: ngoài 7 ngày
    t, recent = watchdog.last_write("book", "BTCUSDT", NOW)
    assert t is None and not recent


def test_targets_bo_qua_cap_khong_con_ghi(root):
    touch(root, "ticks", "BTCUSDT", "date=2026-11-15.p1.parquet", 30)
    touch(root, "book", "BTCUSDT", "date=2026-11-12.p1.parquet", 90000)     # có trong 7 ngày nhưng không có file hôm nay/hôm qua
    out = watchdog.targets(NOW, ["BTCUSDT", "XAUUSDT"])
    assert out == {("ticks", "BTCUSDT"): NOW - 30, ("book", "BTCUSDT"): None}   # book từng ghi nhưng giờ im; XAUUSDT chưa từng có


def test_run_once_gui_tin_va_khong_sap_khi_loi_doc_dia():
    sent: list[str] = []
    dog = Watchdog()
    msgs = watchdog.run_once(dog, lambda m: sent.append(m) or "desktop", NOW, target_fn=lambda n: {("ticks", "BTCUSDT"): NOW - 1000})
    assert sent == msgs and len(sent) == 1

    def boom(_):
        raise OSError("ổ đĩa lỗi")

    assert watchdog.run_once(dog, lambda m: sent.append(m), NOW, target_fn=boom) == []
    assert len(sent) == 1
