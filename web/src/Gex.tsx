import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { LineStyle, type IChartApi, type IPriceLine, type ISeriesApi } from 'lightweight-charts'
import { fetchGex, type GexResponse } from './api'

type Props = {
  on: boolean
  symbol: string
  dark: boolean
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
}

const fmtUsd = (v: number) => {
  const a = Math.abs(v)
  const s = a >= 1e9 ? `${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : `${(a / 1e3).toFixed(0)}K`
  return `${v < 0 ? '-' : ''}$${s}`
}

/**
 * GEX BTC: đường ngang gamma flip, call wall, put wall; histogram GEX theo strike ở mép trái; nhãn tuổi dữ liệu.
 * Chỉ có cho BTCUSDT (nguồn Deribit).
 */
export default function Gex({ on, symbol, dark, chart, candles }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)
  const [info, setInfo] = useState<GexResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const active = on && symbol === 'BTCUSDT'

  useEffect(() => {
    if (!active) {
      setInfo(null)
      setErr(null)
      return
    }
    let stop = false
    const ctrl = new AbortController()
    const load = async () => {
      try {
        const j = await fetchGex(ctrl.signal)
        if (!stop) {
          setInfo(j)
          setErr(null)
        }
      } catch (e) {
        if (!stop && !ctrl.signal.aborted) setErr(String(e))
      }
    }
    void load()
    const t = window.setInterval(() => void load(), 60_000)
    return () => {
      stop = true
      ctrl.abort()
      window.clearInterval(t)
    }
  }, [active])

  // đường ngang trên biểu đồ
  useEffect(() => {
    const s = candles.current
    if (!active || !info || !s) return
    const lines: IPriceLine[] = []
    const add = (price: number | null, color: string, title: string, style: LineStyle) => {
      if (price !== null) lines.push(s.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }))
    }
    add(info.flip, '#f0b90b', 'Gamma flip', LineStyle.Dashed)
    add(info.call_wall, '#26a69a', 'Call wall', LineStyle.Dotted)
    add(info.put_wall, '#ef5350', 'Put wall', LineStyle.Dotted)
    return () => lines.forEach((l) => s.removePriceLine(l))
  }, [active, info, candles])

  // histogram theo strike
  useEffect(() => {
    const canvas = cv.current!
    const ctx = canvas.getContext('2d')!
    if (!active || !info) {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      return
    }
    let stopped = false
    let raf = 0
    let sig = ''
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
      const newSig = `${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${dark}|${info.ts}|${w}|${h}`
      if (newSig === sig) return
      sig = newSig
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      ctx.save()
      ctx.beginPath()
      ctx.rect(0, 0, w, c.panes()[0]?.getHeight() ?? h) // không vẽ lấn xuống các pane volume/delta
      ctx.clip()
      const strikes = info.by_strike
      if (strikes.length === 0) {
        ctx.restore()
        return
      }
      const max = Math.max(...strikes.map((r) => Math.abs(r.net)))
      const maxW = Math.min(160, w * 0.15)
      const gap = strikes.length > 1 ? Math.abs(strikes[1].strike - strikes[0].strike) : 1000
      ctx.font = '10px system-ui, sans-serif'
      ctx.textBaseline = 'middle'
      for (const r of strikes) {
        const y = s.priceToCoordinate(r.strike)
        const y2 = s.priceToCoordinate(r.strike + gap)
        if (y === null) continue
        const hpx = Math.max(2, y2 === null ? 4 : Math.abs(y - y2) * 0.7)
        const len = (Math.abs(r.net) / max) * maxW
        ctx.fillStyle = r.net >= 0 ? 'rgba(38,166,154,.55)' : 'rgba(239,83,80,.55)'
        ctx.fillRect(0, y - hpx / 2, len, hpx)
        if (hpx >= 9) {
          ctx.fillStyle = dark ? '#d1d4dc' : '#1b2430'
          ctx.textAlign = 'left'
          ctx.fillText(`${r.strike / 1000}k ${fmtUsd(r.net)}`, len + 4, y)
        }
      }
      ctx.restore()
    }
    raf = requestAnimationFrame(draw)
    return () => {
      stopped = true
      cancelAnimationFrame(raf)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
    }
  }, [active, info, dark, chart, candles])

  const ageH = info ? Math.floor(info.age_s / 3600) : 0
  const ageM = info ? Math.floor((info.age_s % 3600) / 60) : 0
  return (
    <>
      <canvas ref={cv} className="fp-canvas" aria-hidden="true" />
      {on && symbol !== 'BTCUSDT' && <div className="gexnote">GEX chỉ có cho BTCUSDT (Deribit).</div>}
      {active && err && <div className="gexnote bad" role="alert">GEX: {err}</div>}
      {active && info && (
        <div className="gexnote" title={info.oi_note}>
          GEX tổng {fmtUsd(info.total)}/1% · flip {info.flip ?? 'n/a'} · snapshot {ageH > 0 ? `${ageH}h ` : ''}{ageM}m trước · OI trễ ~8h
        </div>
      )}
    </>
  )
}
