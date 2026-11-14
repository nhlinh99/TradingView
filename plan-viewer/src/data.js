// Nội dung tách khỏi phần vẽ. Mọi ID trong edges và phases phải tồn tại trong components.

export const components = {
  binance: {
    label: 'Binance Futures', sub: 'sàn giao dịch BTC', kind: 'source', badge: 'free',
    what: 'Sàn phái sinh cung cấp giá, lệnh khớp và sổ lệnh của BTCUSDT perpetual qua API công khai.',
    how: 'Ba luồng dữ liệu: nến (REST), lệnh khớp gộp aggTrade (WebSocket), thay đổi sổ lệnh depth (WebSocket). Mỗi lệnh khớp có cờ isBuyerMaker: true nghĩa là bên bán chủ động.',
    pros: 'Miễn phí, không cần key, có đủ dữ liệu cho orderflow và heatmap. File lịch sử aggTrade tải được từ data.binance.vision.',
    cons: 'Lịch sử sổ lệnh miễn phí chỉ có dạng thô: bookDepth cách 30 giây, gồm độ sâu tích luỹ ở 6 dải ±0,2% đến ±5% quanh giá (từ 2023). Lịch sử từng mức giá phải tự ghi. Đây là giá của Binance, không phải mọi sàn.',
    why: 'Đây là nguồn duy nhất cho BTC có cả tick có hướng mua/bán lẫn sổ lệnh mà không tốn tiền.',
  },
  binanceGold: {
    label: 'Binance XAUUSDT', sub: 'hợp đồng perpetual vàng', kind: 'source', badge: 'free',
    what: 'Hợp đồng perpetual vàng thanh toán bằng USDT, ra mắt đầu tháng 1/2026. Là cách miễn phí để có tick và sổ lệnh có hướng cho vàng.',
    how: 'Đã kiểm chứng: klines, aggTrades và depth của XAUUSDT trả dữ liệu qua API công khai, không cần key. Kho data.binance.vision có aggTrades và bookDepth từ 11/12/2025. Binance xếp nó vào loại TRADIFI_PERPETUAL (underlying COMMODITY).',
    pros: 'Miễn phí, dùng chung code với BTC. Có orderflow và heatmap thật của hợp đồng này. Binance liệt kê 237 hợp đồng loại này, nên sau này có thể thêm bạc và các tài sản khác.',
    cons: 'Đây là volume của Binance, không phải volume của COMEX (GC1!). Giá có thể lệch khỏi XAUUSD spot. Cần kiểm tra giờ giao dịch và đơn vị khối lượng (chưa rõ có tính theo ounce hay không).',
    why: 'Đường duy nhất tôi tìm được để có orderflow vàng mà không trả tiền.',
  },
  deribit: {
    label: 'Deribit', sub: 'sàn options BTC', kind: 'source', badge: 'free',
    what: 'Sàn options crypto lớn. Cho biết các strike, open interest (số hợp đồng đang mở) và greeks của options BTC.',
    how: 'Gọi API công khai get_book_summary_by_currency (kind=option) và ticker để lấy IV và greeks.',
    pros: 'Miễn phí, không cần key. Đủ dữ liệu để tính GEX.',
    cons: 'Deribit xác nhận trong changelog: open interest công khai là giá trị của 8 giờ trước, kể cả ở endpoint ticker. GEX chỉ dùng theo ngày. Gọi dồn dập sẽ bị giới hạn tốc độ (tôi đã gặp lỗi khi gọi liên tiếp), nên collector phải giãn nhịp.',
    why: 'Phần lớn open interest options BTC nằm ở Deribit.',
  },
  databento: {
    label: 'Databento', sub: 'dữ liệu CME: GC, options OG', kind: 'source', badge: 'paid',
    what: 'Nhà cung cấp dữ liệu thị trường. Cho tick có hướng mua/bán, sổ lệnh 10 mức (mbp-10) và options vàng (OG) của sàn CME.',
    how: 'Tải lịch sử hoặc nhận live qua thư viện Python. Schema trades có trường side: Bid là bên mua chủ động, Ask là bên bán chủ động.',
    pros: 'Dữ liệu CME chính thức. Có lịch sử từ 2010. Có cả orderflow lẫn options của vàng.',
    cons: 'Trang giá: gói Standard $199/tháng, Plus $1.750/tháng, Unlimited $4.500/tháng (hai gói sau là phí license CME). Tặng $125 credit cho dữ liệu lịch sử, hết hạn sau 6 tháng. Giá theo GB không công bố ở trang đó, và trang có nhắc mốc 3/2025 nên có thể đã cũ. Từng có báo cáo strike OG bị chia 100, cần kiểm tra.',
    why: 'XAUUSD spot không có volume tập trung. Hợp đồng GC là nguồn volume thật cho vàng.',
  },
  vn: {
    label: 'SSI / vnstock', sub: 'cổ phiếu VN100', kind: 'source', badge: 'unverified',
    what: 'SSI FastConnect là API chính thức của công ty chứng khoán SSI. vnstock là thư viện Python gom dữ liệu từ nhiều nguồn miễn phí.',
    how: 'SSI: streaming X-TRADE có trường Side (BU = mua lên, SD = bán xuống). HOSE có 3 mức giá mua/bán, HNX/UPCoM/phái sinh có 10 mức. vnstock: Guest 20 lượt/phút, Community 60 lượt/phút (key miễn phí).',
    pros: 'Có volume thật của HOSE, HNX, UPCoM. vnstock cài nhanh.',
    cons: 'SSI chỉ cấp cho khách có tài khoản SSI, đăng ký qua quầy hoặc môi giới, hạn 1 năm, phí chưa rõ. Trường Side là hướng của tick, không chắc là bên chủ động. vnstock có giấy phép phi thương mại, gói Sponsor trả phí (giá chưa rõ). Không có options cổ phiếu nên không có GEX.',
    why: 'Đây là hai đường dễ nhất để có volume cổ phiếu Việt Nam.',
  },
  collector: {
    label: 'Collector', sub: 'nhận từ mọi nguồn, ghi xuống đĩa', kind: 'process', badge: null,
    what: 'Một chương trình chạy liên tục. Nhận dữ liệu từ các nguồn, chuẩn hoá và ghi xuống đĩa.',
    how: 'Giữ kết nối WebSocket, tự nối lại khi đứt. Dựng nến mọi timeframe từ tick. Mỗi giây chụp sổ lệnh, gom theo bucket giá 1 USD rồi ghi.',
    pros: 'Ghi dữ liệu kể cả khi trình duyệt đóng. Lịch sử depth chỉ có được nhờ chương trình này chạy sớm.',
    cons: 'Phải chạy liên tục. Máy tắt thì mất dữ liệu trong khoảng đó.',
    why: 'Tách việc thu thập khỏi giao diện để dữ liệu không phụ thuộc vào việc bạn có mở chart hay không.',
  },
  alert: {
    label: 'Alert', sub: 'thông báo desktop / Telegram', kind: 'process', badge: null,
    what: 'Kiểm tra điều kiện (giá, Pine alertcondition) và gửi thông báo khi điều kiện đúng.',
    how: 'Chạy trong collector, nên vẫn hoạt động khi trình duyệt đóng.',
    pros: 'Không cần mở chart.',
    cons: 'Telegram cần token bot trong file .env.',
    why: 'Một người dùng không cần hệ thống thông báo riêng.',
  },
  parquet: {
    label: 'DuckDB + Parquet', sub: 'tick, depth, options', kind: 'store', badge: null,
    what: 'Kho dữ liệu chính. Parquet là định dạng file nén theo cột. DuckDB là công cụ SQL chạy ngay trên các file đó.',
    how: 'Collector ghi file theo giờ. Server truy vấn bằng SQL, không cần chạy máy chủ database.',
    pros: 'Nén tốt, truy vấn nhanh, không cần cài máy chủ.',
    cons: 'Không hợp để ghi từ nhiều tiến trình cùng lúc. Với một người dùng thì không thành vấn đề.',
    why: 'Tick và depth tạo ra nhiều dòng. Định dạng cột xử lý loại dữ liệu này hiệu quả hơn SQLite.',
  },
  sqlite: {
    label: 'SQLite', sub: 'layout, hình vẽ, alert', kind: 'store', badge: null,
    what: 'Database nhỏ trong một file. Giữ cài đặt của bạn.',
    how: 'Lưu watchlist, bố cục chart, hình vẽ, điều kiện alert.',
    pros: 'Không cần cài đặt. Sao lưu bằng cách chép một file.',
    cons: 'Không dành cho dữ liệu lớn.',
    why: 'Dữ liệu cấu hình ít và hay thay đổi. SQLite hợp hơn Parquet.',
  },
  server: {
    label: 'Server', sub: 'FastAPI, chạy trên localhost', kind: 'process', badge: null,
    what: 'Nhận yêu cầu từ trình duyệt, đọc dữ liệu và trả về. Đẩy nến đang chạy qua WebSocket.',
    how: 'REST cho dữ liệu lịch sử (/bars, /footprint, /heatmap, /gex). WebSocket /stream cho dữ liệu trực tiếp.',
    pros: 'Python dùng chung ngôn ngữ với Databento và vnstock.',
    cons: 'Chỉ truy cập được từ máy bạn. Đó là điều bạn muốn.',
    why: 'Một lớp mỏng giữa dữ liệu và giao diện.',
  },
  pine: {
    label: 'Pine engine', sub: 'chạy script Pine (tập con)', kind: 'process', badge: null,
    what: 'Bộ thông dịch tự viết, chạy script Pine v5 trên dữ liệu của bạn. TradingView không cung cấp runtime riêng.',
    how: 'Phân tích cú pháp, chạy từng nến, trả về các đường plot, hình, và điều kiện alert. Thêm request.external để dùng delta và mức GEX.',
    pros: 'Chạy được script của bạn trên dữ liệu orderflow thật. Việc này TradingView không làm được.',
    cons: 'Đây là hạng mục lớn nhất. Chỉ hỗ trợ một tập con của Pine. Kết quả phải so với tính tay.',
    why: 'Bạn muốn dùng lại script Pine. Viết lại bằng ngôn ngữ khác tốn công hơn.',
  },
  chart: {
    label: 'Chart', sub: 'nến + volume', kind: 'view', badge: null,
    what: 'Biểu đồ nến, pane volume, chọn timeframe, crosshair, watchlist.',
    how: 'Dùng thư viện Lightweight Charts v5 (mã nguồn mở, Apache-2.0, cần ghi attribution).',
    pros: 'Nhẹ, nhanh. Có cơ chế primitive để vẽ thêm lớp riêng.',
    cons: 'Không có sẵn công cụ vẽ, heatmap hay footprint. Phải tự viết.',
    why: 'Đủ cho một người dùng. Không cần xin license thư viện thương mại.',
  },
  orderflow: {
    label: 'Orderflow', sub: 'footprint, delta, CVD, profile', kind: 'view', badge: null,
    what: 'Cho thấy ai chủ động mua, ai chủ động bán ở từng mức giá trong mỗi nến.',
    how: 'Gom lệnh khớp theo (nến, giá). Delta = volume mua chủ động trừ volume bán chủ động. CVD là tổng delta cộng dồn.',
    pros: 'Thấy áp lực thật phía sau nến.',
    cons: 'Cần tick có hướng. XAUUSD spot không có, nên dùng GC làm proxy.',
    why: 'Đây là tính năng cốt lõi bạn yêu cầu.',
  },
  heat: {
    label: 'Heatmap thanh khoản', sub: 'lệnh chờ theo thời gian', kind: 'view', badge: null,
    what: 'Bản đồ nhiệt của lệnh chờ trên sổ lệnh. Trục ngang là thời gian, trục dọc là giá, màu càng đậm thì lệnh chờ càng lớn.',
    how: 'Đọc bảng depth đã gom bucket. Vẽ bằng canvas dưới lớp nến.',
    pros: 'Thấy vùng giá có nhiều lệnh chờ.',
    cons: 'Lệnh chờ có thể là lệnh giả (spoofing) hoặc lệnh ẩn (iceberg). Heatmap không cho biết ý định.',
    why: 'Bổ sung cho orderflow: orderflow cho thấy lệnh đã khớp, heatmap cho thấy lệnh đang chờ.',
  },
  gex: {
    label: 'GEX', sub: 'gamma exposure', kind: 'view', badge: null,
    what: 'Ước tính mức độ các nhà tạo lập thị trường phải mua hoặc bán để cân bằng rủi ro options. Hiện thành các đường ngang: gamma flip, call wall, put wall.',
    how: 'Với mỗi strike: gamma × OI × contract size × giá² × 0,01. Call tính dương, put tính âm.',
    pros: 'Cho các mức giá tham chiếu từ thị trường options.',
    cons: 'Giả định nhà tạo lập long call và short put. Đây là mô hình, không phải vị thế thật. Cổ phiếu Việt Nam không có.',
    why: 'Bạn yêu cầu GEX cho BTC và vàng.',
  },
};

