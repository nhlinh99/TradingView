"""Kiểm thử 4 script Pine thật: ichimoku_future (v4), cvd_range (v6, import thư viện, nến khung thấp),
volume_profile_total (v6, kiểu do người dùng định nghĩa, polyline) và instituitional_level_indicator (v6, SMC dài 936 dòng).

Mỗi script được chạy trên dữ liệu tổng hợp và đối chiếu với bản tính độc lập viết trong test này nếu công thức đủ rõ
(Ichimoku, CVD, volume profile). Với chỉ báo SMC không có bản tham chiếu độc lập nên chỉ kiểm bất biến và tính lặp lại.
"""
import math
from pathlib import Path

import pytest

from pine import runner
from pine.interp import Bars
from tests.test_pine import make_bars

EX = Path(__file__).resolve().parent.parent / "pine" / "examples"
DAY = 86_400_000


def src(name):
    return (EX / f"{name}.pine").read_text(encoding="utf-8")


def run(name, bars, provider=None, **kw):
    return runner.run_script(src(name), bars, symbol="BTCUSDT", tf="5m", tick=0.1, provider=provider, **kw)


def plot(res, title):
    return next(p for p in res["plots"] if p["title"] == title)


# ---------------------------------------------------------------- Ichimoku Future (Pine v4)

@pytest.fixture(scope="module")
def ichi():
    bars = make_bars(600, seed=2)
    return bars, run("ichimoku_future", bars)


def donchian(bars, i, n):
    """(cao nhất + thấp nhất) / 2 của n nến kết thúc ở nến i."""
    return (max(bars.high[i - n + 1:i + 1]) + min(bars.low[i - n + 1:i + 1])) / 2


def test_ichimoku_lines_match_donchian_midpoints(ichi):
    bars, res = ichi
    for title, n in (("Tenkan", 9), ("Kijun", 17), ("Dao Gam 1", 65), ("Dao Gam 2", 129)):
        v = plot(res, title)["values"]
        assert v[n - 2] is None and v[n - 1] is not None, title
        for i in (n - 1, n + 10, 300, 599):
            assert v[i] == pytest.approx(donchian(bars, i, n), rel=1e-12), (title, i)


def test_ichimoku_cloud_is_shifted_forward_into_the_future(ichi):
    bars, res = ichi
    assert res["future_bars"] == 25
    a, b = plot(res, "Span A"), plot(res, "Span B")
    assert a["offset"] == b["offset"] == 25 and len(a["values"]) == 625
    for i in (30, 300, 574, 599):
        want_a = (donchian(bars, i, 9) + donchian(bars, i, 17)) / 2
        assert a["values"][i + 25] == pytest.approx(want_a, rel=1e-12)
        assert b["values"][i + 25] == pytest.approx(donchian(bars, i, 26), rel=1e-12)
    assert a["values"][599 + 25] is not None and a["values"][24] is None          # mây kéo dài 25 nến sau nến cuối
    fill = res["fills"][0]
    assert (fill["a"], fill["b"]) == (4, 5)
    k = 300 + 25
    assert fill["colors"][k] == ("#33C33A3F" if a["values"][k] > b["values"][k] else "#F2364648")   # xanh khi Span A > Span B


def test_ichimoku_future_projection_lines(ichi):
    bars, res = ichi
    lines = res["objects"]["lines"]
    assert len(lines) == 15 + 15 + 16 + 8                          # (16-1) cho hai Dao Gam, (17-1) cho Kijun, (9-1) cho Tenkan
    last = len(bars) - 1
    kijun = sorted((l for l in lines if l["color"] == "#B41E18"), key=lambda l: l["x1"])
    assert len(kijun) == 16
    for i, l in enumerate(kijun, start=1):
        # đoạn thứ i nối trung điểm của (17 - i + 1) nến cuối với trung điểm của (17 - i) nến cuối
        assert (l["x1"], l["x2"]) == (last + i - 1, last + i)
        assert l["y1"] == pytest.approx(donchian(bars, last, 17 - i + 1), rel=1e-12)
        assert l["y2"] == pytest.approx(donchian(bars, last, 17 - i), rel=1e-12)
        assert l["style"] == "dotted" and l["width"] == 2


# ---------------------------------------------------------------- CVD Range

