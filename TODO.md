# TODO

Cập nhật 2026-11-15. Danh sách gộp từ các file trong [`docs/plan/`](docs/plan/README.md). Chi tiết, số đo và lý do của từng việc nằm trong file tính năng được liên kết ở cuối mỗi dòng. Khi hoàn thành một việc, đánh dấu ở đây và ở file tính năng.

Ký hiệu: `[ ]` chưa làm, `[~]` làm dở, `[x]` xong. **Chặn** nghĩa là cần điều kiện bên ngoài trước.

## 1. Quyết định và việc có rủi ro mất dữ liệu

- [x] Giữ tick một năm hay gom nén: đã chọn gom nén (`full_days = 30`) và đã chạy ngày 15/11. Tick BTCUSDT và XAUUSDT quá 30 ngày thành footprint 1 phút. Muốn lấy lại tick cũ thì tải lại từ kho Binance bằng `collector.backfill`. Xem [10](docs/plan/10-memory-data-optimization.md).
- [ ] **Khởi động lại `dev.ps1` một lần nữa** để nạp giới hạn bộ nhớ DuckDB và bộ giám sát bộ nhớ của server. Server Python không tự nạp lại. [01](docs/plan/01-collector-storage.md)
- [ ] **Theo dõi bộ nhớ server khi chạy nhiều giờ.** Chưa biết nguyên nhân thật của lần phình 28 GB ngày 15/11; xem dòng cảnh báo `server.mem` nếu server tự thoát (mã 75). [01](docs/plan/01-collector-storage.md)
- [ ] **Chạy collector bằng Task Scheduler** thay vì phiên làm việc: `scripts/run-collectors.ps1` (nay có crawl bù khi khởi động) và `python -m collector.daily --vn` lúc 03:00. Sáng 15/11 mất 8 giờ sổ lệnh vì collector dừng theo phiên, và không lấy lại được. Lệnh `schtasks` có trong README. Cần bạn đồng ý vì đây là thay đổi hệ thống. [01](docs/plan/01-collector-storage.md)

## 2. Việc của bạn

- [ ] **Chọn cách giữ dữ liệu khi máy không bật cả ngày.** Khuyến nghị: bật máy mỗi ngày một lúc để vá khoảng hở và chụp Deribit, bật máy trong phiên HOSE (khoảng 08:50 đến 14:50) nếu muốn sổ lệnh VN100, chấp nhận heatmap BTC chỉ có lúc máy bật; thiết bị bật liên tục chỉ khi lịch sử heatmap đáng giá. Chi tiết ở [10](docs/plan/10-memory-data-optimization.md).

- [ ] Xác nhận toast Windows có hiện lên màn hình. [09](docs/plan/09-alerts-drawing-backtest.md)
- [ ] Thêm `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` vào `.env`, rồi thử một cảnh báo thật. [09](docs/plan/09-alerts-drawing-backtest.md)
- [ ] Xoá thư mục thừa `C:\tv-data-bench`. [01](docs/plan/01-collector-storage.md)
- [ ] Chọn giữ hai endpoint VN không chính thức (SSI iBoard, VNDirect dchart) hay chuyển sang SSI FastConnect. [07](docs/plan/07-vn100.md)
- [ ] Thử giao diện chỉ báo mới trên điện thoại thật (đã kiểm bằng giả lập, chưa kiểm cảm ứng).

## 3. Chặn bởi điều kiện bên ngoài

- [ ] **Chặn: cần phiên giao dịch.** Chạy `vn_book` suốt một phiên (Thứ Hai 16/11, từ 08:55 giờ VN), đo số dòng và dung lượng mỗi mã, ghi vào [engineering-notes.md](docs/plan/engineering-notes.md). Nghiệm thu "mỗi mã có sổ lệnh sau một phiên". [07](docs/plan/07-vn100.md)
- [ ] **Chặn: cần khoá và tiền.** GC1! và options vàng qua Databento. Đo giá bằng API đo trước khi mua. [06](docs/plan/06-gold.md)
- [ ] **Chặn: cần tiền.** Heatmap lịch sử trước ngày ghi qua Tardis, để backtest bằng heatmap. [04](docs/plan/04-heatmap.md)
- [ ] **Chặn: cần dữ liệu MBO, Binance không có.** Ký hiệu hình vuông và hình thoi kiểu Deep Trades, iceberg chính xác. [03](docs/plan/03-orderflow.md)

## 4. Tôi làm được tiếp

