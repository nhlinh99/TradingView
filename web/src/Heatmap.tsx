import { useEffect, useRef, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchHeatmap } from './api'
import { heatColor, tfMs, timeToIndex, type Bar } from './logic'

type Props = {
  on: boolean
  mode: 'intensity' | 'side'
  symbol: string
  tf: string
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
  version: number
}

const CELL_PX = 4

/** Heatmap thanh khoản vẽ DƯỚI nến (canvas nằm sau biểu đồ; nền biểu đồ được đặt trong suốt). */
export default function Heatmap({ on, mode, symbol, tf, chart, candles, bars, version }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)

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
    let rows: number[][] = []
    let scale = 1
    let bucket = 0
    let baseBucket = 0
    let tb = 5000
    const step = tfMs(tf) / 1000

    const load = async () => {
      const c = chart.current
      const s = candles.current
      const list = bars.current
      if (!c || !s || list.length === 0) return
      const r = c.timeScale().getVisibleLogicalRange()
      if (!r) return
      const i0 = Math.max(0, Math.floor(r.from))
      const i1 = Math.min(list.length - 1, Math.ceil(r.to))
      if (i1 < i0) return
      const from = list[i0].time * 1000
      const to = list[i1].time * 1000 + tfMs(tf)
      const wpx = c.timeScale().width()
      const tbucket = Math.max(5000, Math.ceil((to - from) / Math.max(1, wpx / CELL_PX) / 5000) * 5000)
      const slice = list.slice(i0, i1 + 1)
      const lo = Math.min(...slice.map((b) => b.low))
      const hi = Math.max(...slice.map((b) => b.high))
      const y1 = s.priceToCoordinate(lo)
      const y2 = s.priceToCoordinate(hi)
      let mult = 1
      if (baseBucket > 0 && y1 !== null && y2 !== null && hi > lo) {
        const pxPerPrice = Math.abs(y1 - y2) / (hi - lo)
        mult = Math.max(1, Math.ceil(CELL_PX / (pxPerPrice * baseBucket)))
      }
      const key = `${symbol}|${from}|${to}|${tbucket}|${mult}`
      if (key === wantKey) return
      wantKey = key
      ctrl?.abort()
      ctrl = new AbortController()
      try {
        const j = await fetchHeatmap(symbol, from, to, tbucket, mult, ctrl.signal)
        const first = baseBucket === 0
        rows = j.rows
        scale = j.scale || 1
        bucket = j.bucket
        baseBucket = j.bucket / mult
        tb = j.tbucket
        sig = ''
        if (first) wantKey = '' // vừa biết bucket cơ sở: tính lại mult
      } catch {
        /* huỷ hoặc lỗi tạm */
      }
    }

    const draw = () => {
      if (stopped) return
      raf = requestAnimationFrame(draw)
      const c = chart.current
      const s = candles.current
      const el = canvas.parentElement
      if (!c || !s || !el) return
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
      const r = c.timeScale().getVisibleLogicalRange()
      const newSig = `${r?.from}|${r?.to}|${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${bars.current.length}|${rows.length}|${mode}`
      if (newSig === sig) return
      sig = newSig
      void load()
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      if (rows.length === 0 || bucket <= 0) return
      const times = bars.current.map((b) => b.time)
      const ts = c.timeScale()
      const plotW = w - c.priceScale('right').width()
      // logicalToCoordinate chỉ đáng tin với số nguyên: lấy hai mốc nguyên rồi tự nội suy tuyến tính
      const a = Math.round(r?.from ?? 0)
      const xa = ts.logicalToCoordinate(a as never)
      const xb = ts.logicalToCoordinate((a + 1) as never)
      if (xa === null || xb === null) return
      const sp = xb - xa
      const xOf = (idx: number) => xa + (idx - a) * sp
      const cache = new Map<number, [number, number]>()
      const span = (t: number): [number, number] => {
        let v = cache.get(t)
        if (!v) {
          v = [xOf(timeToIndex(times, t / 1000, step) - 0.5), xOf(timeToIndex(times, (t + tb) / 1000, step) - 0.5)]
          cache.set(t, v)
        }
        return v
      }
      for (const [t, price, bid, ask] of rows) {
        const [x0, x1] = span(t)
        if (Number.isNaN(x0) || x1 < 0 || x0 > plotW) continue
        const yt = s.priceToCoordinate(price + bucket)
        const yb = s.priceToCoordinate(price)
        if (yt === null || yb === null) continue
        const [R, G, B, A] = mode === 'side' ? heatColor(Math.max(bid, ask) / scale, bid >= ask ? 'bid' : 'ask') : heatColor((bid + ask) / scale)
        if (A === 0) continue
        ctx.fillStyle = `rgba(${R | 0},${G | 0},${B | 0},${A.toFixed(2)})`
        const top = Math.min(yt, yb)
        ctx.fillRect(x0, top, Math.max(1, x1 - x0 + 0.5), Math.max(1, Math.abs(yb - yt) + 0.5))
      }
    }

    void load()
    raf = requestAnimationFrame(draw)
    return () => {
      stopped = true
      cancelAnimationFrame(raf)
      ctrl?.abort()
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [on, mode, symbol, tf, chart, candles, bars, version])

  return <canvas ref={cv} className="heat-canvas" aria-hidden="true" />
}
