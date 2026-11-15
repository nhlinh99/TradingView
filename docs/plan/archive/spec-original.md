# Plan cho Claude Code: Chart cá nhân kiểu TradingView

> Đặc tả gốc từng phase, giữ để tra cứu. Trạng thái hiện tại, số đo và việc còn mở nằm trong các file `docs/plan/01-*.md` đến `09-*.md`. Chỗ nào mâu thuẫn thì các file đó là bản đúng.

Đối tượng đọc: Claude Code. Làm theo thứ tự. Mỗi phase có điều kiện nghiệm thu. Không sang phase sau khi phase trước chưa qua.

## Ràng buộc chung
- **Chỉ dùng nguồn miễn phí theo mặc định.** Không đăng ký, không mua dữ liệu, không dùng key trả phí khi chưa hỏi người dùng. Phase đánh dấu "trả phí" là tuỳ chọn.
- Một người dùng, chạy trên `localhost`. Không làm auth, billing, Redis, multi-tenant.
- Không bịa dữ liệu. Nếu nguồn lỗi hoặc thiếu key, báo lỗi rõ ràng và dừng bước đó.
- Lưu key trong `.env`. Không commit `.env`. Không in key ra log.
- Không dùng tên hay logo TradingView trong giao diện.
- Mỗi phase kết thúc bằng một lệnh chạy được và một ảnh chụp màn hình.
- Ghi vào `NOTES.md` mọi điểm chưa xác minh và mọi quyết định đã đổi.

## Stack cố định
| Lớp | Chọn |
|---|---|
| Collector và API | Python 3.12, FastAPI, `websockets`, `httpx` |
| Lưu trữ | DuckDB + file Parquet (tick, depth, options). SQLite cho layout, hình vẽ, alert |
| Frontend | Vite, React, TypeScript, `lightweight-charts` v5 |
| Vẽ nặng (heatmap, footprint) | Custom primitive trên canvas 2D. Dùng WebGL chỉ khi canvas chậm |

Cấu trúc thư mục:
```
collector/   # ghi dữ liệu nền
server/      # FastAPI: REST + WebSocket
web/         # React app
# dữ liệu nằm ngoài OneDrive, đặt bằng DATA_DIR trong .env (ví dụ C:\tv-data)
NOTES.md
```

## Lưu trữ và thu gọn
Số đo thật từ một ngày dữ liệu Binance (10/11/2026). Ngày biến động mạnh có thể gấp 2 đến 3 lần.

| Dữ liệu một ngày | BTCUSDT | XAUUSDT |
|---|---|---|
| Số lệnh khớp (aggTrades) | 1.521.662 | 602.627 |
| File CSV gốc | 101,1 MB | 38,1 MB |
| Parquet zstd, đủ cột | 6,65 MB | 2,85 MB |
| Parquet, bỏ id, giá dạng số nguyên, qty float32 | 5,22 MB | chưa đo |
| Footprint gom 1 phút, bucket 1 USD (BTC) hoặc 0,01 (XAU) | 0,34 MB | 0,90 MB |
| bookDepth của Binance (zip, 30 giây/lần) | khoảng 0,56 MB | 0,57 MB |

Ước tính dài hạn (BTC + XAUUSDT, nhân từ số đo một ngày):

| Cách lưu | 1 năm | 5 năm |
|---|---|---|
| Giữ CSV gốc | khoảng 51 GB | khoảng 254 GB |
| Parquet đủ cột, giữ mọi tick | khoảng 3,5 GB | khoảng 17 GB |
| Parquet, giữ tick 30 ngày, sau đó chỉ giữ footprint 1 phút | khoảng 0,7 GB | khoảng 2,5 GB |