// kind: request = yêu cầu/phản hồi (xanh), data = dòng dữ liệu (cam)
export const edges = [
  { id: 'e1', s: 'binance', t: 'collector', kind: 'data', label: '', sh: 'r-s', th: 'l-t' },
  { id: 'e2', s: 'deribit', t: 'collector', kind: 'data', label: '', sh: 'r-s', th: 'l-t' },
  { id: 'e2b', s: 'binanceGold', t: 'collector', kind: 'data', label: '', sh: 'r-s', th: 'l-t' },
  { id: 'e3', s: 'databento', t: 'collector', kind: 'data', label: '', sh: 'r-s', th: 'l-t' },
  { id: 'e4', s: 'vn', t: 'collector', kind: 'data', label: '', sh: 'r-s', th: 'l-t' },
  { id: 'e5', s: 'collector', t: 'parquet', kind: 'data', label: 'ghi tick, depth, options', sh: 'r-s', th: 'l-t' },
  { id: 'e6', s: 'collector', t: 'alert', kind: 'data', label: 'điều kiện đúng', sh: 'b-s', th: 't-t' },
  { id: 'e7', s: 'server', t: 'parquet', kind: 'request', label: 'truy vấn SQL', sh: 'l-s', th: 'r-t' },
  { id: 'e8', s: 'server', t: 'sqlite', kind: 'request', label: 'layout, alert', sh: 'l-s', th: 'r-t' },
  { id: 'e9', s: 'chart', t: 'server', kind: 'request', label: '/bars, /stream', sh: 'l-s', th: 'r-t' },
  { id: 'e10', s: 'orderflow', t: 'server', kind: 'request', label: '/footprint', sh: 'l-s', th: 'r-t' },
  { id: 'e11', s: 'heat', t: 'server', kind: 'request', label: '/heatmap', sh: 'l-s', th: 'r-t' },
  { id: 'e12', s: 'gex', t: 'server', kind: 'request', label: '/gex', sh: 'l-s', th: 'r-t' },
  { id: 'e13', s: 'server', t: 'pine', kind: 'request', label: 'chạy script', sh: 'b-s', th: 't-t' },
];

