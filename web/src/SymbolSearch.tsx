import { useEffect, useMemo, useRef, useState } from 'react'
import type { SymbolInfo } from './api'

type Props = {
  all: SymbolInfo[]
  watch: string[]
  current: string
  onPick: (symbol: string) => void
  onClose: () => void
}

const KIND: Record<string, string> = { vn: 'VN100 · HOSE', tvc: 'TradingView · TVC', binance_futures: 'Binance Futures' }

const INDICES = ['VNINDEX', 'VN30']

/** Hộp tìm symbol (mở bằng / hoặc Ctrl+K): gõ để lọc, mũi tên để chọn, Enter để mở; mã chưa có trong danh sách theo dõi sẽ được thêm. */
export default function SymbolSearch({ all, watch, current, onPick, onClose }: Props) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { input.current?.focus() }, [])

  const list = useMemo(() => {
    const t = q.trim().toUpperCase()
    const score = (s: SymbolInfo) => {
      if (!t) return watch.includes(s.symbol) ? 1 : 2
      if (s.symbol === t) return 0
      if (s.symbol.startsWith(t)) return 1
      if (s.symbol.includes(t)) return 2
      return 9
    }
    return all.map((s) => ({ s, k: score(s) })).filter((x) => x.k < 9).sort((a, b) => a.k - b.k || a.s.symbol.localeCompare(b.s.symbol)).slice(0, 60).map((x) => x.s)
  }, [all, watch, q])

  useEffect(() => { setSel(0) }, [q])

  const key = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel((i) => Math.min(list.length - 1, i + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((i) => Math.max(0, i - 1)) }
    else if (e.key === 'Enter' && list[sel]) { e.preventDefault(); onPick(list[sel].symbol) }
    else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }

  return (
    <div className="modal" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="palette" role="dialog" aria-label="Tìm symbol" onKeyDown={key}>
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Gõ mã: BTC, XAU, VNM, FPT..." aria-label="Tìm symbol"
          role="combobox" aria-expanded="true" aria-controls="sym-results" aria-activedescendant={list[sel] ? `sym-${list[sel].symbol}` : undefined} />
        <ul id="sym-results" role="listbox">
          {list.length === 0 && <li className="none">Không có mã nào khớp "{q}".</li>}
          {list.map((s, i) => (
            <li key={s.symbol} id={`sym-${s.symbol}`} role="option" aria-selected={i === sel} className={i === sel ? 'on' : ''}
              onMouseEnter={() => setSel(i)} onMouseDown={(e) => { e.preventDefault(); onPick(s.symbol) }}>
              <b>{s.symbol}</b>
              <span className="mute">{INDICES.includes(s.symbol) ? 'Chỉ số · HOSE' : KIND[s.source ?? ''] ?? s.source ?? ''}</span>
              <span className="tagrow">
                {s.symbol === current && <em>đang xem</em>}
                {watch.includes(s.symbol) ? <em>theo dõi</em> : <em className="add">+ thêm</em>}
              </span>
            </li>
          ))}
        </ul>
        <p className="hint">↑↓ chọn · Enter mở · Esc đóng</p>
      </div>
    </div>
  )
}
