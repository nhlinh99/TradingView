# Changelog

Theo dạng [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/). Dự án chưa đánh số phiên bản: mỗi mục ghi theo ngày và theo phase trong `PLAN-CLAUDE-CODE.md`. Mã commit là 7 ký tự đầu để tra bằng `git show`.

## [Chưa phát hành]

Xem `TODO.md` cho việc còn mở và `docs/plan/README.md` cho kế hoạch từng tính năng. Việc quan trọng nhất: chạy collector bằng Task Scheduler, đo phiên giao dịch VN100 thật (Thứ Hai 16/11), đối chiếu engine Pine với TradingView.

## 2026-11-18

### Thêm
- **Công cụ vẽ** viết lại theo registry (`web/src/drawTools.tsx`), thanh công cụ chia nhóm có menu mở rộng: đường (tia, tia ngang, đường thẳng, đường dọc, chữ thập, info line, góc xu hướng, mũi tên, kênh song song, kênh hồi quy), Fibonacci (mở rộng chỉnh được bề rộng, channel, time zones, fan, circles, arcs, màu từng mức và dải tô kiểu TradingView), Pitchfork (Andrews, Schiff, Modified Schiff), Gann (fan, box), vị thế Long/Short với tỉ lệ R:R và 4 góc điều khiển, đo (thước %, khoảng ngày, khoảng giá), hình khối (ellipse, hình tròn, tam giác, đường gấp khúc, bút vẽ), ghi chú, chú thích, nhãn giá, cờ.
- Chọn hình: kéo 4 góc hoặc điểm neo, kéo thân để di chuyển, phím mũi tên nhích từng bước, thanh thuộc tính (màu, độ dày, kiểu nét, khoá, nhân bản, xoá), nam châm bắt vào giá nến, ẩn mọi hình, hoàn tác và làm lại có hoàn tác cả việc xoá (server nhận lại hình với đúng id cũ), Fib/Pitchfork/Gann không vẽ phần dưới giá 0, nút thu gọn thanh công cụ.
- **Menu chuột phải** trên biểu đồ kiểu TradingView (sao chép giá, thêm cảnh báo tại giá, vẽ đường ngang/dọc, nhãn giá, ghi chú, thêm chỉ báo, đặt lại khung nhìn, nam châm, ẩn/xoá hình; trên một hình thì khoá, nhân bản, xoá; khi đang vẽ dở thì huỷ hình).
- Con trỏ chữ thập nét đứt theo chuột (ẩn khi đang dùng công cụ vẽ).
- **Vùng thanh khoản (rút lệnh)** (`/api/liqzones`, `web/src/LiqZones.tsx`): lệnh chờ lớn vẽ thành thanh kéo dài từ lúc xuất hiện đến lúc biến mất, cuối thanh có ✕ (bị rút), ▶ (bị khớp, đối chiếu với lệnh khớp ở đúng mức giá) hoặc mờ dần (còn hiệu lực); đoạn collector tắt được tách riêng, không tính là rút lệnh. Có tooltip chi tiết và chú giải.
- Heatmap: tooltip bid/ask khi rê chuột, chú giải thang màu, chỉ báo đang tải và tự thử lại, ghi chú độ phủ dữ liệu (`/api/heatmap/coverage`), độ sâu thô ±5% từ `bookDepth` cho đoạn chưa có sổ lệnh chi tiết (`/api/depthbands`).
- XAUUSD có Bookmap, chấm volume, iceberg: lấy từ sổ lệnh XAUUSDT và dịch giá theo chênh lệch trung vị hai mã, kèm ghi chú đây là ước lượng.
- Chỉ báo RSI (Wilder) kèm MA, vùng quá mua/quá bán và cảnh báo (`pine/examples/rsi.pine`).
- Nến ngày của VN100 từ VNDirect `1D` (từ 2014, `vn_daily/<mã>.json`); tuần và tháng ghép từ nến ngày. Dung lượng khoảng 12 MB cho 100 mã.
- `scripts/install-tasks.ps1` đăng ký Task Scheduler: `TradingView-Collectors` lúc đăng nhập và `TradingView-Daily` lúc 03:00. `run-collectors.ps1` có khoá không chạy trùng.
- Nạp nến 1 phút XAUUSD cũ từ Dukascopy (`collector/dukascopy.py`).