Việc vận hành và độ tin cậy:
- [~] Tối ưu bộ nhớ: đã làm trần DuckDB cho collector, giới hạn yêu cầu nặng và chế độ chẩn đoán `SERVER_MEM_DIAG`. Còn chạy thử 6 giờ (`python scripts/soak_server.py --minutes 360`) để biết server có phình không, và khởi động lại `dev.ps1`, `run-collectors.ps1` để nạp mã mới. [10](docs/plan/10-memory-data-optimization.md)
- [ ] Tối ưu dữ liệu: gom sổ lệnh quá 180 ngày thành 5 phút, bỏ cột `id` của tick đã gom, coi `bookDepth` là bộ đệm, cảnh báo đĩa thấp, sao lưu nhóm dữ liệu không tải lại được. [10](docs/plan/10-memory-data-optimization.md)
- [x] Cảnh báo khi collector im lặng hơn 5 phút: xong, nằm trong tiến trình `collector.alerts`. Cần khởi động lại `run-collectors.ps1` để có hiệu lực, và cần kiểm toast, Telegram thật. [09](docs/plan/09-alerts-drawing-backtest.md)
- [ ] Script sao lưu `C:\tv-data` bằng `robocopy`, loại `logs` và file `.tmp`. Viết script, không đặt lịch. [01](docs/plan/01-collector-storage.md)
- [ ] Phát hiện khi SSI, VNDirect hoặc Binance WS đổi định dạng và thông báo thay vì im lặng. [01](docs/plan/01-collector-storage.md)
- [ ] Backfill hàng tháng (`monthly/`) cho lịch sử nhiều năm. Hiện `collector.backfill` từ chối hơn 366 ngày nếu thiếu `--yes`. [01](docs/plan/01-collector-storage.md)
- [ ] Tải bổ sung `metrics` cho 1 năm BTCUSDT và thử lại các ngày `bookDepth` còn thiếu (3 ngày BTC, 4 ngày XAU). [01](docs/plan/01-collector-storage.md)
- [ ] Đo lại dung lượng sổ lệnh lúc biến động mạnh. Mới đo một giờ yên tĩnh. [01](docs/plan/01-collector-storage.md), [04](docs/plan/04-heatmap.md)

Engine Pine và backtest:
- [ ] Cache kết quả chạy theo (script, symbol, khung, tham số, nến cuối). Mỗi chỉ báo nặng đang tốn 0,5 đến 3 giây. [08](docs/plan/08-pine-engine.md)
- [ ] `strategy.exit` với stop và limit, nhiều lệnh cùng lúc, pyramiding, trượt giá theo thanh khoản. [09](docs/plan/09-alerts-drawing-backtest.md)
- [ ] Bản tham chiếu độc lập cho chỉ báo SMC (BOS, CHoCH, order block, FVG). [08](docs/plan/08-pine-engine.md)
- [ ] Hỗ trợ `method`, `map`, `matrix` và thư viện `import` ngoài các shim hiện có. [08](docs/plan/08-pine-engine.md)
- [ ] Ngữ nghĩa thời gian thực: `barstate.isrealtime`, `alert()` theo tần suất. [08](docs/plan/08-pine-engine.md)
- [ ] Editor Monaco hoặc tương đương: gợi ý, gấp mã, báo lỗi khi gõ. [08](docs/plan/08-pine-engine.md)

Cảnh báo:
- [ ] Cảnh báo theo điều kiện orderflow (delta, CVD, imbalance, GEX flip). Hiện chỉ có giá, cắt mức và `alertcondition`. [09](docs/plan/09-alerts-drawing-backtest.md)

VN100 (không cần chờ phiên):
- [ ] Lịch sử sổ lệnh VN100: không có nguồn miễn phí (đã thử 15/11, gồm đọc đặc tả FireAnt, xem [07](docs/plan/07-vn100.md)); chỉ có từ phiên đầu `vn_book` chạy.
- [ ] Tích hợp FireAnt `historical-quotes` (token nặc danh đã thử được, dữ liệu ngày từ 2006): backfill lịch sử ngày VN100 (giá, volume, dòng tiền ngoại, tự doanh, đặt mua và đặt bán) vào kho, và dùng làm volume ngày chuẩn để chốt nguyên nhân nến 1 phút lệch. Cần đọc điều khoản trước. [07](docs/plan/07-vn100.md)
- [ ] Hỏi giá FiinQuant (cần tài khoản): có lịch sử dòng tiền chủ động theo nến 1 đến 15 phút, tức delta thật cho VN, và luồng sổ lệnh theo sự kiện. Xem [07](docs/plan/07-vn100.md).
- [ ] Delta xấp xỉ cho VN từ hiệu của `bu` và `sd` giữa hai lần lấy mẫu. Hiện delta và CVD của VN bằng 0. [07](docs/plan/07-vn100.md)
- [ ] Tìm nguyên nhân volume nến 1 phút lệch volume ngày (trung vị 0 đến 0,85%, xấu nhất 4 đến 13%). Nếu không giải thích được, dùng nến ngày của dchart làm chuẩn cho khung `1d`. [07](docs/plan/07-vn100.md)

