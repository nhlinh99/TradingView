import { useEffect, useRef, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchIcebergs } from './api'
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

/**
 * Dấu hiệu iceberg (ước lượng độ tin cậy thấp): ô mà khối lượng khớp vượt nhiều lần thanh khoản đang hiển thị.
 * Vẽ hình thoi băng giá; viền xanh lá là mua chủ động hấp thụ lệnh bán chờ, viền đỏ là bán chủ động hấp thụ lệnh mua chờ.
 */
export default function Icebergs({ on, symbol, tf, chart, candles, bars, version }: Props) {
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
    let tb = 30_000
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
      const tbucket = Math.max(5000, Math.ceil((to - from) / Math.max(1, c.timeScale().width() / 6) / 5000) * 5000)
      const key = `${symbol}|${from}|${to}|${tbucket}`
      if (key === wantKey) return
      wantKey = key
      ctrl?.abort()
      ctrl = new AbortController()
      try {
        const j = await fetchIcebergs(symbol, from, to, tbucket, ctrl.signal)
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
      canvas.style.clipPath = `inset(0 0 ${Math.max(0, h - (c.panes()[0]?.getHeight() ?? h))}px 0)`
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
      for (const [t, price, traded, shown, side] of rows) {
        const x = xOf(timeToIndex(times, ((t as number) + tb / 2) / 1000, step))
        const y = s.priceToCoordinate(price as number)
        if (y === null || x < 0 || x > plotW) continue
        const ratio = (traded as number) / (shown as number)
        const rad = Math.max(5, Math.min(14, 4 + Math.sqrt((traded as number) / max) * 10))
        ctx.beginPath()
        ctx.moveTo(x, y - rad); ctx.lineTo(x + rad * 0.8, y); ctx.lineTo(x, y + rad); ctx.lineTo(x - rad * 0.8, y); ctx.closePath()
        ctx.fillStyle = 'rgba(190,235,255,.85)'
        ctx.fill()
        ctx.strokeStyle = side === 'buy' ? '#00e676' : '#ff5252'
        ctx.lineWidth = 2
        ctx.stroke()
        if (ratio >= 4) {
          ctx.fillStyle = '#ffffff'
          ctx.font = '10px system-ui, sans-serif'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillText(`${ratio.toFixed(0)}x`, x + rad + 2, y)
        }
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
