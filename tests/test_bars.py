from datetime import date

import pytest

from collector import verify
from common import bars, store

DAY = date(2026, 11, 10)
T0 = 1_794_268_800_000  # 00:00:00 UTC ngày 10/11/2026


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "tv-data"
    monkeypatch.setenv("DATA_DIR", str(root))
    return root


def test_tf_to_ms():
    assert bars.tf_to_ms("1s") == 1000 and bars.tf_to_ms("5m") == 300_000
    assert bars.tf_to_ms("1h") == 3_600_000 and bars.tf_to_ms("1d") == 86_400_000
    assert bars.tf_to_ms(250) == 250
    assert bars.tf_to_ms("1w") == 7 * 86_400_000 and bars.tf_to_ms("1M") == 30 * 86_400_000
    for bad in ("", "m", "0m", "1x", "-1m", "1.5m", "2M"):
        with pytest.raises(ValueError):
            bars.tf_to_ms(bad)


def put(ticks, part=None):
    store.write_partition("ticks", "BTCUSDT", DAY, ticks, part=part)


def test_ohlc_and_buy_sell_split(data_root):
    # cột: ts, id, p, q, m. m=True là taker bán, m=False là taker mua
    put([
        (T0 + 0, 1, 100, 1.0, False),
        (T0 + 10, 2, 105, 2.0, True),
        (T0 + 20, 3, 95, 0.5, False),
        (T0 + 59_999, 4, 102, 1.5, True),
        (T0 + 60_000, 5, 110, 1.0, False),   # nến kế tiếp
    ])
    out = bars.bars_from_ticks("BTCUSDT", "1m")
    assert out[0] == (T0, 100, 105, 95, 102, 5.0, 1.5, 3.5)
    assert out[1] == (T0 + 60_000, 110, 110, 110, 110, 1.0, 1.0, 0.0)


def test_open_close_use_id_order_within_same_millisecond(data_root):
    put([(T0, 7, 120, 1.0, False), (T0, 5, 100, 1.0, False), (T0, 6, 110, 1.0, False)])
    (b,) = bars.bars_from_ticks("BTCUSDT", "1s")
    assert (b[1], b[4]) == (100, 120)  # mở = id nhỏ nhất, đóng = id lớn nhất


def test_second_and_hour_buckets(data_root):
    put([(T0 + 500, 1, 100, 1.0, False), (T0 + 1500, 2, 101, 1.0, False), (T0 + 3_599_000, 3, 102, 1.0, True)])
    assert [b[0] for b in bars.bars_from_ticks("BTCUSDT", "1s")] == [T0, T0 + 1000, T0 + 3_599_000]
    (h,) = bars.bars_from_ticks("BTCUSDT", "1h")
    assert h[0] == T0 and h[5] == 3.0


def test_overlapping_files_do_not_double_count(data_root):
    base = [(T0 + i, i, 100, 1.0, False) for i in range(10)]
    put(base)
    put(base[5:], part="5")  # backfill và collector trùng id 5..9
    (b,) = bars.bars_from_ticks("BTCUSDT", "1m")
    assert b[5] == 10.0


def test_range_filter_and_empty(data_root):
    assert bars.bars_from_ticks("BTCUSDT", "1m") == []
    put([(T0 + i * 60_000, i, 100 + i, 1.0, False) for i in range(5)])
    got = bars.bars_from_ticks("BTCUSDT", "1m", T0 + 60_000, T0 + 3 * 60_000)
    assert [b[0] for b in got] == [T0 + 60_000, T0 + 120_000]


def test_float32_quantity_summed_in_double(data_root):
    put([(T0 + i, i, 100, 0.001, False) for i in range(1000)])
    (b,) = bars.bars_from_ticks("BTCUSDT", "1m")
    assert b[5] == pytest.approx(1.0, rel=1e-6)


# ---------- so khớp với kline ----------

def kline_bar(ts, o, h, l, c, v, buy):
    return (ts, o, h, l, c, v, buy, v - buy)


def test_compare_passes_when_consistent(data_root):
    put([(T0, 1, 100, 1.0, False), (T0 + 5, 2, 105, 2.0, True), (T0 + 60_000, 3, 99, 3.0, False)])
    store.write_partition("bars", "BTCUSDT", DAY, [
        kline_bar(T0, 100, 105, 100, 105, 3.0, 1.0),
        kline_bar(T0 + 60_000, 99, 99, 99, 99, 3.0, 3.0),
    ])
    r = verify.compare("BTCUSDT", T0, T0 + 120_000)
    assert verify.passes(r) and r["ohlc_mismatch_bars"] == 0 and r["bars_compared"] == 2


def test_compare_detects_swapped_buy_side(data_root):
    # tick nói taker mua (m=False) 1.0, nhưng kline nói mua chủ động là 2.0 (phía còn lại)
    put([(T0, 1, 100, 1.0, False), (T0 + 5, 2, 100, 2.0, True)])
    store.write_partition("bars", "BTCUSDT", DAY, [kline_bar(T0, 100, 100, 100, 100, 3.0, 2.0)])
    r = verify.compare("BTCUSDT", T0, T0 + 60_000)
    assert not verify.passes(r) and not r["buy_closer_to_taker_buy_than_sell"]


def test_compare_passes_when_trade_straddles_minute_boundary(data_root):
    """Kline xếp lệnh vào phút 1, aggTrade gán vào phút 2: từng nến lệch nhưng tổng khớp."""
    put([(T0 + 59_990, 1, 100, 1.0, False), (T0 + 60_010, 2, 100, 55.0, False)])  # lệnh 55 BTC thuộc phút 2 theo T
    store.write_partition("bars", "BTCUSDT", DAY, [
        kline_bar(T0, 100, 100, 100, 100, 56.0, 56.0),  # kline: lệnh 55 BTC rơi vào phút 1
        kline_bar(T0 + 60_000, 100, 100, 100, 100, 0.0, 0.0),
    ])
    r = verify.compare("BTCUSDT", T0, T0 + 120_000)
    assert r["worst_minute_volume_rel_err"] > 0.9       # từng nến lệch rất nhiều
    assert r["total_volume_rel_err"] < 1e-9             # nhưng tổng khớp
    assert verify.passes(r)


def test_compare_detects_volume_mismatch(data_root):
    put([(T0, 1, 100, 1.0, False)])
    store.write_partition("bars", "BTCUSDT", DAY, [kline_bar(T0, 100, 100, 100, 100, 1.01, 1.01)])
    assert not verify.passes(verify.compare("BTCUSDT", T0, T0 + 60_000))


def test_compare_without_common_bars_raises(data_root):
    put([(T0, 1, 100, 1.0, False)])
    store.write_partition("bars", "BTCUSDT", DAY, [kline_bar(T0 + 60_000, 1, 1, 1, 1, 1.0, 1.0)])
    with pytest.raises(RuntimeError):
        verify.compare("BTCUSDT")
