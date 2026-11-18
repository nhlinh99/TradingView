import type { Trade } from './logic'

export type SymbolInfo = { symbol: string; tick: number; source: string | null }
export type BarsResponse = {
  symbol: string
  tf: string
  tf_ms: number
  tick: number
  last_trade_id: number | null
  bars: number[][]
}

/** Yêu cầu nặng: thử lại đúng một lần sau 2 giây khi máy chủ báo bận (503), vì mỗi lần thử lại sẽ xếp thêm một truy vấn nặng. */
async function heavyJson<T>(url: string, init?: RequestInit): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const r = await fetch(url, init)
    if (r.status === 503 && attempt < 1) {
      await new Promise<void>((resolve, reject) => {
        const t = setTimeout(resolve, 2000)
        init?.signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('Aborted', 'AbortError')) }, { once: true })
      })
      continue
    }
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`)
    return (await r.json()) as T
  }
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`)
  return (await r.json()) as T
}

export const fetchSymbols = () => json<SymbolInfo[]>('/api/symbols')
export const fetchWatchlist = async () => (await json<{ symbols: string[] }>('/api/watchlist')).symbols
export const saveWatchlist = async (symbols: string[]) =>
  (await json<{ symbols: string[] }>('/api/watchlist', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ symbols }),
  })).symbols

export function fetchBars(symbol: string, tf: string, limit = 1000, to?: number, signal?: AbortSignal) {
  const q = new URLSearchParams({ symbol, tf, limit: String(limit) })
  if (to !== undefined) q.set('to', String(to))
  return json<BarsResponse>(`/api/bars?${q}`, { signal })
}

export type StreamState = 'connecting' | 'connected' | 'reconnecting'
export type StreamHandlers = {
  onTrade: (t: Trade) => void
  onState: (s: StreamState) => void
  /** Gọi mỗi lần (nối lại) kết nối tới server xong và đã đăng ký symbol. Nơi để nạp lại nến. */
  onOpen: () => void
}

