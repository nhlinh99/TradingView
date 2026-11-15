> **Cập nhật 14/11/2026.** File này là bản nghiên cứu ban đầu. Một số nhận định đã được kiểm chứng và sửa:
> - Binance có lịch sử `bookDepth` miễn phí từ 2023, nhưng chỉ ở dạng thô (6 dải, 30 giây).
> - XAUUSDT perpetual của Binance cho orderflow và heatmap vàng miễn phí, từ 11/12/2025.
> - Open interest Deribit trễ 8 giờ (Deribit xác nhận).
> - Cổ phiếu Việt Nam chỉ làm rổ VN100.
> - Giá, dung lượng, backtest: xem `docs/plan/archive/spec-original.md` và `docs/plan/plan.html`.
> Khi mâu thuẫn, các file `docs/plan/01-*.md` đến `09-*.md` là bản đúng. File này đã bị thay thế và chỉ giữ để tra cứu.

# Phương án clone TradingView (đầy đủ tính năng Premium)

## 0. Lưu ý pháp lý / thực tế (đọc trước)
- **Charting Library (Advanced Charts)** của TradingView là sản phẩm thương mại, không có source; cần xin license (có thể miễn phí cho website đạt điều kiện, cần xác nhận với TradingView: platforms@tradingview.com). **Lightweight Charts** thì Apache-2.0, miễn phí, nhưng bắt buộc attribution và chỉ có chart cơ bản (không có công cụ vẽ, đa khung, indicator built-in).
- **Pine Script không chạy ngoài TradingView.** Không có runtime chính thức. Phải: (a) tự viết interpreter/transpiler Pine v5/v6 → JS, hoặc (b) dùng dự án open-source (cần kiểm tra lại: PineTS cho JS, PyneCore cho Python), hoặc (c) viết indicator bằng JS/TS theo API tương tự Pine.
- **Không dùng tên/logo/branding TradingView**; clone UI quá giống có rủi ro pháp lý. Đặt tên riêng.
- **Dữ liệu sàn (CME, HOSE/HNX) có license redistribute** — dùng cho cá nhân/nội bộ thì ổn, public cho nhiều người dùng phải mua license.
- "Premium" của TV = đa chart/layout, nhiều indicator/chart, alert, volume profile/footprint, second-based timeframe, bar replay, custom timeframe, data realtime... Cần chia theo giai đoạn.

## 1. Kiến trúc đề xuất
```
[Data adapters] -> [Normalizer] -> [TimescaleDB/ClickHouse (OHLCV, ticks)]
                                   |-> [Redis pub/sub] -> [WebSocket gateway] -> Frontend
[Pine engine (Node worker / WASM)] <- bars từ DB, trả plots/labels/alerts
[Alert service] , [Auth/Billing], [Layout/Drawing storage (Postgres)]
```
- Frontend: React + TypeScript + Vite; chart = Lightweight Charts v5 (custom primitives/plugins cho drawing tools) hoặc Advanced Charts nếu được cấp license.
- Backend: Node (Fastify) hoặc Python (FastAPI) + WebSocket; Worker chạy Pine.
- DB: TimescaleDB (hoặc ClickHouse nếu cần tick/footprint); Redis cho realtime.

## 2. Nguồn dữ liệu có volume

| Symbol | Nguồn đề xuất | Volume | Ghi chú |
|---|---|---|---|
| **BTCUSD.P** (perp) | **Binance USDⓈ-M Futures** REST `/fapi/v1/klines` + WS `btcusdt@kline_1m`, `@aggTrade` (public, không cần key); thêm Bybit/OKX | Volume thật theo sàn (base + quote + taker buy volume → tính được delta/CVD) | Miễn phí. TV `BTCUSD.P` là Bitstamp/Bybit/… tuỳ sàn → chọn 1 sàn và ghi rõ. Có thể gộp đa sàn. |
| **GC1!** (COMEX Gold futures) | Trả phí: **Databento** (CME Globex MDP3, GLBX.MDP3), Polygon/Massive Futures, Rithmic/CQG/Barchart. Miễn phí/trễ: Yahoo `GC=F` (không ổn định, ToS) | Volume thật (số hợp đồng) | Phải tự ghép hợp đồng liên tục (roll theo volume/OI hoặc ngày hết hạn). Realtime CME cần license. |
| **XAUUSD** (spot) | Spot không có volume tập trung → chỉ có **tick volume** từ broker/LP: Dukascopy (tick data miễn phí, có bid/ask volume), OANDA, FXCM (có volume), MT5 broker; hoặc **dùng volume của GC1! làm proxy** | Tick volume (không phải volume thật) | Khuyến nghị: giá XAUUSD từ LP + volume từ GC1! (cách nhiều script TV đang làm). |
| **Cổ phiếu VN** | **SSI FastConnect Data** (chính thức, đăng ký consumer ID/secret; có EOD, IntradayOhlc, streaming), **vnstock** (Python, wrap VCI/TCBS/KBS… nguồn miễn phí, có thể thay đổi/chặn), DNSE/Entrade (chưa xác minh API), VNDirect/VPS endpoint không chính thức, FiinTrade/WiChart (trả phí) | Volume thật HOSE/HNX/UPCoM | Realtime chính thức: SSI/DNSE. Nên bọc qua adapter để thay nguồn dễ dàng. |

