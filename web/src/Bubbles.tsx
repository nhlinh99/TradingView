import { useEffect, useRef, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchBubbles } from './api'
import { tfMs, timeToIndex, type Bar } from './logic'

type Props = {
  on: boolean
  symbol: string
  tf: string
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
  version: number
}

const MAX_R = 20

/** Bong bóng: cụm lệnh khớp lớn nhất trong đoạn đang nhìn, kích thước theo khối lượng, màu theo phía chủ động. */
export default function Bubbles({ on, symbol, tf, chart, candles, bars, version }: Props) {
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
    let rows: (number | string)[][] = []
    let tb = 10_000
    const step = tfMs(tf) / 1000

    const load = async () => {
      const c = chart.current
      const list = bars.current
      if (!c || list.length === 0) return
      const r = c.timeScale().getVisibleLogicalRange()
      if (!r) return
      const i0 = Math.max(0, Math.floor(r.from))
      const i1 = Math.min(list.length - 1, Math.ceil(r.to))
      if (i1 < i0) return
      const from = list[i0].time * 1000
      const to = list[i1].time * 1000 + tfMs(tf)
      const tbucket = Math.max(1000, Math.ceil((to - from) / Math.max(1, c.timeScale().width() / 10) / 1000) * 1000)
      const key = `${symbol}|${from}|${to}|${tbucket}`
      if (key === wantKey) return
      wantKey = key
      ctrl?.abort()
      ctrl = new AbortController()
      try {
        const j = await fetchBubbles(symbol, from, to, tbucket, 300, ctrl.signal)
        rows = j.rows
        tb = j.tbucket
        sig = ''
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
      const newSig = `${r?.from}|${r?.to}|${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${bars.current.length}|${rows.length}`
      if (newSig === sig) return
      sig = newSig
      void load()
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      if (rows.length === 0) return
      const ts = c.timeScale()
      const a = Math.round(r?.from ?? 0)
      const xa = ts.logicalToCoordinate(a as never)
      const xb = ts.logicalToCoordinate((a + 1) as never)
      if (xa === null || xb === null) return
      const times = bars.current.map((b) => b.time)
      const xOf = (idx: number) => xa + (idx - a) * (xb - xa)
      const plotW = w - c.priceScale('right').width()
      const max = Math.max(...rows.map((x) => x[2] as number))
      for (const [t, price, q, side, n] of rows) {
        const x = xOf(timeToIndex(times, ((t as number) + tb / 2) / 1000, step))
        const y = s.priceToCoordinate(price as number)
        if (y === null || x < 0 || x > plotW) continue
        const rad = Math.max(3, Math.sqrt((q as number) / max) * MAX_R)
        // kiểu Deep Trades: vòng đặc = một lệnh lớn đơn lẻ; vòng rỗng = nhiều lệnh nhỏ cộng lại
        const solid = Number(n) === 1
        const rgb = side === 'buy' ? '38,166,154' : '239,83,80'
        ctx.beginPath()
        ctx.arc(x, y, rad, 0, Math.PI * 2)
        ctx.fillStyle = solid ? `rgba(${rgb},.8)` : `rgba(${rgb},.12)`
        ctx.fill()
        ctx.strokeStyle = `rgba(${rgb},.95)`
        ctx.lineWidth = solid ? 1 : 2
        ctx.stroke()
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
  }, [on, symbol, tf, chart, candles, bars, version])

  return <canvas ref={cv} className="fp-canvas" aria-hidden="true" />
}
