import { useEffect, useRef, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import { fetchFootprint } from './api'
import { heatColor, imbalance, profileStats, stackedImbalance, tfMs, type Bar, type Cell } from './logic'

type Props = {
  on: boolean
  symbol: string
  tf: string
  ratio: number
  fpMode: 'bidask' | 'delta' | 'volume' | 'profile'
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
export default function Footprint({ on, symbol, tf, ratio, fpMode, dark, chart, candles, bars, version }: Props) {
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
      canvas.style.clipPath = `inset(0 0 ${Math.max(0, h - (c.panes()[0]?.getHeight() ?? h))}px 0)` // chỉ vẽ trong pane giá
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr)
        canvas.height = Math.round(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        sig = ''
      }
      const r = g.ts.getVisibleLogicalRange()
      const n = bars.current.length
      const newSig = `${r?.from}|${r?.to}|${g.s.priceToCoordinate(0)}|${g.s.priceToCoordinate(1000)}|${n}|${data.current?.key}|${ratio}|${fpMode}|${dark}`
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
      ctx.textBaseline = 'middle'
      const ink = dark ? '#d1d4dc' : '#1b2430'
      const UP = '38,166,154'
      const DN = '239,83,80'
      for (const b of bars.current) {
        const x = g.ts.timeToCoordinate(b.time as Time)
        if (x === null || x + half < 0 || x - half > plotW) continue
        const cells = (d.cells.get(b.time) ?? []).sort((p, q) => p.price - q.price)
        if (cells.length === 0) continue
        const stats = profileStats(cells)
        const maxVol = Math.max(...cells.map((k) => k.buy + k.sell))
        const maxDelta = Math.max(...cells.map((k) => Math.abs(k.buy - k.sell)), 1e-9)
        const stack = stackedImbalance(cells, step, ratio)
        let lowY = -Infinity
        cells.forEach((cell, i) => {
          const yt = yTop(cell.price)
          const yb = g.s.priceToCoordinate(cell.price)
          if (yt === null || yb === null) return
          const top = Math.min(yt, yb)
          const ht = Math.abs(yb - yt)
          lowY = Math.max(lowY, top + ht)
          const side = imbalance(cells, i, step, ratio)
          const isPoc = stats?.poc === cell.price
          const delta = cell.buy - cell.sell
          const vol = cell.buy + cell.sell
          // nền ô theo kiểu hiển thị
          if (fpMode === 'bidask') {
            ctx.fillStyle = side === 'buy' ? `rgba(${UP},.55)` : side === 'sell' ? `rgba(${DN},.55)` : dark ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.04)'
            ctx.fillRect(x - half, top + 0.5, half * 2, Math.max(1, ht - 1))
          } else if (fpMode === 'delta') {
            const a = 0.12 + 0.6 * (Math.abs(delta) / maxDelta)
            ctx.fillStyle = delta >= 0 ? `rgba(${UP},${a})` : `rgba(${DN},${a})`
            ctx.fillRect(x - half, top + 0.5, half * 2, Math.max(1, ht - 1))
          } else if (fpMode === 'volume') {
            const [R, G, B, A] = heatColor(vol / maxVol)
            ctx.fillStyle = `rgba(${R | 0},${G | 0},${B | 0},${(A * 0.8).toFixed(2)})`
            ctx.fillRect(x - half, top + 0.5, half * 2, Math.max(1, ht - 1))
          } else {
            // profile: thanh ngang hai phía từ tâm nến, dài theo khối lượng mua (phải) và bán (trái)
            const lenB = (cell.buy / maxVol) * half
            const lenS = (cell.sell / maxVol) * half
            ctx.fillStyle = `rgba(${UP},.6)`
            ctx.fillRect(x, top + 1, lenB, Math.max(1, ht - 2))
            ctx.fillStyle = `rgba(${DN},.6)`
            ctx.fillRect(x - lenS, top + 1, lenS, Math.max(1, ht - 2))
          }
          if (isPoc) {
            ctx.strokeStyle = '#f0b90b'
            ctx.lineWidth = 1.5
            ctx.strokeRect(x - half, top + 0.5, half * 2, Math.max(1, ht - 1))
          }
          // chữ tự co theo chiều cao ô (như Deep Print): quá nhỏ thì bỏ chữ
          const fs = Math.max(7, Math.min(13, ht * 0.75))
          if (ht < 8) return
          ctx.font = `${fs.toFixed(1)}px system-ui, sans-serif`
          ctx.fillStyle = ink
          if (fpMode === 'bidask' || fpMode === 'profile') {
            ctx.textAlign = 'right'
            ctx.fillText(fmt(cell.sell), x - 3, top + ht / 2)
            ctx.textAlign = 'left'
            ctx.fillText(fmt(cell.buy), x + 3, top + ht / 2)
          } else {
            ctx.textAlign = 'center'
            ctx.fillText(fmt(fpMode === 'delta' ? delta : vol), x, top + ht / 2)
          }
        })
        // stacked imbalance: khung đậm ở mép nến phía có imbalance liên tiếp
        if (stack) {
          const y1 = g.s.priceToCoordinate(stack.from)
          const y2 = g.s.priceToCoordinate(stack.to + step)
          if (y1 !== null && y2 !== null) {
            ctx.strokeStyle = stack.side === 'buy' ? `rgb(${UP})` : `rgb(${DN})`
            ctx.lineWidth = 3
            const xe = stack.side === 'buy' ? x + half + 1 : x - half - 1
            ctx.beginPath(); ctx.moveTo(xe, Math.min(y1, y2)); ctx.lineTo(xe, Math.max(y1, y2)); ctx.stroke()
          }
        }
        // thống kê dưới nến: delta và khối lượng của cả nến
        if (lowY > -Infinity && g.spacing >= 56) {
          const dl = cells.reduce((a, k) => a + k.buy - k.sell, 0)
          const tv = cells.reduce((a, k) => a + k.buy + k.sell, 0)
          ctx.font = '10px system-ui, sans-serif'
          ctx.textAlign = 'center'
          ctx.fillStyle = dl >= 0 ? `rgb(${UP})` : `rgb(${DN})`
          ctx.fillText(`Δ ${dl >= 0 ? '+' : ''}${fmt(dl)}`, x, lowY + 9)
          ctx.fillStyle = ink
          ctx.fillText(`V ${fmt(tv)}`, x, lowY + 20)
        }
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
  }, [on, symbol, tf, ratio, fpMode, dark, chart, candles, bars, version])

  return <canvas ref={cv} className="fp-canvas" aria-hidden="true" />
}
