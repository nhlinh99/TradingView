# Changelog

Theo dạng [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/). Dự án chưa đánh số phiên bản: mỗi mục ghi theo ngày và theo phase trong `PLAN-CLAUDE-CODE.md`. Mã commit là 7 ký tự đầu để tra bằng `git show`.

## [Chưa phát hành]

Xem `TODO.md` cho việc còn mở và `docs/plan/README.md` cho kế hoạch từng tính năng. Việc quan trọng nhất: chạy collector bằng Task Scheduler, đo phiên giao dịch VN100 thật (Thứ Hai 16/11), đối chiếu engine Pine với TradingView.

## 2026-11-15 (tài liệu)

### Thêm
- Vẽ xong một hình thì tự quay về chế độ Trỏ. Hình đang chọn có nút "Xoá" nổi bên cạnh, bấm một lần là xoá.
- Xoá hình vẽ: bấm vào hình ở chế độ Trỏ để chọn, `Delete` hoặc `Backspace` để xoá, `Esc` để bỏ chọn, nút "Xoá hình đang chọn" trên thanh vẽ. Hình vừa vẽ được chọn sẵn.

- Cài đặt chỉ báo kiểu TradingView: tab Tham số, Kiểu dáng (màu, độ đục, độ dày, nét, bật tắt cho từng đường, mức, tín hiệu, vùng tô), Hiển thị (theo khung thời gian, nhãn giá trị trên thang giá). Có trong bảng chỉ báo và trong hộp bánh răng trên biểu đồ.

- `TODO.md` gộp mọi việc còn mở theo mức ưu tiên và theo người làm.
- Hộp **Thêm chỉ báo và chiến lược** (phím `I`): tìm có tô khớp, phân loại, yêu thích bằng ngôi sao, mũi tên và Enter để thêm, hộp không đóng sau khi thêm.
- Chú giải chỉ báo: giá trị cuối tô màu, tham số đầu, menu ⋯ (nhân bản, sửa mã), nhấp đúp mở cài đặt.
- Hộp Cài đặt chỉ báo dạng cửa sổ có Huỷ, OK, Mặc định; thay đổi áp ngay để xem trước.

### Sửa
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
