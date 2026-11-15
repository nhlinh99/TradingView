import { useCallback, useEffect, useRef, useState, type MutableRefObject, type ReactElement } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { clearDrawings, createDrawing, deleteDrawing, fetchDrawings } from './api'
import {
  FIB_LEVELS, distToSegment, indexToTime, tfMs, timeToIndex,
  type Bar, type DrawKind, type DrawPoint, type Drawing,
} from './logic'

type Tool = 'cursor' | DrawKind | 'erase'
type Props = {
  symbol: string
  tf: string
  dark: boolean
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
}

const TOOLS: { id: Tool; label: string; title: string }[] = [
  { id: 'cursor', label: 'Trỏ', title: 'Di chuyển biểu đồ' },
  { id: 'trend', label: 'Đường', title: 'Đường xu hướng: bấm hai điểm' },
  { id: 'hline', label: 'Ngang', title: 'Đường ngang: bấm một điểm' },
  { id: 'rect', label: 'Hộp', title: 'Hình chữ nhật: bấm hai góc' },
  { id: 'fib', label: 'Fib', title: 'Fibonacci retracement: bấm hai điểm' },
  { id: 'text', label: 'Chữ', title: 'Văn bản: bấm một điểm' },
  { id: 'erase', label: 'Xoá', title: 'Bấm vào hình để xoá' },
]

const ICONS: Record<string, ReactElement> = {
  cursor: <path d="M5 3l12 8-5.5 1.2L9 18z" />,
  trend: <><circle cx="5" cy="17" r="2" /><circle cx="17" cy="5" r="2" /><path d="M6.5 15.5L15.5 6.5" /></>,
  hline: <path d="M2 11h18M2 11l3-3M2 11l3 3" />,
  rect: <rect x="4" y="6" width="14" height="10" rx="1" />,
  fib: <path d="M3 4h16M3 9h16M3 13h16M3 18h16" />,
  text: <path d="M5 5h12M11 5v12M8 17h6" />,
  erase: <path d="M4 15l8-9 6 5-6 7H8zM12 18h7" />,
  clear: <path d="M5 7h12M9 7V5h4v2M7 7l1 11h6l1-11" />,
}
function Icon({ id }: { id: string }) {
  return <svg viewBox="0 0 22 22" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[id]}</svg>
}

const NEED: Record<DrawKind, number> = { trend: 2, hline: 1, rect: 2, fib: 2, text: 1 }
const COLOR = '#f0b90b'

