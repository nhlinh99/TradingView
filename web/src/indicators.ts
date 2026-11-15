import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchPineExamples, runPine, type BacktestOpts, type PineResult } from './api'
import { parseColor, rgba } from './colors'

export type Backtest = { capital: string; fee: string; slip: string; from: string; to: string }
export type Indicator = {
  id: string
  name: string
  source: string
  inputs: Record<string, unknown>   // giá trị người dùng đã chỉnh, theo tiêu đề của input
  visible: boolean
  bt: Backtest
  style?: Record<string, PlotStyle>   // tuỳ chỉnh kiểu dáng theo phần tử: plot:0, hline:1, shape:0, fill:0, bg:0, candle:0
  tfs?: string[]                      // chỉ hiện ở các khung này (bỏ trống: mọi khung)
  scaleLabels?: boolean               // hiện nhãn giá trị cuối trên thang giá
}
export type Dash = 'solid' | 'dashed' | 'dotted'
export type PlotStyle = { visible?: boolean; color?: string; opacity?: number; width?: number; dash?: Dash }
export type RunState = { status: 'idle' | 'loading' | 'ok' | 'error'; result?: PineResult; error?: { message: string; line?: number } }
export type LibraryScript = { name: string; source: string; mine: boolean }

export const DEFAULT_BT: Backtest = { capital: '10000', fee: '0.05', slip: '0', from: '', to: '' }
export const NEW_SCRIPT = `//@version=5
indicator("Chỉ báo mới", overlay=true)
len = input.int(20, "Length", minval=1)
plot(ta.sma(close, len), "SMA", color=color.orange)
`

