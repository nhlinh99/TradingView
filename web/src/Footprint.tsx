import { useEffect, useRef, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import { fetchFootprint } from './api'
import { imbalance, profileStats, tfMs, type Bar, type Cell } from './logic'

type Props = {
  on: boolean
  symbol: string
  tf: string
  ratio: number
  dark: boolean
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
  version: number // đổi khi nến được nạp lại
}

const MIN_CELL_PX = 10
const MIN_BAR_PX = 44
const fmt = (v: number) => (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2))

/** Lớp canvas vẽ ô footprint lên trên biểu đồ. Chỉ vẽ khi nến đủ rộng và đủ cao để đọc. */
export default function Footprint({ on, symbol, tf, ratio, dark, chart, candles, bars, version }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)
  const data = useRef<{ key: string; bucket: number; mult: number; cells: Map<number, Cell[]> } | null>(null)

  useEffect(() => {
    const canvas = cv.current!
    const ctx = canvas.getContext('2d')!
    if (!on) {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      return
    }
    let stopped = false
    let raf = 0
    let sig = ''
    let wantKey = ''
    let ctrl: AbortController | null = null
    let fetchedAt = 0

    const geometry = () => {
      const c = chart.current
      const s = candles.current
      const list = bars.current
      if (!c || !s || list.length < 2) return null
      const ts = c.timeScale()
      const a = list[list.length - 1]
      const b = list[list.length - 2]
      const xa = ts.timeToCoordinate(a.time as Time)
      const xb = ts.timeToCoordinate(b.time as Time)
      if (xa === null || xb === null) return null
      return { ts, s, spacing: Math.abs(xa - xb) }
    }

    const load = async (force = false) => {
      const g = geometry()
      const list = bars.current
      if (!g || g.spacing < MIN_BAR_PX || list.length === 0) return
      const range = g.ts.getVisibleLogicalRange()
      if (!range) return
      const i0 = Math.max(0, Math.floor(range.from) - 1)
      const i1 = Math.min(list.length - 1, Math.ceil(range.to) + 1)
      if (i1 < i0) return
      const lo = Math.min(...list.slice(i0, i1 + 1).map((b) => b.low))
      const hi = Math.max(...list.slice(i0, i1 + 1).map((b) => b.high))
      const y1 = g.s.priceToCoordinate(lo)
      const y2 = g.s.priceToCoordinate(hi)
      if (y1 === null || y2 === null || hi <= lo) return
      const pxPerPrice = Math.abs(y1 - y2) / (hi - lo)
      // mult: số bước bucket cơ sở gộp lại sao cho ô cao tối thiểu MIN_CELL_PX
      const baseBucket = data.current ? data.current.bucket / data.current.mult : 0
      const mult = baseBucket > 0 ? Math.max(1, Math.ceil(MIN_CELL_PX / (pxPerPrice * baseBucket))) : 1
      const from = list[i0].time * 1000
      const to = list[i1].time * 1000 + tfMs(tf)
      const key = `${symbol}|${tf}|${from}|${mult}`
      if (!force && key === wantKey && Date.now() - fetchedAt < 5000) return
      wantKey = key
      fetchedAt = Date.now()
      ctrl?.abort()
      ctrl = new AbortController()
      try {
        const j = await fetchFootprint(symbol, tf, from, to, mult, ctrl.signal)
        const cells = new Map<number, Cell[]>()
        for (const [bar, price, buy, sell] of j.rows) {
          const arr = cells.get(bar / 1000) ?? []
          arr.push({ price, buy, sell })
          cells.set(bar / 1000, arr)
        }
        data.current = { key, bucket: j.bucket, mult, cells }
        sig = ''
      } catch {
        /* huỷ hoặc lỗi tạm: lần sau thử lại */
      }
    }

    const draw = () => {
      if (stopped) return
      raf = requestAnimationFrame(draw)
      const g = geometry()
      const c = chart.current
      const el = canvas.parentElement
      if (!g || !c || !el) return
      const w = el.clientWidth
      const h = el.clientHeight
      const dpr = window.devicePixelRatio || 1
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr)
        canvas.height = Math.round(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        sig = ''
      }
      const r = g.ts.getVisibleLogicalRange()
      const n = bars.current.length
      const newSig = `${r?.from}|${r?.to}|${g.s.priceToCoordinate(0)}|${g.s.priceToCoordinate(1000)}|${n}|${data.current?.key}|${ratio}|${dark}`
      if (newSig === sig) return
      sig = newSig
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      void load()
      const d = data.current
      if (!d || g.spacing < MIN_BAR_PX) return
      const plotW = w - c.priceScale('right').width()
      const half = g.spacing * 0.46
      const step = d.bucket
      const yTop = (p: number) => g.s.priceToCoordinate(p + step)
      ctx.font = '10px system-ui, sans-serif'
      ctx.textBaseline = 'middle'
      for (const b of bars.current) {
        const x = g.ts.timeToCoordinate(b.time as Time)
        if (x === null || x + half < 0 || x - half > plotW) continue
        const cells = (d.cells.get(b.time) ?? []).sort((p, q) => p.price - q.price)
        if (cells.length === 0) continue
        const stats = profileStats(cells)
        cells.forEach((cell, i) => {
          const yt = yTop(cell.price)
          const yb = g.s.priceToCoordinate(cell.price)
          if (yt === null || yb === null) return
          const top = Math.min(yt, yb)
          const ht = Math.abs(yb - yt)
          const side = imbalance(cells, i, step, ratio)
          const isPoc = stats?.poc === cell.price
          ctx.fillStyle = side === 'buy' ? 'rgba(38,166,154,.55)' : side === 'sell' ? 'rgba(239,83,80,.55)' : dark ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.04)'
          ctx.fillRect(x - half, top + 0.5, half * 2, Math.max(1, ht - 1))
          if (isPoc) {
            ctx.strokeStyle = '#f0b90b'
            ctx.lineWidth = 1.5
            ctx.strokeRect(x - half, top + 0.5, half * 2, Math.max(1, ht - 1))
          }
          ctx.fillStyle = dark ? '#d1d4dc' : '#1b2430'
          ctx.textAlign = 'right'
          ctx.fillText(fmt(cell.sell), x - 3, top + ht / 2)
          ctx.textAlign = 'left'
          ctx.fillText(fmt(cell.buy), x + 3, top + ht / 2)
        })
      }
    }

    void load(true)
    const timer = window.setInterval(() => { void load(true) }, 5000)
    raf = requestAnimationFrame(draw)
    return () => {
      stopped = true
      cancelAnimationFrame(raf)
      window.clearInterval(timer)
      ctrl?.abort()
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [on, symbol, tf, ratio, dark, chart, candles, bars, version])

  return <canvas ref={cv} className="fp-canvas" aria-hidden="true" />
}