### Quy tắc
1. **Thư mục dữ liệu nằm ngoài OneDrive.** Dùng `DATA_DIR` trong `.env`, ví dụ `C:\tv-data`. Thư mục dự án nằm trong OneDrive. Nếu để dữ liệu ở đó, OneDrive sẽ đồng bộ hàng nghìn file lớn và khoá file khi collector ghi.
2. **Chỉ lưu Parquet zstd (mức 9).** Không lưu CSV. Chia theo `kind/symbol/date=YYYY-MM-DD.parquet`. DuckDB đọc bằng glob.
3. **Schema gọn.** `ts` int64 mili giây, `p` int32 theo tick size của symbol (đặt `tick` trong config, không viết cứng), `q` float32, `m` bool. Sắp xếp theo `ts` trước khi ghi để nén tốt.
4. **Không lưu lại thứ tải lại được miễn phí.** aggTrades, klines và bookDepth của Binance tải lại được từ `data.binance.vision` (BTC từ 2020, XAUUSDT từ 11/12/2025). Collector chỉ cần giữ tick gần đây. Khi người dùng mở vùng cũ, tải file ngày đó về lại và lưu tạm.
5. **Thứ không tải lại được thì giữ kỹ:** sổ lệnh từng mức giá do collector tự ghi, snapshot options, dữ liệu trả phí.

### Chính sách giữ dữ liệu (file `retention.yaml`, sửa được)
| Loại | Giữ nguyên | Sau đó |
|---|---|---|
| Tick (aggTrades) | 30 ngày | Gom thành footprint 1 phút, xoá tick |
| Footprint 1 phút | mãi mãi | Không đổi |
| Sổ lệnh tự ghi (heatmap) | 7 ngày ở mức 5 giây | Gom thành 1 phút (lấy giá trị lớn nhất mỗi bucket), giữ 180 ngày, sau đó xoá |
| Snapshot options Deribit | mỗi giờ trong 30 ngày | Giữ 1 snapshot mỗi ngày |
| Nến 1 phút | mãi mãi | Không đổi |

Thiết kế sổ lệnh tự ghi: cửa sổ ±1% quanh giá, bucket 5 USD (khoảng 270 bucket), mỗi 5 giây một snapshot. Khoảng 4,6 triệu dòng mỗi ngày. **Dung lượng chưa đo.** Ước tính 15 đến 25 MB mỗi ngày ở mức 5 giây. Phase 1 phải đo con số thật sau 1 giờ chạy và ghi vào `NOTES.md`. Chỉnh bucket hoặc nhịp snapshot nếu vượt 25 MB mỗi ngày.

### Việc gom nén (`collector/compact.py`)
- Chạy mỗi đêm. Đọc `retention.yaml`, gom dữ liệu quá hạn, kiểm tra, rồi mới xoá bản gốc.
- Đặt trần `MAX_DATA_GB` (mặc định 20). Vượt trần thì xoá tầng cũ nhất theo thứ tự: sổ lệnh 1 phút, snapshot options, tick. Ghi log mọi lần xoá.
- Gom footprint làm mất độ phân giải dưới 1 phút. Sau khi gom, footprint của khung dưới 1 phút chỉ dựng lại được bằng cách tải lại file ngày đó từ Binance.

Nghiệm thu: chạy gom nén trên 3 ngày mẫu. Tổng mua, tổng bán và delta theo từng nến 1 phút trước và sau khi gom phải bằng nhau (sai số float32 dưới 1e-5 theo tỉ lệ). Dung lượng sau khi gom nhỏ hơn 10% bản tick.

## Dữ liệu lịch sử và backtest
Ngày bắt đầu lấy từ kho `data.binance.vision`, kiểm tra ngày 14/11/2026.

| Dữ liệu | Symbol | Từ ngày | Dùng cho |
|---|---|---|---|
| `aggTrades` (có cờ mua/bán) | BTCUSDT | 31/12/2019 | Footprint, delta, CVD, volume profile |
| `aggTrades` | XAUUSDT | 11/12/2025 | Như trên, mẫu ngắn (khoảng 11 tháng) |
| `trades` (từng lệnh) | BTCUSDT | 08/09/2019 | Chỉ khi cần chi tiết hơn aggTrades |
| Nến 1 phút | BTCUSDT | 31/12/2019 | Giá, volume |
| `metrics` (open interest, long/short, taker buy/sell, mỗi 5 phút) | BTCUSDT | 01/09/2020 | Bộ lọc vị thế |
| `bookDepth` (6 dải ±0,2% đến ±5%, cách 30 giây) | BTCUSDT | 01/01/2023 | Heatmap thô |
| `bookDepth` | XAUUSDT | 11/12/2025 | Heatmap thô |
| `bookTicker` (giá mua/bán tốt nhất) | BTCUSDT | 16/05/2023, ngừng 30/03/2024 | Spread |

