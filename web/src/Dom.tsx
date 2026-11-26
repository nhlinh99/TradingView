import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchDom, fetchTraded, type DomResponse } from './api'
import { tfMs, type Bar } from './logic'

type Props = {
  on: boolean
  dark: boolean
  symbol: string
  tf: string
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
}

const POLL_MS = 2000
const TRADED_MS = 6000    // cột Khớp làm mới chậm hơn: truy vấn lệnh khớp nặng hơn snapshot sổ lệnh
const DEPTH_FRAC = 0.55   // phần bề rộng của cột Chờ (độ sâu); phần còn lại là cột Khớp
const ROW_PX = 13         // chiều cao một dòng giá: đủ để mọi dòng đều ghi được số

const fmtSize = (q: number) => (q >= 1000 ? `${(q / 1000).toFixed(1)}k` : q >= 100 ? q.toFixed(0) : q >= 10 ? q.toFixed(1) : q >= 1 ? q.toFixed(2) : q.toFixed(3))

/**
 * Bảng độ sâu (DOM) kiểu Bookmap: một cột riêng bên phải trục giá, mỗi dòng ứng với một mức giá của biểu đồ (cùng tung độ).
 * Từ trên xuống: ask (đỏ) rồi bid (xanh); thanh bắt đầu từ mép trái cột và dài theo khối lượng chờ, số ghi ở mọi dòng;
 * dòng bid tốt nhất và ask tốt nhất được tô nền, giá hiện tại có vạch ngang qua cột.
 */