Chuẩn hoá: mọi nguồn → bar `{t,o,h,l,c,v, buyV?, sellV?}` + bảng `ticks` (nếu cần footprint/volume profile). Dùng aggTrade/tick để tự dựng nến mọi timeframe (cả giây).

Sources:
- [Binance USDⓈ-M Futures streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Continuous-Contract-Kline-Candlestick-Streams)
- [SSI FastConnect Data](https://guide.ssi.com.vn/ssi-products/fastconnect-data)
- [vnstock](https://github.com/vnstock-official/vnstock)
- [TradingView Charting Library compare](https://in.tradingview.com/charting-library-docs/latest/product-comparison/)
- [FXCM volume data](https://www.fxcm.com/pro/market-data/volume/)

## 3. Lộ trình
1. **MVP (3–4 tuần):** Lightweight Charts + Binance WS + DB; timeframe 1m→1M; volume pane; watchlist; symbol search.
2. **Data đa thị trường (3–4 tuần):** adapter SSI/vnstock, GC1! (Databento), XAUUSD; ghép contract liên tục; múi giờ/phiên giao dịch.
3. **Indicator & Pine (6–10 tuần):** thư viện `ta.*` (SMA, EMA, RSI, MACD, BB, ATR, VWAP…), `request.security` (đa khung/đa symbol), plot/fill/label/box/line, `strategy.*` backtest; editor Monaco + syntax highlight Pine.
4. **Drawing tools (4–6 tuần):** trendline, fib, channel, rectangle, text… lưu theo layout (dùng custom primitives).
5. **Premium features:** multi-chart layout đồng bộ crosshair, Volume Profile (VPVR/VPSR), footprint/CVD, bar replay, alerts (server-side, webhook/Telegram/email), screener, nhiều indicator/chart, giây timeframe, custom timeframe, template, chia sẻ chart.
6. **Auth/Billing/Ops:** đăng nhập, gói thuê bao (Stripe), rate limit, monitoring.

## 4. Pine Script áp dụng cho website
Dưới đây là script Pine v5 để chạy được **trên TradingView** và cũng là mẫu để engine của bạn hỗ trợ. Nhóm tính năng volume cho XAUUSD/BTC/GC1!/VN.

### 4.1 Volume thật cho XAUUSD từ GC1! + MA + màu tăng/giảm
```pine
//@version=5
indicator("Volume Proxy (GC1! for XAUUSD)", format=format.volume, overlay=false)

useProxy = input.bool(true, "Dùng volume GC1! khi symbol là spot/CFD")
maLen    = input.int(20, "MA length", minval=1)
proxySym = input.symbol("COMEX:GC1!", "Proxy symbol")

proxyVol = request.security(proxySym, timeframe.period, volume, lookahead=barmerge.lookahead_off)
vol = useProxy and (syminfo.type == "forex" or syminfo.type == "cfd") ? proxyVol : volume

up  = close >= open
col = up ? color.new(color.teal, 20) : color.new(color.red, 20)
plot(vol, "Volume", style=plot.style_columns, color=col)
plot(ta.sma(vol, maLen), "Vol MA", color=color.orange)
```

### 4.2 Delta / CVD xấp xỉ (dùng cho BTCUSD.P, VN stock)
```pine
//@version=5
indicator("Volume Delta + CVD (approx)", overlay=false)

rng   = high - low
buyV  = rng > 0 ? volume * (close - low) / rng : volume / 2
sellV = volume - buyV
delta = buyV - sellV

// CVD reset theo phiên
newSession = ta.change(time("D")) != 0
var float cvd = 0.0
cvd := newSession ? delta : cvd + delta

plot(delta, "Delta", style=plot.style_columns, color=delta >= 0 ? color.green : color.red)
plot(cvd,   "CVD",   color=color.blue)
```
> Ở website thật, thay công thức xấp xỉ bằng `takerBuyBaseVolume` của Binance (chính xác) hoặc tick data.

### 4.3 Relative Volume + cảnh báo đột biến (phù hợp cổ phiếu VN)
```pine
//@version=5
indicator("Relative Volume Alert", overlay=true)

len    = input.int(20, "Lookback")
mult   = input.float(2.0, "Ngưỡng x lần", step=0.1)
rvol   = volume / ta.sma(volume, len)
spike  = rvol >= mult and close > open

plotshape(spike, "Spike", shape.triangleup, location.belowbar, color.lime, size=size.small)
bgcolor(spike ? color.new(color.lime, 90) : na)
alertcondition(spike, "Volume Spike", "RVOL >= {{plot_0}} trên {{ticker}}")
```

### 4.4 VWAP + band theo phiên
```pine
//@version=5
indicator("Session VWAP Bands", overlay=true)
mult = input.float(1.0, "Std mult")
[v, up, lo] = ta.vwap(hlc3, ta.change(time("D")) != 0, mult)
plot(v, "VWAP", color.orange)
plot(up, "Upper", color.gray)
plot(lo, "Lower", color.gray)
```

### 4.5 Chiến lược mẫu để test engine backtest
```pine
//@version=5
strategy("EMA Cross + Volume filter", overlay=true, default_qty_type=strategy.percent_of_equity, default_qty_value=100)
fast = ta.ema(close, 20), slow = ta.ema(close, 50)
volOK = volume > ta.sma(volume, 20)
if ta.crossover(fast, slow) and volOK
    strategy.entry("L", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("L")
```

### 4.6 Tích hợp vào website
- Editor: Monaco + ngôn ngữ Pine; nút "Add to chart" gửi source → Pine worker.
- Worker nhận mảng bars → chạy → trả `{plots:[{name,data,style,color}], shapes, labels, alerts, strategyReport}`.
- Frontend vẽ plot bằng Lightweight Charts series/primitives; pane riêng cho indicator `overlay=false`.
- Phạm vi tương thích: bắt đầu với tập con (`ta.*`, `plot`, `plotshape`, `bgcolor`, `input.*`, `request.security`, `alertcondition`, `strategy.entry/close`), mở rộng dần; viết bộ test so sánh kết quả với TradingView.

## 5. Rủi ro chính
1. Volume XAUUSD spot không "thật" — phải nêu rõ là tick volume hoặc proxy GC1!.
2. Chi phí data realtime CME / VN nếu thương mại hoá.
3. Pine engine là hạng mục lớn nhất; nên giới hạn subset trước.
4. Nguồn không chính thức (vnstock/endpoint công khai) dễ vỡ → cần adapter + fallback.
5. License Charting Library & branding.

---
# Bản cập nhật: dùng 1 người + Orderflow + GEX

## A. Rút gọn kiến trúc cho 1 user (local)
Bỏ: Redis, TimescaleDB/ClickHouse cluster, auth, billing, rate limit, multi-tenant, WebSocket gateway.
```
[Collector (1 process, chạy nền)] -> Parquet/DuckDB (bars + ticks + options snapshots)
[Local server (FastAPI/Node)] <- đọc DuckDB, đẩy WS trực tiếp từ collector -> Browser (localhost)
[Pine engine: worker thread/process]
```
- Lưu trữ: **DuckDB + Parquet** (tick/aggTrade nén rất tốt, truy vấn nhanh). SQLite cho layout/drawing/alert.
- Chạy `localhost`, một process collector ghi liên tục; alert gửi Telegram/desktop notification.
- Chi phí chính chỉ còn là data; không cần real-time đa người dùng.

## B. Orderflow (footprint, delta, CVD, volume profile, bid/ask imbalance)
Cần **tick có aggressor side** (hoặc order book). Nguồn:

| Symbol | Nguồn | Orderflow được không |
|---|---|---|
| BTCUSD.P | **Binance Futures `aggTrade`** (WS realtime + `data.binance.vision` file lịch sử từ 2020 miễn phí). Trường `isBuyerMaker`: true = taker bán, false = taker mua. Thêm `@depth` cho heatmap/DOM. | **Có, đầy đủ, miễn phí** |
| GC1! | **Databento GLBX.MDP3**, schema `trades` (có `side`: Bid = buy aggressor, Ask = sell aggressor; implied trade có thể side=None), `mbp-1/mbp-10/mbo` cho DOM. Lịch sử từ 2010, tính theo GB; live nằm trong gói trả phí. | **Có, trả phí** (tốt nhất cho 1 người) |
| XAUUSD spot | Không có tape tập trung → **không có orderflow thật**. Dùng orderflow của GC1! (hoặc MGC) làm proxy, quy đổi giá theo basis. | Chỉ proxy |
| Cổ phiếu VN | Feed khớp lệnh của SSI/DNSE (chưa xác minh trường mua/bán chủ động); nếu không có thì phân loại bằng quy tắc quote/tick từ giá bid/ask. VN30F (phái sinh) cũng cần xác nhận nguồn. | Gần đúng, cần kiểm tra |

Cách tính footprint: gom trade theo (nến, mức giá) → `buyVol`, `sellVol`, `delta`, imbalance (ví dụ ask@p / bid@p-1 ≥ 3). Cần lưu tick, không chỉ OHLCV.

## C. GEX (Gamma Exposure)
GEX cần **chuỗi quyền chọn: strike, loại call/put, open interest, gamma (hoặc IV để tự tính Black-Scholes)**.
Công thức xấp xỉ mỗi strike: `GEX = gamma × OI × contractSize × spot² × 0.01`, call dương, put âm (giả định dealer long call/short put — chỉ là mô hình, không phải vị thế thật). Tổng theo strike → tìm *gamma flip*, call wall, put wall.

| Symbol | Nguồn options | GEX được không |
|---|---|---|
| **BTC** | **Deribit public API** (không cần key): `public/get_book_summary_by_currency?kind=option` (OI, mark IV) và `public/ticker` (greeks). Lưu ý: tài liệu ghi OI ở endpoint book summary **trễ ~8 giờ** nên GEX chỉ theo ngày, không intraday; cần kiểm tra lại. Deribit chiếm phần lớn OI options BTC; có thể thêm OKX/Bybit/CME BTC options. | **Có, miễn phí** |
| **Vàng (GC1!/XAUUSD)** | Options trên GC (ký hiệu OG) trong **Databento GLBX.MDP3** (parent symbol `OG.OPT`, `definition` + `statistics` lấy OI/settlement). Chú ý: từng có lỗi strike OG bị chia 100 → tự kiểm tra scale. Thay thế rẻ: options của ETF **GLD/IAU** (CBOE/Polygon/Tradier). XAUUSD spot không có options niêm yết. | **Có, trả phí** (GC options) hoặc proxy GLD |
| **Cổ phiếu VN** | Không có options cổ phiếu niêm yết (chỉ chứng quyền có đảm bảo & phái sinh VN30). | **Không áp dụng** |

Tính GEX tự code: tải chuỗi options → nếu chưa có gamma thì tính từ IV bằng Black-Scholes (`gamma = φ(d1)/(S·σ·√T)`), nhân OI → cộng theo strike → vẽ histogram/đường level lên chart (dùng custom primitive làm horizontal lines: gamma flip, call wall, put wall). Cập nhật mỗi vài phút–1 ngày tuỳ nguồn.

## D. Pine Script cho orderflow/GEX
- Pine trên TradingView **không có tick/aggressor/OI options** → không tự tính footprint/GEX thật được; Pine chỉ dùng xấp xỉ (delta từ nến).
- Trong website riêng: thêm **data feed mở rộng cho engine Pine**, ví dụ `request.external("delta")`, `request.external("gex_levels")` (API tự đặt, không phải Pine chuẩn) hoặc input `series` từ dữ liệu backend. Plot level GEX bằng `line.new`/`hline` tương đương.
Ví dụ script nhận GEX level từ input (dán tay hoặc từ backend) để chạy được cả trên TradingView:
```pine
//@version=5
indicator("GEX Levels (from input)", overlay=true)
flip  = input.float(0.0, "Gamma flip")
callW = input.float(0.0, "Call wall")
putW  = input.float(0.0, "Put wall")
// Với GC1!/XAUUSD: cộng/trừ basis nếu level lấy từ GC mà chart là spot
basis = input.float(0.0, "Basis (GC - XAU)")
hline(flip  > 0 ? flip  - basis : na, "Flip", color.yellow, hline.style_dashed)
hline(callW > 0 ? callW - basis : na, "Call wall", color.green)
hline(putW  > 0 ? putW  - basis : na, "Put wall", color.red)
```

## E. Chi phí & khuyến nghị cho 1 người
- Miễn phí hoàn toàn: BTC (Binance + Deribit) → orderflow + GEX làm trước, dùng làm PoC.
- Trả phí đáng giá: Databento (GC trades + OG options). Nên bắt đầu với dữ liệu lịch sử + gói live thấp nhất, kiểm tra giá hiện hành trước khi đăng ký.
- VN: chỉ có volume/OHLC + orderflow gần đúng; không GEX.
- Nếu chỉ phục vụ cá nhân, có thể dùng thẳng Lightweight Charts + custom primitives (không cần xin license Advanced Charts).

Sources:
- [Deribit get_book_summary_by_currency](https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency)
- [Databento trades schema](https://databento.com/docs/schemas-and-data-formats/trades)
- [Databento options on futures](https://databento.com/docs/examples/options/options-on-futures-introduction)
- [Databento GC futures](https://databento.com/catalog/cme/GLBX.MDP3/futures/GC)
- [Binance public data (aggTrade)](https://github.com/binance/binance-public-data/)
- [Binance aggTrade stream](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Aggregate-Trade-Streams)

---
# F. Heatmap thanh khoản (liquidity heatmap)
Hai loại khác nhau:
1. **Order-book heatmap (kiểu Bookmap)**: lệnh chờ trên sổ lệnh theo thời gian × giá. Dữ liệu thật, cần depth.
2. **Liquidation heatmap (kiểu Coinglass)**: vùng thanh lý ước tính từ giả định đòn bẩy → là mô hình, không phải dữ liệu thật.

| Symbol | Order-book heatmap | Liquidation |
|---|---|---|
| BTCUSD.P | Binance Futures `@depth` (diff stream) + REST snapshot `/fapi/v1/depth` → tự dựng sổ lệnh. Live miễn phí; **lịch sử phải tự ghi từ lúc bắt đầu** (hoặc mua từ nhà cung cấp như Tardis.dev — chưa xác minh giá/phạm vi). | `@forceOrder` (mẫu 1 lệnh/1000ms/symbol, nên thiếu) hoặc Coinglass API (modeled, heatmap thuộc gói cao — chưa xác minh giá) |
| GC1! (và XAUUSD proxy) | Databento: `mbp-10` (10 mức) hoặc `mbo` (từng lệnh, từ 05/2017); trước đó chỉ có mbp-10. Tự dựng order book từ MBO theo tutorial của Databento. | Không có (không có liquidation công khai) |
| Cổ phiếu VN | Feed của broker thường chỉ có vài mức giá tốt nhất (khoảng 3 mức, chưa xác minh) → heatmap rất nông. | Không áp dụng |

Lưu ý kỹ thuật:
- Thanh khoản hiển thị có thể là **spoofing/iceberg**; heatmap chỉ cho thấy lệnh chờ, không phải ý định.
- Không lưu mọi cập nhật: mỗi giây chụp sổ lệnh, gom vào bucket giá (vd 1 USD với BTC), lưu `(ts, price_bucket, bid_size, ask_size)` vào Parquet. Giảm dung lượng hàng trăm lần.
- Vẽ bằng canvas/WebGL (một ô màu mỗi `(thời gian, giá)`), chồng lên nến + volume bubble từ trade. Lightweight Charts không có sẵn → viết custom primitive.
- Liquidation tự dựng được: lấy OI, funding, trade để ước tính các mức thanh lý theo nhóm đòn bẩy (10x/25x/50x/100x), nhưng đó cũng chỉ là mô hình.

Thứ tự khuyến nghị: bật collector ghi depth BTC **ngay** vì lịch sử không thể lấy lại miễn phí.

Sources:
- [Binance liquidation stream](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Liquidation-Order-Streams)
- [Coinglass liquidation heatmap](https://docs.coinglass.com/v3.0/reference/liquidation-heatmap)
- [Databento MBP-10](https://databento.com/docs/schemas-and-data-formats/mbp-10)
- [Databento order book example](https://databento.com/docs/examples/order-book?lang=python)