Không có miễn phí:
- Sổ lệnh từng mức giá trong quá khứ. Chỉ có từ lúc collector bắt đầu ghi. Tardis.dev có bán (khoảng $700/tháng gói Solo, chưa xác nhận Binance L2 nằm trong gói).
- Lịch sử open interest options Deribit. Chỉ có từ lúc collector ghi snapshot.
- Lịch sử tick cổ phiếu Việt Nam. Chưa tìm thấy nguồn. Lịch sử sổ lệnh VN100 chỉ có từ lúc ghi.
- GC1! trước ngày trả phí. Databento có `mbp-10` từ 2010 và `mbo` từ 2017, giá theo GB không công bố.

### Việc cần làm
1. `collector/backfill.py`: tải file theo ngày (hoặc tháng cho dữ liệu cũ) từ kho Binance, kiểm tra checksum (`.CHECKSUM`), đổi sang Parquet theo schema gọn, ghi nhật ký ngày nào đã tải. Chạy lại không tải trùng.
2. Cho phép chọn khoảng ngày và symbol. Mặc định tải 30 ngày gần nhất. Hỏi người dùng trước khi tải hơn 1 năm (BTC 1 năm khoảng 2,4 GB Parquet, tải xuống khoảng 6,7 GB file nén).
3. `backtest/` đọc từ Parquet bằng DuckDB. Chiến lược nhận dữ liệu từng nến, kèm footprint, delta, và các cột `metrics` gần nhất.
4. Mọi tín hiệu dùng dữ liệu có `ts` nhỏ hơn hoặc bằng thời điểm đóng nến. Không dùng nến chưa đóng.
5. Mô hình phí và trượt giá cấu hình được (mặc định theo biểu phí taker của Binance Futures, kiểm tra trên trang Binance trước khi dùng).

### Giới hạn phải ghi trên báo cáo backtest
- `aggTrades` gộp lệnh cùng giá, cùng thời điểm. Không mô phỏng được khớp từng lệnh.
- Volume và orderflow là của Binance, không phải toàn thị trường.
- Backtest không mô phỏng vị trí hàng đợi và độ trễ. Tín hiệu từ lệnh chờ (heatmap) dễ đẹp hơn thực tế vì lệnh giả (spoofing).
- XAUUSDT chỉ có khoảng 11 tháng, kết quả có độ tin cậy thấp.

Nghiệm thu:
- Tải thử 3 ngày BTC. Checksum khớp. Volume nến 1 phút dựng từ tick khớp file nến Binance, sai lệch dưới 0,1%.
- Test chống nhìn trước: một chiến lược cố tình dùng giá đóng cửa của nến hiện tại để vào lệnh phải bị bộ kiểm tra từ chối.
- Chạy lại `backfill.py` không tải lại ngày đã có.

## Phase 0: Khung dự án
1. Tạo cấu trúc thư mục ở trên, `pyproject.toml`, `web/package.json`, `.gitignore`, `.env.example`.
2. Chạy `server` và `web` cùng lúc bằng một script `dev.ps1`.
3. **Kho dữ liệu.** Không cần cài máy chủ database. DuckDB là thư viện Python (`pip install duckdb`), Parquet là file, SQLite có sẵn trong Python. Việc cần làm:
   - Hỏi người dùng chọn `DATA_DIR` ngoài OneDrive (gợi ý `C:\tv-data`). Ghi vào `.env`. Từ chối nếu đường dẫn nằm trong thư mục OneDrive.
   - Tạo cây thư mục `DATA_DIR/{ticks,bars,book,options,vn_book}/` và file `app.sqlite` (watchlist, layout, hình vẽ, alert).
   - Viết `common/store.py`: một chỗ duy nhất định nghĩa schema (`ts` int64 ms, `p` int32 theo `tick` của symbol, `q` float32, `m` bool), đường dẫn `kind/symbol/date=YYYY-MM-DD.parquet`, hàm ghi (sắp xếp theo `ts`, zstd mức 9, ghi ra file tạm rồi đổi tên để không bị file nửa vời) và hàm đọc bằng DuckDB glob.
   - Viết `config/symbols.yaml` (tick size, nguồn) và `config/retention.yaml` (giá trị mặc định theo mục Lưu trữ).