// Mỗi phase thêm các component. Hiển thị theo kiểu cộng dồn.
export const phases = [
  { id: 'p0', tab: 'P0', title: 'Khung dự án', add: ['server'],
    sum: 'Tạo thư mục, cấu hình, script chạy server và web cùng lúc.',
    ok: 'Mở localhost:5173 thấy dòng "server OK".' },
  { id: 'p1', tab: 'P1', title: 'Collector BTC', add: ['binance', 'collector', 'parquet'],
    sum: 'Ghi nến, lệnh khớp và sổ lệnh BTC từ Binance. Tải thêm 30 ngày lịch sử aggTrade.',
    ok: 'Sau 10 phút, số dòng tick tăng đều. Volume nến 1m khớp kline Binance, sai lệch dưới 0,1%.' },
  { id: 'p2', tab: 'P2', title: 'Chart cơ bản', add: ['chart', 'sqlite'],
    sum: 'Nến, volume, timeframe, watchlist. Nến cập nhật trực tiếp.',
    ok: 'Nến BTC chạy theo thời gian thực. Cuộn về quá khứ không giật.' },
  { id: 'p3', tab: 'P3', title: 'Orderflow', add: ['orderflow'],
    sum: 'Footprint, delta, CVD, volume profile (POC, VAH, VAL).',
    ok: 'Tổng delta trong footprint bằng delta ở pane delta. Có test.' },
  { id: 'p4', tab: 'P4', title: 'Heatmap', add: ['heat'],
    sum: 'Vẽ lệnh chờ dưới nến, thêm bong bóng volume.',
    ok: 'Cuộn và zoom cùng trục với nến. 2 giờ dữ liệu vẽ dưới 100 ms.' },
  { id: 'p5', tab: 'P5', title: 'GEX BTC', add: ['deribit', 'gex'],
    sum: 'Lấy options từ Deribit, tính GEX, vẽ gamma flip và các wall.',
    ok: 'GEX khớp tính tay trên 3 strike mẫu.' },
  { id: 'p6', tab: 'P6', title: 'Vàng', add: ['binanceGold'],
    sum: 'Bản miễn phí: dùng hợp đồng XAUUSDT của Binance cho orderflow và heatmap vàng, qua pipeline đã có. Thêm GEX xấp xỉ từ options GLD nếu điều khoản cho phép.',
    ok: 'XAUUSDT hiện nến, footprint và heatmap. API đã kiểm chứng hoạt động.' },
  { id: 'p6b', tab: 'P6+', title: 'GC1! (tuỳ chọn, trả phí)', add: ['databento'],
    sum: 'Chỉ làm khi bạn có key Databento. Cho volume COMEX thật và options vàng (GEX vàng).',
    ok: 'GC1! hiện footprint thật. Hỏi bạn trước khi tải dữ liệu tính theo GB.' },
  { id: 'p7', tab: 'P7', title: 'Cổ phiếu VN100', add: ['vn'],
    sum: 'Chỉ rổ VN100 (100 mã HOSE, lấy danh sách từ nguồn, không viết cứng). Adapter cho vnstock và SSI. Volume, volume profile, sổ lệnh 3 mức ghi khi có thay đổi. Không có GEX.',
    ok: 'vn100.json có đúng 100 mã. VNM, FPT, VCB khớp volume trang nguồn. Sau một phiên, mỗi mã có sổ lệnh.' },
  { id: 'p8', tab: 'P8', title: 'Pine engine', add: ['pine'],
    sum: 'Parser, thư viện ta.*, request.security, request.external, editor Monaco.',
    ok: '5 script mẫu chạy. SMA và EMA khớp pandas với sai số dưới 1e-9.' },
  { id: 'p9', tab: 'P9', title: 'Vẽ, layout, alert', add: ['alert'],
    sum: 'Công cụ vẽ, nhiều chart đồng bộ, alert, bar replay.',
    ok: 'Đóng trình duyệt, collector vẫn gửi thông báo khi điều kiện đúng.' },
];