/** WebSocket tới /api/stream cho một symbol. Tự nối lại khi mất kết nối. Trả về hàm đóng. */
export function openStream(symbol: string, h: StreamHandlers): () => void {
  let ws: WebSocket | null = null
  let closed = false
  let delay = 500
  let timer: ReturnType<typeof setTimeout> | undefined

  const connect = () => {
    if (closed) return
    h.onState('connecting')
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/stream`)
    ws.onopen = () => {
      delay = 500
      ws?.send(JSON.stringify({ op: 'subscribe', symbol }))
      h.onOpen()
    }
    ws.onmessage = (ev) => {
      let m: { t: string; state?: string; ts?: number; id?: number; p?: number; q?: number; m?: boolean }
      try {
        m = JSON.parse(ev.data as string)
      } catch {
        return
      }
      if (m.t === 'trade') h.onTrade({ ts: m.ts!, id: m.id!, p: m.p!, q: m.q!, m: m.m! })
      else if (m.t === 'status') h.onState(m.state === 'connected' ? 'connected' : 'reconnecting')
    }
    ws.onclose = () => {
      if (closed) return
      h.onState('reconnecting')
      timer = setTimeout(connect, delay)
      delay = Math.min(delay * 2, 15_000)
    }
    ws.onerror = () => ws?.close()
  }
  connect()
  return () => {
    closed = true
    clearTimeout(timer)
    ws?.close()
  }
}

export type FootprintResponse = { symbol: string; tf: string; tick: number; bucket: number; from: number; to: number; rows: number[][] }
export function fetchFootprint(symbol: string, tf: string, from: number, to: number, mult: number, signal?: AbortSignal) {
  const q = new URLSearchParams({ symbol, tf, from: String(from), to: String(to), mult: String(mult) })
  return json<FootprintResponse>(`/api/footprint?${q}`, { signal })
}

export type ProfileResponse = { symbol: string; from: number; to: number; bucket: number; rows: number[][] }
export function fetchProfile(symbol: string, from: number, to: number, mult: number, signal?: AbortSignal) {
  const q = new URLSearchParams({ symbol, from: String(from), to: String(to), mult: String(mult) })
  return json<ProfileResponse>(`/api/profile?${q}`, { signal })
}

/** XAUUSD (vàng spot TVC) không có sổ lệnh: Bookmap, chấm volume và iceberg lấy từ XAUUSDT (Binance) rồi dịch giá theo chênh lệch hai mã. Là ước lượng. */
const FLOW_SOURCE: Record<string, string> = { XAUUSD: 'XAUUSDT' }
let basisCache: { key: string; at: number; p: Promise<number> } | null = null
/** Chênh lệch giá trung vị (đóng cửa mã biểu đồ trừ đóng cửa mã nguồn) trên các nến 5 phút gần nhất. Dùng chung một lời hứa cho các yêu cầu đồng thời và nhớ 60 giây (lỗi: nhớ 5 giây, trả 0). */
function flowBasis(symbol: string, src: string): Promise<number> {
  const key = `${symbol}|${src}`
  if (basisCache && basisCache.key === key && Date.now() - basisCache.at < 60_000) return basisCache.p
  const get = async (s: string) => (await json<{ bars: number[][] }>(`/api/bars?symbol=${s}&tf=5m&limit=300`)).bars
  const entry = { key, at: Date.now(), p: Promise.resolve(0) }
  entry.p = Promise.all([get(symbol), get(src)]).then(([a, b]) => {
    const close = new Map(b.map((r) => [r[0], r[4]] as [number, number]))
    const diffs = a.filter((r) => close.has(r[0])).map((r) => r[4] - (close.get(r[0]) as number)).sort((x, y) => x - y)
    return diffs.length > 0 ? diffs[Math.floor(diffs.length / 2)] : 0
  }).catch(() => { entry.at = Date.now() - 55_000; return 0 })
  basisCache = entry
  return entry.p
}
async function viaFlowSource<T extends { rows: (number | string)[][] }>(symbol: string, call: (s: string) => Promise<T>): Promise<T> {
  const src = FLOW_SOURCE[symbol]
  if (!src) return call(symbol)
  const [res, off] = await Promise.all([call(src), flowBasis(symbol, src)])
  return { ...res, symbol, rows: res.rows.map((r) => { const x = [...r]; x[1] = Math.round((Number(r[1]) + off) * 1e6) / 1e6; return x }) }
}

export type CoverageResponse = { symbol: string; from: number; to: number; segments: [number, number][]; first: number | null; last: number | null; covered_ms: number }
/** Các đoạn thời gian đã ghi sổ lệnh chi tiết (cho heatmap). XAUUSD dùng sổ lệnh XAUUSDT. */
export function fetchCoverage(symbol: string, from: number, to: number, signal?: AbortSignal) {
  const q = new URLSearchParams({ symbol: FLOW_SOURCE[symbol] ?? symbol, from: String(from), to: String(to) })
  return json<CoverageResponse>(`/api/heatmap/coverage?${q}`, { signal })
}

export type DepthBandsResponse = { symbol: string; from: number; to: number; tbucket: number; scale: number; rows: number[][] }
/** Độ sâu thô (±0,2% đến ±5% quanh giá, kho bookDepth của Binance) cho đoạn chưa có heatmap chi tiết. Dải tính theo % nên không cần dịch giá. */
export function fetchDepthBands(symbol: string, from: number, to: number, tbucket: number, signal?: AbortSignal) {
  const q = new URLSearchParams({ symbol: FLOW_SOURCE[symbol] ?? symbol, from: String(from), to: String(to), tbucket: String(tbucket) })
  return heavyJson<DepthBandsResponse>(`/api/depthbands?${q}`, { signal })
}

export type DomResponse = {
  symbol: string; ts: number; age_ms: number; source: 'live' | 'book'; bucket: number; mult: number
  best_bid: number | null; best_ask: number | null; bids: number[][]; asks: number[][]
}
/** Bảng độ sâu hiện tại (bid, ask theo bucket giá). XAUUSD dùng sổ lệnh XAUUSDT, giá dịch theo chênh lệch hai mã. */
export async function fetchDom(symbol: string, mult: number, signal?: AbortSignal): Promise<DomResponse> {
  const src = FLOW_SOURCE[symbol] ?? symbol
  const q = new URLSearchParams({ symbol: src, mult: String(mult) })
  const [res, off] = await Promise.all([json<Omit<DomResponse, 'mult'>>(`/api/dom?${q}`, { signal }), src === symbol ? Promise.resolve(0) : flowBasis(symbol, src)])
  const shift = (rows: number[][]) => rows.map(([p, v]) => [Math.round((p + off) * 1e6) / 1e6, v])
  return {
    ...res, symbol, mult,
    best_bid: res.best_bid === null ? null : res.best_bid + off, best_ask: res.best_ask === null ? null : res.best_ask + off,
    bids: shift(res.bids), asks: shift(res.asks),
  }
}

export type LiqZonesResponse = { symbol: string; from: number; to: number; bucket: number; scale: number; rows: (number | string)[][] }
/** Vùng thanh khoản kéo dài theo thời gian: [phía, giá, bắt đầu, kết thúc, lớn nhất, còn lại, trạng thái] (rút lệnh, bị khớp, còn hiệu lực). */
export function fetchLiqZones(symbol: string, from: number, to: number, mult: number, min: number, top: number, minS: number, signal?: AbortSignal) {
  return viaFlowSource(symbol, (s) => {
    const q = new URLSearchParams({ symbol: s, from: String(from), to: String(to), mult: String(mult), min: String(min), top: String(top), min_s: String(minS) })
    return heavyJson<LiqZonesResponse>(`/api/liqzones?${q}`, { signal })
  })
}

export type HeatmapResponse = { symbol: string; from: number; to: number; tbucket: number; bucket: number; scale: number; rows: number[][] }
export function fetchHeatmap(symbol: string, from: number, to: number, tbucket: number, mult: number, signal?: AbortSignal) {
  return viaFlowSource(symbol, (s) => {
    const q = new URLSearchParams({ symbol: s, from: String(from), to: String(to), tbucket: String(tbucket), mult: String(mult) })
    return json<HeatmapResponse>(`/api/heatmap?${q}`, { signal })
  }) as Promise<HeatmapResponse>
}

export type BubblesResponse = { symbol: string; from: number; to: number; tbucket: number; bucket: number; rows: (number | string)[][] }
export function fetchBubbles(symbol: string, from: number, to: number, tbucket: number, top: number, signal?: AbortSignal) {
  return viaFlowSource(symbol, (s) => {
    const q = new URLSearchParams({ symbol: s, from: String(from), to: String(to), tbucket: String(tbucket), top: String(top) })
    return json<BubblesResponse>(`/api/bubbles?${q}`, { signal })
  })
}

export type GexResponse = {
  symbol: string; ts: number; spot: number; total: number; flip: number | null
  call_wall: number | null; put_wall: number | null; age_s: number; oi_note: string
  by_strike: { strike: number; call: number; put: number; net: number }[]
}
export const fetchGex = (signal?: AbortSignal) => json<GexResponse>('/api/gex', { signal })

export type PineInput = {
  title: string; type: string; default: unknown; minval?: number; maxval?: number; step?: number
  options?: string[]; group?: string; tooltip?: string; inline?: string
}
export type PineResult = {
  symbol: string; tf: string; times: number[]
  meta: { kind: string; title: string; overlay: boolean }
  inputs: PineInput[]
  plots: { title: string; style: string; linewidth: number; offset?: number; values: (number | null)[]; colors: (string | null)[]; dash?: 'solid' | 'dashed' | 'dotted'; hidden?: boolean }[]
  shapes: { title: string; shape: string; location: string; text: string; values: boolean[]; colors: (string | null)[]; hidden?: boolean }[]
  bgcolors: { colors: (string | null)[]; hidden?: boolean }[]
  hlines: { price: number | null; title: string; color: string | null; dash?: 'solid' | 'dashed' | 'dotted'; width?: number; hidden?: boolean }[]
  alerts: { title: string; message: string; bars: number[] }[]
  alert_events?: { bar: number; message: string }[]
  future_bars?: number
  scaleLabels?: boolean      // do giao diện đặt: hiện nhãn giá trị cuối trên thang giá
  candles?: { title: string; ohlc: (number[] | null)[]; color: (string | null)[]; wick: (string | null)[]; border: (string | null)[] }[]
  fills?: { a: number; b: number; title: string; colors: (string | null)[]; hidden?: boolean }[]
  objects?: {
    lines: Record<string, unknown>[]; labels: Record<string, unknown>[]; boxes: Record<string, unknown>[]
    polylines?: { points: { index: number | null; time: number | null; price: number | null }[]; line_color?: string | null; line_width?: number; line_style?: string; closed?: boolean; fill_color?: string | null }[]
    tables: { position: string; rows: number; columns: number; bgcolor?: string | null; border_color?: string | null
      cells: { col: number; row: number; text?: string; text_color?: string; text_size?: string; bgcolor?: string; tooltip?: string }[]; merges: number[][] }[]
  }
  strategy: null | {
    initial_capital: number; net_profit: number; closed_trades: number; win_rate: number; max_drawdown: number; equity: (number | null)[]
    trades: { id: string; dir: string; entry_time: number; entry_price: number; exit_time: number; exit_price: number; qty: number; pnl: number; pnl_pct: number }[]
  }
}
export const fetchPineExamples = () => json<{ name: string; source: string }[]>('/api/pine/examples')
export type BacktestOpts = { from_ms?: number; to_ms?: number; commission_pct?: number; slippage_ticks?: number; initial_capital?: number }
/** Số nến nạp cho script: mặc định 1000; nếu có đầu vào số nguyên lớn (độ dài lookback) thì nạp thêm để lookback không bị cắt. Tối đa 5000 (giới hạn máy chủ). */
export function pineBarLimit(inputs: Record<string, unknown>): number {
  let need = 1000
  for (const v of Object.values(inputs)) if (typeof v === 'number' && Number.isFinite(v) && v >= 1000 && v <= 4900) need = Math.max(need, Math.ceil(v) + 100)
  return need
}
export async function runPine(source: string, symbol: string, tf: string, inputs: Record<string, unknown>, opts: BacktestOpts = {}): Promise<PineResult> {
  const r = await fetch('/api/pine/run', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ source, symbol, tf, limit: pineBarLimit(inputs), inputs, ...opts }),
  })
  const body = await r.json()
  if (!r.ok) throw body
  return body as PineResult
}

import type { Drawing, DrawKind } from './logic'
export const fetchDrawings = (symbol: string) => json<Drawing[]>(`/api/drawings?symbol=${encodeURIComponent(symbol)}`)
export const createDrawing = (symbol: string, kind: DrawKind, payload: Drawing['payload'], id?: number) =>
  json<Drawing>('/api/drawings', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ symbol, kind, payload, id }) })
export const updateDrawing = (id: number, symbol: string, kind: DrawKind, payload: Drawing['payload']) =>
  json<Drawing>(`/api/drawings/${id}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ symbol, kind, payload }) })