4. Kiểm thử kho: ghi 1.000 dòng giả, đọc lại bằng DuckDB, so khớp từng dòng, rồi xoá dữ liệu giả.

Nghiệm thu: mở `http://localhost:5173`, thấy trang trống kèm dòng "server OK" lấy từ `/health`. Test kho ở bước 4 qua. `DATA_DIR` nằm ngoài OneDrive.

## Phase 1: Collector BTCUSD.P (Binance Futures)
1. Lấy nến 1m qua REST `/fapi/v1/klines`. Ghi vào bảng `bars`.
2. Nhận `btcusdt@aggTrade` qua WebSocket. Ghi `ts, price, qty, is_buyer_maker` vào Parquet theo giờ. `is_buyer_maker = true` nghĩa là taker bán.
3. Dựng lại nến mọi timeframe (1s đến 1d) từ tick. Tính `buy_vol` và `sell_vol` mỗi nến.
4. Nhận `btcusdt@depth` (diff) và snapshot REST. Giữ sổ lệnh trong bộ nhớ. Mỗi giây, gom vào bucket giá 1 USD và ghi `(ts, price_bucket, bid_size, ask_size)`.
5. Tự nối lại khi mất kết nối. Kiểm tra `lastUpdateId` để sổ lệnh không lệch.
6. Tải lịch sử aggTrade từ `data.binance.vision` cho 30 ngày gần nhất.
7. Gọi `backfill.py` (xem mục Dữ liệu lịch sử và backtest) thay vì tải thủ công.
8. Tải thêm `bookDepth` (cách 30 giây, độ sâu tích luỹ ở 6 dải ±0,2%, 1, 2, 3, 4, 5% quanh giá). Dùng nó cho bản đồ thanh khoản thô của giai đoạn trước khi collector chạy. Không dùng nó thay cho sổ lệnh từng mức giá.

Nghiệm thu: sau 10 phút chạy, `SELECT count(*)` trên bảng tick tăng đều. Đo dung lượng thật của sổ lệnh sau 1 giờ và ghi vào `NOTES.md`. Tổng `buy_vol + sell_vol` của nến 1m khớp volume của kline Binance, sai lệch dưới 0,1%.

## Phase 2: Chart cơ bản
1. API `GET /bars?symbol&tf&from&to` và WebSocket `/stream` đẩy nến đang chạy.
2. Frontend: nến, pane volume (màu theo hướng), chọn timeframe, crosshair, múi giờ chọn được.
3. Danh sách symbol bên trái (watchlist), lưu trong SQLite.

Nghiệm thu: nến BTC cập nhật theo thời gian thực. Cuộn về quá khứ tải thêm dữ liệu mà không giật.

## Phase 3: Orderflow
1. API `GET /footprint?symbol&tf&from&to` trả về `(bar_ts, price, buy_vol, sell_vol)`.
2. Chế độ footprint: mỗi nến hiện ô giá với `sell x buy`, màu theo imbalance (ngưỡng mặc định 3:1, chỉnh được).
3. Pane delta và CVD (reset theo phiên, chọn được).
4. Volume profile (VPVR và theo phiên) với POC, VAH, VAL.

Nghiệm thu: tổng delta trong footprint bằng delta của pane delta, với mọi nến kiểm tra. Viết test cho điều này.

## Phase 4: Heatmap thanh khoản
1. API `GET /heatmap?symbol&from&to&bucket` đọc bảng depth.
2. Primitive vẽ lớp heatmap dưới nến: trục x là thời gian, trục y là giá, màu là kích thước lệnh chờ. Chuẩn hoá màu theo phân vị 99.
3. Chồng bong bóng volume từ trade lớn lên heatmap (bật tắt được).

Nghiệm thu: heatmap cuộn và zoom cùng trục với nến. Với 2 giờ dữ liệu, vẽ dưới 100 ms mỗi khung hình.