// Vị trí theo cột: nguồn, collector, lưu trữ, server, trình duyệt.
export const layout = {
  binance: { x: 30, y: 50 }, binanceGold: { x: 30, y: 155 }, deribit: { x: 30, y: 260 }, databento: { x: 30, y: 365 }, vn: { x: 30, y: 470 },
  collector: { x: 350, y: 230 }, alert: { x: 350, y: 470 },
  parquet: { x: 660, y: 110 }, sqlite: { x: 660, y: 360 },
  server: { x: 960, y: 230 }, pine: { x: 960, y: 470 },
  chart: { x: 1290, y: 50 }, orderflow: { x: 1290, y: 175 }, heat: { x: 1290, y: 300 }, gex: { x: 1290, y: 425 },
};

export const lanes = [
  { id: 'L1', label: 'Nguồn dữ liệu', x: 0, y: 0, w: 280, h: 600 },
  { id: 'L2', label: 'Thu thập', x: 320, y: 0, w: 280, h: 600 },
  { id: 'L3', label: 'Lưu trữ', x: 630, y: 0, w: 280, h: 600 },
  { id: 'L4', label: 'Server', x: 930, y: 0, w: 280, h: 600 },
  { id: 'L5', label: 'Trình duyệt', x: 1260, y: 0, w: 280, h: 600 },
];

