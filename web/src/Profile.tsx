import { useEffect, useRef, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchProfile } from './api'
import { profileStats, tfMs, type Bar, type Cell } from './logic'

type Props = {
  on: boolean
  symbol: string
  tf: string
  dark: boolean
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
  version: number
}

const TARGET_ROWS = 70

/** VPVR: volume profile của đoạn đang nhìn thấy, vẽ ở mép phải, kèm POC, VAH, VAL. */
export default function Profile({ on, symbol, tf, dark, chart, candles, bars, version }: Props) {
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
    let cells: Cell[] = []
    let bucket = 0
    let baseBucket = 0

    const visible = () => {
      const list = bars.current
      const r = chart.current?.timeScale().getVisibleLogicalRange()
      if (!r || list.length === 0) return null
      const i0 = Math.max(0, Math.floor(r.from))
      const i1 = Math.min(list.length - 1, Math.ceil(r.to))
      return i1 < i0 ? null : { list, i0, i1 }
    }

    const load = async () => {
      const v = visible()
      const s = candles.current
      if (!v || !s) return
      const { list, i0, i1 } = v
      const slice = list.slice(i0, i1 + 1)
      const lo = Math.min(...slice.map((b) => b.low))
      const hi = Math.max(...slice.map((b) => b.high))
      const mult = baseBucket > 0 ? Math.max(1, Math.round((hi - lo) / TARGET_ROWS / baseBucket)) : 1
      const from = list[i0].time * 1000
      const to = list[i1].time * 1000 + tfMs(tf)
      const key = `${symbol}|${from}|${to}|${mult}`
      if (key === wantKey) return
      wantKey = key
      ctrl?.abort()
      ctrl = new AbortController()
      try {
        const j = await fetchProfile(symbol, from, to, mult, ctrl.signal)
        cells = j.rows.map(([price, buy, sell]) => ({ price, buy, sell }))
        bucket = j.bucket
        baseBucket = j.bucket / mult
        sig = ''
        if (mult !== Math.max(1, Math.round((hi - lo) / TARGET_ROWS / baseBucket))) wantKey = '' // bucket cơ sở mới biết: nạp lại
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
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr)
        canvas.height = Math.round(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        sig = ''
      }
      const r = c.timeScale().getVisibleLogicalRange()
      const newSig = `${r?.from}|${r?.to}|${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${bars.current.length}|${cells.length}|${bucket}|${dark}`
      if (newSig === sig) return
      sig = newSig
      void load()
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      if (cells.length === 0 || bucket <= 0) return
      const plotW = w - c.priceScale('right').width()
      const maxW = plotW * 0.22
      const max = Math.max(...cells.map((x) => x.buy + x.sell))
      for (const cell of cells) {
        const yt = s.priceToCoordinate(cell.price + bucket)
        const yb = s.priceToCoordinate(cell.price)
        if (yt === null || yb === null) continue
        const len = ((cell.buy + cell.sell) / max) * maxW
        const buyLen = ((cell.buy) / max) * maxW
        const top = Math.min(yt, yb)
        const ht = Math.max(1, Math.abs(yb - yt) - 1)
        ctx.fillStyle = 'rgba(239,83,80,.35)'
        ctx.fillRect(plotW - len, top, len, ht)
        ctx.fillStyle = 'rgba(38,166,154,.45)'
        ctx.fillRect(plotW - len, top, buyLen, ht)
      }
      const st = profileStats(cells)
      if (st) {
        const line = (price: number, color: string, label: string, dash: number[]) => {
          const y = s.priceToCoordinate(price + bucket / 2)
          if (y === null) return
          ctx.setLineDash(dash)
          ctx.strokeStyle = color
          ctx.lineWidth = 1
          ctx.beginPath()
          ctx.moveTo(plotW - maxW - 6, y)
          ctx.lineTo(plotW, y)
          ctx.stroke()
          ctx.setLineDash([])
          ctx.fillStyle = dark ? '#d1d4dc' : '#1b2430'
          ctx.font = '10px system-ui, sans-serif'
          ctx.textAlign = 'right'
          ctx.textBaseline = 'bottom'
          ctx.fillText(label, plotW - maxW - 8, y - 1)
        }
        line(st.poc, '#f0b90b', 'POC', [])
        line(st.vah, '#8a93a3', 'VAH', [4, 3])
        line(st.val, '#8a93a3', 'VAL', [4, 3])
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
  }, [on, symbol, tf, dark, chart, candles, bars, version])

  return <canvas ref={cv} className="fp-canvas" aria-hidden="true" />
}