export const deleteDrawing = (id: number) => json<{ deleted: number }>(`/api/drawings/${id}`, { method: 'DELETE' })
export const clearDrawings = (symbol: string) => json<{ deleted: number }>(`/api/drawings?symbol=${encodeURIComponent(symbol)}`, { method: 'DELETE' })

export type AlertItem = { id: number; symbol: string; text: string; enabled: boolean; created: string; has_source: boolean; condition: Record<string, unknown> }
export type AlertEvent = { id: number; alert_id: number; ts: number; symbol: string; message: string; sent: string }
export const fetchAlerts = () => json<AlertItem[]>('/api/alerts')
export const fetchAlertEvents = () => json<AlertEvent[]>('/api/alerts/events')
export const createAlert = async (symbol: string, condition: Record<string, unknown>, message?: string) => {
  const r = await fetch('/api/alerts', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ symbol, condition, message }) })
  const b = await r.json()
  if (!r.ok) throw b
  return b as AlertItem
}
export const setAlertEnabled = (id: number, enabled: boolean) =>
  json<{ id: number }>(`/api/alerts/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled }) })
export const deleteAlert = (id: number) => json<{ deleted: number }>(`/api/alerts/${id}`, { method: 'DELETE' })

export type IcebergsResponse = { symbol: string; from: number; to: number; tbucket: number; rows: (number | string)[][] }
export function fetchIcebergs(symbol: string, from: number, to: number, tbucket: number, signal?: AbortSignal) {
  return viaFlowSource(symbol, (s) => {
    const q = new URLSearchParams({ symbol: s, from: String(from), to: String(to), tbucket: String(tbucket) })
    return json<IcebergsResponse>(`/api/icebergs?${q}`, { signal })
  })
}
