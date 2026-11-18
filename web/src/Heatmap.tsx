import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi, MouseEventParams } from 'lightweight-charts'
import { fetchCoverage, fetchDepthBands, fetchHeatmap } from './api'
import { applyCutoff, bestBidAsk, heatColor, indexToTime, tfMs, timeToIndex, type Bar } from './logic'

/** Dải màu CSS của thang nhiệt (cùng bảng màu với ô heatmap) để làm chú giải. */
function legendGradient(mode: 'intensity' | 'side' | 'bookmap'): string {
  const stops: string[] = []
  for (let i = 0; i <= 10; i++) {
    const [r, g, b, a] = heatColor(i / 10, mode === 'bookmap' ? 'bookmap' : mode === 'side' ? 'bid' : undefined)
    stops.push(`rgba(${r | 0},${g | 0},${b | 0},${a.toFixed(2)}) ${i * 10}%`)
  }
  return `linear-gradient(90deg, ${stops.join(', ')})`
}

type Props = {
  on: boolean
  mode: 'intensity' | 'side' | 'bookmap'
  cutLo: number
  cutHi: number
  bestLines: boolean
  strip: boolean
  dark: boolean
  symbol: string
  tf: string
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
  version: number
}

const CELL_PX = 4

/** Heatmap thanh khoản vẽ DƯỚI nến (canvas nằm sau biểu đồ; nền biểu đồ được đặt trong suốt). */
export default function Heatmap({ on, mode, cutLo, cutHi, bestLines, strip, dark, symbol, tf, chart, candles, bars, version }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [note, setNote] = useState<string | null>(null)
  const [unit, setUnit] = useState<number>(0)   // thanh khoản ứng với màu đậm nhất (phân vị 99 của ô)
  const [tip, setTip] = useState<{ x: number; y: number; flip: boolean; price: string; time: string; bid: number; ask: number; rel: number } | null>(null)

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
    let timer = 0
    const schedule = () => { window.clearTimeout(timer); timer = window.setTimeout(() => { void load() }, 350) }   // chờ ngừng kéo 0,35 giây rồi mới tải
    let ctrl: AbortController | null = null
    let rows: number[][] = []
    let byTime = new Map<number, number[][]>()
    let retry = 0
    // đoạn đã có sổ lệnh chi tiết và dải độ sâu thô (chỉ dùng cho đoạn chưa có sổ lệnh chi tiết)
    let segs: [number, number][] = []
    let depthRows: number[][] = []
    let depthScale = 1
    let depthTb = 900_000
    let auxKey = ''
    let auxCtrl: AbortController | null = null
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
      // làm tròn khoảng thời gian theo bội của ô để kéo nhẹ biểu đồ vẫn dùng lại cùng một yêu cầu (máy chủ nhớ kết quả)
      const qm = tbucket * 8
      const fromQ = Math.floor(from / qm) * qm
      const toQ = Math.ceil(to / qm) * qm
      const key = `${symbol}|${fromQ}|${toQ}|${tbucket}|${mult}`
      if (key === wantKey) return
      wantKey = key
      ctrl?.abort()
      ctrl = new AbortController()
      if (!stopped) setStatus('loading')
      try {
        const j = await fetchHeatmap(symbol, fromQ, toQ, tbucket, mult, ctrl.signal)
        const first = baseBucket === 0
        rows = j.rows
        byTime = new Map()
        for (const r of rows) { const a = byTime.get(r[0]); if (a) a.push(r); else byTime.set(r[0], [r]) }
        if (!stopped) setStatus('idle')
        scale = j.scale || 1
        if (!stopped) setUnit(scale)
        bucket = j.bucket
        baseBucket = j.bucket / mult
        tb = j.tbucket
        sig = ''
        if (first) wantKey = '' // vừa biết bucket cơ sở: tính lại mult
        void loadAux(fromQ, toQ, wpx)
      } catch (e) {
        if ((e as Error)?.name === 'AbortError' || stopped) return   // bị thay bằng yêu cầu mới hoặc đã đóng
        wantKey = ''
        setStatus('error')
        retry = window.setTimeout(() => { sig = ''; void load() }, 6000) as unknown as number   // thử lại sau 6 giây
      }
    }

    /** Độ phủ dữ liệu của cửa sổ đang xem; chỗ nào thiếu thì nạp thêm độ sâu thô. Chạy sau khi heatmap chi tiết đã tải xong. */
    const loadAux = async (fromQ: number, toQ: number, wpx: number) => {
      const key = `${symbol}|${fromQ}|${toQ}`
      if (key === auxKey) return
      auxKey = key
      auxCtrl?.abort()
      auxCtrl = new AbortController()
      try {
        const cov = await fetchCoverage(symbol, fromQ, toQ, auxCtrl.signal)
        if (stopped) return
        segs = cov.segments
        const win = toQ - fromQ
        const pct = win > 0 ? (cov.covered_ms / win) * 100 : 0
        const hours = Math.round(cov.covered_ms / 3_600_000)
        const fmt = (ms: number) => new Date(ms).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
        setNote(cov.first === null
          ? 'Chưa có sổ lệnh chi tiết trong khoảng này; phần hiển thị là độ sâu thô (±5%).'
          : pct >= 98 ? null
            : `Sổ lệnh chi tiết: ${hours} giờ (${pct.toFixed(0)}% khoảng đang xem), từ ${fmt(cov.first)}. Chỗ thiếu hiển thị độ sâu thô (±5%).`)
        if (pct >= 98) { depthRows = []; sig = ''; return }
        const tbD = Math.max(60_000, Math.ceil(win / Math.max(1, wpx / 6) / 60_000) * 60_000)
        const d = await fetchDepthBands(symbol, fromQ, toQ, tbD, auxCtrl.signal)
        depthRows = d.rows
        depthScale = d.scale || 1
        depthTb = d.tbucket
        sig = ''
      } catch (e) {
        if ((e as Error)?.name === 'AbortError') return
        auxKey = ''   // lỗi tạm: lần sau thử lại
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
      const newSig = `${r?.from}|${r?.to}|${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${bars.current.length}|${rows.length}|${mode}|${cutLo}|${cutHi}|${bestLines}|${strip}|${dark}`
      if (newSig === sig) return
      sig = newSig
      schedule()
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
      // độ sâu thô (dưới cùng): chỉ vẽ ở các ô thời gian chưa có sổ lệnh chi tiết
      if (depthRows.length > 0) {
        const nb = bars.current.length
        const covered = (t: number) => { const m = t + depthTb / 2; return segs.some(([a, b]) => m >= a && m <= b) }
        const dspan = (t: number): [number, number] => [xOf(timeToIndex(times, t / 1000, step) - 0.5), xOf(timeToIndex(times, (t + depthTb) / 1000, step) - 0.5)]
        for (const [t, lo, hi, dens] of depthRows) {
          if (covered(t)) continue
          const [x0, x1] = dspan(t)
          if (Number.isNaN(x0) || x1 < 0 || x0 > plotW) continue
          const bi = Math.min(nb - 1, Math.max(0, Math.round(timeToIndex(times, (t + depthTb / 2) / 1000, step))))
          const ref = bars.current[bi]?.close
          if (!ref) continue
          const yt = s.priceToCoordinate(ref * (1 + hi / 100))
          const yb = s.priceToCoordinate(ref * (1 + lo / 100))
          if (yt === null || yb === null) continue
          const [R, G, B, A] = heatColor(applyCutoff(dens / depthScale, cutLo, cutHi), mode === 'bookmap' ? 'bookmap' : undefined)
          if (A === 0) continue
          ctx.fillStyle = `rgba(${R | 0},${G | 0},${B | 0},${(A * 0.55).toFixed(2)})`
          ctx.fillRect(x0, Math.min(yt, yb), Math.max(1, x1 - x0 + 0.5), Math.max(1, Math.abs(yb - yt) + 0.5))
        }
      }
      for (const [t, price, bid, ask] of rows) {
        const [x0, x1] = span(t)
        if (Number.isNaN(x0) || x1 < 0 || x0 > plotW) continue
        const yt = s.priceToCoordinate(price + bucket)
        const yb = s.priceToCoordinate(price)
        if (yt === null || yb === null) continue
        const raw = (mode === 'side' ? Math.max(bid, ask) : bid + ask) / scale
        const [R, G, B, A] = mode === 'side' ? heatColor(applyCutoff(raw, cutLo, cutHi), bid >= ask ? 'bid' : 'ask') : heatColor(applyCutoff(raw, cutLo, cutHi), mode === 'bookmap' ? 'bookmap' : undefined)
        if (A === 0) continue
        ctx.fillStyle = `rgba(${R | 0},${G | 0},${B | 0},${A.toFixed(2)})`
        const top = Math.min(yt, yb)
        ctx.fillRect(x0, top, Math.max(1, x1 - x0 + 0.5), Math.max(1, Math.abs(yb - yt) + 0.5))
      }
      // đường bid/ask tốt nhất (bậc thang) như Bookmap
      if (bestLines) {
        const m = bestBidAsk(rows, bucket)
        const draw1 = (pick: 'bid' | 'ask', color: string) => {
          ctx.strokeStyle = color
          ctx.lineWidth = 1.5
          ctx.beginPath()
          let started = false
          for (const t of [...m.keys()].sort((p, q) => p - q)) {
            const price = m.get(t)![pick]
            const [x0, x1] = span(t)
            const y = price === null ? null : s.priceToCoordinate(price)
            if (y === null || Number.isNaN(x0)) { started = false; continue }
            if (!started) { ctx.moveTo(x0, y); started = true } else ctx.lineTo(x0, y)
            ctx.lineTo(x1, y)
          }
          ctx.stroke()
        }
        draw1('bid', '#00e676')
        draw1('ask', '#ff5252')
      }
      // dải volume dưới đáy vùng giá: mua (xanh) chồng lên bán (đỏ), cao theo volume của nến
      if (strip) {
        const list = bars.current
        const paneH = c.panes()[0]?.getHeight() ?? h
        const stripH = Math.max(30, paneH * 0.14)
        const vis = list.filter((b) => { const x = xOf(timeToIndex(times, b.time, step)); return x >= 0 && x <= plotW })
        const vmax = Math.max(1e-9, ...vis.map((b) => b.volume))
        const bw = Math.max(1, Math.abs(xOf(1) - xOf(0)) * 0.8)
        for (const b of vis) {
          const x = xOf(timeToIndex(times, b.time, step))
          const hh = (b.volume / vmax) * stripH
          const share = b.volume > 0 && (b.buy + b.sell) > 0 ? b.buy / (b.buy + b.sell) : 0.5
          ctx.fillStyle = 'rgba(0,230,118,.75)'
          ctx.fillRect(x - bw / 2, paneH - hh * share, bw, hh * share)
          ctx.fillStyle = 'rgba(255,82,82,.75)'
          ctx.fillRect(x - bw / 2, paneH - hh, bw, hh * (1 - share))
        }
      }
    }

    // rê chuột: hiện thanh khoản chờ (bid/ask) tại ô thời gian và giá đang trỏ
    const onMove = (p: MouseEventParams) => {
      const c = chart.current
      const s = candles.current
      const el = canvas.parentElement
      if (!c || !s || !el || !p.point || rows.length === 0 || bucket <= 0) { setTip(null); return }
      const L = c.timeScale().coordinateToLogical(p.point.x)
      const price = s.coordinateToPrice(p.point.y)
      if (L === null || price === null) { setTip(null); return }
      const times = bars.current.map((b) => b.time)
      const t0 = Math.floor((indexToTime(times, Number(L) + 0.5, step) * 1000) / tb) * tb
      const cell = byTime.get(t0)?.find((r) => price >= r[1] && price < r[1] + bucket)
      if (!cell) { setTip(null); return }
      const fmt = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: v < 1 ? 4 : 2 })
      setTip({
        x: p.point.x, y: p.point.y, flip: p.point.x > el.clientWidth * 0.6,
        price: `${fmt(cell[1])} – ${fmt(cell[1] + bucket)}`,
        time: new Date(t0).toLocaleTimeString('vi-VN', { hour12: false }),
        bid: cell[2], ask: cell[3], rel: scale > 0 ? ((cell[2] + cell[3]) / scale) * 100 : 0,
      })
    }
    chart.current?.subscribeCrosshairMove(onMove)

    void load()
    raf = requestAnimationFrame(draw)
    return () => {
      stopped = true
      window.clearTimeout(timer)
      window.clearTimeout(retry)
      auxCtrl?.abort()
      chart.current?.unsubscribeCrosshairMove(onMove)
      setTip(null)
      cancelAnimationFrame(raf)
      ctrl?.abort()
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [on, mode, cutLo, cutHi, bestLines, strip, dark, symbol, tf, chart, candles, bars, version])

  return (
    <>
      <canvas ref={cv} className="heat-canvas" aria-hidden="true" />
      {on && status !== 'idle' && (
        <div className={`flow-status ${status}`} role="status">
          {status === 'loading' ? 'Đang tải heatmap…' : 'Chưa tải được heatmap, đang thử lại…'}
        </div>
      )}
      {on && unit > 0 && (
        <div className="heat-legend" aria-label="Chú giải thang thanh khoản">
          <span>Thanh khoản chờ</span>
          <i style={{ background: legendGradient(mode) }} />
          <span className="ends"><b>{(unit * cutLo).toLocaleString('en-US', { maximumFractionDigits: 2 })}</b><b>{(unit * cutHi).toLocaleString('en-US', { maximumFractionDigits: 2 })}+</b></span>
        </div>
      )}
      {on && note && status === 'idle' && <div className="flow-status info" role="note">{note}</div>}
      {on && tip && (
        <div className="heat-tip" style={{ left: tip.x, top: tip.y, transform: tip.flip ? 'translate(calc(-100% - 14px), 14px)' : 'translate(14px, 14px)' }}>
          <b>{tip.price}</b>
          <span>{tip.time}</span>
          <span>Bid <i className="bid">{tip.bid.toLocaleString('en-US', { maximumFractionDigits: 3 })}</i> · Ask <i className="ask">{tip.ask.toLocaleString('en-US', { maximumFractionDigits: 3 })}</i></span>
          <span>{tip.rel.toFixed(0)}% mức chuẩn (phân vị 99)</span>
        </div>
      )}
    </>
  )
}
