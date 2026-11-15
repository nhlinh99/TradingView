"""Test engine Pine: tính đúng so với công thức độc lập, và chạy được 5 script mẫu trong docs/plan/archive/research-initial.md mục 4.

Không dùng pandas (bị chính sách Application Control của Windows chặn trên máy này). SMA, độ lệch chuẩn,
cực trị đối chiếu với hàm cửa sổ của DuckDB; EMA, RMA, RSI, ATR đối chiếu với bản cài đặt thuần Python viết riêng
theo công thức sách giáo khoa (khởi tạo bằng SMA như Pine).
"""
import math
import random

import duckdb
import pytest

from pine import runner
from pine.interp import Bars, PineRuntimeError, tf_to_ms
from pine.lexer import PineSyntaxError

DAY = 86_400_000


def make_bars(n=400, seed=7, start=1_794_268_800_000, step=60_000):
    rnd = random.Random(seed)
    c, o, h, l, v, t, buy, sell = [], [], [], [], [], [], [], []
    p = 100.0
    for i in range(n):
        op = p
        p = max(1.0, p + rnd.gauss(0, 1))
        hi = max(op, p) + rnd.random()
        lo = min(op, p) - rnd.random()
        vol = 100 + rnd.random() * 900
        b = vol * rnd.random()
        o.append(op); c.append(p); h.append(hi); l.append(lo); v.append(vol); t.append(start + i * step)
        buy.append(b); sell.append(vol - b)
    return Bars(time=t, open=o, high=h, low=l, close=c, volume=v, buy=buy, sell=sell)


def run(src, bars=None, **kw):
    return runner.run_script(src, bars or make_bars(), **kw)


def plot(res, title):
    return next(p["values"] for p in res["plots"] if p["title"] == title)


def close_enough(a, b, tol=1e-9):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        if y is None or (isinstance(y, float) and math.isnan(y)):
            assert x is None or (isinstance(x, float) and math.isnan(x))
        else:
            assert x is not None and abs(x - y) <= tol * max(1.0, abs(y)), (x, y)


# ---------- chỉ báo so với tham chiếu độc lập ----------

def duck_window(values, expr):
    con = duckdb.connect()
    con.execute("CREATE TABLE s (i INT, x DOUBLE)")
    con.executemany("INSERT INTO s VALUES (?, ?)", list(enumerate(values)))
    return [r[0] for r in con.execute(f"SELECT {expr} OVER (ORDER BY i ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) FROM s ORDER BY i").fetchall()]


def mask_warmup(vals, n):
    return [None if i < n - 1 else v for i, v in enumerate(vals)]


def ref_ema(xs, n, alpha=None):
    alpha = alpha if alpha is not None else 2 / (n + 1)
    out, prev = [], None
    for i, x in enumerate(xs):
        if i < n - 1:
            out.append(None)
        elif i == n - 1:
            prev = sum(xs[:n]) / n
            out.append(prev)
        else:
            prev = alpha * x + (1 - alpha) * prev
            out.append(prev)
    return out


def test_sma_stdev_highest_lowest_match_duckdb():
    bars = make_bars()
    res = run('''//@version=5
indicator("t")
plot(ta.sma(close, 10), "sma")
plot(ta.stdev(close, 10), "sd")
plot(ta.highest(high, 10), "hh")
plot(ta.lowest(low, 10), "ll")
''', bars)
    close_enough(plot(res, "sma"), mask_warmup(duck_window(bars.close, "avg(x)"), 10))
    close_enough(plot(res, "sd"), mask_warmup(duck_window(bars.close, "stddev_pop(x)"), 10))
    close_enough(plot(res, "hh"), mask_warmup(duck_window(bars.high, "max(x)"), 10))
    close_enough(plot(res, "ll"), mask_warmup(duck_window(bars.low, "min(x)"), 10))


def test_ema_rma_rsi_atr_match_reference():
    bars = make_bars()
    res = run('''//@version=5
indicator("t")
plot(ta.ema(close, 20), "ema")
plot(ta.rma(close, 14), "rma")
plot(ta.rsi(close, 14), "rsi")
plot(ta.atr(14), "atr")
''', bars)
    close_enough(plot(res, "ema"), ref_ema(bars.close, 20))
    close_enough(plot(res, "rma"), ref_ema(bars.close, 14, 1 / 14))
    # RSI
    ch = [None] + [bars.close[i] - bars.close[i - 1] for i in range(1, len(bars))]
    up = [None] + [max(d, 0) for d in ch[1:]]
    dn = [None] + [max(-d, 0) for d in ch[1:]]
    ru = ref_ema(up[1:], 14, 1 / 14)
    rd = ref_ema(dn[1:], 14, 1 / 14)
    rsi = [None] + [None if a is None else (100.0 if b == 0 else 100 - 100 / (1 + a / b)) for a, b in zip(ru, rd)]
    close_enough(plot(res, "rsi"), rsi)
    # ATR
    tr = [bars.high[0] - bars.low[0]] + [max(bars.high[i] - bars.low[i], abs(bars.high[i] - bars.close[i - 1]),
                                           abs(bars.low[i] - bars.close[i - 1])) for i in range(1, len(bars))]
    close_enough(plot(res, "atr"), ref_ema(tr, 14, 1 / 14))