// Bảng miễn phí / trả phí
export const freeMatrix = [
  { f: 'Nến, volume, footprint, delta, CVD, volume profile cho BTC', c: 'free', n: 'Binance Futures, không cần key. Đã kiểm chứng aggTrades trả dữ liệu có cờ mua/bán.' },
  { f: 'Heatmap thanh khoản BTC, từng mức giá', c: 'free', n: 'Miễn phí nếu bạn tự ghi từ bây giờ.' },
  { f: 'Lịch sử thanh khoản thô của BTC', c: 'free', n: 'Kho Binance có bookDepth từ 2023: cách 30 giây, 6 dải từ ±0,2% đến ±5% quanh giá. Đủ cho bản đồ thô, không đủ cho heatmap từng mức giá.' },
  { f: 'GEX BTC', c: 'free', n: 'Deribit public. Greeks có trong ticker. Open interest trễ 8 giờ (Deribit xác nhận), nên dùng theo ngày.' },
  { f: 'Orderflow, heatmap và lịch sử vàng (XAUUSDT)', c: 'free', n: 'Đã kiểm chứng: klines, aggTrades, depth không cần key. Lịch sử từ 11/12/2025. Là volume của Binance, không phải COMEX.' },
  { f: 'GEX vàng, bản xấp xỉ', c: 'maybe', n: 'Options của ETF GLD có trên Cboe, Yahoo, MarketChameleon (trễ khoảng 15 phút). Điều khoản dùng chưa kiểm tra. Là ETF, không phải COMEX.' },
  { f: 'Volume cổ phiếu Việt Nam', c: 'maybe', n: 'vnstock: Guest 20 lượt/phút, Community 60 lượt/phút (key miễn phí), giấy phép phi thương mại. SSI cần tài khoản SSI, đăng ký qua quầy hoặc môi giới, hạn 1 năm, phí chưa rõ.' },
  { f: 'Orderflow cổ phiếu Việt Nam', c: 'maybe', n: 'SSI có trường Side (BU/SD) nhưng đó là hướng tick, không chắc là bên chủ động. HOSE chỉ 3 mức giá, HNX và UPCoM 10 mức.' },
  { f: 'Pine engine, công cụ vẽ, layout, alert, replay', c: 'free', n: 'Tự viết, chạy trên máy bạn. Tốn công, không tốn tiền. Lightweight Charts là mã nguồn mở.' },
  { f: 'Volume COMEX thật của GC1!', c: 'paid', n: 'Databento: Standard $199/tháng, Plus $1.750, Unlimited $4.500 (theo trang giá, có thể cũ). Tặng $125 credit lịch sử. Giá theo GB không công bố.' },
  { f: 'GEX vàng chính xác (options COMEX)', c: 'paid', n: 'Cần options OG của CME qua Databento.' },
  { f: 'Lịch sử sổ lệnh chi tiết trước ngày bạn bắt đầu ghi', c: 'paid', n: 'Tardis.dev: gói Solo khoảng $700/tháng cho perpetuals (bảng giá không ghi nhãn rõ, tôi suy ra), đơn tối thiểu $300.' },
  { f: 'Heatmap thanh lý (liquidation)', c: 'paid', n: 'Coinglass API từ khoảng $22,75/tháng (trả theo năm). Chưa rõ gói nào có heatmap. Bạn cũng có thể tự ước tính từ open interest và funding, chỉ là mô hình.' },
  { f: 'Spot XAUUSD có volume thật', c: 'none', n: 'Không tồn tại. Spot là thị trường OTC, chỉ có tick volume của từng broker.' },
  { f: 'GEX cổ phiếu Việt Nam', c: 'none', n: 'Không có options cổ phiếu niêm yết.' },
];

