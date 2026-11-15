import { useEffect, useRef, useState } from 'react'
import type { PineResult } from './api'
import Icon from './Icons'
import IndicatorSettings from './IndicatorSettings'
import type { Indicator, RunState } from './indicators'

type Props = {
  list: Indicator[]
  runs: Record<string, RunState>
  tf: string
  onToggle: (id: string) => void
  onRemove: (id: string) => void
  onPatch: (id: string, patch: Partial<Indicator>, rerun?: boolean) => void
  onEdit: (id: string) => void
  onAdd: () => void
  onDuplicate: (id: string) => void
}

const dot = (s: RunState | undefined) => (s?.status === 'loading' ? 'loading' : s?.status === 'error' ? 'error' : s?.status === 'ok' ? 'ok' : 'idle')
const hiddenAt = (i: Indicator, tf: string) => !!(i.tfs && i.tfs.length > 0 && !i.tfs.includes(tf))

const fmt = (v: number) => {
  const a = Math.abs(v)
  if (a >= 1e9) return (v / 1e9).toFixed(2) + 'B'
  if (a >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (a >= 1e4) return (v / 1e3).toFixed(2) + 'K'
  return a >= 100 ? v.toFixed(2) : a >= 1 ? v.toFixed(3) : v.toPrecision(3)
}

/** Giá trị cuối của các đường vẽ, tô theo màu đường (như dòng giá trị trong chú giải của TradingView). Tối đa 4 giá trị. */
function lastValues(r: PineResult | undefined): { text: string; color: string }[] {
  if (!r || r.plots.length === 0) return []
  const last = r.times.length - 1
  const out: { text: string; color: string }[] = []
  for (const p of r.plots) {
    if (out.length >= 4) break
    const v = p.values[last]
    if (v === null || v === undefined || !Number.isFinite(v)) continue
    out.push({ text: fmt(v), color: p.colors[last] ?? p.colors.find((c) => c) ?? 'currentColor' })
  }
  return out
}

/** Vài tham số đầu (số, chữ, nguồn giá) viết cạnh tên, ví dụ "EMA 9 close". */
function paramSummary(ind: Indicator, r: PineResult | undefined): string {
  if (!r) return ''
  return r.inputs
    .filter((d) => ['int', 'float', 'source', 'string'].includes(d.type))
    .slice(0, 3)
    .map((d) => String(ind.inputs[d.title] ?? d.default ?? ''))
    .filter((s) => s !== '' && s.length <= 12)
    .join(' ')
}

/**
 * Chú giải chỉ báo trên biểu đồ. Mỗi dòng: tên, tham số, giá trị cuối. Rê chuột để hiện nút Ẩn, Cài đặt, Sửa mã, Xoá và menu Thêm (nhân bản).
 * Nhấp đúp vào tên để mở Cài đặt. Từ nhiều chỉ báo trở lên có thể thu gọn.
 */
export default function IndicatorLegend({ list, runs, tf, onToggle, onRemove, onPatch, onEdit, onAdd, onDuplicate }: Props) {
  const [settings, setSettings] = useState<string | null>(null)
  const [menu, setMenu] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!menu) return
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setMenu(null) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [menu])
  if (list.length === 0) return null
  const cur = settings ? list.find((i) => i.id === settings) : undefined

  return (
    <div className="indlegend" ref={box}>
      <div className="indhead">
        <button className="linkbtn" onClick={() => setCollapsed((c) => !c)} aria-expanded={!collapsed}>
          <span className={collapsed ? 'chev' : 'chev open'} aria-hidden="true"><Icon name="chevron" size={11} /></span> {list.length} chỉ báo
        </button>
        <button className="linkbtn" onClick={onAdd} title="Thêm chỉ báo (phím I)"><Icon name="plus" size={11} /> Thêm</button>
      </div>
      {!collapsed && list.map((ind) => {
        const st = runs[ind.id]
        const hid = hiddenAt(ind, tf)
        const vals = lastValues(st?.result)
        const sum = paramSummary(ind, st?.result)
        return (
          <div key={ind.id} className={`indrow ${ind.visible && !hid ? '' : 'off'}`} title={hid ? `Đang ẩn ở khung ${tf}` : undefined}>
            <span className={`sdot ${dot(st)}`} title={st?.status === 'error' ? st.error?.message : st?.status === 'loading' ? 'Đang chạy...' : st?.status === 'ok' ? 'Đã chạy' : ''} />
            <span className="indname" title={`${ind.name} (nhấp đúp để mở cài đặt)`} onDoubleClick={() => setSettings(ind.id)}>
              {ind.name}
              {sum && <span className="indsum"> {sum}</span>}
              {vals.map((v, i) => <span key={i} className="indval" style={{ color: v.color }}>{v.text}</span>)}
              {st?.status === 'error' && <span className="inderr"> lỗi</span>}
            </span>
            <span className="indbtns">
              <button aria-label={`${ind.visible ? 'Ẩn' : 'Hiện'} ${ind.name}`} title={ind.visible ? 'Ẩn' : 'Hiện'} onClick={() => onToggle(ind.id)}><Icon name={ind.visible ? 'eye' : 'eyeoff'} size={14} /></button>
              <button aria-label={`Cài đặt ${ind.name}`} title="Cài đặt" onClick={() => setSettings(ind.id)}><Icon name="gear" size={14} /></button>
              <button aria-label={`Sửa mã ${ind.name}`} title="Sửa mã" onClick={() => onEdit(ind.id)}><Icon name="code" size={14} /></button>
              <button aria-label={`Xoá ${ind.name}`} title="Xoá khỏi biểu đồ" onClick={() => onRemove(ind.id)}><Icon name="x" size={13} /></button>
              <button aria-label={`Thêm tuỳ chọn cho ${ind.name}`} aria-expanded={menu === ind.id} aria-haspopup="menu" title="Thêm" onClick={() => setMenu(menu === ind.id ? null : ind.id)}>⋯</button>
            </span>
            {menu === ind.id && (
              <div className="indmenu" role="menu">
                <button role="menuitem" onClick={() => { onDuplicate(ind.id); setMenu(null) }}>Nhân bản</button>
                <button role="menuitem" onClick={() => { setSettings(ind.id); setMenu(null) }}>Cài đặt...</button>
                <button role="menuitem" onClick={() => { onEdit(ind.id); setMenu(null) }}>Sửa mã nguồn</button>
                <button role="menuitem" className="danger" onClick={() => { onRemove(ind.id); setMenu(null) }}>Xoá khỏi biểu đồ</button>
              </div>
            )}
          </div>
        )
      })}
      {cur && <IndicatorSettings ind={cur} run={runs[cur.id]} onPatch={(p, rerun) => onPatch(cur.id, p, rerun)} onClose={() => setSettings(null)} />}
    </div>
  )
}