export default function Dom({ on, dark, symbol, tf, chart, candles, bars }: Props) {
  const panel = useRef<HTMLDivElement>(null)
  const cv = useRef<HTMLCanvasElement>(null)
  const [info, setInfo] = useState<{ text: string; warn: boolean; group: string } | null>(null)

  useEffect(() => {
    const canvas = cv.current
    const el = panel.current
    if (!on || !canvas || !el) return
    const ctx = canvas.getContext('2d')!
    let stopped = false
    let raf = 0
    let timer = 0
    let ctrl: AbortController | null = null
    let dom: DomResponse | null = null
    let traded: { price: number; buy: number; sell: number }[] = []
    let tradedBucket = 0
    let tradedBase = 0
    let tradedCtrl: AbortController | null = null
    let tradedTimer = 0
    let tradedSig = 0
    let baseBucket = 0
    let sig = ''
    let failed = false

    /** Bội của bucket cơ sở để mỗi dòng cao tối thiểu ROW_PX pixel ở mức thu phóng hiện tại. */
    const wantMult = (): number => {
      const s = candles.current
      if (!s || baseBucket <= 0) return 1
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
        const lo = j.bids.length > 0 ? j.bids[j.bids.length - 1][0] : null
        const hi = j.asks.length > 0 ? j.asks[j.asks.length - 1][0] + j.bucket : null
        const mid = j.best_bid !== null && j.best_ask !== null ? (j.best_bid + j.best_ask) / 2 : null
        const reach = lo !== null && hi !== null && mid ? ` · phủ ±${(((hi - lo) / 2 / mid) * 100).toFixed(2)}%` : ''   // sổ lệnh Binance chỉ có 1000 mức mỗi phía nên chỉ phủ một dải hẹp quanh giá
        setInfo({
          text: (j.source === 'live' ? (age > 5 ? `Trực tiếp · trễ ${age}s` : 'Trực tiếp') : `Từ sổ lệnh đã ghi · trễ ${age >= 120 ? `${Math.round(age / 60)} phút` : `${age}s`}`) + reach,
          warn: j.source !== 'live' || age > 15,
          group: `Gom ${j.bucket.toLocaleString('en-US', { maximumFractionDigits: 4 })}`,
        })
      } catch (e) {
        if ((e as Error)?.name === 'AbortError' || stopped) return
        failed = true
        setInfo({ text: 'Không lấy được sổ lệnh', warn: true, group: '' })
      } finally {
        if (!stopped) timer = window.setTimeout(() => void poll(), failed ? 6000 : POLL_MS)
      }
    }

    /** Khối lượng khớp theo giá trong khoảng đang xem (cùng khoảng với heatmap), gom theo bội của bucket footprint gần với độ gom của DOM. */
    const pollTraded = async () => {
      if (stopped) return
      const started = Date.now()
      const first = tradedBase === 0   // lần đầu chưa biết bucket footprint nên hỏi mult = 1
      let refine = false
      try {
        const c = chart.current
        const list = bars.current
        const r = c?.timeScale().getVisibleLogicalRange()
        if (c && r && list.length > 0 && dom) {
          const i0 = Math.max(0, Math.floor(r.from))
          const i1 = Math.min(list.length - 1, Math.ceil(r.to))
          if (i1 >= i0) {
            const from = list[i0].time * 1000
            const to = list[i1].time * 1000 + tfMs(tf)
            const mult = tradedBase > 0 ? Math.max(1, Math.round(dom.bucket / tradedBase)) : 1
            tradedCtrl?.abort()
            tradedCtrl = new AbortController()
            const j = await fetchTraded(symbol, from, to, mult, tradedCtrl.signal)
            if (stopped) return
            traded = j.rows.map(([price, buy, sell]) => ({ price, buy, sell }))
            tradedBucket = j.bucket
            tradedBase = j.bucket / mult
            refine = first && Math.round(dom.bucket / tradedBase) > 1
            tradedSig++
            sig = ''
          }
        }
      } catch (e) {
        if ((e as Error)?.name === 'AbortError' || stopped) return
      } finally {
        // khoảng xem rộng thì truy vấn lâu: giãn nhịp để máy chủ không bận liên tục
        // lần đầu cần gom lại theo độ gom của DOM thì hỏi lại ngay
        if (!stopped) tradedTimer = window.setTimeout(() => void pollTraded(), refine ? 300 : Math.max(TRADED_MS, (Date.now() - started) * 3))
      }
    }

    const draw = () => {
      if (stopped) return
      raf = requestAnimationFrame(draw)
      const c = chart.current
      const s = candles.current
      if (!c || !s) return
      const w = el.clientWidth
      const h = el.clientHeight
      const dpr = window.devicePixelRatio || 1
      const paneH = c.panes()[0]?.getHeight() ?? h
      canvas.style.clipPath = `inset(0 0 ${Math.max(0, h - paneH)}px 0)`
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr)
        canvas.style.width = `${w}px`; canvas.style.height = `${h}px`
        sig = ''
      }
      const newSig = `${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${bars.current.length}|${dark}|${dom ? dom.ts : 0}|${w}|${h}|${tradedSig}`
      if (newSig === sig) return
      sig = newSig
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      if (!dom || dom.bucket <= 0) return
      const rows = [...dom.asks.map(([p, q]) => ({ p, q, side: 'ask' as const })), ...dom.bids.map(([p, q]) => ({ p, q, side: 'bid' as const }))]
      const sizes = rows.map((r) => r.q).sort((a, b) => a - b)
      const cap = Math.max(1e-9, sizes[Math.min(sizes.length - 1, Math.floor(sizes.length * 0.97))] ?? 1)   // phân vị 97: một bức tường không làm các mức khác bé tí
      const depthW = Math.floor(w * DEPTH_FRAC)
      const barMax = depthW - 6
      ctx.font = '10px system-ui, sans-serif'
      ctx.textBaseline = 'middle'
      ctx.textAlign = 'left'
      const bestBidBucket = dom.best_bid === null ? null : Math.floor(dom.best_bid / dom.bucket + 1e-9) * dom.bucket
      const bestAskBucket = dom.best_ask === null ? null : Math.floor(dom.best_ask / dom.bucket + 1e-9) * dom.bucket
      const near = (a: number, b: number | null) => b !== null && Math.abs(a - b) < dom!.bucket * 0.01
      for (const r of rows) {
        const yt = s.priceToCoordinate(r.p + dom.bucket)
        const yb = s.priceToCoordinate(r.p)
        if (yt === null || yb === null) continue
        const top = Math.min(yt, yb)
        const hh = Math.max(1, Math.abs(yb - yt))
        if (top > h || top + hh < 0) continue
        const isBest = r.side === 'bid' ? near(r.p, bestBidBucket) : near(r.p, bestAskBucket)
        // nền dòng: sọc xen kẽ rất nhẹ cho dễ đọc, dòng tốt nhất tô đậm hơn
        if (isBest) {
          ctx.fillStyle = r.side === 'bid' ? 'rgba(0,200,140,0.22)' : 'rgba(255,82,82,0.22)'
          ctx.fillRect(0, top, depthW, hh)
        }
        const len = Math.min(1, r.q / cap) * barMax
        ctx.fillStyle = r.side === 'bid' ? 'rgba(0,200,140,0.65)' : 'rgba(255,82,82,0.65)'
        ctx.fillRect(0, top + 1, len, Math.max(1, hh - 2))
        if (hh >= 9) {
          const txt = fmtSize(r.q)
          ctx.lineWidth = 3; ctx.lineJoin = 'round'
          ctx.strokeStyle = dark ? 'rgba(19,23,34,0.85)' : 'rgba(255,255,255,0.85)'
          ctx.strokeText(txt, 4, top + hh / 2)
          ctx.fillStyle = isBest ? (dark ? '#ffffff' : '#000000') : (dark ? '#d8dce6' : '#2b3340')
          ctx.font = `${isBest ? 'bold ' : ''}10px system-ui, sans-serif`
          ctx.fillText(txt, 4, top + hh / 2)
          ctx.font = '10px system-ui, sans-serif'
        }
      }
      // cột Khớp: khối lượng đã khớp ở từng mức giá trong khoảng đang xem; xanh là mua chủ động, đỏ là bán chủ động, viền sáng là mức khớp nhiều nhất (POC)
      ctx.strokeStyle = dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.12)'
      ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(depthW + 0.5, 0); ctx.lineTo(depthW + 0.5, h); ctx.stroke()
      if (traded.length > 0 && tradedBucket > 0) {
        const tot = traded.map((t) => t.buy + t.sell).sort((a, b) => a - b)
        const tcap = Math.max(1e-9, tot[Math.min(tot.length - 1, Math.floor(tot.length * 0.97))] ?? 1)
        const poc = traded.reduce((m, t) => (t.buy + t.sell > m.buy + m.sell ? t : m), traded[0])
        const x0 = depthW + 3
        const tw = w - x0 - 3
        for (const t of traded) {
          const yt = s.priceToCoordinate(t.price + tradedBucket)
          const yb = s.priceToCoordinate(t.price)
          if (yt === null || yb === null) continue
          const top = Math.min(yt, yb)
          const hh = Math.max(1, Math.abs(yb - yt))
          if (top > h || top + hh < 0) continue
          const total = t.buy + t.sell
          const len = Math.min(1, total / tcap) * tw
          const lenBuy = total > 0 ? (len * t.buy) / total : 0
          ctx.fillStyle = 'rgba(0,200,140,0.7)'
          ctx.fillRect(x0, top + 1, lenBuy, Math.max(1, hh - 2))
          ctx.fillStyle = 'rgba(255,82,82,0.7)'
          ctx.fillRect(x0 + lenBuy, top + 1, len - lenBuy, Math.max(1, hh - 2))
          if (t === poc) { ctx.strokeStyle = dark ? '#ffd54f' : '#b8860b'; ctx.lineWidth = 1.5; ctx.strokeRect(x0 + 0.5, top + 1.5, Math.max(1, len) , Math.max(1, hh - 3)) }
          if (hh >= 9) {
            const txt = fmtSize(total)
            ctx.lineWidth = 3; ctx.lineJoin = 'round'
            ctx.strokeStyle = dark ? 'rgba(19,23,34,0.85)' : 'rgba(255,255,255,0.85)'
            ctx.strokeText(txt, x0 + 2, top + hh / 2)
            ctx.fillStyle = dark ? '#d8dce6' : '#2b3340'
            ctx.fillText(txt, x0 + 2, top + hh / 2)
          }
        }
      }
      // giá hiện tại (giữa bid và ask tốt nhất): vạch ngang qua cột, kèm spread
      if (dom.best_bid !== null && dom.best_ask !== null) {
        const y = s.priceToCoordinate((dom.best_bid + dom.best_ask) / 2)
        if (y !== null) {
          ctx.strokeStyle = dark ? 'rgba(255,255,255,0.8)' : 'rgba(0,0,0,0.7)'
          ctx.lineWidth = 1
          ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke()
          const sp = dom.best_ask - dom.best_bid
          const txt = `Δ ${sp.toLocaleString('en-US', { maximumFractionDigits: 4 })}`   // chỉ ghi spread: giá đã có trên trục, và để không che số ở cột Khớp
          ctx.font = 'bold 10px system-ui, sans-serif'
          const tw = ctx.measureText(txt).width + 8
          ctx.fillStyle = dark ? '#e8ecf3' : '#1b2430'
          ctx.fillRect(w - tw, y - 7, tw, 14)
          ctx.fillStyle = dark ? '#131722' : '#ffffff'
          ctx.textAlign = 'right'
          ctx.fillText(txt, w - 4, y)
          ctx.textAlign = 'left'
          ctx.font = '10px system-ui, sans-serif'
        }
      }
    }

    void poll()
    tradedTimer = window.setTimeout(() => void pollTraded(), 1200)   // chờ có DOM đầu tiên để biết độ gom
    raf = requestAnimationFrame(draw)
    return () => {
      stopped = true
      window.clearTimeout(timer)
      window.clearTimeout(tradedTimer)
      cancelAnimationFrame(raf)
      ctrl?.abort()
      tradedCtrl?.abort()
      setInfo(null)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [on, dark, symbol, tf, chart, candles, bars])   // không phụ thuộc `version`: nạp lại nến không được xoá DOM đang hiện (bars là ref)

  if (!on) return null
  return (
    <div ref={panel} className="dom-panel" aria-label="Bảng độ sâu thị trường">
      <canvas ref={cv} className="dom-canvas" aria-hidden="true" />
      <div className="dom-cols"><span>Chờ</span><span>Khớp</span></div>
      <div className="dom-head"><b>DOM</b>{info?.group && <span>{info.group}</span>}</div>
      {info && <div className={`dom-status${info.warn ? ' warn' : ''}`} role="status">{info.text}</div>}
    </div>
  )
}