// Dung lượng đo từ một ngày dữ liệu Binance (10/11/2026), BTC + XAUUSDT
export const storage = {
  perDay: [
    { k: 'File CSV gốc', btc: 101.1, xau: 38.1 },
    { k: 'Parquet zstd, đủ cột', btc: 6.65, xau: 2.85 },
    { k: 'Footprint 1 phút', btc: 0.34, xau: 0.895 },
  ],
  plans: [
    { k: 'Giữ CSV gốc', y1: 51, y5: 254, note: 'Không nên. Lớn gấp 15 lần Parquet.' },
    { k: 'Parquet, giữ mọi tick', y1: 3.5, y5: 17, note: 'Chạy được, nhưng phần lớn là tick cũ ít khi xem.' },
    { k: 'Parquet, tick 30 ngày, sau đó footprint 1 phút', y1: 0.7, y5: 2.5, note: 'Khuyến nghị. Tick cũ tải lại miễn phí từ Binance khi cần.' },
  ],
  rules: [
    'Để dữ liệu ngoài OneDrive (ví dụ C:\\tv-data). OneDrive sẽ đồng bộ hàng nghìn file lớn và khoá file khi collector ghi.',
    'Chỉ lưu Parquet zstd. Giá dạng số nguyên theo tick size, qty float32, sắp xếp theo thời gian.',
    'Không lưu thứ tải lại được miễn phí: aggTrades, klines, bookDepth của Binance. Chỉ giữ tick gần đây.',
    'Thứ không tải lại được thì giữ kỹ: sổ lệnh từng mức giá tự ghi, snapshot options, dữ liệu trả phí.',
    'Gom nén mỗi đêm theo retention.yaml. Đặt trần dung lượng, vượt trần thì xoá tầng cũ nhất.',
  ],
  depthNote: 'Sổ lệnh tự ghi (cửa sổ ±1%, bucket 5 USD, 5 giây/lần): ước tính 15 đến 25 MB mỗi ngày. Chưa đo. Phase 1 sẽ đo thật.',
};

