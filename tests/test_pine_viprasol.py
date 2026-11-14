"""Kiểm thử script Pine thật dài 1720 dòng (pine/examples/viprasol_liq_trail.pine, Pine v6).

Script dùng switch, mảng, đối tượng vẽ (line, label, box, table), alert(), request.security, ta.dmi. Bộ test này:
  1. chạy được trọn vẹn và sinh đủ loại đầu ra;
  2. băng trail và điểm đảo chiều khớp một bản cài đặt độc lập viết tay trong test này;
  3. mức SL/TP của lệnh khớp công thức rủi ro (TP = entry + k × rủi ro);
  4. không repaint: cắt bớt các nến cuối thì tín hiệu ở các nến trước giữ nguyên;
  5. tham số (preset) đổi được hành vi, và chạy lặp lại cho cùng kết quả.
"""
import math
from pathlib import Path

import pytest

from pine import runner
from pine.interp import Bars, in_session
from tests.test_pine import make_bars, ref_ema

SRC = (Path(__file__).resolve().parent.parent / "pine" / "examples" / "viprasol_liq_trail.pine").read_text(encoding="utf-8")
BARS = make_bars(1500, seed=3)


def run(bars=None, **kw):
    kw.setdefault("symbol", "BTCUSDT")
    kw.setdefault("tf", "5m")
    kw.setdefault("tick", 0.1)
    return runner.run_script(SRC, bars or BARS, **kw)


@pytest.fixture(scope="module")
def result():
    return run()


def test_runs_and_produces_all_output_kinds(result):
    o = result["objects"]
    assert [p["title"] for p in result["plots"]] == ["Band 1", "Band 2", "Band 3", "Band 4"]
    assert len(result["inputs"]) >= 60 and result["meta"]["overlay"] is True
    assert o["lines"] and o["labels"] and o["boxes"] and len(o["tables"]) == 2
    texts = [l["text"] for l in o["labels"]]
    assert any(t.startswith("▲") or t.startswith("▼") for t in texts)          # nhãn đảo chiều
    assert any(t.startswith("ENTRY") for t in texts) and any(t.startswith("SL") for t in texts)
    msgs = [e["message"] for e in result["alert_events"]]
    assert any("FLIP" in m for m in msgs) and any("LONG" in m or "SHORT" in m for m in msgs)
    dash = next(t for t in o["tables"] if t["rows"] > 5)
    assert dash["position"] == "top_right" and any(c["text"] == "Trend" for c in dash["cells"])


def ref_trail(bars, atr_len=13, base=4.0, step=0.25, flip_band=3):
    """Bản cài đặt độc lập của động cơ trail: ATR (RMA khởi tạo SMA), 4 băng, đảo chiều khi src vượt băng thứ flip_band của nến trước."""
    n = len(bars)
    tr = [bars.high[0] - bars.low[0]] + [max(bars.high[i] - bars.low[i], abs(bars.high[i] - bars.close[i - 1]), abs(bars.low[i] - bars.close[i - 1])) for i in range(1, n)]
    atr = [0.0 if v is None else v for v in ref_ema(tr, atr_len, 1 / atr_len)]
    m = [base * (1 + k * step) for k in range(4)]
    ts = [[None] * n for _ in range(4)]
    trend, flips, trends = 1, [], []
    for i in range(n):
        src = bars.close[i]
        up = [src - atr[i] * mk for mk in m]
        lo = [src + atr[i] * mk for mk in m]
        prev = ts[flip_band - 1][i - 1] if i > 0 else None
        old = trend
        if trend == 1 and prev is not None and src < prev:
            trend = -1
        elif trend == -1 and prev is not None and src > prev:
            trend = 1
        for k in range(4):
            p = ts[k][i - 1] if i > 0 else None
            if trend != old:
                ts[k][i] = lo[k] if trend == -1 else up[k]
            elif trend == 1:
                ts[k][i] = max(up[k], p if p is not None else up[k])
            else:
                ts[k][i] = min(lo[k], p if p is not None else lo[k])
        if trend != old:
            flips.append(i)
        trends.append(trend)
    return ts, flips, trends