Orderflow và heatmap:
- [ ] Đo thời gian vẽ heatmap với 2 giờ dữ liệu so với đích 100 ms. [04](docs/plan/04-heatmap.md)
- [ ] Volume profile theo phiên (hiện chỉ có VPVR trên đoạn đang xem). [03](docs/plan/03-orderflow.md)
- [ ] Footprint nhiều cột cạnh nhau, `Imbalance Horizontal`, phân biệt thanh khoản mới và tồn tại lâu. [03](docs/plan/03-orderflow.md)
- [ ] DOM ladder (cần dữ liệu sổ lệnh tức thời trên giao diện). [03](docs/plan/03-orderflow.md), [04](docs/plan/04-heatmap.md)
- [ ] Kiểu gom chấm "Smart" kiểu Bookmap, cột volume và delta theo mức giá ở mép phải. [04](docs/plan/04-heatmap.md)

Giao diện:
- [ ] Kéo thả đổi thứ tự lớp vẽ của nhiều chỉ báo trong chú giải. [02](docs/plan/02-chart-ui.md), [08](docs/plan/08-pine-engine.md)
- [ ] Sửa điểm neo của hình vẽ bằng cách kéo (hiện chỉ xoá rồi vẽ lại). [02](docs/plan/02-chart-ui.md), [09](docs/plan/09-alerts-drawing-backtest.md)
- [ ] Lưu layout nhiều ô vào SQLite và đặt tên được (hiện ở localStorage). [02](docs/plan/02-chart-ui.md)
- [ ] Chia sẻ thư viện script và cài đặt chỉ báo giữa các trình duyệt (hiện ở localStorage). [08](docs/plan/08-pine-engine.md)
- [ ] Kiểm thử giao diện tự động bằng Playwright hoặc tương đương (hiện kiểm tay qua trình duyệt). [02](docs/plan/02-chart-ui.md)
- [ ] Bar replay theo tick, không chỉ theo nến. [09](docs/plan/09-alerts-drawing-backtest.md)

## 5. Kiểm chứng chưa làm

- [ ] Đối chiếu engine Pine với TradingView thật bằng ảnh chụp cùng một đoạn nến (SMA, EMA, Ichimoku, RSI). Chưa có lần nào. [08](docs/plan/08-pine-engine.md)
- [ ] Đọc điều khoản nguồn của options GLD trước khi làm GEX vàng xấp xỉ (6B). Bỏ nếu cấm. [06](docs/plan/06-gold.md)
- [ ] Theo dõi cập nhật Binance (URL WS cũ đã bị khai tử 2026-04-23). [01](docs/plan/01-collector-storage.md)
- [ ] Heatmap thanh lý: chưa rõ gói Coinglass nào có endpoint này. [04](docs/plan/04-heatmap.md)

## 6. Đã xong gần đây

- [x] Gom tài liệu kế hoạch vào `docs/plan/` theo từng tính năng, có sơ đồ Mermaid và sơ đồ tương tác `docs/plan/plan.html`.
- [x] Crawl bù khi khởi động: `run-collectors.ps1` chạy nền `collector.daily --vn`, `dev.ps1` đồng bộ nến 1 phút.
- [x] Lấp khoảng thủng nến BTCUSDT sáng 15/11. Tick được collector tự lấp bằng REST.
- [x] Backfill 1 năm: tick, `bookDepth` và nến 1 phút BTCUSDT; 340 ngày cho XAUUSDT.
- [x] Thiết kế lại bảng chỉ báo, sửa mã Pine tràn khung.
- [x] Cài đặt chỉ báo kiểu TradingView: tab Tham số, Kiểu dáng, Hiển thị, hộp thêm chỉ báo, chú giải có giá trị và menu.
- [x] Xoá hình vẽ bằng chọn và `Delete`, nút Xoá nổi, tự về chế độ Trỏ sau khi vẽ.
