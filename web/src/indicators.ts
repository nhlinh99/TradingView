import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchPineExamples, runPine, type BacktestOpts, type PineResult } from './api'

export type Backtest = { capital: string; fee: string; slip: string; from: string; to: string }
export type Indicator = {
  id: string
  name: string
  source: string
  inputs: Record<string, unknown>   // giá trị người dùng đã chỉnh, theo tiêu đề của input
  visible: boolean
  bt: Backtest
}
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
  const [examples, setExamples] = useState<{ name: string; source: string }[]>([])
  const token = useRef<Record<string, number>>({})
  const ctx = useRef({ symbol, tf })
  ctx.current = { symbol, tf }

  useEffect(() => { fetchPineExamples().then(setExamples).catch(() => setExamples([])) }, [])
  useEffect(() => save('ind.list', list), [list])
  useEffect(() => save('ind.lib', lib), [lib])

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
  return { list, runs, library, add, update, toggle, remove, run, saveToLibrary, removeFromLibrary }
}

/** Kết quả của các chỉ báo đang hiện, theo thứ tự thêm vào, để vẽ lên biểu đồ. */
export function visibleResults(list: Indicator[], runs: Record<string, RunState>): { id: string; result: PineResult }[] {
  return list.flatMap((i) => (i.visible && runs[i.id]?.result ? [{ id: i.id, result: runs[i.id].result as PineResult }] : []))
}
