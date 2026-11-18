import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi, MouseEventParams } from 'lightweight-charts'
import { fetchLiqZones } from './api'
import { heatColor, indexToTime, tfMs, timeToIndex, type Bar } from './logic'

type Props = {
  on: boolean
  minPct: number          // ngưỡng khối lượng chờ, % so với phân vị 99
  dark: boolean
  symbol: string
  tf: string
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
  version: number
}

type Zone = { side: 'bid' | 'ask'; price: number; t0: number; t1: number; peak: number; last: number; status: 'active' | 'gap' | 'filled' | 'pulled' }
const STATUS_TEXT: Record<Zone['status'], string> = {
  active: 'còn hiệu lực', gap: 'không rõ (mất dữ liệu sổ lệnh sau đó)', filled: 'bị khớp (có lệnh khớp ở đúng mức giá)', pulled: 'bị rút lệnh',
}

/**
 * Vùng thanh khoản: mỗi lệnh chờ lớn là một thanh ngang kéo dài từ lúc xuất hiện đến lúc biến mất, đúng mức giá của nó.
 * Cuối thanh có dấu hiệu cho biết vì sao hết: ✕ bị rút lệnh, ▶ bị khớp, thanh mờ dần ra phía phải là còn hiệu lực.
 */
export default function LiqZones({ on, minPct, dark, symbol, tf, chart, candles, bars, version }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)
  const [tip, setTip] = useState<{ x: number; y: number; flip: boolean; lines: string[] } | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')

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
    let retry = 0
    let ctrl: AbortController | null = null
    let zones: Zone[] = []
    let scale = 1
    let bucket = 0
    let baseBucket = 0
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
      const slice = list.slice(i0, i1 + 1)
      const lo = Math.min(...slice.map((b) => b.low))
      const hi = Math.max(...slice.map((b) => b.high))
      const y1 = s.priceToCoordinate(lo)
      const y2 = s.priceToCoordinate(hi)
      let mult = 1
      if (baseBucket > 0 && y1 !== null && y2 !== null && hi > lo) {
        mult = Math.max(1, Math.ceil(3 / ((Math.abs(y1 - y2) / (hi - lo)) * baseBucket)))   // thanh cao tối thiểu khoảng 3px
      }
      const qm = 600_000   // làm tròn khoảng thời gian để kéo nhẹ vẫn dùng lại yêu cầu (máy chủ nhớ kết quả)
      const fromQ = Math.floor(from / qm) * qm
      const toQ = Math.ceil(to / qm) * qm
      // chỉ lấy vùng đủ dài để thấy được: tối thiểu khoảng 6px theo trục thời gian (làm tròn bội 30 giây để dùng lại bộ nhớ của máy chủ)
      const msPerPx = (to - from) / Math.max(1, c.timeScale().width())
      const minS = Math.min(3600, Math.max(30, Math.ceil((6 * msPerPx) / 1000 / 30) * 30))
      const key = `${symbol}|${fromQ}|${toQ}|${mult}|${minPct}|${minS}`
      if (key === wantKey) return
      wantKey = key
      ctrl?.abort()
      ctrl = new AbortController()
      if (!stopped) setState('loading')
      try {
        const j = await fetchLiqZones(symbol, fromQ, toQ, mult, minPct / 100, 400, minS, ctrl.signal)
        zones = j.rows.map((x) => ({ side: x[0] as Zone['side'], price: x[1] as number, t0: x[2] as number, t1: x[3] as number, peak: x[4] as number, last: x[5] as number, status: x[6] as Zone['status'] }))
        scale = j.scale || 1
        bucket = j.bucket
        if (baseBucket === 0 && mult === 1) baseBucket = j.bucket
        sig = ''
        if (!stopped) setState('idle')
        if (baseBucket > 0 && mult === 1 && j.bucket === baseBucket) wantKey = key   // đã biết bucket cơ sở
      } catch (e) {
        if ((e as Error)?.name === 'AbortError' || stopped) return
        wantKey = ''
        setState('error')
        retry = window.setTimeout(() => { sig = ''; void load() }, 6000)
      }
    }
    const schedule = () => { window.clearTimeout(timer); timer = window.setTimeout(() => { void load() }, 350) }

    const geo = () => {
      const c = chart.current
      const s = candles.current
      const list = bars.current
      if (!c || !s || list.length === 0) return null
      const ts = c.timeScale()
      const r = ts.getVisibleLogicalRange()
      const a = Math.round(r?.from ?? 0)
      const xa = ts.logicalToCoordinate(a as never)
      const xb = ts.logicalToCoordinate((a + 1) as never)
      if (xa === null || xb === null) return null
      const times = list.map((b) => b.time)
      return { c, s, r, times, xOf: (idx: number) => xa + (idx - a) * (xb - xa), xt: (tMs: number) => xa + (timeToIndex(times, tMs / 1000, step) - 0.5 - a) * (xb - xa) }
    }

    const draw = () => {
      if (stopped) return
      raf = requestAnimationFrame(draw)
      const g = geo()
      const el = canvas.parentElement
      if (!g || !el) return
      const { c, s, r } = g
      const w = el.clientWidth
      const h = el.clientHeight
      const dpr = window.devicePixelRatio || 1
      canvas.style.clipPath = `inset(0 0 ${Math.max(0, h - (c.panes()[0]?.getHeight() ?? h))}px 0)`
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr)
        canvas.style.width = `${w}px`; canvas.style.height = `${h}px`
        sig = ''
      }
      const newSig = `${r?.from}|${r?.to}|${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${bars.current.length}|${zones.length}|${dark}`
      if (newSig === sig) return
      sig = newSig
      schedule()
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      if (zones.length === 0 || bucket <= 0) return
      const plotW = w - c.priceScale('right').width()
      for (const z of zones) {
        const x0 = g.xt(z.t0)
        const x1 = g.xt(z.t1)
        if (Number.isNaN(x0) || x1 < 0 || x0 > plotW) continue
        const yt = s.priceToCoordinate(z.price + bucket)
        const yb = s.priceToCoordinate(z.price)
        if (yt === null || yb === null) continue
        const top = Math.min(yt, yb)
        const hh = Math.max(2, Math.abs(yb - yt))
        const xs = Math.max(0, x0)
        const xe = Math.min(plotW, Math.max(x1, x0 + 2))
        const [R, G, B] = heatColor(Math.min(1, z.peak / scale), 'bookmap')
        const base = z.side === 'bid' ? '0,200,140' : '255,90,90'   // viền theo phía: mua xanh, bán đỏ
        // thân thanh: màu theo cỡ lệnh; còn hiệu lực thì mờ dần về bên phải
        if (z.status === 'active' || z.status === 'gap') {
          const grad = ctx.createLinearGradient(xs, 0, xe, 0)
          grad.addColorStop(0, `rgba(${R | 0},${G | 0},${B | 0},0.9)`)
          grad.addColorStop(1, `rgba(${R | 0},${G | 0},${B | 0},${z.status === 'active' ? 0.25 : 0.5})`)
          ctx.fillStyle = grad
        } else {
          ctx.fillStyle = `rgba(${R | 0},${G | 0},${B | 0},0.9)`
        }
        ctx.fillRect(xs, top, Math.max(1, xe - xs), hh)
        ctx.fillStyle = `rgba(${base},0.95)`   // mép dưới mỏng cho biết phía
        ctx.fillRect(xs, top + hh - 1, Math.max(1, xe - xs), 1)
        // dấu hiệu kết thúc
        if (x1 >= 0 && x1 <= plotW) {
          const cy = top + hh / 2
          if (z.status === 'pulled') {
            ctx.strokeStyle = dark ? '#ffffff' : '#111111'
            ctx.lineWidth = 1.5
            const k = Math.max(3, Math.min(5, hh / 2 + 1))
            ctx.beginPath(); ctx.moveTo(x1 - k, cy - k); ctx.lineTo(x1 + k, cy + k); ctx.moveTo(x1 + k, cy - k); ctx.lineTo(x1 - k, cy + k); ctx.stroke()
          } else if (z.status === 'filled') {
            ctx.fillStyle = '#ffb300'
            const k = Math.max(3, Math.min(5, hh / 2 + 1))
            ctx.beginPath(); ctx.moveTo(x1 - 1, cy - k); ctx.lineTo(x1 + k + 1, cy); ctx.lineTo(x1 - 1, cy + k); ctx.closePath(); ctx.fill()
          }
        }
      }
    }

    // rê chuột: chi tiết vùng thanh khoản đang trỏ
    const onMove = (p: MouseEventParams) => {
      const g = geo()
      const el = canvas.parentElement
      if (!g || !el || !p.point || zones.length === 0) { setTip(null); return }
      const price = g.s.coordinateToPrice(p.point.y)
      const L = g.c.timeScale().coordinateToLogical(p.point.x)
      if (price === null || L === null) { setTip(null); return }
      const tMs = indexToTime(g.times, Number(L) + 0.5, step) * 1000
      const pad = bucket * 0.6
      let best: Zone | null = null
      for (const z of zones) {
        if (tMs < z.t0 - 5000 || tMs > z.t1 + 5000) continue
        if (price < z.price - pad || price > z.price + bucket + pad) continue
        if (!best || z.peak > best.peak) best = z
      }
      if (!best) { setTip(null); return }
      const fmtT = (ms: number) => new Date(ms).toLocaleTimeString('vi-VN', { hour12: false })
      const dur = Math.round((best.t1 - best.t0) / 1000)
      const durTxt = dur >= 60 ? `${Math.floor(dur / 60)} phút ${dur % 60} giây` : `${dur} giây`
      const fmt = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 3 })
      setTip({
        x: p.point.x, y: p.point.y, flip: p.point.x > el.clientWidth * 0.6,
        lines: [
          `${best.side === 'bid' ? 'Lệnh mua chờ' : 'Lệnh bán chờ'} tại ${fmt(best.price)}`,
          `Lớn nhất ${fmt(best.peak)} · trước khi hết ${fmt(best.last)}`,
          `${fmtT(best.t0)} → ${fmtT(best.t1)} (${durTxt})`,
          `Kết thúc: ${STATUS_TEXT[best.status]}`,
        ],
      })
    }
    chart.current?.subscribeCrosshairMove(onMove)

    void load()
    raf = requestAnimationFrame(draw)
    return () => {
      stopped = true
      window.clearTimeout(timer)
      window.clearTimeout(retry)
      chart.current?.unsubscribeCrosshairMove(onMove)
      cancelAnimationFrame(raf)
      ctrl?.abort()
      setTip(null)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [on, minPct, dark, symbol, tf, chart, candles, bars, version])

  return (
    <>
      <canvas ref={cv} className="heat-canvas zone-canvas" aria-hidden="true" />
      {on && state === 'loading' && <div className="flow-status zone-status" role="status">Đang tải vùng thanh khoản…</div>}
      {on && state === 'error' && <div className="flow-status zone-status error" role="status">Chưa tải được vùng thanh khoản, đang thử lại…</div>}
      {on && (
        <div className="zone-legend" aria-label="Chú giải vùng thanh khoản">
          <span><b className="x">✕</b> rút lệnh</span>
          <span><b className="f">▶</b> bị khớp</span>
          <span><b className="a">▭</b> còn hiệu lực</span>
        </div>
      )}
      {on && tip && (
        <div className="heat-tip zone-tip" style={{ left: tip.x, top: tip.y, transform: tip.flip ? 'translate(calc(-100% - 14px), 14px)' : 'translate(14px, 14px)' }}>
          <b>{tip.lines[0]}</b>
          {tip.lines.slice(1).map((l) => <span key={l}>{l}</span>)}
        </div>
      )}
    </>
  )
}