### Đổi
- Heatmap dễ đọc hơn: thanh khoản thấp mờ dần vào nền (gamma 0.8, độ đục tối thiểu gần 0), preset Bookmap cắt nhiễu 15%, nến rỗng màu xám khi bật heatmap, chấm volume và iceberg bớt lấn át.
- Máy chủ gộp các yêu cầu nặng giống hệt nhau và nhớ kết quả 20 giây (`limits.coalesce`), giao diện làm tròn khoảng thời gian và chờ 0,35 giây sau khi kéo, nên hàng đợi yêu cầu nặng không còn đầy khi kéo biểu đồ.
- Bỏ dòng ghi chú nguồn dữ liệu của cổ phiếu VN100.

### Sửa
- VN100 khung ngày, tuần, tháng thiếu dữ liệu (FPT thiếu 11/2025 đến 5/2026): nguồn không có nến phút cho giai đoạn đó, nên khung ngày trở lên lấy thẳng nến ngày.
- Volume Profile by Range lỗi khi chọn 1 Hour, 3 Month, 6 Month: engine Pine thiếu dạng gọi hàm của `hour(time)`, `month(time)`, `dayofmonth(time)` và các hàm cùng loại (có tham số múi giờ).
- Menu nhóm công cụ vẽ bị ô biểu đồ khác đè ở layout nhiều ô: vẽ qua portal ở tầng trên cùng.
- Nhãn giá không còn chồng lên Long/Short: chữ chốt lời, cắt lỗ và thẻ R:R nằm bên phải hộp, ghi chú và nhãn giá luôn vẽ trên cùng.

## 2026-11-16

### Thêm
- Mã `XAUUSD` (vàng giao ngay) lấy từ TradingView, nguồn TVC (`collector/tvc.py`, mã gốc `TVC:GOLD` vì `TVC:XAUUSD` bị từ chối với tài khoản ẩn danh). Chỉ có nến 1 phút trở lên, không tick, không heatmap. Nguồn ẩn danh chỉ trả khoảng 7.800 nến 1 phút (5 ngày), nên phải chạy `collector.tvc` đều đặn (đã thêm vào `dev.ps1` và `collector.daily`) để lịch sử dài ra.

### Thêm (tiếp)
- XAUUSD có lịch sử dài ở các khung lớn: 5m từ 21/10, 1h từ 01/2026, 4h từ 2023, 1d từ 2007 trở về trước (hàng chục năm), cả 1w và 1M. Nến TradingView ở các khung này được lưu riêng (`DATA_DIR/tvc/XAUUSD/<khung>.json`, nạp bằng `python -m collector.tvc --history`) và server trả đúng nó khi chọn khung tương ứng; khung khác (ví dụ 2h) vẫn dựng từ nến 1 phút nên chỉ có vài ngày. Nến 1 phút vẫn chỉ sâu khoảng 5 ngày do giới hạn của nguồn.

### Sửa
- XAUUSD thiếu nến mới: không có luồng trực tiếp nên nến dừng ở lần nạp lúc khởi động. Giờ server tự kéo đuôi nến từ TradingView khi có người xem (tối đa 20 giây một lần). Ngày 08/11 (60 nến mở cửa Chủ nhật) cũng đã nạp bù. Các khoảng trống 22:00 đến 23:00 UTC mỗi ngày và cuối tuần là giờ nghỉ của thị trường.
- Đổi mã trên biểu đồ: bật lại tự co giãn trục giá để thang khớp giá của mã mới (trước đó kéo tay trục giá thì sang mã khác vẫn giữ thang cũ).
- Indicator volume profile (`volume_profile_total`) không hiện số: engine Pine bỏ mất `text_size`, `text_color`, `text_halign`, `text_valign` của `box.new`, và biểu đồ không vẽ chữ trong box. Đã sửa cả hai.

## 2026-11-15 (tài liệu)

### Thêm
- Vẽ xong một hình thì tự quay về chế độ Trỏ. Hình đang chọn có nút "Xoá" nổi bên cạnh, bấm một lần là xoá.
- Xoá hình vẽ: bấm vào hình ở chế độ Trỏ để chọn, `Delete` hoặc `Backspace` để xoá, `Esc` để bỏ chọn, nút "Xoá hình đang chọn" trên thanh vẽ. Hình vừa vẽ được chọn sẵn.

- Cài đặt chỉ báo kiểu TradingView: tab Tham số, Kiểu dáng (màu, độ đục, độ dày, nét, bật tắt cho từng đường, mức, tín hiệu, vùng tô), Hiển thị (theo khung thời gian, nhãn giá trị trên thang giá). Có trong bảng chỉ báo và trong hộp bánh răng trên biểu đồ.

