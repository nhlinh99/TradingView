from datetime import datetime, timedelta, timezone

import pytest

from collector import backfill, compact, daily, klines


@pytest.fixture()
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(klines, "sync", lambda symbol, **kw: log.append(("klines", symbol)) or {"bars": 1})

    def fake_backfill(symbol, dataset, start, end, **kw):
        log.append(("backfill", symbol, dataset, start, end))
        return {"ok": 1, "skipped": 0, "missing": 0, "days": []}

    monkeypatch.setattr(backfill, "backfill", fake_backfill)
    monkeypatch.setattr(compact, "compact_all", lambda **kw: log.append(("compact",)) or {"merged_files": 0})
    return log


def test_order_klines_then_backfill_then_compact(calls):
    r = daily.run(["BTCUSDT", "XAUUSDT"])
    assert r["failures"] == []
    kinds = [c[0] for c in calls]
    assert kinds == ["klines", "backfill", "backfill", "backfill", "klines", "backfill", "backfill", "backfill", "compact"]
    assert [c[2] for c in calls if c[0] == "backfill"][:3] == ["aggTrades", "bookDepth", "metrics"]


def test_backfill_window_ends_yesterday_utc_and_spans_n_days(calls):
    daily.run(["BTCUSDT"], backfill_days=3)
    start, end = [c for c in calls if c[0] == "backfill"][0][3:5]
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    assert end == yesterday and (end - start).days == 2


def test_one_failing_step_does_not_block_the_rest(calls, monkeypatch):
    def boom(symbol, **kw):
        raise RuntimeError("mạng lỗi")

    monkeypatch.setattr(klines, "sync", boom)
    r = daily.run(["BTCUSDT"])
    assert len(r["failures"]) == 1 and "klines BTCUSDT" in r["failures"][0]
    assert ("compact",) in calls and sum(1 for c in calls if c[0] == "backfill") == 3


def test_failure_in_backfill_dataset_is_isolated(calls, monkeypatch):
    def flaky(symbol, dataset, start, end, **kw):
        calls.append(("backfill", symbol, dataset, start, end))
        if dataset == "bookDepth":
            raise backfill.ChecksumError("sai checksum")
        return {"ok": 1, "skipped": 0, "missing": 0, "days": []}

    monkeypatch.setattr(backfill, "backfill", flaky)
    r = daily.run(["BTCUSDT"])
    assert len(r["failures"]) == 1 and "bookDepth" in r["failures"][0]
    assert sum(1 for c in calls if c[0] == "backfill") == 3      # metrics vẫn chạy sau bookDepth lỗi


def test_skip_compact(calls):
    daily.run(["BTCUSDT"], do_compact=False)
    assert ("compact",) not in calls


def test_configured_symbols_come_from_config():
    assert {"BTCUSDT", "XAUUSDT"} <= set(daily.configured_symbols())


def test_main_exits_nonzero_on_failure(calls, monkeypatch):
    monkeypatch.setattr(klines, "sync", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("sys.argv", ["daily", "--symbols", "BTCUSDT"])
    with pytest.raises(SystemExit) as e:
        daily.main()
    assert e.value.code == 1