def test_macd_bb_cross_change():
    bars = make_bars()
    res = run('''//@version=5
indicator("t")
[m, s, h] = ta.macd(close, 12, 26, 9)
plot(m, "m")
plot(s, "s")
plot(h, "h")
[b, u, l] = ta.bb(close, 20, 2.0)
plot(u - l, "width")
plot(ta.change(close), "chg")
plot(ta.crossover(ta.sma(close, 5), ta.sma(close, 20)) ? 1 : 0, "xo")
plot(ta.crossunder(ta.sma(close, 5), ta.sma(close, 20)) ? 1 : 0, "xu")
''', bars)
    ef, es = ref_ema(bars.close, 12), ref_ema(bars.close, 26)
    macd = [None if a is None or b is None else a - b for a, b in zip(ef, es)]
    close_enough(plot(res, "m"), macd)
    first = next(i for i, v in enumerate(macd) if v is not None)
    sig = [None] * first + ref_ema(macd[first:], 9)
    close_enough(plot(res, "s"), sig)
    close_enough(plot(res, "h"), [None if a is None or b is None else a - b for a, b in zip(macd, sig)])
    sd = duck_window(bars.close, "stddev_pop(x)")  # cửa sổ 10, chỉ để dùng lại hàm; bb dùng 20 nên tính riêng
    assert plot(res, "width")[19] is not None and plot(res, "width")[18] is None
    chg = plot(res, "chg")
    assert chg[0] is None and chg[5] == pytest.approx(bars.close[5] - bars.close[4])
    s5 = duck_window(bars.close, "avg(x)")
    assert sum(plot(res, "xo")) + sum(plot(res, "xu")) > 0
    # crossover chỉ xảy ra khi SMA5 vừa vượt SMA20: kiểm tra lại bằng tay
    def sma(xs, n): return [None if i < n - 1 else sum(xs[i - n + 1:i + 1]) / n for i in range(len(xs))]
    a, b = sma(bars.close, 5), sma(bars.close, 20)
    want = [0] + [1 if (a[i] is not None and b[i] is not None and a[i - 1] is not None and b[i - 1] is not None
                        and a[i] > b[i] and a[i - 1] <= b[i - 1]) else 0 for i in range(1, len(a))]
    assert plot(res, "xo") == want


# ---------- ngôn ngữ ----------

def test_var_history_if_for_function_tuple():
    res = run('''//@version=5
indicator("t")
var float acc = 0.0
acc := acc + 1
prev = acc[1]
sq(x) =>
    y = x * x
    y + 1
total = 0.0
for i = 1 to 3
    total += i
cond = close > open ? 1 : 0
if cond == 1
    flag = 10
else
    flag = 20
plot(acc, "acc")
plot(prev, "prev")
plot(sq(3), "sq")
plot(total, "total")
plot(flag, "flag")
plot(close[2], "c2")
plot((close + open)[1], "expr1")
''', make_bars(5))
    assert plot(res, "acc") == [1, 2, 3, 4, 5]
    assert plot(res, "prev")[:3] == [None, 1, 2]
    assert set(plot(res, "sq")) == {10} and set(plot(res, "total")) == {6}
    assert set(plot(res, "flag")) <= {10, 20}
    b = make_bars(5)
    assert plot(res, "c2")[2] == pytest.approx(b.close[0]) and plot(res, "c2")[1] is None
    assert plot(res, "expr1")[1] == pytest.approx(b.close[0] + b.open[0])