- `TODO.md` gộp mọi việc còn mở theo mức ưu tiên và theo người làm.
- Hộp **Thêm chỉ báo và chiến lược** (phím `I`): tìm có tô khớp, phân loại, yêu thích bằng ngôi sao, mũi tên và Enter để thêm, hộp không đóng sau khi thêm.
- Chú giải chỉ báo: giá trị cuối tô màu, tham số đầu, menu ⋯ (nhân bản, sửa mã), nhấp đúp mở cài đặt.
- Hộp Cài đặt chỉ báo dạng cửa sổ có Huỷ, OK, Mặc định; thay đổi áp ngay để xem trước.

- Cảnh báo khi collector im lặng hơn 5 phút (`collector/watchdog.py`), chạy trong tiến trình `collector.alerts`, gửi qua toast và Telegram; nhắc lại mỗi 30 phút, báo khi phục hồi.

- Chụp lại toàn bộ ảnh giao diện trong `docs/screenshots/` theo giao diện mới, thêm ảnh hộp thêm chỉ báo và hộp cài đặt chỉ báo; README mô tả lại phần chỉ báo.

### Sửa
- Tối ưu bộ nhớ: trần DuckDB cho đường ghi và collector (`store.work_conn()`), giới hạn 3 yêu cầu nặng cùng lúc (`server/limits.py`, 503 khi chờ quá 60 giây), chế độ chẩn đoán `SERVER_MEM_DIAG=1`, `scripts/soak_server.py` để chạy thử dài.
- Đã chạy gom nén theo quyết định giữ `full_days = 30`: 644 ngày tick của BTCUSDT và XAUUSDT thành footprint 1 phút, giải phóng 2,65 GB; `DATA_DIR` từ khoảng 3,4 GB còn 0,7 GB.
- Đã thử FireAnt: đăng nhập nặc danh lấy được token, `historical-quotes` cho dữ liệu ngày VN từ 2006 (có dòng tiền ngoại, tự doanh, đặt mua và đặt bán), không có sổ lệnh hay tick. Chưa tích hợp vào kho. Xem `docs/plan/07-vn100.md`.
- Phương án tối ưu bộ nhớ và dữ liệu: `docs/plan/10-memory-data-optimization.md`, tóm tắt trong README (mục Tài nguyên máy).
- Ghi chú GEX bị thanh vẽ che: chuyển sang góc trên bên phải.
- Layout nhiều ô: thanh vẽ nằm ngang, không phủ hết chiều cao của ô nhỏ.
- Cột phải của bảng soạn mã rộng hơn để đủ 5 tab của chiến lược; hộp Cài đặt không còn viền focus trên tab đầu.
- Server phình tới 27,9 GB bộ nhớ cam kết sau nhiều giờ chạy (Windows commit 99%). Nay dùng một instance DuckDB dùng chung có trần 1 GB, có bộ giám sát bộ nhớ tự thoát khi vượt trần, `dev.ps1` tự khởi động lại server. Nguyên nhân gốc chưa xác định.
- `dev.ps1` bị vỡ do ký tự `\r` trong một comment (đã sửa ở `71809a5`).
- Mã Pine tràn ra ngoài khung trong bảng chỉ báo: luật CSS của trình soạn gắn nhầm vào `.pine` nên không áp dụng cho bảng mới. Nay mã cuộn trong khung, có số dòng.
- `--hover`, `--veil`, `--focus` ở giao diện sáng tự tham chiếu nên mất màu (chú giải chỉ báo trong suốt).
- `input(defval=hlc3)` kiểu cũ hiện thành ô số thay vì ô chọn nguồn giá (cần khởi động lại server).

### Thay đổi
- Thiết kế lại bảng chỉ báo: biểu tượng SVG thay emoji, thẻ chỉ báo và thư viện có nhãn, tab Tham số, Backtest, Kết quả, ô bật tắt, đổi được chiều cao, tấm trượt trên điện thoại.
- Tài liệu kế hoạch gom vào `docs/plan/`, mỗi tính năng một file (có sơ đồ). `PLAN.md`, `PLAN-CLAUDE-CODE.md` chuyển vào `docs/plan/archive/`, `NOTES.md` thành `docs/plan/engineering-notes.md`, `TODO.md` chia vào từng file tính năng.
- Sơ đồ tương tác `docs/plan/plan.html` có tab theo tính năng và nét đứt cho phần chưa làm.
- Mỗi lần khởi động tự crawl bù dữ liệu: `scripts/run-collectors.ps1` chạy nền `collector.daily --vn` (tắt bằng `-SkipCatchup`), `dev.ps1` đồng bộ nến 1 phút 3 ngày trước khi mở server.

