# Biểu đồ và giao diện

Phase 2 và nhóm UX. Trạng thái: xong. Còn việc nhỏ ở layout, editor và kiểm thử giao diện.

Stack cố định: Vite, React, TypeScript, Lightweight Charts v5 (Apache-2.0, bắt buộc ghi attribution). Lightweight Charts chỉ có nến cơ bản, nên heatmap, footprint và hình vẽ là primitive canvas 2D tự viết. Dự án không dùng tên, logo hay giao diện của TradingView.

## Sơ đồ

```mermaid
flowchart LR
  W[Trình duyệt<br/>React + Lightweight Charts] -->|GET /api/bars| S[Server FastAPI]
  W <-->|WebSocket /stream| S
  S -->|SQL| P[(Parquet)]
  S -->|watchlist, hình vẽ| Q[(SQLite)]
  W -->|layout, chỉ báo, script| L[(localStorage)]
```

## Tính năng đã làm

Nến, pane volume (màu theo hướng), crosshair, múi giờ chọn được, khung `1s` đến `1M`, nến chạy trực tiếp qua WebSocket, cuộn về quá khứ tải thêm dữ liệu. Danh sách theo dõi kéo thả để sắp xếp, lưu trong SQLite. Giao diện tối là mặc định theo hệ thống, có nút đổi sang sáng.

Thanh trên cùng có một hàng: symbol và trạng thái trực tiếp, khung thời gian, nút **Chỉ báo**, bố cục 1/2/4 ô, múi giờ, Replay, Cảnh báo, Pine, đổi sáng/tối. Mọi tính năng orderflow nằm trong bảng **Chỉ báo**: bốn mẫu dựng sẵn (Sạch, Footprint, Bookmap, Profile), công tắc có mô tả một dòng, thanh trượt cho ngưỡng. Tính năng không dùng được cho symbol hiện tại (ví dụ tick của cổ phiếu VN) bị làm mờ kèm giải thích. Trên điện thoại (390 px) vùng biểu đồ chiếm hơn một nửa màn hình, thanh vẽ nằm ngang và ô múi giờ ẩn (giá trị đã lưu vẫn dùng).

Phím tắt: `/` hoặc `Ctrl+K` tìm symbol, `[` và `]` đổi khung, `T` đổi sáng/tối, `I` mở bảng chỉ báo, `?` xem danh sách phím, `Ctrl+Enter` chạy Pine, `Esc` đóng bảng.

### Thêm chỉ báo và cài đặt, theo cách tương tác của TradingView

Ngày 2026-11-15 tôi mở trang biểu đồ công khai của TradingView (không đăng nhập) để xem cách thêm chỉ báo. Chỉ ghi lại cách tương tác, không sao chép mã, biểu tượng hay giao diện của họ. Quan sát được:

- Nút **Indicators** trên thanh trên mở một hộp thoại giữa màn hình, ô tìm kiếm tự focus, phím tắt `/`.
- Cột trái chia loại (của tôi, có sẵn, cộng đồng), cột phải là danh sách có chip lọc Indicators, Strategies, Profiles, Patterns, Options. Từ khoá tìm được tô màu ngay trong tên.
- Bấm một dòng là thêm vào biểu đồ và hộp vẫn mở, nên thêm được nhiều cái liền nhau. Một số mục cộng đồng đòi đăng nhập, nên tôi không xem tiếp phần này.
- Mỗi chỉ báo có một dòng trong chú giải với nút Hide, Settings, Remove và More, kèm giá trị hiện tại.
- Cạnh nút Indicators có nút riêng cho chỉ báo yêu thích.

Phần tương ứng đã làm trong dự án:

| TradingView | Dự án này |
|---|---|
| Hộp thoại thêm chỉ báo, `/` | Hộp **Thêm chỉ báo và chiến lược**, phím `I` hoặc nút Chỉ báo. Tìm có tô khớp, mũi tên chọn dòng, Enter thêm, Esc đóng |
| Hộp không đóng sau khi thêm | Giữ nguyên. Dòng đã thêm hiện dấu ✓ và số bản (×2), cuối hộp báo "Đã thêm ..." |
| Phân loại bên trái | Tất cả, Yêu thích, Script của tôi, Chỉ báo có sẵn, Chiến lược có sẵn |
| Chỉ báo yêu thích | Ngôi sao ở mỗi dòng, lưu trong trình duyệt (`ind.fav`), mục Yêu thích ở cột trái |
| Dòng chú giải với Hide, Settings, Remove, More | Nút hiện khi rê chuột (luôn hiện trên màn hình cảm ứng): Ẩn, Cài đặt, Sửa mã, Xoá, và menu ⋯ gồm Nhân bản, Cài đặt, Sửa mã nguồn, Xoá |
| Giá trị hiện tại trong chú giải | Tối đa 4 giá trị cuối, tô theo màu từng đường, kèm vài tham số đầu (ví dụ `9 17 26`) |
| Nhấp đúp vào chỉ báo để mở cài đặt | Nhấp đúp vào tên trong chú giải |
| Hộp Settings có tab, nút Cancel, Ok, Defaults | Hộp **Cài đặt** có tab Tham số, Kiểu dáng, Hiển thị. Thay đổi áp ngay để xem trước. **Huỷ** hoặc Esc trả về lúc mở hộp, OK giữ lại, **Mặc định** đặt lại |

Chưa làm: kéo thả đổi thứ tự chỉ báo trong chú giải, nhóm chỉ báo cộng đồng, và hộp so sánh symbol. Tôi chưa mở hộp Settings của TradingView để đối chiếu từng ô, nên các tab ở đây theo cách làm quen thuộc của họ chứ không phải bản sao từng chi tiết.

### Bảng chỉ báo

Bảng quản lý chỉ báo có ba cột: danh sách chỉ báo và thư viện (kèm nhãn chỉ báo hoặc chiến lược), trình soạn mã có số dòng, thanh trạng thái và dòng lỗi đánh dấu đỏ, và cột tham số (chiến lược có thêm tab Backtest và Kết quả). Kéo thanh trên cùng để đổi chiều cao, nhấp đúp hoặc bấm nút mở rộng để lên 80% màn hình. Trên điện thoại bảng thành tấm trượt từ dưới lên, có nút đóng. Mã dài cuộn trong khung soạn, không còn tràn sang cột tham số.

### Khung tuần và tháng

`1w` bắt đầu thứ Hai 00:00 UTC, `1M` bắt đầu ngày 1 00:00 UTC, gộp từ nến 1 phút trong DuckDB. Ranh giới theo lịch, không chia đều từ epoch, vì chia đều thì tuần bắt đầu thứ Năm. Nến đang chạy cập nhật theo lệnh khớp với cùng ranh giới. Không hỗ trợ `2M`, `2w`, và footprint không có hai khung này. Ngày tính theo UTC nên tuần của cổ phiếu VN (phiên 02:00 đến 08:00 UTC) vẫn đúng.

### Layout nhiều ô

Ô 1, 2 hoặc 4. Mỗi ô chọn symbol và khung riêng, lưu trong localStorage. Cuộn, zoom và crosshair đồng bộ theo mốc thời gian. Chỉ thay đổi do người dùng thao tác trực tiếp mới lan sang ô khác, để việc nạp dữ liệu của một ô không kéo các ô còn lại. Ô phụ chưa có Pine và replay. Mỗi ô mở một kết nối trực tiếp riêng, và server dùng chung nguồn Binance.

## Nghiệm thu

- Nến BTC cập nhật theo thời gian thực. Đã qua.
- Cuộn về quá khứ tải thêm dữ liệu mà không giật. Đã qua.
- Trang trống hiện "server OK" từ `/health` ở Phase 0. Đã qua.

## Việc còn mở

- [ ] Lưu layout nhiều ô vào SQLite và đặt tên được. Hiện nằm trong localStorage.
- [ ] Kiểm thử giao diện tự động bằng Playwright hoặc tương đương. Hiện kiểm thử giao diện làm tay qua trình duyệt.
- [ ] Sắp xếp lớp vẽ của nhiều chỉ báo bằng kéo thả. Xem [08-pine-engine.md](08-pine-engine.md).
- [ ] Sửa điểm neo của hình vẽ. Hiện chỉ xoá rồi vẽ lại. Xem [09-alerts-drawing-backtest.md](09-alerts-drawing-backtest.md).