## Phase 5: GEX cho BTC (Deribit)
1. Lấy chuỗi options từ Deribit public API: `public/get_book_summary_by_currency?kind=option` và `public/ticker` cho greeks. Lưu snapshot mỗi 15 phút.
2. Tính GEX mỗi strike: `gamma × OI × contract_size × spot² × 0.01`. Call dương, put âm. Nếu thiếu gamma, tính từ IV bằng Black-Scholes.
3. Tìm gamma flip, call wall, put wall. Vẽ thành đường ngang trên chart và một histogram GEX theo strike.
4. Hiện nhãn "OI trễ 8 giờ" trên UI. Deribit xác nhận điều này trong changelog, kể cả endpoint `ticker`. Giãn nhịp gọi API (có giới hạn tốc độ) và thử lại khi bị từ chối.

Nghiệm thu: tổng GEX khớp với tính tay trên 3 strike mẫu (ghi cách tính vào test).

## Phase 6: Vàng
### 6A. Bản miễn phí (làm trước): XAUUSDT perpetual của Binance
Binance ra mắt hợp đồng vàng XAUUSDT (perpetual, thanh toán USDT) đầu tháng 1/2026.
1. Đã kiểm chứng ngày 14/11/2026: `klines`, `aggTrades`, `depth` của `XAUUSDT` trả dữ liệu không cần key (hợp đồng loại `TRADIFI_PERPETUAL`). Kho lưu trữ có `aggTrades` và `bookDepth` từ 11/12/2025. Kiểm tra giờ giao dịch (`/fapi/v1/tradingSchedule`) và đơn vị khối lượng, ghi vào `NOTES.md`.
2. Dùng lại collector, footprint và heatmap của Phase 1, 3, 4 với symbol `XAUUSDT`.
3. Ghi chú trên UI: "Volume và orderflow của hợp đồng Binance, không phải COMEX".

Nghiệm thu: XAUUSDT hiện nến, footprint và heatmap. Giá lệch XAUUSD spot được ghi nhận trong `NOTES.md`.

### 6B. Tuỳ chọn, miễn phí nhưng chưa chắc: GEX vàng xấp xỉ từ options GLD
Lấy chuỗi options GLD (trễ khoảng 15 phút) từ Cboe delayed quotes hoặc Yahoo. Đọc điều khoản sử dụng trước khi tự động hoá và ghi kết luận vào `NOTES.md`. Nếu điều khoản cấm, bỏ phần này. Đây là ETF, không phải COMEX. Quy đổi mức giá sang XAUUSD bằng tỉ lệ GLD/spot.

### 6C. Tuỳ chọn, trả phí: GC1! và options vàng
Chỉ bắt đầu khi người dùng đồng ý trả tiền và `.env` có `DATABENTO_API_KEY`. Nếu không, bỏ qua.
1. Lấy `trades` và `mbp-10` của GC từ `GLBX.MDP3`. Ghép hợp đồng liên tục theo volume.
2. Options OG: lấy `definition` và `statistics`, tính GEX như Phase 5. Kiểm tra scale strike (từng có báo cáo lỗi chia 100).
3. Hỏi người dùng trước khi tải dữ liệu tính theo GB.

Nghiệm thu: GC1! hiện footprint thật.

## Phase 7: Cổ phiếu Việt Nam (chỉ VN100)
Phạm vi: chỉ các mã trong rổ VN100 (VN30 cộng 70 mã VNMidCap, đều niêm yết HOSE). Không thu thập mã ngoài rổ.

1. **Danh sách mã.** Không viết cứng. Lấy thành phần VN100 từ nguồn dữ liệu (SSI có endpoint danh sách chỉ số, hoặc trang của HOSE) và lưu vào `vn100.json` kèm ngày lấy. Rổ được rà soát định kỳ, nên cho phép cập nhật bằng một lệnh `refresh-vn100`. Mã rời rổ vẫn giữ dữ liệu cũ, chỉ ngừng thu thập.
2. **Adapter.** Interface chung `get_bars`, `stream_ticks`, `stream_book`. Cài hai nguồn: `vnstock` (miễn phí) cho nến, SSI FastConnect (cần key) cho streaming.
3. **Lệnh khớp.** SSI `X-TRADE` có trường `Side` (BU = mua lên, SD = bán xuống). Đó là hướng tick, không chắc là bên chủ động. Dùng nó cho delta gần đúng và ghi rõ trên UI.
4. **Sổ lệnh theo thời gian.** Chỉ chạy khi `.env` có khoá SSI. Đăng ký `X-QUOTE` cho các mã trong `vn100.json`. HOSE chỉ có 3 mức giá, nên mỗi dòng gồm `ts, symbol, bid1..3 (giá, khối lượng), ask1..3`. Ghi khi có thay đổi, không ghi theo nhịp cố định. Bỏ qua phiên ATO và ATC cho sổ lệnh liên tục, chỉ ghi `EstMatchedPrice`.
5. **Lưu trữ.** Parquet zstd theo `vn_book/symbol/date=YYYY-MM-DD.parquet`, nằm ngoài OneDrive. Sau 7 ngày gom thành snapshot mỗi phút. Dùng `retention.yaml` chung.
6. Hiển thị volume, volume profile, delta gần đúng, và bản đồ nhiệt nông 3 mức giá. Không làm GEX cho VN.
7. **Đo dung lượng.** Sau một phiên ghi thử, đo số dòng và dung lượng thật, ghi vào `NOTES.md`. Chưa có số đo.

