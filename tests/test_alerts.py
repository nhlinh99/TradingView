import json

import httpx
import pytest
from fastapi.testclient import TestClient

from collector import alerts
from common import appdb
from server.main import app

client = TestClient(app)
T = 1_794_700_000_000


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "tv-data"))
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)


def make(symbol="BTCUSDT", **cond):
    r = client.post("/api/alerts", json={"symbol": symbol, "condition": cond})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def state(i):
    con = appdb.connect()
    try:
        r = con.execute("SELECT enabled, condition FROM alerts WHERE id = ?", (i,)).fetchone()
        return bool(r[0]), json.loads(r[1])
    finally:
        con.close()


def events():
    return client.get("/api/alerts/events").json()


def boom(*a, **k):
    raise RuntimeError("mạng chết")


def test_check_price_and_cross():
    assert alerts.check_price({"type": "price", "op": ">=", "value": 100}, 100, None)
    assert not alerts.check_price({"type": "price", "op": ">=", "value": 100}, 99.9, None)
    assert alerts.check_price({"type": "price", "op": "<=", "value": 100}, 99, None)
    up = {"type": "cross", "level": 100, "dir": "up"}
    assert alerts.check_price(up, 101, 99) and not alerts.check_price(up, 101, 100.5) and not alerts.check_price(up, 99, 101)
    assert not alerts.check_price(up, 101, None)       # chưa có giá trước: không bắn
    assert alerts.check_price({"type": "cross", "level": 100, "dir": "down"}, 99, 101)
    assert alerts.check_price({"type": "cross", "level": 100}, 99, 101) and alerts.check_price({"type": "cross", "level": 100}, 101, 99)


def test_price_alert_fires_once_and_persists_state(data_root):
    i = make(type="price", op=">=", value=70000)
    sent = []
    notifier = lambda m: (sent.append(m), "desktop")[1]
    assert alerts.tick({"BTCUSDT": 69000.0}, notifier, now_ms=T) == 0 and sent == []
    assert alerts.tick({"BTCUSDT": 70500.0}, notifier, now_ms=T + 15_000) == 1
    assert "70500" in sent[0] and "BTCUSDT" in sent[0]
    on, cond = state(i)
    assert on is False and cond["triggered_at"] == T + 15_000          # đã tắt, không bắn lại
    assert alerts.tick({"BTCUSDT": 71000.0}, notifier, now_ms=T + 30_000) == 0 and len(sent) == 1
    ev = events()
    assert len(ev) == 1 and ev[0]["sent"] == "desktop" and ev[0]["alert_id"] == i


def test_cross_uses_previous_price_across_restarts(data_root):
    i = make(type="cross", level=100.0, dir="up")
    notifier = lambda m: "x"
    alerts.tick({"BTCUSDT": 99.0}, notifier, now_ms=T)
    assert state(i)[1]["last_price"] == 99.0                       # trạng thái nằm trong DB, không trong RAM
    assert alerts.tick({"BTCUSDT": 101.0}, notifier, now_ms=T + 1) == 1


def test_repeating_alert_has_cooldown(data_root):
    make(type="price", op=">=", value=10, once=False, cooldown_s=60)
    n = lambda m: "x"
    assert alerts.tick({"BTCUSDT": 11.0}, n, now_ms=T) == 1
    assert alerts.tick({"BTCUSDT": 11.0}, n, now_ms=T + 30_000) == 0
    assert alerts.tick({"BTCUSDT": 11.0}, n, now_ms=T + 61_000) == 1


def test_missing_price_does_not_break_other_alerts(data_root):
    make(type="price", op=">=", value=1)                 # BTC: có giá
    b = make("XAUUSDT", type="price", op=">=", value=1)  # XAU: thiếu giá nên bỏ qua
    assert alerts.tick({"BTCUSDT": 5.0}, lambda m: "telegram", now_ms=T) == 1
    assert state(b)[0] is True and events()[0]["symbol"] == "BTCUSDT"


