# Ghi chú kỹ thuật

Quyết định đã đổi so với kế hoạch, số đo thật, và việc còn mở. Ngày đo: 14/11/2026.

## Quyết định đã đổi

| Điều | Kế hoạch ghi | Thực tế | Lý do |
|---|---|---|---|
| Định dạng cấu hình | YAML | TOML (`tomllib`) | PyYAML chưa có bản dựng sẵn cho Python 3.15 |
| `uvicorn[standard]` | có | `uvicorn` thường | `[standard]` kéo theo PyYAML. Mất tự reload |
| Schema `ticks` | `ts, p, q, m` | thêm `id` (aggregate trade id) | Cần khoá để loại trùng giữa backfill và collector, và để phát hiện khoảng hở |
| WebSocket aggTrade | `wss://fstream.binance.com/ws/...` | `/market/ws/<symbol>@aggTrade` | Binance đã chia đường dẫn (`/public`, `/market`, `/private`) và gỡ URL cũ ngày 2026-04-23. Đã thử: URL cũ im lặng với aggTrade |
| WebSocket depth | như trên | `/public/ws/<symbol>@depth@100ms` | Như trên |
| Cửa sổ sổ lệnh | ±1% quanh giá, bucket 5 USD | ±0,15% (BTC), ±0,30% (vàng), bucket 1 USD / 0,1 | Xem mục Số đo: snapshot chỉ phủ ±0,2% |
| `node_modules` của web | junction trực tiếp | cài ở `C:\tv-data\web-deps`, nối junction sau | `npm install` chạy trong `web\` xoá junction và cài vào OneDrive. Luôn dùng `scripts\web-deps.ps1` |
| File `.ps1` | có tiếng Việt | ASCII thuần | Windows PowerShell 5.1 đọc UTF-8 không BOM theo ANSI |

## Số đo thật

### Khớp giữa nến dựng từ tick và kline (3 ngày, 4320 nến 1 phút mỗi symbol)
| | BTCUSDT | XAUUSDT |
|---|---|---|
| Sai lệch tổng volume | 9,5e-9 | 1,2e-9 |
| Sai lệch tổng mua chủ động | 1,8e-10 | 7,8e-11 |
| Lệch lớn nhất một nến 1 phút | 27% | 350% (nến gần như không có volume) |
| Lệch lớn nhất một giờ | 0,67% | 1,3e-8 |
| Nến lệch giá mở/đóng | 187 | 55 |

Tổng khớp gần tuyệt đối và chiều mua/bán đúng. Lệch từng nến đến theo cặp bù trừ (ví dụ +55,8 BTC ở một phút, -55,8 ở phút kế): Binance gộp lệnh cùng giá trong 100ms thành một aggTrade và gán thời điểm của lệnh đầu, còn kline xếp từng lệnh theo thời điểm riêng. Đây là tính chất của dữ liệu. Nến 1 phút "chuẩn" vì vậy lấy từ kline (kho `bars`), còn nến dựng từ tick dùng cho timeframe khác. Ảnh hưởng tới backtest: tín hiệu dựa vào giá mở/đóng của nến sát ranh giới có thể lệch nhẹ so với TradingView.

Binance ghi aggTrade không gồm lệnh RPI (changelog 29/12/2025, trường mới `nq` và `st`). Chưa kiểm tra lệnh RPI có nằm trong kline hay không. Tổng khớp tới 1e-8 cho thấy ảnh hưởng không đáng kể ở hai symbol này.

### Dải giá của snapshot REST 1000 mức
| | Phủ |
|---|---|
| BTCUSDT | -0,207% / +0,199% |
| XAUUSDT | -0,364% / +0,352% |

Luồng diff gửi cập nhật cho mọi mức giá, nhưng mức ngoài dải chỉ được biết khi nó thay đổi. Vì giá di chuyển, collector lấy snapshot mới mỗi 60 giây (sổ cũ vẫn chạy cho tới khi sổ mới đồng bộ xong, rồi đổi). Mép ngoài của cửa sổ vẫn có thể thiếu nếu giá đi hơn khoảng 0,05% trong 60 giây. Chưa đánh dấu dòng nào là "không đầy đủ".

### Gom nén tick -> footprint 1 phút (dữ liệu thật, 3 ngày mỗi symbol)
| | Tick | Footprint | Tỉ lệ |
|---|---|---|---|
| BTCUSDT | 15,40 MB | 0,895 MB | 5,8% |
| XAUUSDT | 5,14 MB | 0,318 MB | 6,2% |

Đạt mục tiêu dưới 10%. Việc kiểm tra tổng mua và bán từng phút trước khi xoá tick qua trên dữ liệu thật.

### Sổ lệnh tự ghi (mẫu 14,4 phút, 173 snapshot; kế hoạch yêu cầu đo sau 1 giờ nên đây là sơ bộ)
| | BTCUSDT | XAUUSDT |
|---|---|---|
| Số bucket mỗi snapshot | khoảng 202 | khoảng 235 |
| Ngoại suy mỗi ngày, file con theo phút | 13,6 MB | 7,0 MB |
| Ngoại suy mỗi ngày, đã gộp một file | 12,5 MB | 2,5 MB |

Thấp hơn ước tính 15-25 MB trong kế hoạch, nhưng mẫu chỉ 14 phút ở một thời điểm trong ngày, nên số thật có thể lệch nhiều (lúc biến động mạnh số bucket đổi nhiều hơn và nén kém hơn). Đo lại: chạy `python -m collector.live_book` ít nhất một giờ rồi so dung lượng thư mục `book` với thời gian chạy. Collector sổ lệnh đã chạy 14 lần đồng bộ lại trong 14 phút (mỗi 60 giây một lần) và không có cảnh báo `pu != u`.

## Việc còn mở
- Đo lại dung lượng sổ lệnh trên mẫu dài hơn (xem trên).
- Backfill hàng tháng (`monthly/`) của kho Binance chưa làm. Daily đủ cho 30 ngày, nhưng tải nhiều năm sẽ cần monthly. `collector.backfill` hiện từ chối hơn 366 ngày nếu thiếu `--yes`.
- Khoảng hở lớn khi collector khởi động lâu sau lần ghi cuối: được lấp bằng REST ở luồng riêng (giãn 0,6 giây mỗi trang, khoảng 1,5 phút cho mỗi 100 nghìn dòng, tức khoảng 15 phút cho 900 nghìn id). Khoảng hở trên `max_gap` (5 triệu id) bị bỏ qua và ghi `skipped`, phải dùng `collector.backfill`.
- Lỗi thật đã sửa khi chạy nhiều giờ: luồng lấp khoảng hở chết vì `PermissionError` khi đọc `config/symbols.toml` (file nằm trong OneDrive, bị khoá tạm thời) và không tự thử lại. Nguyên nhân gốc là `to_int_price` đọc lại file TOML cho từng tick. Đã thêm nhớ đệm theo mtime, tiến độ có thể tiếp tục và tự thử lại. Bài học: mọi thứ nằm trong OneDrive đều có thể bị khoá bất ngờ, nên không đọc cấu hình trong vòng lặp nóng.
- Compaction chưa được cài lịch chạy. Xem README.
- Giá Databento, phí SSI, điều khoản options GLD, gói Coinglass: chưa xác minh (xem `PLAN-CLAUDE-CODE.md`).
- Đơn vị khối lượng của XAUUSDT: chưa xác minh (kho ghi `quantity` dạng số thập phân, tick 0,01, bước 0,001).

### Đo lại dung lượng sổ lệnh (1 giờ, 19:00-20:01 giờ máy)

Thư mục `book` sau 61 phút: BTCUSDT 0,56 MB (59 file part), XAUUSDT 0,31 MB (58 file part), chưa gộp. Quy ra khoảng 13 MB/ngày cho BTC, 7 MB/ngày cho XAU. Số BTC khớp mẫu 14 phút (12,5 MB/ngày). Số XAU cao hơn mẫu cũ (2,5 MB/ngày) vì file part chưa gộp nên còn tốn phần đầu file; sau `merge_day` số này sẽ giảm. Vẫn trong ngân sách kế hoạch (15-25 MB/ngày). Mới đo một giờ, chưa đo lúc biến động mạnh.

### Kiểm thử chạy thật (2026-11-14 20:02)

`scripts/run-collectors.ps1`: cả hai collector (trades, book) khởi động, log nằm ở `C:\tv-data\logs`. Kết thúc một tiến trình trades thì script dựng lại tiến trình mới trong vài giây. `python -m collector.daily` chạy xong 9 bước trong 3 giây, thoát mã 0, trong lúc collector vẫn chạy. Mỗi collector hiện hai PID trong danh sách tiến trình vì venv của Python 3.15 có một bộ khởi chạy và một tiến trình con; đó là bình thường. Phase 1 đóng.

### Vàng: XAUUSDT của Binance (kiểm tra 2026-11-14, Phase 6A)

- Hợp đồng: `TRADIFI_PERPETUAL`, `underlyingType` COMMODITY, tick 0,01 USDT, bước khối lượng 0,001. Khối lượng tính theo ounce vàng (1 hợp đồng = 1 oz; lệnh nhỏ nhất 0,001 oz).
- `/fapi/v1/tradingSchedule` báo nhóm COMMODITY đóng cửa từ thứ Sáu 22:00 đến Chủ nhật 23:00 UTC (NO_TRADING). Nhưng hợp đồng perpetual vẫn khớp lệnh suốt thứ Bảy 14/11: collector ghi 12 triệu tick trong 24 giờ, mọi giờ đều có lệnh. Vậy cuối tuần giá XAUUSDT không bám giá COMEX hay spot vì thị trường gốc nghỉ; đừng dùng nó để so sánh với XAUUSD vào cuối tuần.
- Chênh lệch với chỉ số của Binance: lúc đo, giá cuối 3878,84, `indexPrice` 3881,10, tức perp thấp hơn chỉ số khoảng 0,06%. Chưa có nguồn miễn phí cho XAUUSD spot để đối chiếu độc lập; khi có Databento (6C) thì so với GC.
- Dung lượng: khoảng 12 triệu tick/ngày, nhiều hơn BTC trong cùng ngày. Gom nén (`footprint_1m`) vẫn giữ nguyên quy tắc 30 ngày.
- UI ghi rõ: "Volume và orderflow của hợp đồng Binance, không phải COMEX".
- Phase 6B (GEX vàng từ options GLD) chưa làm: nguồn miễn phí tự động hoá được chưa kiểm chứng điều khoản sử dụng, và GLD là ETF chứ không phải COMEX. 6C (GC1!, options vàng) cần trả phí Databento, bỏ qua khi chưa có khoá. Cả hai là tuỳ chọn.

### VN100: nguồn và kiểm tra (Phase 7, 2026-11-14)

Không có khoá SSI FastConnect, nên dùng hai endpoint công khai không có tài liệu chính thức (có thể đổi hoặc bị chặn; chỉ dùng cá nhân, gọi thưa, chưa đọc điều khoản của hai bên):
- **Danh sách và bảng giá 3 mức**: SSI iBoard `iboard-query.ssi.com.vn/stock/group/VN100`. Trả đúng 100 mã, tất cả `hose`, 196 KB và 0,2 giây mỗi lần gọi. Có `best1..3Bid/Offer` kèm khối lượng, `nmTotalTradedQty`, `stockBUVol` (mua lên) và `stockSDVol` (bán xuống); BU + SD bằng đúng tổng khối lượng khớp. Đây là snapshot, không phải từng lệnh khớp, nên mọi số liệu orderflow VN là xấp xỉ theo nhịp lấy mẫu (10 giây).
- **Nến lịch sử**: VNDirect dchart `dchart-api.vndirect.com.vn/dchart/history`. Nến 1 phút có khoảng 270 ngày (từ 2025-10-31), ~29 000 nến mỗi mã. Giá là nghìn đồng, 3 chữ số thập phân (đã điều chỉnh sự kiện doanh nghiệp), nên kho dùng tick 0,001.
- Kiểm tra volume ngày (43 ngày gần nhất, tổng nến 1 phút so với nến ngày của dchart): VNM trung vị lệch 0,00%, tối đa 4,06%; FPT trung vị 0,85%, tối đa 7,84%; VCB trung vị 0,50%, tối đa 13,13%. Nến ngày của dchart khớp chính xác `nmTotalTradedQty` của SSI (VNM 2026-11-13: 2 391 600 ở cả hai). Vậy nến 1 phút của dchart thiếu một phần lệnh khớp ở một số ngày; chưa rõ nguyên nhân (nến ATO 09:15 và ATC 14:45 có mặt). Đích nghiệm thu 0,5% chỉ đạt với nến ngày, chưa đạt với tổng nến phút. Khi cần volume ngày chính xác, dùng nến ngày của dchart hoặc bộ đếm `tv` của sổ lệnh.
- Dung lượng nến 1 phút: ghi 131 file ngày mỗi mã trong lần nạp đầu; mỗi lần ghi file khoảng 0,2 giây nên nạp cả VN100 mất khoảng 1,5 giờ.
- Chưa có số đo sổ lệnh VN: thị trường đóng cửa vào thứ Bảy 14/11. Việc đo cần một phiên (thứ Hai 16/11).

### Engine Pine (Phase 8): khác với kế hoạch

- **Python, không phải Node/WASM.** Engine nằm ở `pine/` (lexer, parser, interpreter, `ta.py`) và chạy trong server Python, gần dữ liệu DuckDB. Phù hợp một người dùng, tránh dựng thêm tiến trình Node.
- **Tập con hỗ trợ**: `indicator`, `strategy`, `input.*`, `var`, `if/else if/else`, `for ... to ... by`, `while`, `break/continue`, hàm người dùng, tuple, `x[n]`, `ta.sma/ema/rma/rsi/macd/bb/atr/vwap/crossover/crossunder/change/highest/lowest/stdev/tr`, `math.*`, `nz`, `na`, `time("D"|"W"|"M"|"15")`, `plot`, `plotshape`, `bgcolor`, `hline`, `alertcondition`, `color.*`, `request.security`, `request.external("delta"|"cvd"|"gex_levels")`, `strategy.entry/close/close_all`. Không hỗ trợ: `switch`, mảng, `line.new/label.new/box.new`, `type/method`, `import`, `strategy.exit`.
- **`request.security` không nhìn trước**: tại nến đang xét chỉ dùng nến của khung/symbol kia đã đóng tại thời điểm đóng của nến này. Ví dụ khung giờ trên biểu đồ 1 phút: giá trị của giờ j chỉ xuất hiện ở phút cuối cùng của giờ j. `lookahead_on` cho thấy giá trị cuối cùng của giờ đang chạy ngay từ phút đầu. Test kiểm tra cả hai, và kiểm tra rằng đổi dữ liệu giờ sau không làm đổi giá trị trước đó.
- **Backtest** là bản tối giản: lệnh đặt ở nến i khớp ở giá mở của nến i+1, một vị thế ròng, không pyramiding, phí theo phần trăm. Không có trượt giá, `strategy.exit`, stop/limit. Bộ test so với mô phỏng viết tay trên 600 nến (số lệnh và lãi ròng khớp 1e-9).
- **Đối chiếu với pandas không làm được**: pandas cài được nhưng Windows Application Control chặn DLL của nó trên máy này (`DLL load failed ... blocked`), nên đã gỡ. Thay bằng: SMA, stdev, highest, lowest đối chiếu với hàm cửa sổ của DuckDB; EMA, RMA, RSI, ATR, MACD đối chiếu với bản cài đặt thuần Python viết riêng theo công thức (khởi tạo bằng SMA như Pine). Sai số cho phép 1e-9 tương đối; thực tế khớp hơn thế.
- **Editor là ô văn bản có tô màu cú pháp** (lớp `pre` phía sau ô `textarea` trong suốt, bộ tách từ nhẹ ở `highlightPine`), chưa phải Monaco: không có gợi ý tự động, gấp mã hay báo lỗi ngay khi gõ. Ctrl+Enter chạy lại. Mã lưu trong trình duyệt.
- **`bgcolor`** được vẽ thành cột mờ cao hết vùng giá trên một thang giá ẩn (chỉ cho script overlay). Marker của `plotshape` cũng chỉ vẽ cho script overlay.
- Script không đúng ngữ nghĩa Pine ở một số chỗ: gọi `ta.*` trong nhánh `if` cho kết quả sai (giống Pine); biến khai báo trong khối `if` lộ ra cả hàm bao ngoài.

### Phase 9: công cụ vẽ, layout, alert, replay, backtest (2026-11-15)

- **Công cụ vẽ**: đường xu hướng, đường ngang, hộp, Fibonacci, văn bản. Lưu trong SQLite theo symbol, điểm neo là (thời gian, giá) nên đúng ở mọi khung. Chưa kéo sửa điểm neo; muốn đổi thì xoá rồi vẽ lại. Chưa có layout đặt tên: bản vẽ dùng chung cho mọi ô của symbol đó.
- **Layout nhiều ô** (1, 2, 4): mỗi ô chọn symbol và khung riêng, lưu trong trình duyệt (localStorage), không lưu vào SQLite. Cuộn/zoom đồng bộ theo mốc thời gian và crosshair đồng bộ; chỉ lan truyền thay đổi do người dùng thao tác trực tiếp, để việc nạp dữ liệu của một ô không kéo các ô khác. Ô phụ chưa có Pine, replay. Mỗi ô mở một kết nối trực tiếp riêng (server dùng chung nguồn Binance).
- **Cảnh báo**: tiến trình nền `python -m collector.alerts` (đã thêm vào `run-collectors.ps1`) kiểm mỗi 15 giây, độc lập với trình duyệt và server web. Điều kiện: giá chạm mức, giá cắt mức, `alertcondition` của Pine ở nến vừa đóng. Trạng thái nằm trong SQLite nên khởi động lại không bắn lại hay bỏ sót. Nếu không kênh nào gửi được thì thử lại tối đa 3 lượt rồi ghi nhận với `sent` rỗng. Kênh: toast Windows và Telegram (cần `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` trong `.env`). **Chưa kiểm tra bằng mắt**: lệnh toast trả mã thành công nhưng tôi không xác nhận được thông báo có hiện trên màn hình; Telegram chưa thử vì chưa có khoá, chỉ có test với máy chủ giả.
- **Bar replay**: phát lại từng nến (tiến/lùi, phát/tạm dừng, 1 đến 30 nến/giây, thanh trượt) trên 1000 nến đã tải. Không phát lại tick, và lệnh khớp trực tiếp bị bỏ qua khi đang phát lại. Thoát replay thì nạp lại nến mới nhất.
- **Backtest**: dùng engine Pine, thêm vốn, phí, trượt giá (tick) và khoảng ngày. Phí và trượt giá được kiểm bằng mô phỏng tay. Mỗi lần tối đa 5000 nến. Giới hạn dữ liệu: delta, heatmap, GEX chỉ có từ lúc bắt đầu thu thập (BTC/XAU tick từ 2026-11-14 sau khi tải bù; nến 1 phút từ lịch sử Binance), nên backtest dựa trên các nguồn đó chỉ đúng trong khoảng này.


### Khung tuần và tháng

Thêm `1w` (tuần, bắt đầu thứ Hai 00:00 UTC) và `1M` (tháng dương lịch, bắt đầu ngày 1 00:00 UTC), gộp từ nến 1 phút trong DuckDB. Ranh giới theo lịch, không chia đều từ epoch (chia đều thì tuần bắt đầu thứ Năm). Nến tuần/tháng đang chạy cập nhật theo lệnh khớp trực tiếp với cùng ranh giới. Không hỗ trợ `2M`, `2w`. Footprint không hỗ trợ hai khung này. Ngày tính theo UTC nên tuần của cổ phiếu VN (phiên 02:00-08:00 UTC) vẫn đúng.


### Thiết kế orderflow theo DeepCharts

Nguồn tham khảo: trang trợ giúp DeepDom về heatmap và ghi chú bản v15.6 của DeepCharts. Không có ảnh chụp hay đặc tả màu chính thức, nên mã màu và tỉ lệ là của dự án, chỉ giữ thứ tự thang màu và ý tưởng.
- Đã làm: thang heatmap đen, xanh dương, trắng, vàng, cam, đỏ; kiểu màu mua (xanh lá) và bán (tím); thang tự chuẩn hoá theo phân vị 99; footprint có kiểu Bid x Ask, Delta, Volume, Profile; chữ tự co; thống kê delta và volume dưới nến; stacked imbalance; ký hiệu lệnh lớn đặc và rỗng.
- Chưa làm: DOM ladder (thiếu dữ liệu sổ lệnh tức thời trên giao diện), nhiều cột footprint cạnh nhau (Multi Column), phân biệt thanh khoản mới và thanh khoản tồn tại lâu, ký hiệu hình vuông và hình thoi của Deep Trades (cần dữ liệu MBO để biết lệnh chờ hay lệnh chủ động; Binance chỉ có aggTrade), Imbalance Horizontal, FVG.
- Lệnh lớn của DeepCharts phân loại bằng MBO. Ở đây vòng đặc nghĩa là cụm chỉ có một aggTrade, vòng rỗng là nhiều aggTrade trong cùng ô thời gian và giá, nên không tương đương hoàn toàn.


### Thiết kế orderflow theo Bookmap

Nguồn tham khảo: kết quả tìm kiếm về Bookmap (heatmap, volume dots, iceberg, CVD) và blog bản 7 của Bookmap; chưa đọc tài liệu gốc. Màu mặc định của Bookmap được các nguồn mô tả không thống nhất nên thang màu ở đây là của dự án.
- Đã làm: kiểu màu Bookmap (mặc định), cắt thấp/cao, đường bid/ask tốt nhất bậc thang, dải volume mua/bán dưới đáy, cỡ chấm và lọc chấm nhỏ, dấu hiệu iceberg.
- **Iceberg chỉ là ước lượng độ tin cậy thấp.** Ô (thời gian, giá) bị đánh dấu khi khối lượng khớp lớn hơn 5 lần thanh khoản hiển thị ở phía bị đánh. Sổ lệnh của dự án chỉ lấy mẫu mỗi 5 giây và gom theo bucket 1 USD (BTC), còn khối lượng khớp cộng cả ô thời gian, nên trên dữ liệu thật hàng nghìn ô vượt ngưỡng chỉ vì dòng lệnh bình thường. Vì vậy API chỉ giữ 40 ô có khối lượng khớp lớn nhất. Bookmap suy luận tương tự nhưng dùng dữ liệu sổ lệnh đầy đủ từng lệnh (MBO); ở đây không có.
- Chưa làm: gom chấm kiểu "Smart", đặt lệnh và phát hiện lệnh stop, cột volume và delta theo mức giá ở mép phải gắn với heatmap (đã có VPVR riêng), thanh trượt thật thay cho ô chọn.


### Cải thiện giao diện (dễ dùng hơn)

Header từ ba hàng ô chọn xuống một hàng; gom tính năng orderflow vào bảng "Chỉ báo" có mẫu dựng sẵn, công tắc, thanh trượt và mô tả; nút phân đoạn cho khung thời gian và bố cục; thanh vẽ dùng biểu tượng. Trên điện thoại (390 px) vùng biểu đồ chiếm hơn một nửa màn hình thay vì khoảng một phần ba; ô chọn múi giờ bị ẩn ở màn hình hẹp (giá trị đã lưu vẫn dùng). Đã thêm sau đó: hộp tìm symbol (`/`, `Ctrl+K`) và phím tắt (`[` `]`, `T`, `?`). Danh sách theo dõi kéo thả để sắp xếp được (lưu vào SQLite).


### Gộp nóng file con trong ngày

Mỗi collector ghi một file con mỗi 60 giây, nên cuối ngày mỗi symbol có hàng trăm file và truy vấn chậm đi (một lần tải biểu đồ từng mất khoảng 15 giây khi có hơn 1000 file con của hôm nay). `python -m collector.hotmerge` (đã thêm vào `run-collectors.ps1`) gộp file con của NGÀY HÔM NAY mỗi 30 phút khi có từ 40 file; `python -m collector.compact --hot` chạy một lần. Gộp an toàn khi collector đang chạy: chỉ gộp các file có mặt lúc bắt đầu và chỉ xoá đúng các file đó. Chạy thử trên dữ liệu thật: 1072 file con còn 31.


### Kiểm tra script Pine thật: Viprasol Liquidity Trail Matrix (1720 dòng, Pine v6)

File `pine/examples/viprasol_liq_trail.pine`. Ban đầu engine KHÔNG chạy được: lỗi cú pháp ở dòng 407 (`switch`), rồi hàng loạt hàm chưa có. Đã bổ sung vào engine: `switch` (biểu thức, có tuple), khai báo kiểu có mảng (`var box[] x`, `float[] v`), `for x in mảng`, mảng (`array.*`), chuỗi (`str.tostring` với `format.mintick`, `#.##`, `str.length`, `str.substring`...), đối tượng vẽ `line/label/box/table` kèm hàm set/delete, `table.cell/merge_cells`, `alert()`, `fill`, `barcolor`, `color.r/g/b/t/from_gradient`, `ta.dmi`, `ta.cum`, `chart.bg_color`, `syminfo.mintick`, `input.session`, `time(tf, session)`, các hằng `display.*`, `position.*`, `label.style_*`, `line.style_*`, `alert.freq_*`. Web vẽ line, box, label, bảng dashboard; `fill` (tô giữa hai băng) chưa vẽ.

