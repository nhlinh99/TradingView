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