export const isStrategy = (src: string) => /\bstrategy\s*\(/.test(src)

/** Tên hiển thị lấy từ indicator("...") hoặc strategy("...") hoặc study("..."). */
export function scriptName(src: string): string {
  const m = /\b(?:indicator|strategy|study)\s*\(\s*(?:title\s*=\s*)?(["'])(.*?)\1/s.exec(src)
  return (m?.[2] ?? 'Script').trim() || 'Script'
}

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}
function save(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* bị chặn: bỏ qua */ }
}

export function btOpts(ind: Indicator): BacktestOpts {
  if (!isStrategy(ind.source)) return {}
  const o: BacktestOpts = { commission_pct: Number(ind.bt.fee) || 0, slippage_ticks: Number(ind.bt.slip) || 0, initial_capital: Number(ind.bt.capital) || 10000 }
  if (ind.bt.from) o.from_ms = Date.parse(ind.bt.from + 'T00:00:00Z')
  if (ind.bt.to) o.to_ms = Date.parse(ind.bt.to + 'T00:00:00Z') + 86_400_000
  return o
}

const uid = () => Math.random().toString(36).slice(2, 9)

/**
 * Quản lý nhiều chỉ báo Pine cùng lúc: danh sách (lưu trong trình duyệt), kết quả chạy của từng chỉ báo, thư viện script.
 * Mọi chỉ báo đang hiện được chạy lại khi đổi symbol hoặc khung; đổi tham số hay mã chỉ chạy lại chính chỉ báo đó.
 */
export function useIndicators(symbol: string, tf: string) {
  const [list, setList] = useState<Indicator[]>(() => load<Indicator[]>('ind.list', []))
  const [runs, setRuns] = useState<Record<string, RunState>>({})
  const [lib, setLib] = useState<{ name: string; source: string }[]>(() => load('ind.lib', []))
  const [fav, setFav] = useState<string[]>(() => load<string[]>('ind.fav', []))
  const [examples, setExamples] = useState<{ name: string; source: string }[]>([])
  const token = useRef<Record<string, number>>({})
  const ctx = useRef({ symbol, tf })
  ctx.current = { symbol, tf }

  useEffect(() => { fetchPineExamples().then(setExamples).catch(() => setExamples([])) }, [])
  useEffect(() => save('ind.list', list), [list])
  useEffect(() => save('ind.lib', lib), [lib])
  useEffect(() => save('ind.fav', fav), [fav])

  const run = useCallback(async (ind: Indicator) => {
    const my = (token.current[ind.id] = (token.current[ind.id] ?? 0) + 1)
    setRuns((r) => ({ ...r, [ind.id]: { ...r[ind.id], status: 'loading' } }))
    try {
      const res = await runPine(ind.source, ctx.current.symbol, ctx.current.tf, ind.inputs, btOpts(ind))
      if (token.current[ind.id] === my) setRuns((r) => ({ ...r, [ind.id]: { status: 'ok', result: res } }))
    } catch (e) {
      const d = (e as { detail?: { message?: string; line?: number } }).detail
      if (token.current[ind.id] === my) setRuns((r) => ({ ...r, [ind.id]: { status: 'error', error: { message: d?.message ?? String(e), line: d?.line } } }))
    }
  }, [])

  // đổi symbol hoặc khung: kết quả cũ không còn đúng, chạy lại mọi chỉ báo đang hiện
  const listRef = useRef(list)
  listRef.current = list
  useEffect(() => {
    setRuns({})
    for (const ind of listRef.current) if (ind.visible) void run(ind)
  }, [symbol, tf, run])

  const add = useCallback((source: string, name?: string): string => {
    const ind: Indicator = { id: uid(), name: name ?? scriptName(source), source, inputs: {}, visible: true, bt: { ...DEFAULT_BT } }
    setList((l) => [...l, ind])
    void run(ind)
    return ind.id
  }, [run])

  const update = useCallback((id: string, patch: Partial<Indicator>, rerun = true) => {
    const cur = listRef.current.find((x) => x.id === id)
    if (!cur) return
    const next = { ...cur, ...patch }
    if (patch.source !== undefined && patch.name === undefined) next.name = scriptName(next.source)
    setList((l) => l.map((x) => (x.id === id ? next : x)))
    if (rerun && next.visible) void run(next)
  }, [run])

  const duplicate = useCallback((id: string): string | null => {
    const cur = listRef.current.find((x) => x.id === id)
    if (!cur) return null
    const copy: Indicator = { ...cur, id: uid(), inputs: { ...cur.inputs }, style: cur.style ? { ...cur.style } : undefined, bt: { ...cur.bt } }
    setList((l) => { const i = l.findIndex((x) => x.id === id); return [...l.slice(0, i + 1), copy, ...l.slice(i + 1)] })
    void run(copy)
    return copy.id
  }, [run])

  const toggleFav = useCallback((name: string) => setFav((f) => (f.includes(name) ? f.filter((x) => x !== name) : [...f, name])), [])

  const toggle = useCallback((id: string) => {
    const cur = listRef.current.find((x) => x.id === id)
    if (!cur) return
    setList((l) => l.map((x) => (x.id === id ? { ...x, visible: !x.visible } : x)))
    if (!cur.visible && !runs[id]?.result) void run({ ...cur, visible: true })
  }, [run, runs])

  const remove = useCallback((id: string) => {
    setList((l) => l.filter((x) => x.id !== id))
    setRuns((r) => { const n = { ...r }; delete n[id]; return n })
  }, [])

  const saveToLibrary = useCallback((name: string, source: string) => {
    setLib((l) => [...l.filter((x) => x.name !== name), { name, source }])
  }, [])
  const removeFromLibrary = useCallback((name: string) => setLib((l) => l.filter((x) => x.name !== name)), [])

  const library: LibraryScript[] = [
    ...lib.map((x) => ({ ...x, mine: true })),
    ...examples.map((x) => ({ name: x.name, source: x.source, mine: false })),
  ]
  return { list, runs, library, fav, toggleFav, add, update, duplicate, toggle, remove, run, saveToLibrary, removeFromLibrary }
}

/** Màu mới theo tuỳ chỉnh: giữ ô trống (không vẽ), đổi mọi ô có màu sang màu đã chọn. Độ đục mặc định lấy từ màu gốc. */
function recolor(colors: (string | null)[], st: PlotStyle): (string | null)[] {
  if (!st.color) return colors
  const baseA = parseColor(colors.find((c) => c))?.a ?? 1
  const col = rgba(st.color, st.opacity ?? baseA)
  return colors.map((c) => (c ? col : c))
}

const cache = new WeakMap<PineResult, { key: string; out: PineResult }>()

/** Áp tuỳ chỉnh kiểu dáng của người dùng lên kết quả chạy. Có nhớ đệm để không dựng lại khi không đổi, tránh vẽ lại cả biểu đồ. */
export function styledResult(res: PineResult, ind: Pick<Indicator, 'style' | 'scaleLabels'>): PineResult {
  const style = ind.style ?? {}
  const key = JSON.stringify([style, !!ind.scaleLabels])
  const hit = cache.get(res)
  if (hit && hit.key === key) return hit.out
  if (Object.keys(style).length === 0 && !ind.scaleLabels) { cache.set(res, { key, out: res }); return res }
  const g = (k: string): PlotStyle => style[k] ?? {}
  const out: PineResult = {
    ...res,
    scaleLabels: !!ind.scaleLabels,
    plots: res.plots.map((p, i) => {
      const s = g(`plot:${i}`)
      return { ...p, colors: recolor(p.colors, s), linewidth: s.width ?? p.linewidth, dash: s.dash ?? p.dash, hidden: s.visible === false }
    }),
    hlines: res.hlines.map((h, i) => {
      const s = g(`hline:${i}`)
      const c = s.color ? rgba(s.color, s.opacity ?? parseColor(h.color)?.a ?? 1) : h.color
      return { ...h, color: c, dash: s.dash ?? h.dash, width: s.width ?? h.width, hidden: s.visible === false }
    }),
    shapes: res.shapes.map((sh, i) => { const s = g(`shape:${i}`); return { ...sh, colors: recolor(sh.colors, s), hidden: s.visible === false } }),
    bgcolors: res.bgcolors.map((b, i) => { const s = g(`bg:${i}`); return { ...b, colors: recolor(b.colors, s), hidden: s.visible === false } }),
    fills: res.fills?.map((f, i) => { const s = g(`fill:${i}`); return { ...f, colors: recolor(f.colors, s), hidden: s.visible === false } }),
    candles: res.candles?.filter((_, i) => g(`candle:${i}`).visible !== false),
  }
  cache.set(res, { key, out })
  return out
}

/** Kết quả của các chỉ báo đang hiện ở khung `tf`, theo thứ tự thêm vào, đã áp kiểu dáng, để vẽ lên biểu đồ. */
export function visibleResults(list: Indicator[], runs: Record<string, RunState>, tf?: string): { id: string; result: PineResult }[] {
  return list.flatMap((i) => {
    const r = runs[i.id]?.result
    if (!i.visible || !r) return []
    if (tf && i.tfs && i.tfs.length > 0 && !i.tfs.includes(tf)) return []
    return [{ id: i.id, result: styledResult(r, i) }]
  })
}
