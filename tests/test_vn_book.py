import json
from datetime import datetime, timezone

import pytest

from collector import vn_book
from common import store


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))
    f = tmp_path / "vn100.json"
    f.write_text(json.dumps({"symbols": ["VNM", "FPT"]}), encoding="utf-8")
    monkeypatch.setattr(store, "VN100_FILE", f)
    monkeypatch.setattr(store, "_symbols_cache", None)


def rec(sym, bid=53600, tv=1000, bu=300, sd=200, **kw):
    n = bid if isinstance(bid, int) else 0
    d = {"stockSymbol": sym, "best1Bid": bid, "best1BidVol": 100, "best2Bid": n - 100, "best2BidVol": 200,
         "best3Bid": n - 200, "best3BidVol": 300, "best1Offer": n + 100, "best1OfferVol": 50,
         "best2Offer": n + 200, "best2OfferVol": 60, "best3Offer": n + 300, "best3OfferVol": 70,
         "matchedPrice": n, "nmTotalTradedQty": tv, "stockBUVol": bu, "stockSDVol": sd}
    d.update(kw)
    return d


def test_session_window():
    def at(h, m, day=12):  # 2026-11-12 là thứ Năm; giờ Việt Nam
        return datetime(2026, 11, day, h - 7, m, tzinfo=timezone.utc) if h >= 7 else datetime(2026, 11, day, h + 17, m, tzinfo=timezone.utc)
    assert vn_book.in_session(at(9, 30)) and vn_book.in_session(at(14, 45)) and vn_book.in_session(at(15, 5))
    assert not vn_book.in_session(at(8, 54)) and not vn_book.in_session(at(15, 6))
    assert not vn_book.in_session(at(10, 0, day=14))   # thứ Bảy
    assert not vn_book.in_session(at(10, 0, day=15))   # Chủ nhật


def test_only_changes_are_recorded_and_flushed(data_root):
    r = vn_book.Recorder()
    t0 = int(datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert r.feed([rec("VNM"), rec("FPT", bid=120000)], t0) == 2
    assert r.feed([rec("VNM"), rec("FPT", bid=120000)], t0 + 10_000) == 0          # không đổi
    assert r.feed([rec("VNM", tv=1500, bu=500), rec("FPT", bid=120000)], t0 + 20_000) == 1
    assert r.feed([rec("VNM", bid="ATO", tv=1500, bu=500)], t0 + 30_000) == 1       # giá chữ: ghi 0
    assert r.flush() == 3 + 1
    vnm = store.read("vn_book", "VNM")
    assert [x[0] for x in vnm] == [t0, t0 + 20_000, t0 + 30_000]
    assert vnm[0][1:4] == (53600, 100, 53500) and vnm[1][14:17] == (1500, 500, 200)   # tv, bu, sd
    assert vnm[2][1] == 0
    assert r.flush() == 0 and len(store.read("vn_book", "FPT")) == 1
    # sau khi ghi, mẫu giống lần cuối vẫn không sinh dòng
    assert r.feed([rec("FPT", bid=120000)], t0 + 40_000) == 0
