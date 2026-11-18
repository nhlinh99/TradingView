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

export type HeatmapResponse = { symbol: string; from: number; to: number; tbucket: number; bucket: number; scale: number; rows: number[][] }
export function fetchHeatmap(symbol: string, from: number, to: number, tbucket: number, mult: number, signal?: AbortSignal) {
  const q = new URLSearchParams({ symbol, from: String(from), to: String(to), tbucket: String(tbucket), mult: String(mult) })
  return json<HeatmapResponse>(`/api/heatmap?${q}`, { signal })
}

export type BubblesResponse = { symbol: string; from: number; to: number; tbucket: number; bucket: number; rows: (number | string)[][] }
export function fetchBubbles(symbol: string, from: number, to: number, tbucket: number, top: number, signal?: AbortSignal) {
  const q = new URLSearchParams({ symbol, from: String(from), to: String(to), tbucket: String(tbucket), top: String(top) })
  return json<BubblesResponse>(`/api/bubbles?${q}`, { signal })
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
  const q = new URLSearchParams({ symbol, from: String(from), to: String(to), tbucket: String(tbucket) })
  return json<IcebergsResponse>(`/api/icebergs?${q}`, { signal })
}