// Dữ liệu lịch sử cho backtest (ngày bắt đầu kiểm tra 14/11/2026)
export const history = [
  { d: 'aggTrades (có cờ mua/bán)', s: 'BTCUSDT', from: '31/12/2019', use: 'Footprint, delta, CVD, volume profile', c: 'free' },
  { d: 'aggTrades', s: 'XAUUSDT', from: '11/12/2025', use: 'Như trên, mẫu ngắn khoảng 11 tháng', c: 'free' },
  { d: 'Nến 1 phút', s: 'BTCUSDT', from: '31/12/2019', use: 'Giá, volume', c: 'free' },
  { d: 'metrics: open interest, long/short, taker (5 phút)', s: 'BTCUSDT', from: '01/09/2020', use: 'Bộ lọc vị thế', c: 'free' },
  { d: 'bookDepth: 6 dải ±0,2% đến ±5%, cách 30 giây', s: 'BTCUSDT', from: '01/01/2023', use: 'Heatmap thô', c: 'free' },
  { d: 'bookDepth', s: 'XAUUSDT', from: '11/12/2025', use: 'Heatmap thô', c: 'free' },
  { d: 'Sổ lệnh từng mức giá', s: 'BTC, vàng', from: 'Từ lúc bạn ghi', use: 'Heatmap chi tiết. Mua từ Tardis.dev khoảng $700/tháng (chưa xác nhận)', c: 'paid' },
  { d: 'Lịch sử options (GEX)', s: 'BTC', from: 'Từ lúc bạn ghi', use: 'Backtest GEX. Deribit không có lịch sử OI miễn phí', c: 'paid' },
  { d: 'mbp-10, mbo của GC', s: 'GC1!', from: '2010 (mbp-10), 2017 (mbo)', use: 'Databento, giá theo GB không công bố', c: 'paid' },
  { d: 'Tick cổ phiếu VN100', s: 'VN100', from: 'Chưa tìm thấy nguồn', use: 'Chỉ có nến từ vnstock', c: 'none' },
];
export const historyLimits = [
  'aggTrades gộp lệnh cùng giá, cùng thời điểm. Không mô phỏng được khớp từng lệnh.',
  'Volume và orderflow là của Binance, không phải toàn thị trường.',
  'Backtest không mô phỏng vị trí hàng đợi và độ trễ. Tín hiệu từ heatmap dễ đẹp hơn thực tế vì lệnh giả.',
  'XAUUSDT chỉ có khoảng 11 tháng, độ tin cậy thấp.',
  'Chỉ dùng dữ liệu có thời gian không muộn hơn lúc nến đóng. Có bộ kiểm tra chống nhìn trước.',
];
