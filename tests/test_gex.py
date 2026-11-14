import math
from datetime import datetime, timezone

import pytest

from common import gex

YEAR = gex.YEAR_MS
NOW = 1_794_000_000_000


def test_bs_gamma_matches_hand_calculation():
    # F=K=100, sigma=50%, T=1: d1=0.25, phi(0.25)=0.386668, gamma=phi/(F*sigma*sqrt(T))=0.0077334
    g = gex.bs_gamma(100, 100, 50, 1.0)
    assert g == pytest.approx(math.exp(-0.5 * 0.25**2) / math.sqrt(2 * math.pi) / 50, rel=1e-12)
    assert g == pytest.approx(0.0077334, abs=1e-6)
    assert gex.bs_gamma(100, 100, 0, 1) == 0 and gex.bs_gamma(100, 100, 50, 0) == 0


def test_parse_instrument():
    ms, k, call = gex.parse_instrument("BTC-29JAN27-72000-C")
    assert (k, call) == (72000, True)
    assert datetime.fromtimestamp(ms / 1000, timezone.utc) == datetime(2027, 1, 29, 8, tzinfo=timezone.utc)
    assert gex.parse_instrument("BTC-5DEC26-50000-P")[2] is False
    for bad in ("BTC-PERPETUAL", "BTC-29XXX27-1-C", "BTC-29JAN27-72000-X", ""):
        assert gex.parse_instrument(bad) is None


def test_gex_three_strikes_by_hand():
    """3 strike, 1 kỳ hạn đúng 1 năm sau, F=spot=100, IV 50%. GEX = gamma * OI * 100^2 * 0.01 = gamma * OI * 100.

    K=100: d1=0.25,    phi=0.386668, gamma=0.386668/50=0.0077334 -> call OI 10: +7.7334
    K=120: d1=-0.11464, phi=0.396330, gamma=0.0079266            -> call OI 5:  +3.9633
    K=80:  d1=0.69628,  phi=0.313030, gamma=0.0062606            -> put  OI 20: -12.5212
    """
    exp = NOW + YEAR
    opts = [
        (exp, 100, True, 10.0, 50.0, 100.0),
        (exp, 120, True, 5.0, 50.0, 100.0),
        (exp, 80, False, 20.0, 50.0, 100.0),
    ]
    per = gex.gex_by_strike(opts, NOW, 100.0)
    assert per[100]["call"] == pytest.approx(7.7334, abs=2e-3)
    assert per[120]["call"] == pytest.approx(3.9633, abs=2e-3)
    assert per[80]["put"] == pytest.approx(-12.5212, abs=2e-3)
    assert gex.total_gex(opts, NOW, 100.0) == pytest.approx(7.7334 + 3.9633 - 12.5212, abs=5e-3)
    lv = gex.levels(opts, NOW, 100.0)
    assert lv["call_wall"] == 100  # 7.73 > 3.96
    assert lv["put_wall"] == 80


def test_expired_and_missing_iv_ignored_and_flip():
    exp = NOW + YEAR
    opts = [(NOW - 1, 100, True, 99.0, 50.0, 100.0), (exp, 100, True, 5.0, 0.0, 100.0)]
    assert gex.gex_by_strike(opts, NOW, 100.0) == {}
    assert gex.levels(opts, NOW, 100.0)["flip"] is None
    # put nhiều dưới spot, call nhiều trên spot: tổng GEX đổi dấu khi giá dịch, nên có flip
    opts = [(exp, 90, False, 50.0, 50.0, 100.0), (exp, 110, True, 50.0, 50.0, 100.0)]
    lv = gex.levels(opts, NOW, 100.0)
    assert lv["flip"] is not None and 70 <= lv["flip"] <= 130


def test_option_rows_from_summary():
    summary = [
        {"instrument_name": "BTC-29JAN27-72000-C", "open_interest": 79.7, "mark_iv": 37.9,
         "underlying_price": 67549.67, "estimated_delivery_price": 66777.98},
        {"instrument_name": "BTC-PERPETUAL", "open_interest": 1, "underlying_price": 1},
        {"instrument_name": "BTC-29JAN27-1000-P", "open_interest": 0, "mark_iv": None,
         "underlying_price": 67549.67, "estimated_delivery_price": 66777.98},
    ]
    rows, spot = gex.option_rows(summary)
    assert spot == 66777.98 and len(rows) == 2
    assert rows[0][1:] == (72000, True, 79.7, 37.9, 67549.67)
    assert rows[1][4] == 0.0