def split_bars(b: Bars, k=5):
    """Chia mỗi nến thành k nến con (giá đi thẳng từ open tới close) làm dữ liệu khung thấp cho request.security_lower_tf."""
    t, o, h, l, c, v = [], [], [], [], [], []
    step = (b.time[1] - b.time[0]) // k
    for i in range(len(b)):
        for j in range(k):
            op = b.open[i] + (b.close[i] - b.open[i]) * j / k
            cl = b.open[i] + (b.close[i] - b.open[i]) * (j + 1) / k
            t.append(b.time[i] + j * step); o.append(op); c.append(cl)
            h.append(max(op, cl) + 0.01); l.append(min(op, cl) - 0.01); v.append(b.volume[i] / k)
    return Bars(time=t, open=o, high=h, low=l, close=c, volume=v)


@pytest.fixture(scope="module")
def cvd():
    base = make_bars(200, seed=3, step=300_000)          # 200 nến 5 phút = 16,7 giờ, nằm gọn trong một ngày UTC
    fine = split_bars(base)
    res = run("cvd_range", base, provider=lambda s, tf: fine if tf in ("1", "1m") else None)
    return base, fine, res


def test_cvd_matches_intrabar_up_down_volume(cvd):
    base, fine, res = cvd
    delta = []
    for i in range(len(base)):
        sub = [j for j in range(len(fine)) if base.time[i] <= fine.time[j] < base.time[i] + 300_000]
        assert len(sub) == 5
        up = sum(fine.volume[j] for j in sub if fine.close[j] > fine.open[j])
        dn = sum(fine.volume[j] for j in sub if fine.close[j] < fine.open[j])
        delta.append(up - dn)
    # dữ liệu tổng hợp nằm gọn trong một ngày UTC, "Resets every 1D" => CVD cộng dồn từ nến đầu
    assert base.time[-1] // DAY == base.time[0] // DAY
    after = plot(res, "CVD after this bar")["values"]
    before = plot(res, "CVD before this bar")["values"]
    vol_delta = plot(res, "Volume delta for the bar")["values"]
    running = 0.0
    for i in (0, 1, 2, 50, 100, 199):
        running = sum(delta[:i + 1])
        assert vol_delta[i] == pytest.approx(delta[i], abs=1e-9), i
        assert after[i] == pytest.approx(running, abs=1e-6), i
        assert before[i] == pytest.approx(running - delta[i], abs=1e-6), i
    assert plot(res, "Intrabars in this bar")["values"][100] == 5.0
    assert plot(res, "Total volume")["values"][100] == pytest.approx(base.volume[100], rel=1e-9)