## 2026-11-15

### Thêm
- Engine Pine chạy thêm 4 script thật: `ichimoku_future` (Pine v4), `cvd_range`, `volume_profile_total`, `instituitional_level_indicator` (SMC, 936 dòng). Bổ sung: `type` do người dùng định nghĩa, đọc và gán trường, gọi như phương thức, `import` với shim thư viện (`PineCoders/lower_tf`, `Time`, `VisibleChart`, `TradingView/ta`), `request.security_lower_tf`, `array<T>`, `for [i, x] in`, `if` làm biểu thức, `plotcandle`/`plotchar`/`plotarrow`, `chart.point`, `polyline`, `plot(offset=)`, `fill()`, `ta.supertrend`, `ta.sar`, `ta.highestbars`, hàm kiểu v4. (`09edd3b`)
- 13 test đối chiếu độc lập cho 4 script trên (Ichimoku, CVD, volume profile; SMC chỉ kiểm bất biến). (`09edd3b`)
- Web vẽ `fill` giữa hai plot, `polyline`, nến `plotcandle`, và tự chừa lề phải cho đối tượng nằm sau nến cuối. (`09edd3b`)
- `TODO.md` (nay đã chia vào `docs/plan/`). (`4d4aa4e`)
- `CHANGELOG.md`.

### Sửa
- `var` bên trong hàm người dùng không giữ giá trị giữa các lần gọi, làm nhãn bị tạo lặp mỗi nến. (`09edd3b`)
- `for ... in` duyệt bản sao nên chỉ số lệch khi script xoá phần tử trong vòng lặp. (`09edd3b`)
- `request.security_lower_tf` báo lỗi khi dữ liệu khung thấp bắt đầu muộn hơn nến đầu của biểu đồ; nay các nến đó nhận mảng rỗng. (`09edd3b`)

### Thay đổi
- README cập nhật theo trạng thái thật (nguồn VN100, lệnh thu thập mới, cấu trúc thư mục, số test).

## 2026-11-14 (buổi tối)

### Thêm
- **Quản lý nhiều chỉ báo Pine**: chú giải trên biểu đồ, bảng quản lý với thư viện có tìm kiếm và trình soạn mã, form tham số tự sinh theo nhóm (thanh trượt, ô chọn, ô màu, tìm kiếm, đặt lại). (`ce5152c`)
- Engine Pine chạy được script thật 1720 dòng (Viprasol Liquidity Trail Matrix, Pine v6): `switch`, mảng, `line`/`label`/`box`/`table`, `alert()`, `ta.dmi`, `str.*`, `color.*`; web vẽ line, box, label, bảng; 6 test đối chiếu (băng trail, điểm đảo chiều, SL/TP, không repaint). (`244a799`)
- Editor Pine có tô màu cú pháp; `bgcolor` được vẽ trên biểu đồ; danh sách theo dõi kéo thả sắp xếp. (`63f1c2f`, `0d89fe9`)
- Hộp tìm symbol (`/`, `Ctrl+K`) và phím tắt (`[` `]`, `T`, `I`, `?`). (`34ffce3`)
- Gộp nóng file con của ngày hôm nay mỗi 30 phút (`collector.hotmerge`). (`cba464a`)
- Giao diện một hàng: bảng Orderflow với mẫu dựng sẵn, công tắc, thanh trượt; nút phân đoạn; thanh vẽ dùng biểu tượng; bố cục điện thoại. (`dd84c82`)
- Thiết kế orderflow theo Bookmap: thang màu, ngưỡng cắt, đường bid/ask tốt nhất, dải volume, cỡ chấm và lọc chấm nhỏ, iceberg ước lượng (`/api/icebergs`). (`68a3eee`)
- Thiết kế orderflow theo DeepCharts: thang màu heatmap, màu mua/bán, footprint 4 kiểu (Bid x Ask, Delta, Volume, Profile), chữ tự co, thống kê Δ và V dưới nến, stacked imbalance, chấm đặc và rỗng. (`31acdb3`)
- Ảnh chụp giao diện trong README. (`0f646ee`)
- Khung thời gian `1w` (thứ Hai 00:00 UTC) và `1M` (tháng dương lịch). (`93fb997`)

