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

export const TIMEFRAMES = ['1s', '1m', '5m', '15m', '1h', '4h', '1d'] as const
const UNIT: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000 }

export function tfMs(tf: string): number {
  const m = /^(\d+)([smhd])$/.exec(tf)
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
export function applyTrade(bars: Bar[], tf: number, t: Trade): Bar | null {
  const time = Math.floor(t.ts / tf) * (tf / 1000)
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
