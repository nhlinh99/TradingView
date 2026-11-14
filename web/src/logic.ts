// Logic thuần của biểu đồ (không đụng DOM), có test trong logic.test.ts.

export type Bar = {
  time: number // giây UTC, đầu nến
  open: number
  high: number
  low: number
  close: number
  volume: number
  buy: number
  sell: number
}
export type Trade = { ts: number; id: number; p: number; q: number; m: boolean }

export const TIMEFRAMES = ['1s', '1m', '5m', '15m', '1h', '4h', '1d', '1w', '1M'] as const
// w = tuần (thứ Hai 00:00 UTC), M = tháng dương lịch; độ dài của M chỉ là số danh nghĩa 30 ngày
const UNIT: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000, w: 7 * 86_400_000, M: 30 * 86_400_000 }

/** Mili giây mở nến chứa tsMs. Tuần bắt đầu thứ Hai, tháng bắt đầu ngày 1 (UTC), còn lại chia đều theo bội của khung. */
export function bucketStartMs(tf: string, tsMs: number): number {
  const step = tfMs(tf)
  if (tf.endsWith('w')) {
    const shift = 3 * 86_400_000 // 1970-01-01 là thứ Năm
    return Math.floor((tsMs + shift) / step) * step - shift
  }
  if (tf.endsWith('M')) {
    const d = new Date(tsMs)
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)
  }
  return Math.floor(tsMs / step) * step
}

export function tfMs(tf: string): number {
  const m = /^(\d+)([smhdwM])$/.exec(tf)
  if (!m || Number(m[1]) <= 0) throw new Error(`timeframe không hợp lệ: ${tf}`)
  return Number(m[1]) * UNIT[m[2]]
}

/** Số chữ số thập phân hiển thị theo tick size: 0.1 -> 1, 0.01 -> 2, 1 -> 0. */
export function decimalsFromTick(tick: number): number {
  let d = 0
  while (d < 8 && Math.abs(Math.round(tick * 10 ** d) - tick * 10 ** d) > 1e-9) d++
  return d
}

/** Dòng nến của server [ts_ms, o, h, l, c, v, buy, sell] -> Bar. */
export function barFromRow(r: number[]): Bar {
  return { time: r[0] / 1000, open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5], buy: r[6], sell: r[7] }
}

/**
 * Áp một lệnh khớp vào mảng nến (sửa tại chỗ). Trả về nến vừa đổi hoặc vừa thêm, hoặc null nếu
 * lệnh thuộc nến cũ hơn nến cuối (không sửa quá khứ).
 */
export function applyTrade(bars: Bar[], tf: number, t: Trade, tfName?: string): Bar | null {
  const time = tfName ? bucketStartMs(tfName, t.ts) / 1000 : Math.floor(t.ts / tf) * (tf / 1000)
  const buy = t.m ? 0 : t.q // isBuyerMaker=true nghĩa là taker bán
  const sell = t.m ? t.q : 0
  const last = bars[bars.length - 1]
  if (!last || time > last.time) {
    const b: Bar = { time, open: t.p, high: t.p, low: t.p, close: t.p, volume: t.q, buy, sell }
    bars.push(b)
    return b
  }
  if (time < last.time) return null
  last.high = Math.max(last.high, t.p)
  last.low = Math.min(last.low, t.p)
  last.close = t.p
  last.volume += t.q
  last.buy += buy
  last.sell += sell
  return last
}

/** Ghép nến cũ hơn vào đầu mảng, bỏ trùng theo time, giữ thứ tự tăng dần. */
export function mergeOlder(existing: Bar[], older: Bar[]): Bar[] {
  const seen = new Set(existing.map((b) => b.time))
  const add = older.filter((b) => !seen.has(b.time))
  return [...add, ...existing].sort((a, b) => a.time - b.time)
}

export const TIMEZONES: { id: string; label: string }[] = [
  { id: 'UTC', label: 'UTC' },
  { id: 'Asia/Ho_Chi_Minh', label: 'Hồ Chí Minh (UTC+7)' },
  { id: 'local', label: 'Máy tính' },
]