Nghiệm thu:
- `vn100.json` có đúng 100 mã, tất cả trên HOSE.
- VNM, FPT, VCB hiển thị volume khớp trang nguồn.
- Sau một phiên, mỗi mã có sổ lệnh với số dòng lớn hơn 0.
- Tổng volume từ `X-TRADE` bằng volume nến ngày của vnstock, sai lệch dưới 0,5%.

Còn mở: giới hạn số mã đăng ký streaming cùng lúc trên một key SSI. Nếu dưới 100, chia nhiều kết nối hoặc ưu tiên VN30 trước.

## Phase 8: Engine Pine Script (tập con)
1. Parser cho Pine v5: `indicator`, `input.*`, biến `var`, `if`, `for`, hàm do người dùng định nghĩa.
2. Thư viện: `ta.sma, ema, rma, rsi, macd, bb, atr, vwap, crossover, crossunder`, `math.*`, `plot`, `plotshape`, `bgcolor`, `hline`, `alertcondition`.
3. `request.security` cho đa khung và đa symbol, không nhìn trước (`lookahead_off`).
4. Mở rộng riêng: `request.external("delta" | "cvd" | "gex_levels")`.
5. Editor Monaco trong web, nút "Add to chart".
6. Dùng 5 script mẫu trong `PLAN.md` (mục 4) làm bộ test. So kết quả với giá trị tính tay bằng pandas.

Nghiệm thu: cả 5 script chạy, đồ thị khớp pandas với sai số dưới 1e-9 cho SMA và EMA.

## Phase 9: Công cụ vẽ, layout, alert, backtest
1. Công cụ vẽ: đường xu hướng, đường ngang, fib, hình chữ nhật, văn bản. Lưu theo symbol và layout.
2. Layout nhiều chart (2 đến 4 ô) đồng bộ crosshair và thời gian.
3. Alert: điều kiện giá, điều kiện Pine `alertcondition`. Gửi qua thông báo desktop và Telegram (key trong `.env`).
4. Bar replay: phát lại nến và tick theo tốc độ chọn được.
5. Giao diện backtest: chọn chiến lược Pine (`strategy.*`), khoảng ngày, phí, trượt giá. Hiện đường vốn, danh sách lệnh, và các giới hạn ở mục Dữ liệu lịch sử và backtest.

Nghiệm thu: tạo alert, đóng trình duyệt, collector vẫn gửi thông báo khi điều kiện đúng.

## Việc đã kiểm chứng và việc còn mở (14/11/2026)
Đã kiểm chứng: XAUUSDT public API; kho Binance có `bookDepth`; Deribit open interest trễ 8 giờ; SSI có trường `Side`.
Còn mở (ghi vào `NOTES.md` khi kiểm tra):
- Giá theo GB và giá live của Databento cho CME (trang giá có thể cũ).
- Phí đăng ký SSI FastConnect, và giới hạn số mã streaming trên một key (cần đủ 100 mã).
- Điều khoản sử dụng dữ liệu options GLD của Cboe và Yahoo.
- Gói Coinglass nào có endpoint heatmap thanh lý.
- Đơn vị khối lượng của XAUUSDT.

## Khi bị kẹt
Dừng và hỏi người dùng nếu cần key, cần trả tiền, hoặc cần chọn giữa hai nguồn dữ liệu. Không đoán.