def test_trail_bands_and_flips_match_independent_reference(result):
    ts, flips, trends = ref_trail(BARS)
    assert len(flips) >= 5                                   # dữ liệu thử có đảo chiều để so sánh
    flip_set = set(flips)
    for k in range(4):
        got = result["plots"][k]["values"]
        for i in range(len(BARS)):
            if i in flip_set:
                assert got[i] is None, (k, i)                 # script vẽ na tại nến đảo chiều
            else:
                assert got[i] == pytest.approx(ts[k][i], rel=1e-9, abs=1e-9), (k, i)


def test_trade_levels_follow_risk_formula(result):
    """Balanced: TP1 = 1R, TP2 = 2R, TP3 = 3R tính từ entry; SL cùng phía với hướng ngược lại."""
    labels = {}
    for l in result["objects"]["labels"]:
        for key in ("ENTRY", "SL", "TP1", "TP2", "TP3"):
            if l["text"].startswith(key + " "):
                labels[key] = l["y"]
    assert set(labels) == {"ENTRY", "SL", "TP1", "TP2", "TP3"}
    e, sl = labels["ENTRY"], labels["SL"]
    risk = abs(e - sl)
    assert risk > 0
    sign = 1 if labels["TP1"] > e else -1
    assert (sl < e) == (sign == 1)                          # lệnh mua: SL dưới entry; lệnh bán: SL trên entry
    for key, mult in (("TP1", 1.0), ("TP2", 2.0), ("TP3", 3.0)):
        assert (labels[key] - e) * sign == pytest.approx(mult * risk, rel=1e-9)


def key_events(res, upto):
    return [(e["bar"], e["message"]) for e in res["alert_events"] if e["bar"] < upto]


def test_no_repainting_when_future_bars_are_removed(result):
    full = key_events(result, 1200)
    assert len(full) >= 3
    cut = make_bars(1500, seed=3)
    for name in ("time", "open", "high", "low", "close", "volume", "buy", "sell"):
        setattr(cut, name, getattr(cut, name)[:1200])
    short = key_events(run(cut), 1199)         # nến cuối còn đang chạy, bỏ ra khỏi so sánh
    assert [e for e in full if e[0] < 1199] == short


def test_is_deterministic_and_presets_change_behaviour(result):
    again = run()
    assert again["alert_events"] == result["alert_events"]
    assert [p["values"] for p in again["plots"]] == [p["values"] for p in result["plots"]]
    scalp = run(inputs={"Band Width Preset": "Scalping"})
    assert scalp["plots"][0]["values"] != result["plots"][0]["values"]
    ts, _, _ = ref_trail(BARS, base=2.5, step=0.20)
    flips = set(ref_trail(BARS, base=2.5, step=0.20)[1])
    i = next(i for i in range(100, 1400) if i not in flips)
    assert scalp["plots"][1]["values"][i] == pytest.approx(ts[1][i], rel=1e-9)
    deep = run(inputs={"Flip Band": "Deep (Band 4)"})
    assert deep["alert_events"] != result["alert_events"] or deep["plots"][3]["values"] != result["plots"][3]["values"]


def test_session_helper_and_symbol_without_volume():
    assert in_session("0000-2400", 3600_000 * 5)
    assert in_session("0930-1600", (9 * 60 + 30) * 60_000) and not in_session("0930-1600", (16 * 60) * 60_000)
    assert in_session("2200-0600", 23 * 3_600_000) and in_session("2200-0600", 3 * 3_600_000) and not in_session("2200-0600", 12 * 3_600_000)
    novol = make_bars(400, seed=5)
    novol.volume = [0.0] * 400
    res = run(novol)                           # forex: script phải dùng nhánh volume thay thế mà không lỗi
    assert res["objects"]["tables"]