def test_notify_collects_successful_channels_and_telegram_payload(data_root, monkeypatch):
    seen = {}

    def handler(req):
        seen["url"], seen["body"] = str(req.url), json.loads(req.content)
        return httpx.Response(200, json={"ok": True})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    alerts.send_telegram("xin chào", httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen["url"] == "https://api.telegram.org/botTOK/sendMessage" and seen["body"] == {"chat_id": "42", "text": "xin chào"}
    monkeypatch.setattr(alerts, "send_desktop", boom)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert alerts.notify("x", ("desktop", "telegram")) == ""         # cả hai lỗi: không kênh nào
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    monkeypatch.setattr(alerts, "send_telegram", lambda m, c=None: None)
    assert alerts.notify("x", ("desktop", "telegram")) == "telegram"  # desktop lỗi không chặn telegram


def test_pine_alert_fires_once_per_new_closed_bar(data_root):
    src = 'indicator("t")\nalertcondition(close > open, "Up bar", "msg")\n'
    i = make(type="pine", source=src, tf="5m", title="Up bar")
    sent = []
    seq = iter([(False, 100), (True, 160), (True, 160), (True, 220)])
    n = lambda m: (sent.append(m), "desktop")[1]
    for k in range(4):
        alerts.tick({}, n, now_ms=T + k, pine_eval=lambda a: next(seq))
    assert len(sent) == 2                       # nến 160 bắn một lần dù được kiểm hai lần; nến 220 bắn tiếp
    assert state(i)[1]["last_bar"] == 220 and state(i)[0] is True


def test_api_validation_and_crud(data_root):
    bad = [{"type": "price", "op": "=", "value": 1}, {"type": "price", "op": ">=", "value": "x"}, {"type": "cross", "level": 1, "dir": "left"},
           {"type": "pine", "source": "plot(close)"}, {"type": "zzz"}]
    for c in bad:
        assert client.post("/api/alerts", json={"symbol": "BTCUSDT", "condition": c}).status_code == 422, c
    assert client.post("/api/alerts", json={"symbol": "NOPE", "condition": {"type": "price", "op": ">=", "value": 1}}).status_code == 404
    i = make(type="price", op=">=", value=5)
    lst = client.get("/api/alerts").json()
    assert lst[0]["id"] == i and lst[0]["enabled"] and "BTCUSDT giá >= 5" in lst[0]["text"]
    assert client.patch(f"/api/alerts/{i}", json={"enabled": False}).json()["enabled"] is False
    assert client.get("/api/alerts").json()[0]["enabled"] is False
    assert client.delete(f"/api/alerts/{i}").status_code == 200 and client.delete(f"/api/alerts/{i}").status_code == 404


def test_failed_delivery_is_retried_then_recorded(data_root):
    i = make(type="price", op=">=", value=1)
    sent = []
    n = lambda m: (sent.append(m), "")[1]          # không kênh nào gửi được
    assert alerts.tick({"BTCUSDT": 5.0}, n, now_ms=T) == 0
    assert state(i)[0] is True and events() == []   # vẫn chờ, chưa ghi nhận
    assert alerts.tick({"BTCUSDT": 5.0}, n, now_ms=T + 1) == 0
    assert alerts.tick({"BTCUSDT": 5.0}, n, now_ms=T + 2) == 1   # lần thứ 3: bỏ cuộc, ghi lại với sent rỗng
    assert state(i)[0] is False and events()[0]["sent"] == "" and len(sent) == 3
    j = make(type="price", op=">=", value=1)
    ok = iter(["", "desktop"])
    assert alerts.tick({"BTCUSDT": 5.0}, lambda m: next(ok), now_ms=T + 3) == 0
    assert alerts.tick({"BTCUSDT": 5.0}, lambda m: next(ok), now_ms=T + 4) == 1 and events()[0]["sent"] == "desktop"
