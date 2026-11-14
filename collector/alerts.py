"""Bộ kiểm tra cảnh báo chạy nền, độc lập với trình duyệt: đóng web thì cảnh báo vẫn bắn.

Điều kiện lưu trong bảng `alerts` (cột `condition` là JSON):
  {"type": "price", "op": ">=" | "<=", "value": 70000}            bắn khi giá thoả điều kiện
  {"type": "cross", "level": 70000, "dir": "up" | "down" | "any"}  bắn khi giá cắt qua mức giữa hai lần kiểm
  {"type": "pine", "source": "...", "tf": "5m", "title": "Volume Spike"}   bắn khi `alertcondition` đúng ở nến vừa đóng
Mặc định mỗi cảnh báo chỉ bắn một lần rồi tự tắt (`once`: false để bắn lặp). Trạng thái (giá lần trước, nến Pine đã
xét) lưu trong chính JSON nên khởi động lại tiến trình không làm bắn lại hay bỏ sót.

Kênh gửi: thông báo Windows (toast) và Telegram nếu `.env` có TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID. Lỗi một kênh
không chặn kênh khác; kết quả ghi trong `alert_events.sent`.

Chạy:  python -m collector.alerts [--interval 15]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from typing import Callable

import httpx

from common import appdb, store

log = logging.getLogger("collector.alerts")

INTERVAL_S = 15


# ---------- logic điều kiện (thuần) ----------

def check_price(cond: dict, price: float, prev: float | None) -> bool:
    t = cond.get("type")
    if t == "price":
        return price >= cond["value"] if cond["op"] == ">=" else price <= cond["value"]
    if t == "cross":
        if prev is None:
            return False
        lv, d = cond["level"], cond.get("dir", "any")
        up = prev < lv <= price
        down = prev > lv >= price
        return up if d == "up" else down if d == "down" else (up or down)
    return False


def describe(symbol: str, cond: dict) -> str:
    t = cond.get("type")
    if t == "price":
        return f"{symbol} giá {cond['op']} {cond['value']}"
    if t == "cross":
        return f"{symbol} cắt {cond.get('dir', 'any')} mức {cond['level']}"
    return f"{symbol} Pine: {cond.get('title') or 'alertcondition'}"


# ---------- kênh gửi ----------

def send_desktop(title: str, message: str) -> None:
    """Toast Windows bằng PowerShell, không cần module bổ sung."""
    esc = lambda s: s.replace("'", "''").replace("\n", " ")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
        "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent('ToastText02');"
        f"$t=$x.GetElementsByTagName('text');$t.Item(0).AppendChild($x.CreateTextNode('{esc(title)}'))|Out-Null;"
        f"$t.Item(1).AppendChild($x.CreateTextNode('{esc(message)}'))|Out-Null;"
        "$n=[Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('TradingView local').Show($n)"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace")[:200])


def send_telegram(message: str, client: httpx.Client | None = None) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong .env")
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        r = client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": message})
        if r.status_code != 200:
            raise RuntimeError(f"Telegram trả về HTTP {r.status_code}")
    finally:
        if own:
            client.close()


def notify(message: str, channels: tuple[str, ...] = ("desktop", "telegram")) -> str:
    """Gửi qua các kênh, trả về danh sách kênh thành công (ngăn cách bằng dấu phẩy)."""
    ok = []
    for ch in channels:
        try:
            if ch == "desktop":
                send_desktop("Cảnh báo", message)
            elif ch == "telegram":
                send_telegram(message)
            ok.append(ch)
        except Exception as e:  # noqa: BLE001 - một kênh lỗi không chặn kênh khác
            log.warning("kênh %s lỗi: %s", ch, e)
    return ",".join(ok)


# ---------- nguồn giá ----------

def latest_prices(symbols: set[str]) -> dict[str, float]:
    """Giá gần nhất của từng symbol: Binance qua REST ticker, cổ phiếu VN qua bảng giá SSI (đơn vị nghìn đồng)."""
    from collector import binance, vn
    out: dict[str, float] = {}
    crypto = [s for s in symbols if store.symbol_config(s).get("market") != "vn"]
    vns = {s for s in symbols if store.symbol_config(s).get("market") == "vn"}
    if crypto:
        client = binance.make_client()
        try:
            for s in crypto:
                try:
                    out[s] = float(binance.get_json(client, "/fapi/v1/ticker/price", {"symbol": s})["price"])
                except Exception as e:  # noqa: BLE001
                    log.warning("không lấy được giá %s: %s", s, e)
        finally:
            client.close()
    if vns:
        try:
            with vn.make_client() as c:
                for r in vn.fetch_group(c):
                    if r.get("stockSymbol") in vns and r.get("matchedPrice"):
                        out[r["stockSymbol"]] = float(r["matchedPrice"]) / 1000.0
        except Exception as e:  # noqa: BLE001
            log.warning("không lấy được bảng giá VN: %s", e)
    return out


# ---------- vòng kiểm ----------

def load_alerts(con) -> list[dict]:
    rows = con.execute("SELECT id, symbol, condition FROM alerts WHERE enabled = 1 ORDER BY id").fetchall()
    return [{"id": r[0], "symbol": r[1], "cond": json.loads(r[2])} for r in rows]


def save_cond(con, alert_id: int, cond: dict, enabled: bool | None = None) -> None:
    if enabled is None:
        con.execute("UPDATE alerts SET condition = ? WHERE id = ?", (json.dumps(cond), alert_id))
    else:
        con.execute("UPDATE alerts SET condition = ?, enabled = ? WHERE id = ?", (json.dumps(cond), int(enabled), alert_id))


MAX_SEND_ATTEMPTS = 3


def fire(con, alert: dict, message: str, now_ms: int, notifier: Callable[[str], str]) -> bool:
    """Gửi thông báo. Nếu không kênh nào gửi được thì giữ cảnh báo ở trạng thái chờ (trả về False) để thử lại ở lượt sau,
    tối đa MAX_SEND_ATTEMPTS lần; sau đó ghi nhận là đã bắn với `sent` rỗng để không mất dấu vết."""
    cond = alert["cond"]
    sent = notifier(message)
    if not sent and cond.get("attempts", 0) + 1 < MAX_SEND_ATTEMPTS:
        cond["attempts"] = cond.get("attempts", 0) + 1
        log.warning("không kênh nào gửi được (lần %d): %s", cond["attempts"], message)
        return False
    cond.pop("attempts", None)
    con.execute("INSERT INTO alert_events(alert_id, ts, symbol, message, sent) VALUES (?, ?, ?, ?, ?)",
                (alert["id"], now_ms, alert["symbol"], message, sent))
    log.info("ĐÃ BẮN: %s (gửi: %s)", message, sent or "không kênh nào")
    return True


def pine_triggers(alert: dict) -> tuple[bool, int | None]:
    """Chạy script Pine của cảnh báo; trả về (alertcondition đúng ở nến đã đóng mới nhất?, thời điểm nến đó)."""
    from server import pine_api
    cond = alert["cond"]
    bars = pine_api.load_bars(alert["symbol"], cond.get("tf", "5m"), 500)
    if bars is None or len(bars) < 3:
        return False, None
    res = pine_api.runner.run_script(cond["source"], bars, symbol=alert["symbol"], tf=cond.get("tf", "5m"))
    closed = len(bars) - 2           # nến cuối còn đang chạy; nến kề trước đã đóng
    for a in res["alerts"]:
        if cond.get("title") and a["title"] != cond["title"]:
            continue
        if closed in a["bars"]:
            return True, bars.time[closed]
    return False, bars.time[closed]


def tick(prices: dict[str, float] | Callable[[set[str]], dict[str, float]] = latest_prices,
         notifier: Callable[[str], str] = notify, now_ms: int | None = None, pine_eval=pine_triggers) -> int:
    """Một lượt kiểm tất cả cảnh báo đang bật. Trả về số cảnh báo đã bắn."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    appdb.init()
    con = appdb.connect()
    fired = 0
    try:
        alerts = load_alerts(con)
        price_alerts = [a for a in alerts if a["cond"].get("type") in ("price", "cross")]
        px = prices({a["symbol"] for a in price_alerts}) if callable(prices) else prices
        for a in alerts:
            cond = a["cond"]
            try:
                if cond.get("type") in ("price", "cross"):
                    price = px.get(a["symbol"])
                    if price is None:
                        continue
                    hit = check_price(cond, price, cond.get("last_price"))
                    if hit and now_ms - cond.get("triggered_at", 0) < cond.get("cooldown_s", 300) * 1000:
                        hit = False      # cảnh báo lặp: không bắn dồn dập khi giá nằm yên trong vùng điều kiện
                    cond["last_price"] = price
                    if hit and fire(con, a, cond.get("message") or f"{describe(a['symbol'], cond)} (giá {price})", now_ms, notifier):
                        fired += 1
                        cond["triggered_at"] = now_ms
                        save_cond(con, a["id"], cond, enabled=not cond.get("once", True))
                    else:
                        save_cond(con, a["id"], cond)
                elif cond.get("type") == "pine":
                    hit, bar_t = pine_eval(a)
                    if bar_t is None or bar_t == cond.get("last_bar"):
                        continue
                    if hit and not fire(con, a, cond.get("message") or describe(a["symbol"], cond), now_ms, notifier):
                        save_cond(con, a["id"], cond)      # chưa gửi được: không đánh dấu nến đã xét, lượt sau thử lại
                        continue
                    cond["last_bar"] = bar_t
                    if hit:
                        fired += 1
                        cond["triggered_at"] = now_ms
                        save_cond(con, a["id"], cond, enabled=not cond.get("once", False))
                    else:
                        save_cond(con, a["id"], cond)
            except Exception:  # noqa: BLE001 - một cảnh báo lỗi không chặn các cảnh báo khác
                log.exception("cảnh báo %s lỗi", a["id"])
        con.commit()
    finally:
        con.close()
    return fired


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=INTERVAL_S)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001
            log.exception("lượt kiểm lỗi")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