Kết quả chạy: BTCUSDT 5m và XAUUSDT 15m (1000 nến) khoảng 1,8 giây, VNM 0,4 giây; sinh nhãn đảo chiều, tín hiệu retest, lệnh với đường entry/SL/TP1-3, volume profile (31 hộp, POC, VAH, VAL, LVN), bảng dashboard 27 dòng và các alert.

`tests/test_pine_viprasol.py` kiểm tra: (1) chạy trọn vẹn và đủ loại đầu ra; (2) 4 băng trail và các điểm đảo chiều khớp một bản cài đặt độc lập viết tay trong test (sai số 1e-9, 1500 nến, 5 lần đảo chiều trở lên); (3) SL/TP của lệnh đúng công thức 1R/2R/3R; (4) không repaint: cắt 300 nến cuối thì mọi sự kiện ở các nến trước giữ nguyên; (5) kết quả lặp lại y hệt, đổi preset đổi băng đúng theo tham chiếu; (6) chạy được với symbol không có volume.

Giới hạn khi chạy trên engine này: mọi nến đều là nến lịch sử, nên `barstate.isconfirmed` luôn đúng và `barstate.isrealtime` luôn sai; tần suất của `alert()` (`once_per_bar_close`...) bị bỏ qua, mỗi lần gọi ghi một sự kiện; `max_bars_back`, `max_lines_count` bị bỏ qua (giữ tối đa 500 đối tượng mỗi loại); `request.security` với khung rỗng chạy trên cùng khung của biểu đồ; thống kê (`Trades`, `W/L`) tính lại từ nến đã tải (tối đa 1000-5000 nến) nên khác với số liệu trên TradingView nếu lịch sử dài hơn. Chưa đối chiếu từng giá trị với TradingView vì không có TradingView ở đây; phần được kiểm là logic của chính script (trail, đảo chiều, SL/TP) và tính nhất quán.
