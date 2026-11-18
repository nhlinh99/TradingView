import { useCallback, useEffect, useRef, useState, type MutableRefObject, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { clearDrawings, createAlert, createDrawing, deleteDrawing, fetchDrawings, updateDrawing } from './api'
import { indexToTime, tfMs, timeToIndex, type Bar, type DrawKind, type DrawPoint, type Drawing } from './logic'
import { GROUP_LABEL, GROUP_ORDER, KINDS, REGISTRY, fmtPrice, handlesFor, zOrdered, type Geo, type Group, type Pt } from './drawTools'

type Tool = 'cursor' | DrawKind | 'erase'
type Props = {
  symbol: string
  tf: string
  dark: boolean
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  bars: MutableRefObject<Bar[]>
}

const ICONS: Record<string, ReactElement> = {
  cursor: <path d="M5 3l12 8-5.5 1.2L9 18z" />,
  erase: <path d="M4 15l8-9 6 5-6 7H8zM12 18h7" />,
  clear: <path d="M5 7h12M9 7V5h4v2M7 7l1 11h6l1-11" />,
  magnet: <path d="M5 3v8a6 6 0 0 0 12 0V3h-4v8a2 2 0 0 1-4 0V3zM5 7h4M13 7h4" />,
  eye: <><path d="M2 11s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z" /><circle cx="11" cy="11" r="2.5" /></>,
  eyeoff: <><path d="M2 11s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z" /><path d="M3 3l16 16" /></>,
  undo: <path d="M7 5L3 9l4 4M3 9h9a5 5 0 0 1 0 10H8" />,
  redo: <path d="M15 5l4 4-4 4M19 9h-9a5 5 0 0 0 0 10h4" />,
  lock: <><rect x="5" y="10" width="12" height="9" rx="1.5" /><path d="M8 10V7a3 3 0 0 1 6 0v3" /></>,
  unlock: <><rect x="5" y="10" width="12" height="9" rx="1.5" /><path d="M8 10V7a3 3 0 0 1 5.5-1.6" /></>,
  pencil: <path d="M4 18l1-4L15 4l3 3L8 17zM13 6l3 3" />,
  chevron: <path d="M13 5l-6 6 6 6" />,
  clone: <><rect x="7" y="7" width="11" height="11" rx="1.5" /><path d="M4 14V5a1 1 0 0 1 1-1h9" /></>,
}
function Icon({ node }: { node: ReactElement }) {
  return <svg viewBox="0 0 22 22" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{node}</svg>
}

const COLOR = '#f0b90b'
const DASH: Record<string, number[]> = { solid: [], dash: [7, 5], dot: [2, 4] }
const MAX_HISTORY = 60
let nextInstance = 1
let activeInstance = 0   // ô biểu đồ cuối cùng được bấm vào; phím tắt hoàn tác chỉ áp dụng cho ô này

/** Lớp vẽ tay lên biểu đồ. Điểm neo lưu theo (thời gian, giá) nên đúng ở mọi khung thời gian; lưu trong SQLite qua /api/drawings. */
export default function Drawings({ symbol, tf, dark, chart, candles, bars }: Props) {
  const cv = useRef<HTMLCanvasElement>(null)
  const inst = useRef(nextInstance++)
  const [tool, setTool] = useState<Tool>('cursor')
  const [items, setItems] = useState<Drawing[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [hideAll, setHideAll] = useState(false)
  const [magnet, setMagnet] = useState(false)
  const [openGrp, setOpenGrp] = useState<Group | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; price: number; time: number; hitId: number | null } | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const ctxHandler = useRef<(e: MouseEvent) => void>(() => {})
  const [flyPos, setFlyPos] = useState<{ left: number; top: number } | null>(null)
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('drawToolsCollapsed') === '1' } catch { return false } })
  const [lastTool, setLastTool] = useState<Record<Group, DrawKind>>({ line: 'trend', fib: 'fib', pitchfork: 'pitchfork', gann: 'gannfan', position: 'long', measure: 'ruler', shape: 'rect', text: 'text' })
  const pending = useRef<DrawPoint[]>([])
  const brush = useRef<DrawPoint[] | null>(null)
  const hover = useRef<DrawPoint | null>(null)
  const itemsRef = useRef<Drawing[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [chip, setChip] = useState<{ x: number; y: number } | null>(null)
  const chipRef = useRef<{ x: number; y: number } | null>(null)
  const selRef = useRef<number | null>(null)
  const toolRef = useRef<Tool>('cursor')
  const hideRef = useRef(false)
  const magnetRef = useRef(false)
  const redraw = useRef<() => void>(() => {})
  const completePendingRef = useRef<(t: DrawKind) => Promise<void>>(async () => {})
  const hist = useRef<{ undo: Drawing[][]; redo: Drawing[][] }>({ undo: [], redo: [] })
  const [histLen, setHistLen] = useState({ undo: 0, redo: 0 })
  itemsRef.current = items
  selRef.current = selected
  toolRef.current = tool
  hideRef.current = hideAll
  magnetRef.current = magnet
  const step = tfMs(tf) / 1000

  const syncHist = () => setHistLen({ undo: hist.current.undo.length, redo: hist.current.redo.length })
  /** Ghi lại trạng thái trước một thay đổi để hoàn tác được. */
  const pushHistory = (before: Drawing[]) => {
    hist.current.undo.push(before)
    if (hist.current.undo.length > MAX_HISTORY) hist.current.undo.shift()
    hist.current.redo = []
    syncHist()
  }

  useEffect(() => {
    let stop = false
    setItems([])
    setSelected(null)
    pending.current = []
    hist.current = { undo: [], redo: [] }
    syncHist()
    fetchDrawings(symbol).then((d) => { if (!stop) setItems(d) }).catch((e: unknown) => setErr(String(e)))
    return () => { stop = true }
  }, [symbol])

  // đang dùng một công cụ vẽ: ẩn hai đường chữ thập nét đứt theo chuột (nhãn giá và giờ ở trục vẫn giữ); về chế độ Trỏ thì hiện lại
  useEffect(() => {
    const c = chart.current
    if (!c) return
    const drawing = tool !== 'cursor' && tool !== 'erase'
    c.applyOptions({ crosshair: { vertLine: { visible: !drawing }, horzLine: { visible: !drawing } } })
    return () => { c.applyOptions({ crosshair: { vertLine: { visible: true }, horzLine: { visible: true } } }) }
  }, [tool, chart])

  // đổi công cụ: bỏ hình đang vẽ dở
  useEffect(() => { pending.current = []; brush.current = null; hover.current = null; redraw.current() }, [tool])
  useEffect(() => { redraw.current() }, [items, hideAll])

  const geo = useCallback((): (Geo & { c: IChartApi }) | null => {
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
      idx: (time: number) => timeToIndex(times, time, step),
    }
  }, [chart, candles, bars, step])

  const toScreen = useCallback((g: Geo, p: DrawPoint): Pt | null => {
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
      const ns = `${r?.from}|${r?.to}|${g.s.priceToCoordinate(0)}|${g.s.priceToCoordinate(1000)}|${itemsRef.current.length}|${pending.current.length}|${brush.current?.length}|${hv?.time}|${hv?.price}|${dark}|${g.times.length}|${selRef.current}|${hideRef.current}`
      if (!force && ns === sig) return
      sig = ns
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      if (hideRef.current) { if (chipRef.current) { chipRef.current = null; setChip(null) } return }
      const plotW = w - g.c.priceScale('right').width()
      const ink = dark ? '#d1d4dc' : '#1b2430'
      const shapes: { d: Pick<Drawing, 'kind' | 'payload'>; preview: boolean }[] = zOrdered(itemsRef.current).map((d) => ({ d, preview: false }))
      const tl = toolRef.current
      if (pending.current.length > 0 && hv && tl in REGISTRY) {
        const kind = tl as DrawKind
        shapes.push({ d: { kind, payload: { points: [...pending.current, hv].slice(0, REGISTRY[kind].max) } }, preview: true })
      }
      if (brush.current && brush.current.length >= 2) shapes.push({ d: { kind: 'brush', payload: { points: brush.current } }, preview: true })
      let anchor: { x: number; y: number } | null = null
      for (const { d, preview } of shapes) {
        const def = REGISTRY[d.kind]
        if (!def) continue
        const pts = d.payload.points.map((p) => toScreen(g, p))
        if (pts.some((p) => p === null)) continue
        const P = pts as Pt[]
        const col = d.payload.color ?? COLOR
        ctx.save()
        // Fib, Pitchfork, Gann kéo dài ra nhiều mức: không vẽ phần dưới giá 0 (giá không âm)
        if (def.group === 'fib' || def.group === 'pitchfork' || def.group === 'gann') {
          const y0 = g.s.priceToCoordinate(0)
          if (y0 !== null && y0 < h) { ctx.beginPath(); ctx.rect(0, 0, w, Math.max(0, y0)); ctx.clip() }
        }
        ctx.strokeStyle = col
        ctx.fillStyle = col
        const isSel = !preview && (d as Drawing).id === selRef.current
        if (isSel) {
          const ax = d.kind === 'hline' ? plotW - 64 : Math.max(...P.map((q) => q.x))
          const ay = d.kind === 'hline' ? P[0].y : Math.min(...P.map((q) => q.y))
          anchor = { x: Math.min(Math.max(ax + 6, 8), Math.max(8, plotW - 250)), y: Math.min(Math.max(ay - 38, 4), h - 40) }
        }
        const bw = d.payload.width ?? 1.5
        ctx.lineWidth = isSel ? bw + 1.5 : bw
        if (isSel) { ctx.shadowColor = col; ctx.shadowBlur = 8 }
        ctx.setLineDash(preview ? [5, 4] : DASH[d.payload.dash ?? 'solid'])
        def.draw({ ctx, g, plotW, h, step, ink, dark, bars: bars.current, preview }, P, d.payload.points, d.payload.text)
        if (isSel && !(d.payload.locked)) {
          ctx.shadowBlur = 0; ctx.setLineDash([]); ctx.fillStyle = '#fff'; ctx.strokeStyle = col; ctx.lineWidth = 2
          for (const q of handlesFor(d.kind, P, plotW)) { ctx.beginPath(); ctx.arc(q.x, q.y, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke() }
        }
        ctx.restore()
      }
      const prev = chipRef.current
      if (!anchor ? prev !== null : !prev || Math.abs(prev.x - anchor.x) > 1 || Math.abs(prev.y - anchor.y) > 1) { chipRef.current = anchor; setChip(anchor) }
    }
    redraw.current = () => draw(true)
    raf = requestAnimationFrame(() => draw(true))
    return () => { stopped = true; cancelAnimationFrame(raf); ctx.clearRect(0, 0, canvas.width, canvas.height) }
  }, [geo, toScreen, dark, bars, step])

  /** Đổi toạ độ màn hình thành (thời gian, giá). Có nam châm thì bắt vào nến và giá O/H/L/C gần nhất. */
  const pointFromClient = (clientX: number, clientY: number, snap = true): DrawPoint | null => {
    const g = geo()
    const rect = cv.current?.getBoundingClientRect()
    if (!g || !rect) return null
    const px = clientX - rect.left
    const py = clientY - rect.top
    const price = g.s.coordinateToPrice(py)
    if (price === null) return null
    let p: DrawPoint = { time: g.time(px), price }
    if (snap && magnetRef.current && bars.current.length > 0) {
      const list = bars.current
      const i = Math.round(g.idx(p.time))
      if (i >= 0 && i < list.length) {
        const b = list[i]
        let best = p.price
        let bd = 24
        for (const v of [b.open, b.high, b.low, b.close]) {
          const y = g.s.priceToCoordinate(v)
          if (y !== null && Math.abs(y - py) < bd) { bd = Math.abs(y - py); best = v }
        }
        p = { time: b.time, price: best }
      }
    }
    return p
  }

  const hitAt = (clientX: number, clientY: number): Drawing | null => {
    if (hideRef.current) return null
    const g = geo()
    const rect = cv.current?.getBoundingClientRect()
    if (!g || !rect) return null
    const px = clientX - rect.left
    const py = clientY - rect.top
    const plotW = rect.width - g.c.priceScale('right').width()
    let best: { d: Drawing; dist: number } | null = null
    for (const d of zOrdered(itemsRef.current)) {
      const def = REGISTRY[d.kind]
      if (!def) continue
      const P = d.payload.points.map((p) => toScreen(g, p))
      if (P.some((p) => p === null)) continue
      const dist = def.hit({ g, bars: bars.current, step, plotW }, P as Pt[], d.payload.points, px, py)
      if (dist <= 8 && (!best || dist <= best.dist)) best = { d, dist }   // hoà thì lấy hình vẽ sau (nằm trên)
    }
    return best?.d ?? null
  }
  const hit = (e: React.PointerEvent) => hitAt(e.clientX, e.clientY)

  // ---------- thay đổi dữ liệu (đều ghi lịch sử để hoàn tác) ----------

  const remove = async (id: number) => {
    const d = itemsRef.current.find((x) => x.id === id)
    if (!d || d.payload.locked) return
    pushHistory(itemsRef.current)
    try { await deleteDrawing(id); setItems((l) => l.filter((x) => x.id !== id)); setSelected((c) => (c === id ? null : c)); setErr(null) } catch (x) { setErr(String(x)) }
  }

  /** Đưa kho (và màn hình) về đúng danh sách `target`: xoá hình thừa, tạo lại hình thiếu với id cũ, cập nhật hình đã đổi. */
  const restore = async (target: Drawing[]) => {
    const cur = itemsRef.current
    setItems(target); setSelected(null)
    try {
      for (const d of cur) if (!target.some((t) => t.id === d.id)) await deleteDrawing(d.id)
      for (const t of target) {
        const c = cur.find((x) => x.id === t.id)
        if (!c) await createDrawing(symbol, t.kind, t.payload, t.id)
        else if (JSON.stringify(c.payload) !== JSON.stringify(t.payload)) await updateDrawing(t.id, symbol, t.kind, t.payload)
      }
      setErr(null)
    } catch (x) { setErr(String(x)) }
  }
  const undo = () => {
    const t = hist.current.undo.pop()
    if (!t) return
    hist.current.redo.push(itemsRef.current)
    syncHist()
    void restore(t)
  }
  const redo = () => {
    const t = hist.current.redo.pop()
    if (!t) return
    hist.current.undo.push(itemsRef.current)
    syncHist()
    void restore(t)
  }

  // chỉnh kiểu: áp ngay lên màn hình, gửi lên máy chủ sau khi ngừng chỉnh 0,5 giây (một lần hoàn tác cho cả đợt chỉnh)
  const burst = useRef<{ id: number; timer: number } | null>(null)
  const patchSelected = (patch: Partial<Drawing['payload']>, immediate = false) => {
    const id = selRef.current
    const d = itemsRef.current.find((x) => x.id === id)
    if (!d) return
    if (!burst.current || burst.current.id !== d.id) pushHistory(itemsRef.current)
    const next = { ...d, payload: { ...d.payload, ...patch } }
    itemsRef.current = itemsRef.current.map((x) => (x.id === d.id ? next : x))
    setItems(itemsRef.current)
    if (burst.current) window.clearTimeout(burst.current.timer)
    const send = async () => {
      burst.current = null
      const latest = itemsRef.current.find((x) => x.id === d.id)
      if (!latest) return
      try { await updateDrawing(latest.id, latest.symbol, latest.kind, latest.payload); setErr(null) } catch (x) { setErr(String(x)) }
    }
    if (immediate) { burst.current = null; void send() } else burst.current = { id: d.id, timer: window.setTimeout(() => void send(), 500) }
  }

  const clone = async () => {
    const d = itemsRef.current.find((x) => x.id === selRef.current)
    if (!d) return
    pushHistory(itemsRef.current)
    const shift = step * 3
    try {
      const n = await createDrawing(symbol, d.kind, { ...d.payload, locked: false, points: d.payload.points.map((p) => ({ ...p, time: p.time + shift })) })
      setItems((l) => [...l, n]); setSelected(n.id); setErr(null)
    } catch (x) { setErr(String(x)) }
  }

  // Chế độ Trỏ: bấm vào hình để chọn (kéo biểu đồ không tính là bấm). Delete xoá, Esc bỏ chọn, Ctrl+Z / Ctrl+Y hoàn tác / làm lại.
  useEffect(() => {
    const host = cv.current?.parentElement
    if (!host) return
    let down: { x: number; y: number } | null = null
    const onDown = (e: PointerEvent) => { activeInstance = inst.current; down = { x: e.clientX, y: e.clientY } }
    const onUp = (e: PointerEvent) => {
      if ((e.target as HTMLElement | null)?.closest?.('.draw-chip, .draw-tools')) { down = null; return }
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
      if ((e.ctrlKey || e.metaKey) && activeInstance === inst.current) {
        const k = e.key.toLowerCase()
        if (k === 'z' && !e.shiftKey) { e.preventDefault(); undo(); return }
        if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); redo(); return }
      }
      // phím mũi tên dời hình đang chọn: lên/xuống đổi giá (1px, giữ Shift là 10px), trái/phải dời một nến (Shift: 10 nến)
      if (e.key.startsWith('Arrow') && selRef.current !== null && toolRef.current === 'cursor' && activeInstance === inst.current && !(e.ctrlKey || e.metaKey || e.altKey)) {
        const d = itemsRef.current.find((x) => x.id === selRef.current)
        const g = geo()
        if (!d || !g || d.payload.locked) return
        e.preventDefault()
        const n = e.shiftKey ? 10 : 1
        let pts = d.payload.points
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
          const dy = (e.key === 'ArrowUp' ? -1 : 1) * n
          pts = pts.map((p) => {
            const y = g.s.priceToCoordinate(p.price)
            const np = y === null ? null : g.s.coordinateToPrice(y + dy)
            return np === null ? p : { ...p, price: np }
          })
        } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
          const dt = (e.key === 'ArrowLeft' ? -1 : 1) * n * step
          pts = pts.map((p) => ({ ...p, time: p.time + dt }))
        } else return
        patchSelected({ points: pts })
        return
      }
      if (e.key === 'Enter' && pending.current.length > 0) {
        const t = toolRef.current
        if (t !== 'cursor' && t !== 'erase') { e.preventDefault(); void completePendingRef.current(t) }
        return
      }
      if (e.key === 'Escape') { pending.current = []; setSelected(null); setOpenGrp(null); setTool('cursor'); redraw.current() }
      else if ((e.key === 'Delete' || e.key === 'Backspace') && selRef.current !== null) { e.preventDefault(); void remove(selRef.current) }
    }
    host.addEventListener('pointerdown', onDown)
    host.addEventListener('pointerup', onUp)
    window.addEventListener('keydown', onKey)
    return () => { host.removeEventListener('pointerdown', onDown); host.removeEventListener('pointerup', onUp); window.removeEventListener('keydown', onKey) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo])

  // Kéo hình đang chọn: kéo tay nắm (4 góc với hình dạng hộp, các điểm neo với hình khác) để đổi cỡ, kéo thân hình để di chuyển.
  // Chạy ở pha capture để biểu đồ không bị cuộn theo khi đang kéo hình.
  useEffect(() => {
    const host = cv.current?.parentElement
    if (!host) return
    const onDownCap = (e: PointerEvent) => {
      if (toolRef.current !== 'cursor' || selRef.current === null || e.button !== 0 || hideRef.current) return
      const overUi = !!(e.target as HTMLElement | null)?.closest?.('.draw-chip, .draw-tools')
      const g = geo()
      const rect = cv.current?.getBoundingClientRect()
      const d = itemsRef.current.find((x) => x.id === selRef.current)
      if (!g || !rect || !d || d.payload.locked) return
      const S = d.payload.points.map((p) => toScreen(g, p))
      if (S.some((p) => p === null)) return
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top
      const plotW = rect.width - g.c.priceScale('right').width()
      // tay nắm nằm dưới thanh công cụ vẫn kéo được; thân hình thì nhường cho thanh công cụ
      const h = handlesFor(d.kind, S as Pt[], plotW).find((q) => Math.hypot(px - q.x, py - q.y) <= 12)
      const body = !h && !overUi && hitAt(e.clientX, e.clientY)?.id === d.id
      if (!h && !body) return
      const start = pointFromClient(e.clientX, e.clientY, false)
      if (!start) return
      e.stopPropagation(); e.preventDefault()
      activeInstance = inst.current
      const before = itemsRef.current
      const orig = d.payload.points
      let cur = orig
      const apply = (pts: DrawPoint[]) => { cur = pts; setItems((l) => l.map((x) => (x.id === d.id ? { ...x, payload: { ...x.payload, points: pts } } : x))); redraw.current() }
      const onMove = (ev: PointerEvent) => {
        const np = pointFromClient(ev.clientX, ev.clientY, !!h)
        if (!np) return
        if (h) apply(h.set(orig, np))
        else apply(orig.map((p) => ({ time: p.time + (np.time - start.time), price: p.price + (np.price - start.price) })))
      }
      const onUpDrag = async () => {
        window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUpDrag)
        if (cur === orig) return
        pushHistory(before)
        try { await updateDrawing(d.id, d.symbol, d.kind, { ...d.payload, points: cur }); setErr(null) }
        catch (x) { setErr(String(x)); setItems((l) => l.map((y) => (y.id === d.id ? d : y))); redraw.current() }
      }
      window.addEventListener('pointermove', onMove); window.addEventListener('pointerup', onUpDrag)
    }
    const onHover = (e: PointerEvent) => {
      if (e.buttons !== 0) return
      let cursor = ''
      const d = toolRef.current === 'cursor' && selRef.current !== null && !hideRef.current ? itemsRef.current.find((x) => x.id === selRef.current) : undefined
      if (d && !d.payload.locked) {
        const g = geo()
        const rect = cv.current?.getBoundingClientRect()
        const S = g ? d.payload.points.map((p) => toScreen(g, p)) : []
        if (g && rect && S.length > 0 && !S.some((p) => p === null)) {
          const plotW = rect.width - g.c.priceScale('right').width()
          const px = e.clientX - rect.left
          const py = e.clientY - rect.top
          const h = handlesFor(d.kind, S as Pt[], plotW).find((q) => Math.hypot(px - q.x, py - q.y) <= 12)
          if (h) cursor = h.cursor
          else if (!(e.target as HTMLElement | null)?.closest?.('.draw-chip, .draw-tools') && hitAt(e.clientX, e.clientY)?.id === d.id) cursor = 'move'
        }
      }
      if (host.style.cursor !== cursor) host.style.cursor = cursor
    }
    host.addEventListener('pointerdown', onDownCap, true)
    host.addEventListener('pointermove', onHover)
    return () => { host.removeEventListener('pointerdown', onDownCap, true); host.removeEventListener('pointermove', onHover); host.style.cursor = '' }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo])

  // chuột phải trên biểu đồ: menu ngữ cảnh kiểu TradingView (bản xử lý mới nhất nằm trong ctxHandler)
  useEffect(() => {
    const host = cv.current?.parentElement
    if (!host) return
    const onCtx = (e: MouseEvent) => ctxHandler.current(e)
    host.addEventListener('contextmenu', onCtx)
    return () => host.removeEventListener('contextmenu', onCtx)
  }, [])

  // đóng menu chuột phải khi bấm ra ngoài, cuộn, đổi cỡ cửa sổ hoặc nhấn Esc
  useEffect(() => {
    if (!menu) return
    const close = (e: Event) => { if (!(e.target as HTMLElement | null)?.closest?.('.ctx-menu')) setMenu(null) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null) }
    window.addEventListener('pointerdown', close, true)
    window.addEventListener('wheel', close, { passive: true, capture: true })
    window.addEventListener('resize', close)
    window.addEventListener('blur', close)
    window.addEventListener('keydown', esc)
    return () => {
      window.removeEventListener('pointerdown', close, true)
      window.removeEventListener('wheel', close, { capture: true } as EventListenerOptions)
      window.removeEventListener('resize', close)
      window.removeEventListener('blur', close)
      window.removeEventListener('keydown', esc)
    }
  }, [menu])

  // đóng menu nhóm công cụ khi bấm ra ngoài
  useEffect(() => {
    if (!openGrp) return
    const close = (e: PointerEvent) => { if (!(e.target as HTMLElement | null)?.closest?.('.draw-grp, .draw-fly')) setOpenGrp(null) }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [openGrp])

  const finishCreate = async (kind: DrawKind, payload: Drawing['payload']) => {
    pushHistory(itemsRef.current)
    try {
      const d = await createDrawing(symbol, kind, payload)
      setItems((l) => [...l, d])
      setSelected(d.id)
      setTool('cursor')
      setErr(null)
    } catch (x) { setErr(String(x)) }
  }

  const onDown = async (e: React.PointerEvent) => {
    activeInstance = inst.current
    const t = toolRef.current
    if (t === 'cursor') return
    if (t === 'erase') {
      const d = hit(e)
      if (d) await remove(d.id)
      return
    }
    const p = pointFromClient(e.clientX, e.clientY)
    if (!p) return
    if (t === 'brush') {
      brush.current = [p]
      try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId) } catch { /* không bắt buộc */ }
      return
    }
    const def = REGISTRY[t]
    const g0 = geo()
    const lastP = pending.current[pending.current.length - 1]
    if (g0 && lastP && def.min !== def.max) {
      // công cụ nhiều điểm: bỏ qua cú bấm trùng điểm trước (nửa sau của bấm đúp)
      const a = toScreen(g0, lastP); const b = toScreen(g0, p)
      if (a && b && Math.hypot(a.x - b.x, a.y - b.y) < 4) return
    }
    pending.current = [...pending.current, p]
    if (pending.current.length >= def.max) await completePending(t)
    redraw.current()
  }

  /** Hoàn tất hình đang vẽ dở: hỏi nội dung nếu là công cụ chữ, rồi lưu. */
  const completePending = async (t: DrawKind) => {
    const def = REGISTRY[t]
    if (pending.current.length < def.min) return
    const payload: Drawing['payload'] = { points: pending.current, color: COLOR }
    if (t === 'long' || t === 'short') payload.points = payload.points.map((p, i) => (i === 2 ? { ...p, time: payload.points[1].time } : p))
    if (def.ask) {
      const text = window.prompt('Nội dung (xuống dòng bằng \\n)')
      if (!text) { pending.current = []; redraw.current(); return }
      payload.text = text.replace(/\\n/g, '\n')
    }
    pending.current = []
    hover.current = null
    await finishCreate(t, payload)
  }

  completePendingRef.current = completePending

  const onMove = (e: React.PointerEvent) => {
    if (brush.current) {
      const p = pointFromClient(e.clientX, e.clientY, false)
      const g = geo()
      const last = brush.current[brush.current.length - 1]
      if (p && g) {
        const a = toScreen(g, last); const b = toScreen(g, p)
        if (a && b && Math.hypot(a.x - b.x, a.y - b.y) >= 3 && brush.current.length < REGISTRY.brush.max) { brush.current = [...brush.current, p]; redraw.current() }
      }
      return
    }
    if (pending.current.length > 0) { hover.current = pointFromClient(e.clientX, e.clientY); redraw.current() }
  }

  const onUp = async () => {
    const pts = brush.current
    if (!pts) return
    brush.current = null
    if (pts.length < 2) { redraw.current(); return }
    await finishCreate('brush', { points: pts, color: COLOR, width: 2 })
  }

  const clearAll = async () => {
    if (items.length === 0 || !window.confirm(`Xoá ${items.length} hình của ${symbol}?`)) return
    pushHistory(itemsRef.current)
    try { await clearDrawings(symbol); setItems([]); setSelected(null) } catch (x) { setErr(String(x)) }
  }

  /** Mở menu nhóm: vẽ qua portal ở body (không bị ô biểu đồ khác đè) và đặt cạnh nút, trong khung nhìn. */
  const openFly = (gr: Group, btn: HTMLElement) => {
    if (openGrp === gr) { setOpenGrp(null); return }
    const r = btn.getBoundingClientRect()
    const nItems = KINDS.filter((k) => REGISTRY[k].group === gr).length
    const h = Math.min(nItems * 31 + 40, window.innerHeight - 16)
    setFlyPos({ left: Math.min(r.right + 6, window.innerWidth - 206), top: Math.max(8, Math.min(r.top, window.innerHeight - h - 8)) })
    setOpenGrp(gr)
  }
  const toggleCollapsed = () => setCollapsed((v) => { const n = !v; try { localStorage.setItem('drawToolsCollapsed', n ? '1' : '0') } catch { /* bỏ qua */ } return n })

  const say = (msg: string) => { setToast(msg); window.setTimeout(() => setToast((t) => (t === msg ? null : t)), 2600) }

  ctxHandler.current = (e: MouseEvent) => {
    if ((e.target as HTMLElement | null)?.closest?.('.draw-tools, .draw-chip, .ctx-menu')) return
    e.preventDefault()
    // đang vẽ dở một hình: chuột phải là huỷ hình đó (như TradingView), chưa mở menu
    if (pending.current.length > 0 || brush.current) { pending.current = []; brush.current = null; hover.current = null; redraw.current(); return }
    const p = pointFromClient(e.clientX, e.clientY, false)
    if (!p) return
    const hitD = toolRef.current === 'cursor' ? hitAt(e.clientX, e.clientY) : null
    if (hitD) { setSelected(hitD.id); redraw.current() }
    setMenu({ x: e.clientX, y: e.clientY, price: p.price, time: p.time, hitId: hitD?.id ?? null })
  }

  const menuItems = (): ({ label: string; hint?: string; run: () => void; danger?: boolean } | 'sep')[] => {
    if (!menu) return []
    const pt: DrawPoint = { time: menu.time, price: menu.price }
    const priceTxt = fmtPrice(menu.price)
    const act = (fn: () => void | Promise<void>) => () => { setMenu(null); void fn() }
    const items: ({ label: string; hint?: string; run: () => void; danger?: boolean } | 'sep')[] = []
    const d = menu.hitId !== null ? itemsRef.current.find((x) => x.id === menu.hitId) : undefined
    if (d) {
      items.push({ label: d.payload.locked ? 'Mở khoá hình' : 'Khoá hình', run: act(() => patchSelected({ locked: !d.payload.locked }, true)) })
      items.push({ label: 'Nhân bản hình', run: act(() => clone()) })
      items.push({ label: 'Xoá hình', hint: 'Delete', danger: true, run: act(() => remove(d.id)) })
      items.push('sep')
    }
    items.push({
      label: `Sao chép giá ${priceTxt}`,
      run: act(async () => {
        try { await navigator.clipboard.writeText(String(Number(menu.price.toFixed(6)))); say(`Đã sao chép giá ${priceTxt}`) } catch { say('Không sao chép được (trình duyệt chặn clipboard)') }
      }),
    })
    items.push({
      label: `Thêm cảnh báo khi giá chạm ${priceTxt}`,
      run: act(async () => {
        try { await createAlert(symbol, { type: 'cross', level: Number(menu.price.toFixed(6)), dir: 'any', once: true }); say(`Đã thêm cảnh báo tại ${priceTxt} (xem ở mục Cảnh báo)`) } catch (x) { setErr(String(x)) }
      }),
    })
    items.push('sep')
    items.push({ label: `Vẽ đường ngang tại ${priceTxt}`, run: act(() => finishCreate('hline', { points: [pt], color: COLOR })) })
    items.push({ label: 'Vẽ đường dọc tại đây', run: act(() => finishCreate('vline', { points: [pt], color: COLOR })) })
    items.push({ label: 'Thêm nhãn giá tại đây', run: act(() => finishCreate('pricelabel', { points: [pt], color: COLOR })) })
    items.push({
      label: 'Thêm ghi chú tại đây…',
      run: act(async () => {
        const text = window.prompt('Nội dung ghi chú (xuống dòng bằng \\n)')
        if (text) await finishCreate('note', { points: [pt], color: COLOR, text: text.replace(/\\n/g, '\n') })
      }),
    })
    items.push('sep')
    items.push({ label: 'Thêm chỉ báo…', hint: 'I', run: act(() => { window.dispatchEvent(new CustomEvent('open-indicator-picker')) }) })
    items.push({
      label: 'Đặt lại khung nhìn',
      run: act(() => {
        const c = chart.current
        if (!c) return
        c.timeScale().resetTimeScale()
        c.timeScale().scrollToRealTime()
        candles.current?.priceScale().applyOptions({ autoScale: true })
      }),
    })
    items.push('sep')
    items.push({ label: magnet ? 'Tắt nam châm' : 'Bật nam châm (bắt vào giá nến)', run: act(() => setMagnet((v) => !v)) })
    items.push({ label: hideAll ? 'Hiện mọi hình vẽ' : 'Ẩn mọi hình vẽ', run: act(() => setHideAll((v) => !v)) })
    items.push({ label: `Xoá mọi hình vẽ của ${symbol}`, danger: true, run: act(() => clearAll()) })
    return items
  }

  const pick = (k: DrawKind) => {
    setTool(k); setOpenGrp(null)
    setLastTool((m) => ({ ...m, [REGISTRY[k].group]: k }))
  }

  const sel = items.find((x) => x.id === selected) ?? null
  const selDef = sel ? REGISTRY[sel.kind] : null
  const toolGroup = tool !== 'cursor' && tool !== 'erase' ? REGISTRY[tool].group : null

  return (
    <>
      <canvas
        ref={cv} className="draw-canvas" aria-hidden="true" data-tool={tool}
        style={{ pointerEvents: tool === 'cursor' ? 'none' : 'auto', cursor: tool === 'erase' ? 'pointer' : 'crosshair' }}
        onPointerDown={(e) => void onDown(e)}
        onPointerMove={onMove}
        onPointerUp={() => void onUp()}
        onDoubleClick={() => { const t = toolRef.current; if (t !== 'cursor' && t !== 'erase' && REGISTRY[t].min !== REGISTRY[t].max && t !== 'brush') void completePending(t) }}
      />
      {sel && selDef && chip && !hideAll && (
        <div className="draw-chip" style={{ left: chip.x, top: chip.y }} role="toolbar" aria-label="Thuộc tính hình đang chọn">
          {!selDef.ownColors && (
            <input type="color" title="Màu" aria-label="Màu" disabled={sel.payload.locked} value={sel.payload.color ?? COLOR} onChange={(e) => patchSelected({ color: e.target.value })} />
          )}
          <select title="Độ dày nét" aria-label="Độ dày nét" disabled={sel.payload.locked} value={String(sel.payload.width ?? 1.5)} onChange={(e) => patchSelected({ width: Number(e.target.value) }, true)}>
            {[1, 1.5, 2, 3, 4].map((w) => <option key={w} value={w}>{w}px</option>)}
          </select>
          <select title="Kiểu nét" aria-label="Kiểu nét" disabled={sel.payload.locked} value={sel.payload.dash ?? 'solid'} onChange={(e) => patchSelected({ dash: e.target.value as 'solid' | 'dash' | 'dot' }, true)}>
            <option value="solid">Liền</option><option value="dash">Đứt</option><option value="dot">Chấm</option>
          </select>
          <button title={sel.payload.locked ? 'Mở khoá hình' : 'Khoá hình (không kéo, không xoá được)'} aria-label="Khoá hình" aria-pressed={!!sel.payload.locked} onClick={() => patchSelected({ locked: !sel.payload.locked }, true)}><Icon node={ICONS[sel.payload.locked ? 'lock' : 'unlock']} /></button>
          <button title="Nhân bản hình" aria-label="Nhân bản hình" onClick={() => void clone()}><Icon node={ICONS.clone} /></button>
          <button className="del" title="Xoá hình này (Delete)" aria-label="Xoá hình đang chọn" disabled={sel.payload.locked} onClick={() => void remove(sel.id)}><Icon node={ICONS.clear} /></button>
        </div>
      )}
      {toast && <div className="draw-toast" role="status">{toast}</div>}
      {menu && createPortal(
        <div className="ctx-menu" role="menu" aria-label="Menu biểu đồ"
          style={{ left: Math.min(menu.x, window.innerWidth - 290), top: Math.max(8, Math.min(menu.y, window.innerHeight - 24 - menuItems().length * 31)) }}>
          {menuItems().map((it, i) => it === 'sep'
            ? <div key={`s${i}`} className="sep" role="separator" />
            : <button key={it.label} role="menuitem" className={it.danger ? 'danger' : ''} onClick={it.run}><span>{it.label}</span>{it.hint && <kbd>{it.hint}</kbd>}</button>)}
        </div>,
        document.body,
      )}
      <div className={collapsed ? 'draw-tools collapsed' : 'draw-tools'} role="toolbar" aria-label="Công cụ vẽ">
        <button title={collapsed ? 'Mở thanh công cụ vẽ' : 'Thu gọn thanh công cụ vẽ'} aria-label={collapsed ? 'Mở thanh công cụ vẽ' : 'Thu gọn thanh công cụ vẽ'} aria-expanded={!collapsed} className="fold" onClick={toggleCollapsed}>
          <Icon node={collapsed ? ICONS.pencil : ICONS.chevron} />
        </button>
        {!collapsed && <>
        <button title="Trỏ: di chuyển biểu đồ, bấm để chọn hình" aria-label="Trỏ" aria-pressed={tool === 'cursor'} className={tool === 'cursor' ? 'on' : ''} onClick={() => setTool('cursor')}><Icon node={ICONS.cursor} /></button>
        {GROUP_ORDER.map((gr) => {
          const kinds = KINDS.filter((k) => REGISTRY[k].group === gr)
          const cur = lastTool[gr]
          return (
            <div className="draw-grp" key={gr}>
              <button title={`${REGISTRY[cur].title}`} aria-label={REGISTRY[cur].label} aria-pressed={toolGroup === gr} className={toolGroup === gr ? 'on' : ''} onClick={() => pick(cur)}>
                <Icon node={REGISTRY[toolGroup === gr ? (tool as DrawKind) : cur].icon} />
              </button>
              {kinds.length > 1 && <button className="caret" title={`Thêm công cụ ${GROUP_LABEL[gr].toLowerCase()}`} aria-label={`Mở nhóm ${GROUP_LABEL[gr]}`} aria-expanded={openGrp === gr} onClick={(e) => openFly(gr, e.currentTarget.parentElement ?? e.currentTarget)}>▾</button>}
            </div>
          )
        })}
        <button title="Xoá: bấm vào hình để xoá" aria-label="Xoá" aria-pressed={tool === 'erase'} className={tool === 'erase' ? 'on' : ''} onClick={() => setTool('erase')}><Icon node={ICONS.erase} /></button>
        <span className="sep" aria-hidden="true" />
        <button title="Nam châm: bắt điểm vào giá mở, cao, thấp, đóng của nến" aria-label="Nam châm" aria-pressed={magnet} className={magnet ? 'on' : ''} onClick={() => setMagnet((v) => !v)}><Icon node={ICONS.magnet} /></button>
        <button title={hideAll ? 'Hiện mọi hình' : 'Ẩn mọi hình'} aria-label="Ẩn hiện hình" aria-pressed={hideAll} className={hideAll ? 'on' : ''} onClick={() => setHideAll((v) => !v)}><Icon node={ICONS[hideAll ? 'eyeoff' : 'eye']} /></button>
        <button title="Hoàn tác (Ctrl+Z)" aria-label="Hoàn tác" disabled={histLen.undo === 0} onClick={undo}><Icon node={ICONS.undo} /></button>
        <button title="Làm lại (Ctrl+Y)" aria-label="Làm lại" disabled={histLen.redo === 0} onClick={redo}><Icon node={ICONS.redo} /></button>
        <button title="Xoá mọi hình của symbol này" aria-label="Xoá mọi hình" onClick={() => void clearAll()} disabled={items.length === 0}><Icon node={ICONS.clear} /></button>
        </>}
        {err && <span className="bad" role="alert" title={err}>{err.length > 40 ? `${err.slice(0, 40)}…` : err}</span>}
      </div>
      {openGrp && flyPos && !collapsed && createPortal(
        <div className="draw-fly" role="menu" aria-label={GROUP_LABEL[openGrp]} style={{ left: flyPos.left, top: flyPos.top, maxHeight: window.innerHeight - flyPos.top - 8 }}>
          <div className="fly-title">{GROUP_LABEL[openGrp]}</div>
          {KINDS.filter((k) => REGISTRY[k].group === openGrp).map((k) => (
            <button key={k} role="menuitem" title={REGISTRY[k].title} className={tool === k ? 'on' : ''} onClick={() => pick(k)}>
              <Icon node={REGISTRY[k].icon} /><span>{REGISTRY[k].label}</span>
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  )
}