export function formatTime(sec: number, tz: string, withSeconds = false): string {
  const opts: Intl.DateTimeFormatOptions = {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    hour12: false, ...(withSeconds ? { second: '2-digit' } : {}),
  }
  if (tz !== 'local') opts.timeZone = tz
  return new Intl.DateTimeFormat('en-GB', opts).format(new Date(sec * 1000))
}

/** Nhãn trục thời gian ngắn: ngày nếu là mốc ngày, ngược lại giờ:phút. */
export function tickLabel(sec: number, tz: string, tfMillis: number): string {
  const opts: Intl.DateTimeFormatOptions = tz === 'local' ? {} : { timeZone: tz }
  const d = new Date(sec * 1000)
  if (tfMillis >= 86_400_000)
    return new Intl.DateTimeFormat('en-GB', { ...opts, day: '2-digit', month: '2-digit' }).format(d)
  return new Intl.DateTimeFormat('en-GB', {
    ...opts, hour: '2-digit', minute: '2-digit', hour12: false,
    ...(tfMillis < 60_000 ? { second: '2-digit' } : {}),
  }).format(d)
}

export function formatVolume(v: number): string {
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(2) + 'K'
  return v.toFixed(v < 1 ? 4 : 2)
}

// ---------- orderflow ----------

export const delta = (b: Bar) => b.buy - b.sell

/** CVD cộng dồn delta. session='day': về 0 vào đầu mỗi ngày UTC. */
export function cvdSeries(bars: Bar[], session: 'none' | 'day'): number[] {
  const out: number[] = []
  let sum = 0
  let day = -1
  for (const b of bars) {
    const d = Math.floor(b.time / 86400)
    if (session === 'day' && d !== day) sum = 0
    day = d
    sum += delta(b)
    out.push(sum)
  }
  return out
}

export type Cell = { price: number; buy: number; sell: number }
export type ImbalanceSide = 'buy' | 'sell' | null

/**
 * Imbalance chéo kiểu footprint: mua ở mức giá p so với bán ở mức giá thấp hơn một bước (và ngược lại),
 * vì người mua chủ động khớp với lệnh bán chờ nằm ở mức giá cao hơn, tức bán ở p-1 bước đối ứng mua ở p.
 * Trả về 'buy' nếu buy[p] >= ratio * sell[p - step], 'sell' nếu sell[p] >= ratio * buy[p + step].
 */
export function imbalance(cells: Cell[], i: number, step: number, ratio: number, minVol = 0): ImbalanceSide {
  const c = cells[i]
  const below = cells.find((x) => Math.abs(x.price - (c.price - step)) < step / 2)
  const above = cells.find((x) => Math.abs(x.price - (c.price + step)) < step / 2)
  if (below && below.sell > 0 && c.buy >= minVol && c.buy >= ratio * below.sell) return 'buy'
  if (above && above.buy > 0 && c.sell >= minVol && c.sell >= ratio * above.buy) return 'sell'
  return null
}

/** Volume profile: POC và vùng giá trị (VAH/VAL) chứa `share` tổng khối lượng, mở rộng từ POC. */
export function profileStats(cells: Cell[], share = 0.7): { poc: number; vah: number; val: number } | null {
  const rows = cells.filter((c) => c.buy + c.sell > 0).sort((a, b) => a.price - b.price)
  if (rows.length === 0) return null
  const vol = rows.map((c) => c.buy + c.sell)
  const total = vol.reduce((a, b) => a + b, 0)
  let poc = 0
  vol.forEach((v, i) => { if (v > vol[poc]) poc = i })
  let lo = poc
  let hi = poc
  let acc = vol[poc]
  while (acc < share * total && (lo > 0 || hi < rows.length - 1)) {
    const down = lo > 0 ? vol[lo - 1] : -1
    const up = hi < rows.length - 1 ? vol[hi + 1] : -1
    if (up >= down) acc += vol[++hi]
    else acc += vol[--lo]
  }
  return { poc: rows[poc].price, vah: rows[hi].price, val: rows[lo].price }
}

// ---------- heatmap ----------

