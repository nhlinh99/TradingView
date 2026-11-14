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
