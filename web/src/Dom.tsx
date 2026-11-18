import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchDom, type DomResponse } from './api'
import type { Bar } from './logic'

type Props = {
  on: boolean
  dark: boolean
  symbol: string
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
  version: number
}

const POLL_MS = 2000
const ROW_PX = 5          // chiều cao tối thiểu của một dòng giá

/**
 * Bảng độ sâu (DOM) kiểu Bookmap: cột thanh khoản đang chờ ở từng mức giá, nằm sát trục giá bên phải.
 * Bid (xanh) nằm dưới giá, ask (đỏ) nằm trên giá, thanh càng dài thì khối lượng chờ càng lớn; các mức lớn nhất ghi số.
 */
export default function Dom({ on, dark, symbol, chart, candles, bars, version }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)
  const [info, setInfo] = useState<{ text: string; warn: boolean } | null>(null)

  useEffect(() => {
    const canvas = cv.current!
    const ctx = canvas.getContext('2d')!
    if (!on) {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      return
    }
    let stopped = false
    let raf = 0
    let timer = 0
    let ctrl: AbortController | null = null
    let dom: DomResponse | null = null
    let baseBucket = 0
    let sig = ''
    let failed = false

    /** Bội của bucket cơ sở để mỗi dòng cao tối thiểu ROW_PX pixel ở mức thu phóng hiện tại. */
    const wantMult = (): number => {
      const s = candles.current
      const el = canvas.parentElement
      if (!s || !el || baseBucket <= 0) return 1
      const p0 = s.coordinateToPrice(0)
      const p1 = s.coordinateToPrice(el.clientHeight)
      if (p0 === null || p1 === null) return 1
      const pxPerPrice = el.clientHeight / Math.max(1e-9, Math.abs(p0 - p1))
      return Math.max(1, Math.ceil(ROW_PX / (pxPerPrice * baseBucket)))
    }

    const poll = async () => {
      if (stopped) return
      ctrl?.abort()
      ctrl = new AbortController()
      try {
        const j = await fetchDom(symbol, wantMult(), ctrl.signal)
        if (stopped) return
        dom = j
        failed = false
        if (baseBucket === 0 && j.mult === 1) baseBucket = j.bucket
        sig = ''
        const age = Math.round(j.age_ms / 1000)
        setInfo({
          text: j.source === 'live' ? `DOM trực tiếp${age > 5 ? ` · trễ ${age}s` : ''}` : `DOM từ sổ lệnh đã ghi · trễ ${age >= 120 ? `${Math.round(age / 60)} phút` : `${age}s`}`,
          warn: j.source !== 'live' || age > 15,
        })
      } catch (e) {
        if ((e as Error)?.name === 'AbortError' || stopped) return
        failed = true
        setInfo({ text: 'DOM: không lấy được sổ lệnh', warn: true })
      } finally {
        if (!stopped) timer = window.setTimeout(() => void poll(), failed ? 6000 : POLL_MS)
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
        canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr)
        canvas.style.width = `${w}px`; canvas.style.height = `${h}px`
        sig = ''
      }
      const newSig = `${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${bars.current.length}|${dark}|${dom ? dom.ts : 0}|${w}`
      if (newSig === sig) return
      sig = newSig
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      if (!dom || dom.bucket <= 0) return
      const plotW = w - c.priceScale('right').width()
      const colW = Math.max(60, Math.min(130, plotW * 0.13))
      const rows = [...dom.bids.map(([p, q]) => ({ p, q, side: 'bid' as const })), ...dom.asks.map(([p, q]) => ({ p, q, side: 'ask' as const }))]
      const sizes = rows.map((r) => r.q).sort((a, b) => a - b)
      const cap = Math.max(1e-9, sizes[Math.min(sizes.length - 1, Math.floor(sizes.length * 0.97))] ?? 1)   // phân vị 97 để một bức tường không làm các mức khác bé tí
      const labelMin = cap * 0.4
      ctx.font = '10px system-ui, sans-serif'
      ctx.textBaseline = 'middle'
      // nền mờ của cột để chữ và thanh đọc được trên nến
      ctx.fillStyle = dark ? 'rgba(19,23,34,0.35)' : 'rgba(255,255,255,0.45)'
      ctx.fillRect(plotW - colW, 0, colW, h)
      for (const r of rows) {
        const yt = s.priceToCoordinate(r.p + dom.bucket)
        const yb = s.priceToCoordinate(r.p)
        if (yt === null || yb === null) continue
        const top = Math.min(yt, yb)
        const hh = Math.max(1, Math.abs(yb - yt) - 0.5)
        if (top > h || top + hh < 0) continue
        const len = Math.min(1, r.q / cap) * (colW - 4)
        ctx.fillStyle = r.side === 'bid' ? 'rgba(0,200,140,0.7)' : 'rgba(255,82,82,0.7)'
        ctx.fillRect(plotW - len, top, len, hh)
        if (r.q >= labelMin && hh >= 8) {
          const txt = r.q >= 100 ? r.q.toFixed(0) : r.q >= 1 ? r.q.toFixed(1) : r.q.toFixed(3)
          ctx.textAlign = 'right'
          ctx.lineWidth = 3; ctx.lineJoin = 'round'
          ctx.strokeStyle = dark ? 'rgba(19,23,34,0.9)' : 'rgba(255,255,255,0.9)'
          ctx.strokeText(txt, plotW - len - 3, top + hh / 2)
          ctx.fillStyle = dark ? '#e8ecf3' : '#1b2430'
          ctx.fillText(txt, plotW - len - 3, top + hh / 2)
        }
      }
      // bid và ask tốt nhất: hai vạch mảnh chạy hết cột, kèm khoảng cách
      const line = (price: number | null, color: string) => {
        if (price === null) return null
        const y = s.priceToCoordinate(price)
        if (y === null) return null
        ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([3, 3])
        ctx.beginPath(); ctx.moveTo(plotW - colW, y); ctx.lineTo(plotW, y); ctx.stroke(); ctx.setLineDash([])
        return y
      }
      line(dom.best_bid, '#00e676')
      line(dom.best_ask, '#ff5252')
      if (dom.best_bid !== null && dom.best_ask !== null) {
        const mid = s.priceToCoordinate((dom.best_bid + dom.best_ask) / 2)
        if (mid !== null) {
          const sp = dom.best_ask - dom.best_bid
          const txt = `spread ${sp.toLocaleString('en-US', { maximumFractionDigits: 4 })}`
          ctx.textAlign = 'left'
          ctx.lineWidth = 3; ctx.strokeStyle = dark ? 'rgba(19,23,34,0.9)' : 'rgba(255,255,255,0.9)'
          ctx.strokeText(txt, plotW - colW + 4, mid)
          ctx.fillStyle = dark ? '#c9ced8' : '#3b4252'
          ctx.fillText(txt, plotW - colW + 4, mid)
        }
      }
    }

    void poll()
    raf = requestAnimationFrame(draw)
    return () => {
      stopped = true
      window.clearTimeout(timer)
      cancelAnimationFrame(raf)
      ctrl?.abort()
      setInfo(null)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [on, dark, symbol, chart, candles, bars, version])

  return (
    <>
      <canvas ref={cv} className="dom-canvas" aria-hidden="true" />
      {on && info && <div className={`dom-status${info.warn ? ' warn' : ''}`} role="status">{info.text}</div>}
    </>
  )
}