/** Chỉ số (thập phân) của thời điểm tSec trên trục nến; nến i có tâm ở i. Nội suy tuyến tính giữa các nến. */
export function timeToIndex(times: number[], tSec: number, stepSec: number): number {
  const n = times.length
  if (n === 0) return 0
  if (tSec <= times[0]) return (tSec - times[0]) / stepSec
  if (tSec >= times[n - 1]) return n - 1 + (tSec - times[n - 1]) / stepSec
  let lo = 0
  let hi = n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= tSec) lo = mid
    else hi = mid
  }
  return lo + (tSec - times[lo]) / (times[hi] - times[lo])
}

type RGB = [number, number, number]

function ramp(stops: [number, RGB][], x: number): RGB {
  for (let k = 1; k < stops.length; k++) {
    if (x <= stops[k][0]) {
      const [x0, a] = stops[k - 1]
      const [x1, b] = stops[k]
      const f = (x - x0) / (x1 - x0)
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
    }
  }
  return stops[stops.length - 1][1]
}

// Thang cường độ kiểu DeepDom của DeepCharts: đen (ít) -> xanh dương -> trắng -> vàng -> cam -> đỏ (nhiều nhất).
const INTENSITY_STOPS: [number, RGB][] = [
  [0, [0, 0, 0]], [0.2, [20, 40, 170]], [0.5, [255, 255, 255]], [0.72, [255, 235, 59]], [0.88, [255, 152, 0]], [1, [244, 67, 54]],
]
// Thang kiểu Bookmap: nền đen, xanh đậm, xanh dương, cyan, vàng, cam, đỏ (thanh khoản lớn nhất).
const BOOKMAP_STOPS: [number, RGB][] = [
  [0, [0, 0, 0]], [0.15, [0, 16, 63]], [0.4, [10, 90, 203]], [0.62, [18, 214, 224]], [0.8, [255, 233, 74]], [0.92, [255, 138, 0]], [1, [255, 45, 45]],
]
// Kiểu theo phía: lệnh mua chờ màu xanh lá, lệnh bán chờ màu tím.
const BID_STOPS: [number, RGB][] = [[0, [0, 0, 0]], [0.5, [0, 120, 70]], [1, [140, 255, 200]]]
const ASK_STOPS: [number, RGB][] = [[0, [0, 0, 0]], [0.5, [110, 50, 190]], [1, [235, 190, 255]]]

/** Màu ô heatmap: v = thanh khoản / phân vị 99 (có thể lớn hơn 1, sẽ bị cắt). Trả về [r,g,b,a]. */
export function heatColor(v: number, side?: 'bid' | 'ask' | 'bookmap'): [number, number, number, number] {
  const x = Math.min(1, Math.max(0, v))
  if (x === 0) return [0, 0, 0, 0]
  const s = Math.pow(x, 0.5)
  const [r, g, b] = ramp(side === 'bid' ? BID_STOPS : side === 'ask' ? ASK_STOPS : side === 'bookmap' ? BOOKMAP_STOPS : INTENSITY_STOPS, s)
  return [r, g, b, 0.3 + 0.65 * s]
}

/** Ngược của timeToIndex: thời điểm (giây) ứng với chỉ số thập phân idx trên trục nến. */
export function indexToTime(times: number[], idx: number, stepSec: number): number {
  const n = times.length
  if (n === 0) return 0
  if (idx <= 0) return times[0] + idx * stepSec
  if (idx >= n - 1) return times[n - 1] + (idx - (n - 1)) * stepSec
  const lo = Math.floor(idx)
  return times[lo] + (idx - lo) * (times[lo + 1] - times[lo])
}

export type DrawKind = 'trend' | 'hline' | 'rect' | 'fib' | 'text'
export type DrawPoint = { time: number; price: number }
export type Drawing = { id: number; symbol: string; kind: DrawKind; payload: { points: DrawPoint[]; color?: string; text?: string } }
export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]

/** Khoảng cách (px) từ điểm (px,py) tới đoạn thẳng a-b. */
export function distToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax
  const dy = by - ay
  const len2 = dx * dx + dy * dy
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