def test_na_semantics_and_errors():
    res = run('''//@version=5
indicator("t")
x = na
plot(x, "n")
plot(na(x) ? 1 : 0, "isna")
plot(nz(x, 5), "nz")
plot(x == x ? 1 : 0, "eq")
plot(1 / 0, "div")
plot(math.max(3, 4) + math.abs(-2) + math.round(2.5), "m")
''', make_bars(3))
    assert plot(res, "n") == [None] * 3 and plot(res, "isna") == [1] * 3 and plot(res, "nz") == [5] * 3
    assert plot(res, "eq") == [0] * 3 and plot(res, "div") == [None] * 3 and plot(res, "m")[0] == 9
    with pytest.raises(PineSyntaxError):
        run("plot(close\n")
    with pytest.raises(PineRuntimeError):
        run("plot(foo)")
    with pytest.raises(PineRuntimeError):
        run("plot(ta.nonexistent(close))")
    with pytest.raises(PineRuntimeError):
        run("y := 1")


def test_tf_to_ms():
    assert tf_to_ms("1") == 60_000 and tf_to_ms("60") == 3_600_000 and tf_to_ms("D") == DAY
    assert tf_to_ms("15m") == 900_000 and tf_to_ms("4h") == 14_400_000 and tf_to_ms("1d") == DAY
    with pytest.raises(PineRuntimeError):
        tf_to_ms("xyz")


# ---------- request.security: không nhìn trước ----------