### Sửa
- Tải biểu đồ có lúc mất khoảng 15 giây vì hơn 1000 file con trong ngày chưa gộp; nay gộp nóng mỗi 30 phút. (`cba464a`)

## 2026-11-14 (giữa ngày đến chiều)

### Thêm
- **Phase 9**: công cụ vẽ (đường xu hướng, đường ngang, hộp, Fibonacci, văn bản) lưu trong SQLite theo symbol (`6d8b9e8`); cảnh báo nền giá, cắt mức và `alertcondition` với toast Windows và Telegram, có thử lại (`ad2b1b8`); giao diện backtest gồm vốn, phí, trượt giá, khoảng ngày, bảng lệnh (`889543d`); phát lại từng nến (`45250bc`); bố cục 1/2/4 ô đồng bộ cuộn và crosshair (`8c96414`).
- **Phase 8**: engine Pine (lexer, parser, thông dịch, `ta.*`, `request.security`, `request.external` cho delta/CVD/GEX, backtest tối giản) kèm 5 script mẫu có đối chiếu (`58da5d0`); `/api/pine/run`, panel Pine và lớp vẽ trong web (`a3e669f`).
- **Phase 7**: danh sách VN100 từ SSI (`config/vn100.json`), nến 1 phút từ VNDirect, bộ ghi sổ lệnh 3 mức, mã VN trong API và giao diện; `collector.daily --vn`. (`b2720f4`, `d89a8c0`)
- **Phase 6A**: ghi chú và kiểm tra XAUUSDT (đơn vị oz, giờ giao dịch, chênh lệch so với chỉ số), cắt lớp phủ trong vùng giá. (`5ceec56`)
- **Phase 5**: GEX BTC từ options Deribit (snapshot 15 phút, gamma từ IV theo Black-76, gamma flip, call/put wall), `/api/gex` và lớp phủ. (`041c133`)
- **Phase 4**: heatmap thanh khoản (`/api/heatmap`, thang theo phân vị 99) và bong bóng lệnh lớn (`/api/bubbles`). (`c6d4d9b`, `cf8db35`)
- **Phase 3**: footprint (`/api/footprint`) kèm test delta khớp nến, lớp phủ imbalance và POC, pane delta và CVD, VPVR với POC/VAH/VAL (`/api/profile`). (`752c30d`, `928f815`, `2193bf0`)
- **Phase 2**: `/api/bars` (có đuôi REST và `last_trade_id`), danh sách theo dõi lưu SQLite, WebSocket `/api/stream`, biểu đồ nến có volume, múi giờ, cuộn nạp lịch sử, giao diện tối. (`dbeea0b`, `57c9f89`, `f55fb73`, `07fd328`, `6215e91`, `a95aa0e`)

### Sửa
- Luồng bù khoảng hở tick chết vì file cấu hình bị khoá và không thử lại; thêm bộ nhớ đệm cấu hình, thử lại có lùi. (`ad179c7`)
- Truy vấn khoảng thời gian chậm 2,6 giây; nay chỉ đọc file của các ngày liên quan và lọc `ts` trước khi loại trùng (0,07 giây). (`a33a16a`)

### Đo
- Sổ lệnh 1 giờ: BTC khoảng 13 MB/ngày, XAU khoảng 7 MB/ngày (chưa gộp). Phase 1 đóng. (`90045da`, `95bbfd9`)

## 2026-11-14 (sáng và trưa): nền tảng

### Thêm
- **Phase 0 và 1**: khung dự án, kho Parquet (tick có `id`, tên file con không va chạm, loại trùng, gộp ngày), SQLite, client REST Binance và đồng bộ nến 1 phút, backfill từ `data.binance.vision` có kiểm checksum, nến dựng từ tick đối chiếu kline, collector tick trực tiếp, collector sổ lệnh (diff depth và snapshot REST), gom nén theo `retention.toml`, việc hằng đêm `collector.daily`, script `run-collectors.ps1`. (`b087a91` đến `d734885`)
- Kế hoạch nghiên cứu (`PLAN.md`, `PLAN-CLAUDE-CODE.md`), trang kế hoạch tương tác, README, `NOTES.md` (nay ở `docs/plan/`). (`ffa30b7`, `036e770`, `7130b55`)

### Ghi nhận
- Nhiều quyết định trong kế hoạch ban đầu đã được sửa sau khi kiểm chứng; xem `docs/plan/engineering-notes.md` mục "Quyết định đã đổi so với kế hoạch" và ghi chú đầu `docs/plan/archive/research-initial.md`.