/** Lớp vẽ tay lên biểu đồ. Điểm neo lưu theo (thời gian, giá) nên đúng ở mọi khung thời gian; lưu trong SQLite qua /api/drawings. */
export default function Drawings({ symbol, tf, dark, chart, candles, bars }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)
  const [tool, setTool] = useState<Tool>('cursor')
  const [items, setItems] = useState<Drawing[]>([])
  const [err, setErr] = useState<string | null>(null)
  const pending = useRef<DrawPoint[]>([])
  const hover = useRef<DrawPoint | null>(null)
  const itemsRef = useRef<Drawing[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [chip, setChip] = useState<{ x: number; y: number } | null>(null)
  const chipRef = useRef<{ x: number; y: number } | null>(null)
  const selRef = useRef<number | null>(null)
  const toolRef = useRef<Tool>('cursor')
  const redraw = useRef<() => void>(() => {})
  itemsRef.current = items
  selRef.current = selected
  toolRef.current = tool
  const step = tfMs(tf) / 1000

  useEffect(() => {
    let stop = false
    setItems([])
    setSelected(null)
    pending.current = []
    fetchDrawings(symbol).then((d) => { if (!stop) setItems(d) }).catch((e: unknown) => setErr(String(e)))
    return () => { stop = true }
  }, [symbol])

  // đổi công cụ: bỏ hình đang vẽ dở
  useEffect(() => { pending.current = []; hover.current = null; redraw.current() }, [tool])

  const geo = useCallback(() => {
    const c = chart.current
    const s = candles.current
    const list = bars.current
    if (!c || !s || list.length < 2) return null
    const ts = c.timeScale()
    const r = ts.getVisibleLogicalRange()
    if (!r) return null
    const a = Math.round(r.from)
    const xa = ts.logicalToCoordinate(a as never)
    const xb = ts.logicalToCoordinate((a + 1) as never)
    if (xa === null || xb === null) return null
    const times = list.map((b) => b.time)
    const sp = xb - xa
    return {
      c, s, times,
      x: (time: number) => xa + (timeToIndex(times, time, step) - a) * sp,
      time: (px: number) => indexToTime(times, a + (px - xa) / sp, step),
    }
  }, [chart, candles, bars, step])

  const toScreen = useCallback((g: NonNullable<ReturnType<typeof geo>>, p: DrawPoint) => {
    const y = g.s.priceToCoordinate(p.price)
    return y === null ? null : { x: g.x(p.time), y }
  }, [])

  useEffect(() => {
    const canvas = cv.current!
    const ctx = canvas.getContext('2d')!
    let raf = 0
    let stopped = false
    let sig = ''
    const draw = (force = false) => {
      raf = requestAnimationFrame(() => draw())
      if (stopped) return
      const g = geo()
      const el = canvas.parentElement
      if (!g || !el) return
      const w = el.clientWidth
      const h = el.clientHeight
      const dpr = window.devicePixelRatio || 1
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr)
        canvas.height = Math.round(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        force = true
      }
      const paneH = g.c.panes()[0]?.getHeight() ?? h
      canvas.style.clipPath = `inset(0 0 ${Math.max(0, h - paneH)}px 0)`
      const r = g.c.timeScale().getVisibleLogicalRange()
      const hv = hover.current
      const ns = `${r?.from}|${r?.to}|${g.s.priceToCoordinate(0)}|${g.s.priceToCoordinate(1000)}|${itemsRef.current.length}|${pending.current.length}|${hv?.time}|${hv?.price}|${dark}|${g.times.length}|${selRef.current}`
      if (!force && ns === sig) return
      sig = ns
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const plotW = w - g.c.priceScale('right').width()
      const ink = dark ? '#d1d4dc' : '#1b2430'
      const shapes: { d: Pick<Drawing, 'kind' | 'payload'>; preview: boolean }[] = itemsRef.current.map((d) => ({ d, preview: false }))
      if (pending.current.length > 0 && hv) {
        const kind = toolRef.current as DrawKind
        if (kind in NEED) shapes.push({ d: { kind, payload: { points: [...pending.current, hv].slice(0, NEED[kind]) } }, preview: true })
      }
      let anchor: { x: number; y: number } | null = null
      for (const { d, preview } of shapes) {
        const col = d.payload.color ?? COLOR
        const pts = d.payload.points.map((p) => toScreen(g, p))
        if (pts.some((p) => p === null)) continue
        const P = pts as { x: number; y: number }[]
        ctx.save()
        ctx.strokeStyle = col
        ctx.fillStyle = col
        const isSel = !preview && (d as Drawing).id === selRef.current
        if (isSel) {
          const ax = d.kind === 'hline' ? plotW - 64 : Math.max(...P.map((q) => q.x))
          const ay = d.kind === 'hline' ? P[0].y : Math.min(...P.map((q) => q.y))
          anchor = { x: Math.min(Math.max(ax + 6, 8), plotW - 62), y: Math.min(Math.max(ay - 30, 4), h - 34) }
        }
        ctx.lineWidth = isSel ? 3 : 1.5
        if (isSel) { ctx.shadowColor = col; ctx.shadowBlur = 8 }
        ctx.setLineDash(preview ? [5, 4] : [])
        if (d.kind === 'trend' && P.length === 2) {
          ctx.beginPath(); ctx.moveTo(P[0].x, P[0].y); ctx.lineTo(P[1].x, P[1].y); ctx.stroke()
          for (const p of P) { ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI * 2); ctx.fill() }
        } else if (d.kind === 'hline') {
          ctx.beginPath(); ctx.moveTo(0, P[0].y); ctx.lineTo(plotW, P[0].y); ctx.stroke()
          ctx.font = '11px system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'
          ctx.fillText(String(d.payload.points[0].price), 6, P[0].y - 2)
        } else if (d.kind === 'rect' && P.length === 2) {
          const x = Math.min(P[0].x, P[1].x); const y = Math.min(P[0].y, P[1].y)
          ctx.globalAlpha = 0.12; ctx.fillRect(x, y, Math.abs(P[1].x - P[0].x), Math.abs(P[1].y - P[0].y)); ctx.globalAlpha = 1
          ctx.strokeRect(x, y, Math.abs(P[1].x - P[0].x), Math.abs(P[1].y - P[0].y))
        } else if (d.kind === 'fib' && P.length === 2) {
          const [a, b] = d.payload.points
          const x0 = Math.min(P[0].x, P[1].x); const x1 = Math.max(P[0].x, P[1].x, x0 + 60)
          ctx.font = '10px system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'
          FIB_LEVELS.forEach((lv) => {
            const price = b.price + (a.price - b.price) * lv
            const y = g.s.priceToCoordinate(price)
            if (y === null) return
            ctx.globalAlpha = lv === 0 || lv === 1 ? 1 : 0.7
            ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke()
            ctx.globalAlpha = 1
            ctx.fillText(`${lv} (${price.toFixed(2)})`, x0 + 3, y - 1)
          })
        } else if (d.kind === 'text') {
          ctx.fillStyle = ink
          ctx.font = '13px system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
          ctx.fillText(d.payload.text ?? '', P[0].x, P[0].y)
        }
        if (isSel) {
          ctx.shadowBlur = 0; ctx.setLineDash([]); ctx.fillStyle = '#fff'; ctx.strokeStyle = col; ctx.lineWidth = 2
          for (const q of P) { ctx.beginPath(); ctx.arc(q.x, q.y, 5, 0, Math.PI * 2); ctx.fill(); ctx.stroke() }
        }
        ctx.restore()
      }
      const prev = chipRef.current
      if (!anchor ? prev !== null : !prev || Math.abs(prev.x - anchor.x) > 1 || Math.abs(prev.y - anchor.y) > 1) { chipRef.current = anchor; setChip(anchor) }
    }
    redraw.current = () => draw(true)
    raf = requestAnimationFrame(() => draw(true))
    return () => { stopped = true; cancelAnimationFrame(raf); ctx.clearRect(0, 0, canvas.width, canvas.height) }
  }, [geo, toScreen, dark])

  const pointAt = (e: React.PointerEvent): DrawPoint | null => {
    const g = geo()
    const rect = cv.current?.getBoundingClientRect()
    if (!g || !rect) return null
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top
    const price = g.s.coordinateToPrice(py)
    return price === null ? null : { time: g.time(px), price }
  }

  const hitAt = (clientX: number, clientY: number): Drawing | null => {
    const g = geo()
    const rect = cv.current?.getBoundingClientRect()
    if (!g || !rect) return null
    const px = clientX - rect.left
    const py = clientY - rect.top
    let best: { d: Drawing; dist: number } | null = null
    for (const d of itemsRef.current) {
      const P = d.payload.points.map((p) => toScreen(g, p))
      if (P.some((p) => p === null)) continue
      const S = P as { x: number; y: number }[]
      let dist = Infinity
      if (d.kind === 'trend') dist = distToSegment(px, py, S[0].x, S[0].y, S[1].x, S[1].y)
      else if (d.kind === 'hline') dist = Math.abs(py - S[0].y)
      else if (d.kind === 'text') dist = Math.hypot(px - S[0].x - 20, py - S[0].y)
      else if (d.kind === 'rect' || d.kind === 'fib') {
        const x0 = Math.min(S[0].x, S[1].x); const x1 = Math.max(S[0].x, S[1].x)
        const y0 = Math.min(S[0].y, S[1].y); const y1 = Math.max(S[0].y, S[1].y)
        dist = px >= x0 - 6 && px <= x1 + 6 && py >= y0 - 6 && py <= y1 + 6 ? 0 : Infinity
      }
      if (dist <= 8 && (!best || dist < best.dist)) best = { d, dist }
    }
    return best?.d ?? null
  }
  const hit = (e: React.PointerEvent) => hitAt(e.clientX, e.clientY)

  const remove = async (id: number) => {
    try { await deleteDrawing(id); setItems((l) => l.filter((x) => x.id !== id)); setSelected((c) => (c === id ? null : c)); setErr(null) } catch (x) { setErr(String(x)) }
  }

  // Chế độ Trỏ: bấm vào hình để chọn (kéo biểu đồ không tính là bấm). Delete hoặc Backspace xoá hình đã chọn, Esc bỏ chọn.
  useEffect(() => {
    const host = cv.current?.parentElement
    if (!host) return
    let down: { x: number; y: number } | null = null
    const onDown = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY } }
    const onUp = (e: PointerEvent) => {
      if ((e.target as HTMLElement | null)?.closest?.('.draw-del, .draw-tools')) { down = null; return }
      if (!down || toolRef.current !== 'cursor') return
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4
      down = null
      if (moved) return
      const d = hitAt(e.clientX, e.clientY)
      setSelected(d ? d.id : null)
      redraw.current()
    }
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
      if (e.key === 'Escape') { setSelected(null); redraw.current() }
      else if ((e.key === 'Delete' || e.key === 'Backspace') && selRef.current !== null) { e.preventDefault(); void remove(selRef.current) }
    }
    host.addEventListener('pointerdown', onDown)
    host.addEventListener('pointerup', onUp)
    window.addEventListener('keydown', onKey)
    return () => { host.removeEventListener('pointerdown', onDown); host.removeEventListener('pointerup', onUp); window.removeEventListener('keydown', onKey) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo])

  const onDown = async (e: React.PointerEvent) => {
    const t = toolRef.current
    if (t === 'cursor') return
    if (t === 'erase') {
      const d = hit(e)
      if (d) await remove(d.id)
      return
    }
    const p = pointAt(e)
    if (!p) return
    pending.current = [...pending.current, p]
    if (pending.current.length >= NEED[t]) {
      const payload: Drawing['payload'] = { points: pending.current, color: COLOR }
      if (t === 'text') {
        const text = window.prompt('Nội dung văn bản')
        if (!text) { pending.current = []; redraw.current(); return }
        payload.text = text
      }
      pending.current = []
      try {
        const d = await createDrawing(symbol, t, payload)
        setItems((l) => [...l, d])
        setSelected(d.id)
        setTool('cursor')
        setErr(null)
      } catch (x) { setErr(String(x)) }
    }
    redraw.current()
  }

  const clearAll = async () => {
    if (items.length === 0 || !window.confirm(`Xoá ${items.length} hình của ${symbol}?`)) return
    try { await clearDrawings(symbol); setItems([]); setSelected(null) } catch (x) { setErr(String(x)) }
  }

  return (
    <>
      <canvas
        ref={cv} className="draw-canvas" aria-hidden="true" data-tool={tool}
        style={{ pointerEvents: tool === 'cursor' ? 'none' : 'auto', cursor: tool === 'erase' ? 'pointer' : 'crosshair' }}
        onPointerDown={(e) => void onDown(e)}
        onPointerMove={(e) => { if (pending.current.length > 0) { hover.current = pointAt(e); redraw.current() } }}
      />
      {selected !== null && chip && (
        <button className="draw-del" style={{ left: chip.x, top: chip.y }} onClick={() => void remove(selected)} title="Xoá hình này (Delete)" aria-label="Xoá hình đang chọn">
          <Icon id="clear" /> Xoá
        </button>
      )}
      <div className="draw-tools" role="toolbar" aria-label="Công cụ vẽ">
        {TOOLS.map((t) => (
          <button key={t.id} title={t.title} aria-label={t.title} aria-pressed={tool === t.id} className={tool === t.id ? 'on' : ''} onClick={() => setTool(t.id)}>
            <Icon id={t.id} />
          </button>
        ))}
        <span className="sep" aria-hidden="true" />
        <button title="Xoá hình đang chọn (Delete)" aria-label="Xoá hình đang chọn" className="del" disabled={selected === null} onClick={() => { if (selected !== null) void remove(selected) }}><Icon id="erase" /></button>
        <button title="Xoá mọi hình của symbol này" aria-label="Xoá mọi hình" onClick={() => void clearAll()} disabled={items.length === 0}><Icon id="clear" /></button>
        {err && <span className="bad" role="alert">{err}</span>}
      </div>
    </>
  )
}
