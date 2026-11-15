import { useEffect, useRef, useState } from 'react'
import Icon from './Icons'
import InputsForm from './InputsForm'
import type { Indicator, RunState } from './indicators'

type Props = {
  list: Indicator[]
  runs: Record<string, RunState>
  onToggle: (id: string) => void
  onRemove: (id: string) => void
  onInput: (id: string, title: string, value: unknown) => void
  onResetInputs: (id: string) => void
  onEdit: (id: string) => void
  onAdd: () => void
}

const dot = (s: RunState | undefined) => (s?.status === 'loading' ? 'loading' : s?.status === 'error' ? 'error' : s?.status === 'ok' ? 'ok' : 'idle')

/**
 * Chú giải chỉ báo trên biểu đồ (như TradingView): mỗi chỉ báo một dòng có nút ẩn/hiện, cài đặt, sửa mã, xoá.
 * Từ 5 chỉ báo trở lên tự thu gọn thành một dòng tóm tắt để không che biểu đồ.
 */
export default function IndicatorLegend({ list, runs, onToggle, onRemove, onInput, onResetInputs, onEdit, onAdd }: Props) {
  const [open, setOpen] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(null) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(null) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  if (list.length === 0) return null
  const shown = collapsed ? [] : list
  const cur = open ? list.find((i) => i.id === open) : undefined
  const res = cur ? runs[cur.id] : undefined

  return (
    <div className="indlegend" ref={box}>
      <div className="indhead">
        <button className="linkbtn" onClick={() => setCollapsed((c) => !c)} aria-expanded={!collapsed}>
          <span className={collapsed ? 'chev' : 'chev open'} aria-hidden="true"><Icon name="chevron" size={11} /></span> {list.length} chỉ báo
        </button>
        <button className="linkbtn" onClick={onAdd} title="Thêm chỉ báo (phím I)"><Icon name="plus" size={11} /> Thêm</button>
      </div>
      {shown.map((ind) => {
        const st = runs[ind.id]
        return (
          <div key={ind.id} className={`indrow ${ind.visible ? '' : 'off'}`}>
            <span className={`sdot ${dot(st)}`} title={st?.status === 'error' ? st.error?.message : st?.status === 'loading' ? 'Đang chạy...' : st?.status === 'ok' ? 'Đã chạy' : ''} />
            <span className="indname" title={ind.name}>{ind.name}</span>
            <button aria-label={`${ind.visible ? 'Ẩn' : 'Hiện'} ${ind.name}`} title={ind.visible ? 'Ẩn' : 'Hiện'} onClick={() => onToggle(ind.id)}><Icon name={ind.visible ? 'eye' : 'eyeoff'} size={14} /></button>
            <button aria-label={`Cài đặt ${ind.name}`} title="Cài đặt" aria-expanded={open === ind.id} onClick={() => setOpen(open === ind.id ? null : ind.id)}><Icon name="gear" size={14} /></button>
            <button aria-label={`Sửa mã ${ind.name}`} title="Sửa mã" onClick={() => onEdit(ind.id)}><Icon name="code" size={14} /></button>
            <button aria-label={`Xoá ${ind.name}`} title="Xoá khỏi biểu đồ" onClick={() => onRemove(ind.id)}><Icon name="x" size={13} /></button>
          </div>
        )
      })}
      {cur && (
        <div className="indpop" role="dialog" aria-label={`Cài đặt ${cur.name}`}>
          <header><b>{cur.name}</b><button className="linkbtn" onClick={() => setOpen(null)} aria-label="Đóng"><Icon name="x" size={13} /></button></header>
          {res?.status === 'error' && <p className="status bad" role="alert">{res.error?.line ? `Dòng ${res.error.line}: ` : ''}{res.error?.message}</p>}
          {res?.status === 'loading' && !res.result && <p className="mute">Đang chạy...</p>}
          <InputsForm defs={res?.result?.inputs ?? []} values={cur.inputs} onChange={(t, v) => onInput(cur.id, t, v)} onReset={() => onResetInputs(cur.id)} />
        </div>
      )}
    </div>
  )
}
