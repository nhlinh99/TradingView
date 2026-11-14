import { useEffect, useMemo, useRef, type MutableRefObject } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import type { PineResult } from './api'
import { tfMs, timeToIndex, type Bar } from './logic'

type Props = {
  result: PineResult | null
  tf: string
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
  version: number
}

const css = (c: unknown, fallback: string) => (typeof c === 'string' && c ? c : fallback)
const FONT: Record<string, number> = { tiny: 8, small: 10, normal: 12, large: 15, huge: 20, auto: 11 }
const DASH: Record<string, number[]> = { solid: [], dashed: [6, 4], dotted: [2, 3] }

/** Vẽ line, box, label và table do script Pine tạo ra. Toạ độ x của script là chỉ số nến (có thể vượt nến cuối). */
export default function PineObjects({ result, tf, chart, candles, bars, version }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)
  const objs = result?.objects
  const step = tfMs(tf) / 1000
  const tables = useMemo(() => objs?.tables.filter((t) => t.cells.length > 0) ?? [], [objs])

  useEffect(() => {
    const canvas = cv.current!
    const ctx = canvas.getContext('2d')!
    if (!result || !objs) {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      return
    }
    let stopped = false
    let raf = 0
    let sig = ''
    const rtimes = result.times.map((ms) => ms / 1000)
    const timeOfIndex = (idx: number) => {
      const n = rtimes.length
      if (n === 0) return 0
      if (idx <= 0) return rtimes[0] + idx * step
      if (idx >= n - 1) return rtimes[n - 1] + (idx - (n - 1)) * step
      const lo = Math.floor(idx)
      return rtimes[lo] + (idx - lo) * (rtimes[lo + 1] - rtimes[lo])
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
      const newSig = `${r?.from}|${r?.to}|${s.priceToCoordinate(0)}|${s.priceToCoordinate(1000)}|${bars.current.length}`
      if (newSig === sig) return
      sig = newSig
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const list = bars.current
      if (!r || list.length < 2) return
      const ts = c.timeScale()
      const a = Math.round(r.from)
      const xa = ts.logicalToCoordinate(a as never)
      const xb = ts.logicalToCoordinate((a + 1) as never)
      if (xa === null || xb === null) return
      const times = list.map((b) => b.time)
      const xOf = (barIndex: number) => xa + (timeToIndex(times, timeOfIndex(barIndex), step) - a) * (xb - xa)
      const plotW = w - c.priceScale('right').width()
      const yOf = (p: number) => s.priceToCoordinate(p)

      // fill giữa hai plot (ví dụ đám mây Ichimoku): tô từng đoạn giữa hai nến liên tiếp theo màu của nến đó
      for (const f of result.fills ?? []) {
        const A = result.plots[f.a]?.values
        const B = result.plots[f.b]?.values
        if (!A || !B) continue
        for (let i = 0; i < f.colors.length - 1; i++) {
          const col = f.colors[i]
          if (!col || A[i] == null || B[i] == null || A[i + 1] == null || B[i + 1] == null) continue
          const x1 = xOf(i); const x2 = xOf(i + 1)
          if (Math.max(x1, x2) < 0 || Math.min(x1, x2) > plotW) continue
          const ya1 = yOf(A[i] as number); const yb1 = yOf(B[i] as number); const ya2 = yOf(A[i + 1] as number); const yb2 = yOf(B[i + 1] as number)
          if (ya1 === null || yb1 === null || ya2 === null || yb2 === null) continue
          ctx.fillStyle = col
          ctx.beginPath(); ctx.moveTo(x1, ya1); ctx.lineTo(x2, ya2); ctx.lineTo(x2, yb2); ctx.lineTo(x1, yb1); ctx.closePath(); ctx.fill()
        }
      }
      for (const b of objs.boxes) {
        const x1 = xOf(b.left as number); const x2 = xOf(b.right as number)
        const y1 = yOf(b.top as number); const y2 = yOf(b.bottom as number)
        if (y1 === null || y2 === null || Math.max(x1, x2) < 0 || Math.min(x1, x2) > plotW) continue
        const x = Math.min(x1, x2); const y = Math.min(y1, y2)
        const bw = Math.abs(x2 - x1); const bh = Math.abs(y2 - y1)
        if (b.bgcolor) { ctx.fillStyle = css(b.bgcolor, 'transparent'); ctx.fillRect(x, y, bw, Math.max(1, bh)) }
        if (b.border_color) {
          ctx.strokeStyle = css(b.border_color, '#888'); ctx.lineWidth = Number(b.border_width) || 1
          ctx.setLineDash(DASH[String(b.border_style)] ?? []); ctx.strokeRect(x, y, bw, Math.max(1, bh)); ctx.setLineDash([])
        }
      }
      for (const l of objs.lines) {
        const y1 = yOf(l.y1 as number); const y2 = yOf(l.y2 as number)
        if (y1 === null || y2 === null) continue
        let x1 = xOf(l.x1 as number); let x2 = xOf(l.x2 as number)
        if (l.extend === 'right' || l.extend === 'both') x2 = plotW
        if (l.extend === 'left' || l.extend === 'both') x1 = 0
        ctx.strokeStyle = css(l.color, '#888'); ctx.lineWidth = Number(l.width) || 1; ctx.setLineDash(DASH[String(l.style)] ?? [])
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); ctx.setLineDash([])
      }
      for (const lb of objs.labels) {
        const px = xOf(lb.x as number)
        const py = yOf(lb.y as number)
        if (py === null || px < -50 || px > plotW + 80) continue
        const text = String(lb.text ?? '')
        const fs = FONT[String(lb.size)] ?? 11
        ctx.font = `${fs}px system-ui, sans-serif`
        const tw = ctx.measureText(text).width
        const padX = 5; const padY = 3
        const bw = tw + padX * 2; const bh = fs + padY * 2
        const style = String(lb.style)
        let bx = px - bw / 2; let by = py - bh - 5     // label_down: nhãn nằm phía trên điểm
        if (style === 'label_up') by = py + 5
        else if (style === 'label_left') { bx = px + 5; by = py - bh / 2 }
        else if (style === 'label_right') { bx = px - bw - 5; by = py - bh / 2 }
        else if (style === 'label_center') by = py - bh / 2
        if (lb.color) {
          ctx.fillStyle = css(lb.color, '#888')
          ctx.beginPath(); ctx.roundRect(bx, by, bw, bh, 3); ctx.fill()
        }
        ctx.fillStyle = css(lb.textcolor, '#d1d4dc'); ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
        ctx.fillText(text, bx + padX, by + bh / 2)
      }
    }
    raf = requestAnimationFrame(draw)
    return () => { stopped = true; cancelAnimationFrame(raf); ctx.clearRect(0, 0, canvas.width, canvas.height) }
  }, [result, objs, step, chart, candles, bars, version])

  return (
    <>
      <canvas ref={cv} className="fp-canvas" aria-hidden="true" />
      {tables.map((t, ti) => {
        const merged = new Map<string, { cs: number; rs: number }>()
        const covered = new Set<string>()
        for (const [c0, r0, c1, r1] of t.merges) {
          merged.set(`${c0},${r0}`, { cs: c1 - c0 + 1, rs: r1 - r0 + 1 })
          for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) if (c !== c0 || r !== r0) covered.add(`${c},${r}`)
        }
        const byPos = new Map(t.cells.map((cell) => [`${cell.col},${cell.row}`, cell]))
        const rows = Number(t.rows); const cols = Number(t.columns)
        return (
          <table key={ti} className={`pinetable pos-${t.position}`} style={{ background: css(t.bgcolor, 'transparent'), borderColor: css(t.border_color, 'transparent') }}>
            <tbody>
              {Array.from({ length: rows }, (_, r) => (
                <tr key={r}>
                  {Array.from({ length: cols }, (_, c) => {
                    const key = `${c},${r}`
                    if (covered.has(key)) return null
                    const cell = byPos.get(key)
                    const m = merged.get(key)
                    return (
                      <td key={c} colSpan={m?.cs} rowSpan={m?.rs} title={typeof cell?.tooltip === 'string' ? cell.tooltip : undefined}
                        style={{ background: css(cell?.bgcolor, 'transparent'), color: css(cell?.text_color, 'inherit'), fontSize: FONT[String(cell?.text_size)] ?? 10 }}>
                        {String(cell?.text ?? '')}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )
      })}
    </>
  )
}