/** Số mức imbalance chéo liên tiếp dài nhất trong một nến (stacked imbalance). Từ 3 trở lên thường được coi là vùng quan trọng. */
export function stackedImbalance(cells: Cell[], step: number, ratio: number): { side: 'buy' | 'sell'; from: number; to: number } | null {
  const sorted = [...cells].sort((a, b) => a.price - b.price)
  let best: { side: 'buy' | 'sell'; from: number; to: number } | null = null
  let run: { side: 'buy' | 'sell'; from: number; to: number } | null = null
  sorted.forEach((c, i) => {
    const side = imbalance(sorted, i, step, ratio)
    if (side && run && run.side === side && Math.abs(c.price - run.to - step) < step / 2) {
      run.to = c.price
    } else {
      run = side ? { side, from: c.price, to: c.price } : null
    }
    if (run && (!best || run.to - run.from > best.to - best.from)) best = { ...run }
  })
  const b = best as { side: 'buy' | 'sell'; from: number; to: number } | null
  return b && Math.round((b.to - b.from) / step) + 1 >= 3 ? b : null
}

/** Cắt thang màu như Bookmap: dưới `lo` không vẽ, từ `hi` trở lên là màu đậm nhất. v, lo, hi đều theo thang 0..1 của phân vị 99. */
export function applyCutoff(v: number, lo: number, hi: number): number {
  if (hi <= lo) return v >= hi ? 1 : 0
  return Math.min(1, Math.max(0, (v - lo) / (hi - lo)))
}

/** Đường bid/ask tốt nhất theo từng ô thời gian, lấy từ các ô heatmap: bid = giá cao nhất còn lệnh mua chờ, ask = giá thấp nhất còn lệnh bán chờ. */
export function bestBidAsk(rows: number[][], bucket: number): Map<number, { bid: number | null; ask: number | null }> {
  const out = new Map<number, { bid: number | null; ask: number | null }>()
  for (const [t, price, bid, ask] of rows) {
    const e = out.get(t) ?? { bid: null, ask: null }
    if (bid > 0 && (e.bid === null || price + bucket > e.bid)) e.bid = price + bucket
    if (ask > 0 && (e.ask === null || price < e.ask)) e.ask = price
    out.set(t, e)
  }
  return out
}

// ---------- tô màu cú pháp Pine (nhẹ, không dùng thư viện) ----------

export type PineToken = { text: string; kind: 'comment' | 'string' | 'number' | 'keyword' | 'func' | 'const' | 'plain' }
const PINE_KW = new Set(['if', 'else', 'for', 'to', 'by', 'while', 'var', 'varip', 'and', 'or', 'not', 'true', 'false', 'break', 'continue', 'na'])
const PINE_NS = /^(ta|math|color|input|request|strategy|plot|shape|location|size|format|barmerge|hline|syminfo|timeframe|barstate|str|array)$/

/** Tách mã Pine thành các đoạn để tô màu. Nối lại các `text` luôn cho đúng chuỗi gốc. */
export function highlightPine(src: string): PineToken[] {
  const out: PineToken[] = []
  const re = /(\/\/[^\n]*)|("(?:[^"\\n]|\.)*"|'(?:[^'\\n]|\.)*')|(#[0-9a-fA-F]{6,8}\b)|(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)|([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) out.push({ text: src.slice(last, m.index), kind: 'plain' })
    const t = m[0]
    if (m[1]) out.push({ text: t, kind: 'comment' })
    else if (m[2]) out.push({ text: t, kind: 'string' })
    else if (m[3] || m[4]) out.push({ text: t, kind: m[3] ? 'const' : 'number' })
    else {
      const root = t.split('.')[0]
      const after = src[m.index + t.length]
      if (PINE_KW.has(t)) out.push({ text: t, kind: 'keyword' })
      else if (t.includes('.') && PINE_NS.test(root)) out.push({ text: t, kind: after === '(' ? 'func' : 'const' })
      else if (after === '(' && ['indicator', 'strategy', 'plot', 'plotshape', 'bgcolor', 'hline', 'alertcondition', 'input', 'nz', 'time'].includes(t)) out.push({ text: t, kind: 'func' })
      else out.push({ text: t, kind: 'plain' })
    }
    last = m.index + t.length
  }
  if (last < src.length) out.push({ text: src.slice(last), kind: 'plain' })
  return out
}