def hourly_provider(base: Bars):
    """Gộp nến 1 phút của `base` thành nến 1 giờ để làm nguồn cho request.security."""
    out: dict[int, list] = {}
    for i, t in enumerate(base.time):
        out.setdefault(t // 3_600_000 * 3_600_000, []).append(i)
    ts = sorted(out)
    pick = lambda f: [f(out[k]) for k in ts]
    return Bars(time=ts, open=pick(lambda ix: base.open[ix[0]]), high=pick(lambda ix: max(base.high[i] for i in ix)),
                low=pick(lambda ix: min(base.low[i] for i in ix)), close=pick(lambda ix: base.close[ix[-1]]),
                volume=pick(lambda ix: sum(base.volume[i] for i in ix)))


def test_security_no_lookahead_and_lookahead_on():
    start = 1_794_268_800_000   # đầu giờ
    base = make_bars(240, start=start)
    hour = hourly_provider(base)
    provider = lambda sym, tf: hour if tf in ("60", "1h") else None
    res = run('''//@version=5
indicator("t")
h1 = request.security("X", "60", close, lookahead=barmerge.lookahead_off)
h2 = request.security("X", "60", close, lookahead=barmerge.lookahead_on)
plot(h1, "off")
plot(h2, "on")
''', base, symbol="X", tf="1m", provider=provider)
    off, on = plot(res, "off"), plot(res, "on")
    for i in range(240):
        j = i // 60
        # lookahead_off: giá đóng của giờ j chỉ có ở nến phút cuối cùng của giờ đó (i % 60 == 59)
        want_off = hour.close[j] if i % 60 == 59 else (hour.close[j - 1] if j > 0 else None)
        close_enough([off[i]], [want_off])
        # lookahead_on: thấy giá đóng của giờ đang chạy ngay từ phút đầu (nhìn trước)
        close_enough([on[i]], [hour.close[j]])
    # không nhìn trước thì giá trị tại phút 0 của giờ 2 không phụ thuộc dữ liệu giờ 2
    base2 = make_bars(240, start=start)
    for i in range(120, 180):
        base2.close[i] += 1000
    hour2 = hourly_provider(base2)
    res2 = run('''//@version=5
indicator("t")
plot(request.security("X", "60", close), "off")
''', base2, symbol="X", tf="1m", provider=lambda s, t: hour2)
    assert plot(res2, "off")[:119] == plot(run('''//@version=5
indicator("t")
plot(request.security("X", "60", close), "off")
''', base, symbol="X", tf="1m", provider=provider), "off")[:119]


def test_security_same_timeframe_other_symbol_and_expression():
    base = make_bars(50)
    other = make_bars(50, seed=99)
    res = run('''//@version=5
indicator("t")
n = input.int(5, "n")
plot(request.security("Y", "1m", ta.sma(close, n)), "ys")
plot(request.security("Y", timeframe.period, close), "yc")
''', base, symbol="X", tf="1m", provider=lambda s, t: other)
    close_enough(plot(res, "yc"), other.close)
    sma5 = [None if i < 4 else sum(other.close[i - 4:i + 1]) / 5 for i in range(50)]
    close_enough(plot(res, "ys"), sma5)
    with pytest.raises(PineRuntimeError):
        run('indicator("t")\nplot(request.security("Y", "1m", close))', base)   # không có provider


# ---------- request.external ----------

def test_external_delta_cvd_gex():
    bars = make_bars(300)
    res = run('''//@version=5
indicator("t")
plot(request.external("delta"), "delta")
plot(request.external("cvd"), "cvd")
[flip, cw, pw] = request.external("gex_levels")
plot(flip, "flip")
''', bars, external={"gex_levels": {"flip": 70000.0, "call_wall": 80000.0, "put_wall": 60000.0}})
    close_enough(plot(res, "delta"), [b - s for b, s in zip(bars.buy, bars.sell)])
    cvd, day, acc = [], None, 0.0
    for i, t in enumerate(bars.time):
        if t // DAY != day:
            day, acc = t // DAY, 0.0
        acc += bars.buy[i] - bars.sell[i]
        cvd.append(acc)
    close_enough(plot(res, "cvd"), cvd)
    assert set(plot(res, "flip")) == {70000.0}


# ---------- 5 script mẫu trong docs/plan/archive/research-initial.md mục 4 (file trong pine/examples) ----------

from pathlib import Path


def example(name):
    return (Path(__file__).resolve().parent.parent / "pine" / "examples" / f"{name}.pine").read_text(encoding="utf-8")


S1 = example("volume_proxy")

S2 = example("delta_cvd")

S3 = example("relative_volume_alert")

S4 = example("session_vwap")

S5 = example("ema_cross_strategy")


def test_sample_1_volume_proxy():
    bars = make_bars(60)
    other = make_bars(60, seed=3)
    res = run(S1, bars, syminfo_type="crypto", provider=lambda s, t: other)   # crypto: dùng volume của chính symbol
    assert plot(res, "Volume") == [pytest.approx(v) for v in bars.volume]
    p = next(p for p in res["plots"] if p["title"] == "Volume")
    assert p["style"] == "columns" and p["colors"][0] in ("#089981CC", "#F23645CC")
    assert [i["title"] for i in res["inputs"]] == ["Dùng volume GC1! khi symbol là spot/CFD", "MA length", "Proxy symbol"]
    # forex: dùng volume của symbol proxy
    res = run(S1, bars, syminfo_type="forex", provider=lambda s, t: other)
    close_enough(plot(res, "Volume"), other.volume)
    # override input
    res = run(S1, bars, inputs={"MA length": 5}, provider=lambda s, t: other)
    ma = plot(res, "Vol MA")
    assert ma[3] is None and ma[4] == pytest.approx(sum(bars.volume[:5]) / 5)


def test_sample_2_delta_cvd_session_reset():
    bars = make_bars(300, start=1_794_268_800_000 + 22 * 3_600_000)   # qua nửa đêm UTC sau 2 giờ
    res = run(S2, bars)
    delta = plot(res, "Delta")
    for i in range(len(bars)):
        rng = bars.high[i] - bars.low[i]
        buy = bars.volume[i] * (bars.close[i] - bars.low[i]) / rng
        assert delta[i] == pytest.approx(2 * buy - bars.volume[i])
    cvd = plot(res, "CVD")
    cut = next(i for i, t in enumerate(bars.time) if i and t // DAY != bars.time[i - 1] // DAY)
    assert cvd[cut] == pytest.approx(delta[cut])                      # reset ở nến đầu phiên mới
    assert cvd[cut - 1] == pytest.approx(sum(delta[:cut]))            # trước đó là cộng dồn từ nến đầu tiên
    assert cvd[-1] == pytest.approx(sum(delta[cut:]))


def test_sample_3_relative_volume_alert():
    bars = make_bars(200)
    bars.volume[100] *= 20
    bars.close[100] = bars.open[100] + 1
    res = run(S3, bars)
    sm = [None if i < 19 else sum(bars.volume[i - 19:i + 1]) / 20 for i in range(200)]
    want = [sm[i] is not None and bars.volume[i] / sm[i] >= 2.0 and bars.close[i] > bars.open[i] for i in range(200)]
    assert res["shapes"][0]["values"] == want and want[100]
    assert res["alerts"][0]["bars"] == [i for i, w in enumerate(want) if w]
    assert res["shapes"][0]["shape"] == "triangleup" and res["shapes"][0]["location"] == "belowbar"
    bg = res["bgcolors"][0]["colors"]
    assert [c is not None for c in bg] == want and bg[100] == "#00E6761A"


def test_sample_4_session_vwap_bands():
    bars = make_bars(300, start=1_794_268_800_000 + 22 * 3_600_000)
    res = run(S4, bars)
    v, up, lo = plot(res, "VWAP"), plot(res, "Upper"), plot(res, "Lower")
    cut = next(i for i, t in enumerate(bars.time) if i and t // DAY != bars.time[i - 1] // DAY)
    for i in (5, cut - 1, cut, cut + 7, 299):
        start = 0 if i < cut else cut
        idx = range(start, i + 1)
        tp = [(bars.high[k] + bars.low[k] + bars.close[k]) / 3 for k in idx]
        w = [bars.volume[k] for k in idx]
        vw = sum(a * b for a, b in zip(tp, w)) / sum(w)
        var = sum(b * (a - vw) ** 2 for a, b in zip(tp, w)) / sum(w)
        assert v[i] == pytest.approx(vw, rel=1e-9)
        assert up[i] == pytest.approx(vw + math.sqrt(var), rel=1e-9) and lo[i] == pytest.approx(vw - math.sqrt(var), rel=1e-9)


def test_sample_5_strategy_backtest_matches_manual():
    bars = make_bars(600, seed=11)
    res = run(S5, bars)
    st = res["strategy"]
    assert st["closed_trades"] > 0
    # mô phỏng tay: tín hiệu ở nến i, khớp ở giá mở cửa nến i+1, 100% vốn, không phí
    def ema(xs, n): return ref_ema(xs, n)
    f, s = ema(bars.close, 20), ema(bars.close, 50)
    sma20 = [None if i < 19 else sum(bars.volume[i - 19:i + 1]) / 20 for i in range(600)]
    eq, pos, entry, qty, trades, pend = 10000.0, 0, 0.0, 0.0, [], None
    for i in range(600):
        if pend:
            px = bars.open[i]
            if pend == "L" and pos == 0:
                qty, entry, pos = eq / px, px, 1
            elif pend == "C" and pos == 1:
                eq += qty * (px - entry)
                trades.append(qty * (px - entry))
                pos = 0
            pend = None
        ok = all(x is not None for x in (f[i], s[i], f[i - 1] if i else None, s[i - 1] if i else None))
        if ok and f[i] > s[i] and f[i - 1] <= s[i - 1] and bars.volume[i] > (sma20[i] or 1e18):
            pend = "L"
        elif ok and f[i] < s[i] and f[i - 1] >= s[i - 1]:
            pend = "C"
    assert st["closed_trades"] == len(trades)
    assert st["net_profit"] == pytest.approx(sum(trades), rel=1e-9)
    assert len(st["equity"]) == 600 and st["trades"][0]["dir"] == "long"


def manual_cross_backtest(bars, commission_pct=0.0, slip=0.0, initial=10000.0):
    f, s = ref_ema(bars.close, 20), ref_ema(bars.close, 50)
    sma20 = [None if i < 19 else sum(bars.volume[i - 19:i + 1]) / 20 for i in range(len(bars))]
    realized, pos, entry, qty, pend, entry_fee, pnls = 0.0, 0, 0.0, 0.0, None, 0.0, []
    for i in range(len(bars)):
        if pend:
            px = bars.open[i]
            if pend == "L" and pos == 0:
                qty = (initial + realized) / px
                entry = px + slip
                entry_fee = qty * entry * commission_pct / 100
                realized -= entry_fee
                pos = 1
            elif pend == "C" and pos == 1:
                exit_px = px - slip
                fee = qty * exit_px * commission_pct / 100
                realized += qty * (exit_px - entry) - fee
                pnls.append(qty * (exit_px - entry) - fee - entry_fee)
                pos = 0
            pend = None
        ok = i > 0 and all(x is not None for x in (f[i], s[i], f[i - 1], s[i - 1]))
        if ok and f[i] > s[i] and f[i - 1] <= s[i - 1] and bars.volume[i] > (sma20[i] or 1e18):
            pend = "L"
        elif ok and f[i] < s[i] and f[i - 1] >= s[i - 1]:
            pend = "C"
    return pnls


def test_backtest_fees_and_slippage_match_manual_and_reduce_profit():
    bars = make_bars(600, seed=11)
    base = run(S5, bars)["strategy"]
    costly = run(S5, bars, strategy_opts={"commission_pct": 0.1, "slippage": 0.25})["strategy"]
    want = manual_cross_backtest(bars, 0.1, 0.25)
    assert costly["closed_trades"] == len(want) > 0
    assert costly["net_profit"] == pytest.approx(sum(want), rel=1e-9)
    assert costly["net_profit"] < base["net_profit"]
    assert [t["pnl"] for t in costly["trades"]] == [pytest.approx(x, rel=1e-9) for x in want]
    # vốn ban đầu được ghi đè
    big = run(S5, bars, strategy_opts={"initial_capital": 50000.0})["strategy"]
    assert big["initial_capital"] == 50000.0 and big["equity"][0] == pytest.approx(50000.0, rel=1e-3)
