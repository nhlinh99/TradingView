# TODO

Cập nhật: 2026-11-15. Tình trạng từng phase xem `README.md`; giới hạn và quyết định xem `NOTES.md`.
Ký hiệu: `[ ]` chưa làm, `[~]` làm dở, `[x]` xong. **Chặn** nghĩa là cần điều kiện bên ngoài trước.

## 1. Cần làm sớm (dữ liệu chỉ tích luỹ khi máy chạy)
- [ ] Chạy collector bằng Task Scheduler thay vì phiên làm việc: `scripts/run-collectors.ps1` (trades, book, Deribit, alerts, hotmerge, vn_book) và `python -m collector.daily --vn`. Hướng dẫn `schtasks` có trong README. Mỗi ngày bỏ lỡ là mất tick, sổ lệnh và snapshot options vĩnh viễn.
- [ ] Cảnh báo khi collector im lặng hơn 5 phút (đọc mốc ghi cuối của `ticks` và `book`, gửi qua cùng kênh với alert giá).
- [ ] Sao lưu `C:\tv-data` (nằm ngoài OneDrive nên chưa có bản sao): `robocopy` hằng tuần sang ổ khác; loại `logs` và file `.tmp`.
- [ ] Xoá thư mục thừa `C:\tv-data-bench` (bạn tự xoá).

## 2. Phase 7: cổ phiếu VN100
- [ ] **Chặn: cần phiên giao dịch.** Chạy `vn_book` suốt một phiên (Thứ Hai 16/11, từ 08:55 giờ VN), rồi đo số dòng và dung lượng mỗi mã, ghi vào `NOTES.md` (mục 7 của plan: chưa có số đo).
- [ ] Nghiệm thu "mỗi mã có sổ lệnh với số dòng lớn hơn 0 sau một phiên".
- [ ] Tìm nguyên nhân volume nến 1 phút lệch volume ngày (trung vị 0,0–0,85%, xấu nhất 4–13% ở VNM, FPT, VCB). So với bộ đếm `tv` của sổ lệnh; nếu không giải thích được thì dùng nến ngày của dchart làm chuẩn cho khung `1d`.
- [ ] Delta xấp xỉ cho VN từ hiệu của `bu` và `sd` giữa hai lần lấy mẫu, hiện delta và CVD của VN bằng 0.
- [ ] Volume profile theo phiên và bản đồ nhiệt 3 mức giá cho VN (cần dữ liệu sổ lệnh thật trước).
- [ ] Quyết định có chuyển sang SSI FastConnect (có khoá, ổn định hơn) hay giữ hai endpoint không chính thức (SSI iBoard, VNDirect dchart).

## 3. Cảnh báo và thông báo
- [ ] Bạn xác nhận toast Windows có hiện lên màn hình (lệnh trả mã thành công nhưng chưa thấy bằng mắt).
- [ ] Thêm `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID` vào `.env`, thử một cảnh báo thật (hiện mới thử với máy chủ giả).
- [ ] Cảnh báo theo điều kiện orderflow (delta, CVD, imbalance, GEX flip), hiện chỉ có giá, cắt mức và `alertcondition` của Pine.

## 4. Engine Pine
- [ ] Cache kết quả chạy theo (script, symbol, khung, tham số, nến cuối) để nhiều chỉ báo không tính lại; mỗi chỉ báo nặng đang tốn 0,5–3 giây.
- [ ] `strategy.exit` với stop và limit, nhiều lệnh cùng lúc, pyramiding, trượt giá theo thanh khoản.
- [ ] Hỗ trợ `method`, `map`, `matrix`, thư viện `import` ngoài các shim đã có (`PineCoders/lower_tf`, `Time`, `VisibleChart`, `TradingView/ta`).
- [ ] Đối chiếu với TradingView bằng ảnh chụp cùng một đoạn nến cho SMA, EMA, Ichimoku, RSI (chưa có lần nào so với TradingView thật).
- [ ] Bản tham chiếu độc lập cho chỉ báo SMC `instituitional_level_indicator` (hiện chỉ kiểm bất biến); xác minh BOS, CHoCH, order block, FVG.
- [ ] Editor Monaco hoặc tương đương: gợi ý tự động, gấp mã, báo lỗi ngay khi gõ (hiện là ô văn bản có tô màu).
- [ ] Ngữ nghĩa thời gian thực (`barstate.isrealtime`, `alert()` theo tần suất); hiện mọi nến coi là lịch sử.

## 5. Orderflow và giao diện
- [ ] DOM ladder (cần dữ liệu sổ lệnh tức thời trên giao diện).
- [ ] Footprint nhiều cột cạnh nhau, `Imbalance Horizontal`, phân biệt thanh khoản mới và tồn tại lâu.
- [ ] Kiểu gom chấm "Smart" kiểu Bookmap; ký hiệu hình vuông và hình thoi kiểu Deep Trades (cần dữ liệu MBO, Binance không có).
- [ ] Đo thời gian vẽ heatmap (đích plan: dưới 100 ms mỗi khung hình với 2 giờ dữ liệu; chưa đo).
- [ ] Sắp xếp lớp vẽ của nhiều chỉ báo bằng kéo thả.
- [ ] Lưu layout nhiều ô vào SQLite và đặt tên được (hiện nằm trong localStorage).
- [ ] Chia sẻ thư viện script giữa các trình duyệt (hiện nằm trong localStorage).
- [ ] Sửa điểm neo của hình vẽ (hiện chỉ xoá rồi vẽ lại).
- [ ] Bar replay theo tick, không chỉ theo nến.

## 6. Dữ liệu
- [ ] **Chặn: cần khoá và tiền.** GC1! và options vàng qua Databento (6C); đo giá thật trước khi mua.
- [ ] GEX vàng xấp xỉ từ options GLD (6B): đọc điều khoản nguồn trước khi tự động hoá; bỏ nếu cấm.
- [ ] Heatmap lịch sử trước ngày bắt đầu thu thập (Tardis, trả phí) để backtest bằng heatmap.
- [ ] Đo lại dung lượng sổ lệnh trong lúc biến động mạnh (mới đo 1 giờ yên tĩnh: BTC khoảng 13 MB/ngày, XAU khoảng 7 MB/ngày chưa gộp).

## 7. Chất lượng và vận hành
- [ ] Kiểm thử giao diện tự động (Playwright hoặc tương đương); hiện kiểm thử giao diện làm tay qua trình duyệt.
- [ ] Phát hiện khi endpoint không chính thức đổi định dạng (SSI, VNDirect, Binance WS): thông báo thay vì im lặng.
- [ ] Tiếp tục theo dõi khi cập nhật Binance (URL WS cũ đã bị khai tử 2026-04-23, đã chuyển sang đường dẫn mới).

## 8. Đã xong gần đây (để tham chiếu)
- [x] Phase 0 đến 9, khung `1w` và `1M`, giao diện tối, tìm symbol, phím tắt.
- [x] Thiết kế orderflow theo DeepCharts và Bookmap (heatmap, footprint, chấm, iceberg ước lượng).
- [x] Quản lý nhiều chỉ báo Pine (chú giải trên biểu đồ, bảng quản lý, form tham số theo nhóm).
- [x] Chạy được 6 script Pine thật, trong đó 4 có đối chiếu tham chiếu độc lập (`tests/test_pine_examples.py`).
- [x] Gộp nóng file con trong ngày mỗi 30 phút.
