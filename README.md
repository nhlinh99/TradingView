# TradingView

Biểu đồ giá chạy trên máy cá nhân, dùng một người, lấy cảm hứng từ TradingView. Mục tiêu: nến, volume, orderflow (footprint, delta, CVD), heatmap thanh khoản và GEX cho BTC và vàng, cộng volume cổ phiếu VN100. Script Pine chạy trên dữ liệu của bạn.

Dự án không liên kết với TradingView. Không dùng tên, logo hay giao diện của họ.

## Trạng thái

| Phase | Nội dung | Trạng thái |
|---|---|---|
| 0 | Khung dự án, kho Parquet, server, trang web | Xong |
| 1 | Collector BTC (Binance Futures) | Chưa làm |
| 2 | Chart cơ bản | Chưa làm |
| 3 | Orderflow | Chưa làm |
| 4 | Heatmap thanh khoản | Chưa làm |
| 5 | GEX BTC (Deribit) | Chưa làm |
| 6 | Vàng (XAUUSDT; GC1! tuỳ chọn, trả phí) | Chưa làm |
| 7 | Cổ phiếu VN100 | Chưa làm |
| 8 | Engine Pine Script (tập con) | Chưa làm |
| 9 | Công cụ vẽ, layout, alert, backtest | Chưa làm |

Kế hoạch chi tiết, điều kiện nghiệm thu từng phase và các việc chưa xác minh nằm trong [`PLAN-CLAUDE-CODE.md`](PLAN-CLAUDE-CODE.md). Bản nghiên cứu đầu tiên là [`PLAN.md`](PLAN.md). Một số nhận định trong đó đã được sửa, xem ghi chú đầu file.

Sơ đồ tương tác của kế hoạch: mở `plan-viewer/dist/plan.html` bằng trình duyệt. Trang chạy offline. Dựng lại bằng `cd plan-viewer && npm install && node build.mjs`.

## Nguồn dữ liệu

| Dữ liệu | Nguồn | Chi phí |
|---|---|---|
| BTC: nến, lệnh khớp, sổ lệnh | Binance Futures (API công khai, không cần key) | Miễn phí |
| BTC: GEX | Deribit (open interest trễ 8 giờ) | Miễn phí |
| Vàng: orderflow, heatmap | Binance XAUUSDT, lịch sử từ 11/12/2025 | Miễn phí |
| Vàng: volume COMEX, options | Databento (GC1!) | Trả phí |
| Cổ phiếu VN100 | vnstock, SSI FastConnect (cần tài khoản SSI) | Miễn phí hoặc chưa rõ |

Lịch sử sổ lệnh từng mức giá không có miễn phí. Collector phải ghi từ lúc bạn bắt đầu chạy. Bảng đầy đủ, kèm giá và giới hạn, nằm trong kế hoạch.

## Cài đặt (Windows)

Cần Python 3.11 trở lên (đã chạy trên 3.15.2) và Node.js (đã chạy trên 26.13).

1. Sao chép `.env.example` thành `.env`. Đặt `DATA_DIR` **ngoài OneDrive**, ví dụ `C:\tv-data`. Code từ chối đường dẫn nằm trong OneDrive, vì OneDrive sẽ đồng bộ hàng nghìn file dữ liệu và khoá file khi ghi.
2. Tạo môi trường Python trong `DATA_DIR` và cài thư viện:
   ```powershell
   python -m venv C:\tv-data\.venv
   C:\tv-data\.venv\Scripts\python.exe -m pip install fastapi uvicorn duckdb httpx websockets python-dotenv pytest
   ```
   Không dùng `uvicorn[standard]`: nó kéo theo PyYAML, chưa có bản dựng sẵn cho Python 3.15.
3. Tạo thư mục dữ liệu và `app.sqlite`:
   ```powershell
   C:\tv-data\.venv\Scripts\python.exe -m common.init_data
   ```
4. Cài thư viện web ngoài OneDrive (script tạo junction `web\node_modules`):
   ```powershell
   .\scripts\web-deps.ps1
   ```
   Luôn thêm gói qua script này (`-Add 'tên-gói'`). `npm install` chạy thẳng trong `web\` sẽ xoá junction và cài vào OneDrive.

## Chạy

```powershell
.\dev.ps1
```

Mở `http://localhost:5173`. Trang hiện "server OK" khi server Python (`127.0.0.1:8000`) hoạt động. Nhấn Ctrl+C để dừng cả hai.

Chạy test:
```powershell
C:\tv-data\.venv\Scripts\python.exe -m pytest
```

## Cấu trúc

```
common/      kho Parquet (store.py), SQLite (appdb.py), khởi tạo thư mục
collector/   thu thập dữ liệu nền (Phase 1)
server/      FastAPI: /health, sau này /bars, /footprint, /heatmap, /gex
web/         Vite + React + TypeScript + Lightweight Charts
config/      symbols.toml (tick size), retention.toml (chính sách giữ dữ liệu)
tests/       pytest
scripts/     web-deps.ps1
plan-viewer/ sơ đồ tương tác của kế hoạch
```

Dữ liệu nằm ngoài repo, trong `DATA_DIR`, dạng Parquet nén zstd theo `kind/symbol/date=YYYY-MM-DD.parquet`, đọc bằng DuckDB. Một ngày BTCUSDT khoảng 6,65 MB. Ước tính dung lượng dài hạn và chính sách gom nén nằm trong kế hoạch.

## Lưu ý

- File `.ps1` phải giữ ASCII thuần. Windows PowerShell 5.1 đọc UTF-8 không BOM theo bảng mã ANSI và làm hỏng chuỗi tiếng Việt.
- Lightweight Charts theo giấy phép Apache-2.0 và yêu cầu ghi attribution.
- Mỗi nguồn dữ liệu có điều khoản riêng. Dùng cá nhân. Đọc điều khoản trước khi chia sẻ dữ liệu hoặc công bố kết quả.
- Đây không phải lời khuyên đầu tư. Orderflow, heatmap và GEX là mô hình ước tính với giả định riêng. Xem giới hạn trong kế hoạch.