def test_cvd_resets_on_a_new_day():
    base = make_bars(800, seed=3, start=1_794_268_800_000 + 10 * 3_600_000, step=300_000)   # nến đầu lúc 10:00 UTC, qua 00:00 sau 14 giờ
    fine = split_bars(base)
    res = run("cvd_range", base, provider=lambda s, tf: fine if tf in ("1", "1m") else None)
    cut = next(i for i in range(1, 800) if base.time[i] // DAY != base.time[i - 1] // DAY)
    before = plot(res, "CVD before this bar")["values"]
    delta = plot(res, "Volume delta for the bar")["values"]
    after = plot(res, "CVD after this bar")["values"]
    assert before[cut] == pytest.approx(0.0, abs=1e-9) and after[cut] == pytest.approx(delta[cut], abs=1e-9)
    assert abs(before[cut - 1]) > 0                                 # ngay trước đó vẫn là số cộng dồn của ngày cũ


def test_cvd_rejects_charts_without_intrabar_data():
    base = make_bars(100, seed=3, step=60_000)             # khung 1 phút: không có dữ liệu nhỏ hơn
    with pytest.raises(Exception, match="Không có dữ liệu trong nến"):
        runner.run_script(src("cvd_range"), base, symbol="BTCUSDT", tf="1m", tick=0.1)


# ---------------------------------------------------------------- Volume profile total

def ref_profile(bars, lookback=200, rows=25, va=0.70):
    """Volume profile độc lập: chia khoảng giá của `lookback` nến cuối thành `rows` hàng; mỗi nến rải volume theo tỉ lệ chồng lấn
    giữa [low, high] của nến và từng hàng; POC là hàng lớn nhất; vùng giá trị mở rộng từ POC, luôn lấy phía có volume lớn hơn."""
    n = len(bars)
    idx = range(n - lookback, n)
    lo = min(bars.low[i] for i in idx)
    hi = max(bars.high[i] for i in idx)
    step = (hi - lo) / rows
    vol = [0.0] * rows
    for i in idx:
        h, l, v = bars.high[i], bars.low[i], bars.volume[i]
        rng = h - l
        for r in range(rows):
            a, b = lo + r * step, lo + (r + 1) * step
            overlap = max(0.0, min(h, b) - max(l, a))
            if rng > 1e-10:
                vol[r] += v * overlap / rng
    poc = vol.index(max(vol))
    acc, up, dn = vol[poc], poc, poc
    while acc < sum(vol) * va and (up < rows - 1 or dn > 0):
        vu = vol[up + 1] if up < rows - 1 else -1.0
        vd = vol[dn - 1] if dn > 0 else -1.0
        if vu >= vd:
            up += 1
            acc += vu
        else:
            dn -= 1
            acc += vd
    return {"lo": lo, "hi": hi, "step": step, "poc": lo + (poc + 0.5) * step, "vah": lo + (up + 1.0) * step, "val": lo + dn * step, "vol": vol}


@pytest.fixture(scope="module")
def vpt():
    bars = make_bars(1500, seed=3)
    return bars, run("volume_profile_total", bars)


def test_volume_profile_poc_vah_val_match_reference(vpt):
    bars, res = vpt
    ref = ref_profile(bars)
    o = res["objects"]
    lines = sorted(o["lines"], key=lambda l: l["y1"])
    assert len(lines) == 2
    assert lines[0]["y1"] == pytest.approx(ref["val"], rel=1e-9) and lines[1]["y1"] == pytest.approx(ref["vah"], rel=1e-9)
    assert (lines[0]["x1"], lines[0]["x2"]) == (len(bars) - 200, len(bars) - 1)
    texts = sorted(l["text"] for l in o["labels"])
    assert texts[0].startswith("VAH") and texts[1].startswith("VAL")
    poly = o["polylines"][0]["points"]
    assert len(poly) == 2 and poly[0]["price"] == pytest.approx(ref["poc"], rel=1e-9) == pytest.approx(poly[1]["price"], rel=1e-9)
    assert poly[0]["index"] == len(bars) - 200 and poly[1]["index"] == len(bars) - 1


def test_volume_profile_boxes_stay_inside_the_profile_range(vpt):
    bars, res = vpt
    ref = ref_profile(bars)
    boxes = res["objects"]["boxes"]
    assert len(boxes) >= 25
    for b in boxes:
        lo_, hi_ = min(b["top"], b["bottom"]), max(b["top"], b["bottom"])      # script có khi truyền cận thấp làm "top"; Pine chấp nhận
        assert ref["lo"] - 1e-9 <= lo_ < hi_ <= ref["hi"] + 1e-9


def test_volume_profile_boxes_carry_row_text(vpt):
    """Mỗi hàng profile có số (volume, delta, %) trong box; engine phải giữ text và kiểu chữ để biểu đồ vẽ ra."""
    _, res = vpt
    boxes = [b for b in res["objects"]["boxes"] if b.get("text")]
    assert len(boxes) >= 25
    assert {b["text_halign"] for b in boxes} >= {"left", "right"}
    assert all(b["text_color"] for b in boxes) and all(b["text_size"] == "tiny" for b in boxes)
    assert any(b["text"].endswith("%") for b in boxes)


def test_volume_profile_changes_with_inputs(vpt):
    bars, res = vpt
    narrow = run("volume_profile_total", bars, inputs={"  Lookback Length / Fixed Range": 100})
    ref = ref_profile(bars, lookback=100)
    ys = sorted(l["y1"] for l in narrow["objects"]["lines"])
    assert ys[0] == pytest.approx(ref["val"], rel=1e-9) and ys[1] == pytest.approx(ref["vah"], rel=1e-9)


# ---------------------------------------------------------------- Institutional level indicator (SMC)

@pytest.fixture(scope="module")
def smc():
    bars = make_bars(1500, seed=3)
    return bars, run("instituitional_level_indicator", bars)


def test_smc_runs_and_draws_structures(smc):
    bars, res = smc
    o = res["objects"]
    assert len(o["lines"]) > 5 and len(o["labels"]) > 5 and len(o["boxes"]) >= 1
    assert [p["title"] for p in res["plots"]] == ["VWAP"] and len(res["candles"]) == 1
    texts = [l["text"] for l in o["labels"]]
    # đường swing mạnh/yếu: mỗi loại đúng một nhãn, kiểu mạnh hoặc yếu tuỳ xu hướng swing
    assert sum(t in ("Strong Resistance", "Weak Resistance") for t in texts) == 1
    assert sum(t in ("Strong Support", "Weak Support") for t in texts) == 1


def test_smc_order_blocks_and_levels_are_inside_the_price_range(smc):
    bars, res = smc
    lo, hi = min(bars.low), max(bars.high)
    for b in res["objects"]["boxes"]:
        assert b["top"] > b["bottom"] and lo - 1e-9 <= b["bottom"] and b["top"] <= hi + 1e-9
        assert 0 <= b["left"] <= len(bars) + 5 and b["right"] >= b["left"]
    for l in res["objects"]["lines"]:
        assert lo - 1e-9 <= l["y1"] <= hi + 1e-9 and l["x2"] >= l["x1"] - 1e-9
    # nến tô lại màu: dữ liệu OHLC của chính nến, không phải giá trị bịa
    assert all(v is None for v in res["candles"][0]["ohlc"])        # "Color Candles" tắt mặc định: plotcandle(na, ...) không vẽ gì
    on = run("instituitional_level_indicator", bars, inputs={"Color Candles": True})
    c = on["candles"][0]
    drawn = [i for i, v in enumerate(c["ohlc"]) if v is not None]
    assert len(drawn) == len(bars)
    for i in drawn[::97]:
        o_, h_, l_, c_ = c["ohlc"][i]
        assert h_ == bars.high[i] and l_ == bars.low[i] and c_ == bars.close[i]


def test_smc_is_deterministic_and_inputs_toggle_features(smc):
    bars, res = smc
    again = run("instituitional_level_indicator", bars)
    assert again["objects"]["labels"] == res["objects"]["labels"] and again["objects"]["boxes"] == res["objects"]["boxes"]
    off = run("instituitional_level_indicator", bars, inputs={"Show Strong/Weak Resistance/Support": False})
    t_off = [l["text"] for l in off["objects"]["labels"]]
    assert not any(t in ("Strong Resistance", "Weak Resistance", "Strong Support", "Weak Support") for t in t_off)


def test_cvd_tolerates_chart_bars_without_intrabar_data():
    """Khi dữ liệu khung thấp chỉ bắt đầu sau nến đầu của biểu đồ, các nến đầu nhận mảng rỗng thay vì làm script lỗi."""
    base = make_bars(120, seed=3, step=300_000)
    fine = split_bars(base)
    cut = 20 * 5                                                    # bỏ 20 nến đầu của dữ liệu khung thấp
    late = Bars(time=fine.time[cut:], open=fine.open[cut:], high=fine.high[cut:], low=fine.low[cut:], close=fine.close[cut:], volume=fine.volume[cut:])
    res = run("cvd_range", base, provider=lambda s, tf: late if tf in ("1", "1m") else None)
    assert plot(res, "Intrabars in this bar")["values"][5] in (0.0, None)
    assert plot(res, "Intrabars in this bar")["values"][50] == 5.0


# ---------------------------------------------------------------- Volume Profile by Range (hàm ngày giờ dạng gọi hàm)

@pytest.mark.parametrize("rng, n, step", [
    ("1 Hour", 600, 60_000), ("Day", 600, 3_600_000), ("Week", 400, 6 * 3_600_000),
    ("Month", 400, 12 * 3_600_000), ("3 Month", 400, DAY), ("6 Month", 500, DAY),
])
def test_volume_profile_range_every_period(rng, n, step):
    bars = make_bars(n, seed=5, start=1_735_689_600_000, step=step)   # bắt đầu 2025-01-01 để có đủ ranh giới quý và nửa năm
    res = runner.run_script(src("volume_profile_range"), bars, symbol="BTCUSDT", tf="1d", tick=0.1, inputs={"  Range": rng})
    assert len(res["objects"]["boxes"]) > 0, rng
    assert len(res["objects"]["lines"]) > 0, rng


def test_date_functions_match_variables_and_timezone():
    from pine.interp import Bars as B
    t0 = 1_735_689_600_000   # 2025-01-01 00:00 UTC (thứ Tư)
    bars = B(time=[t0 + i * 3_600_000 for i in range(30)], open=[1.0] * 30, high=[2.0] * 30, low=[1.0] * 30, close=[1.0] * 30, volume=[1.0] * 30)
    code = ('indicator("t")\n'
            'plot(month(time) - month, "dm")\nplot(hour(time) - hour, "dh")\nplot(dayofmonth(time) - dayofmonth, "dd")\n'
            'plot(year(time), "y")\nplot(hour(time, "UTC+7"), "h7")\nplot(dayofweek(time), "dw")\n')
    res = runner.run_script(code, bars, symbol="X", tf="60", tick=0.01)
    g = lambda title: next(p for p in res["plots"] if p["title"] == title)["values"]
    assert set(g("dm")) == {0.0} and set(g("dh")) == {0.0} and set(g("dd")) == {0.0}
    assert g("y")[0] == 2025.0 and g("dw")[0] == 4.0
    assert g("h7")[0] == 7.0 and g("h7")[20] == 3.0   # 20:00 UTC = 03:00 hôm sau theo UTC+7
