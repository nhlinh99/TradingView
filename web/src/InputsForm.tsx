import { useEffect, useMemo, useRef, useState } from 'react'
import type { PineInput } from './api'

type Props = {
  defs: PineInput[]
  values: Record<string, unknown>
  onChange: (title: string, value: unknown) => void
  onReset?: () => void
}

const NUMERIC = new Set(['int', 'float'])

/** Một ô nhập có gửi giá trị đi sau 450 ms không gõ nữa (số, chữ), để không chạy lại script ở từng phím bấm. */
function Debounced({ value, onCommit, ...rest }: { value: string; onCommit: (v: string) => void } & React.InputHTMLAttributes<HTMLInputElement>) {
  const [v, setV] = useState(value)
  const t = useRef<number>(0)
  useEffect(() => setV(value), [value])
  return (
    <input {...rest} value={v}
      onChange={(e) => { setV(e.target.value); window.clearTimeout(t.current); const nv = e.target.value; t.current = window.setTimeout(() => onCommit(nv), 450) }}
      onBlur={() => { window.clearTimeout(t.current); if (v !== value) onCommit(v) }}
      onKeyDown={(e) => { if (e.key === 'Enter') { window.clearTimeout(t.current); onCommit(v) } }} />
  )
}

function Field({ d, value, onChange }: { d: PineInput; value: unknown; onChange: (v: unknown) => void }) {
  const cur = value ?? d.default
  if (d.type === 'bool') {
    return <input type="checkbox" role="switch" checked={Boolean(cur)} onChange={(e) => onChange(e.target.checked)} aria-label={d.title} />
  }
  if (d.options && d.options.length > 0) {
    return (
      <select value={String(cur ?? '')} onChange={(e) => onChange(NUMERIC.has(d.type) ? Number(e.target.value) : e.target.value)} aria-label={d.title}>
        {d.options.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
      </select>
    )
  }
  if (d.type === 'source') {
    return (
      <select value={String(cur ?? 'close')} onChange={(e) => onChange(e.target.value)} aria-label={d.title}>
        {['close', 'open', 'high', 'low', 'hl2', 'hlc3', 'ohlc4', 'hlcc4', 'volume'].map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    )
  }
  if (d.type === 'color' && typeof cur === 'string' && /^#[0-9a-fA-F]{6}/.test(cur)) {
    return <input type="color" value={cur.slice(0, 7)} onChange={(e) => onChange(e.target.value.toUpperCase())} aria-label={d.title} />
  }
  if (NUMERIC.has(d.type)) {
    const min = d.minval; const max = d.maxval
    const step = d.type === 'int' ? 1 : (d.step ?? 0.1)
    return (
      <span className="numfield">
        {min !== undefined && max !== undefined && max - min <= 400 && (
          <input type="range" min={min} max={max} step={step} value={Number(cur)} onChange={(e) => onChange(Number(e.target.value))} aria-label={`${d.title} (thanh trượt)`} />
        )}
        <Debounced type="number" value={String(cur ?? '')} min={min} max={max} step={step} aria-label={d.title}
          onCommit={(v) => { const n = Number(v); if (Number.isFinite(n)) onChange(n) }} />
      </span>
    )
  }
  return <Debounced type="text" value={String(cur ?? '')} aria-label={d.title} onCommit={onChange} />
}

/** Form tham số tự sinh từ các lời gọi input.* của script: nhóm theo `group`, có tooltip, thanh trượt khi có min/max, ô tìm khi nhiều tham số. */
export default function InputsForm({ defs, values, onChange, onReset }: Props) {
  const [q, setQ] = useState('')
  const groups = useMemo(() => {
    const m = new Map<string, PineInput[]>()
    const needle = q.trim().toLowerCase()
    for (const d of defs) {
      if (needle && !d.title.toLowerCase().includes(needle)) continue
      const g = (d.group ?? 'Chung').replace(/^\W+/u, '').trim() || 'Chung'
      m.set(g, [...(m.get(g) ?? []), d])
    }
    return [...m.entries()]
  }, [defs, q])
  const changed = defs.filter((d) => d.title in values).length
  if (defs.length === 0) return <p className="mute">Script này không có tham số.</p>
  return (
    <div className="inputsform">
      {defs.length > 10 && <input className="isearch" type="search" placeholder={`Tìm trong ${defs.length} tham số...`} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Tìm tham số" />}
      {changed > 0 && onReset && <button className="linkbtn" onClick={onReset}>Đặt lại {changed} tham số đã đổi</button>}
      {groups.length === 0 && <p className="mute">Không có tham số nào khớp.</p>}
      {groups.map(([g, items]) => (
        <details key={g} open={groups.length <= 2 || g === groups[0][0]}>
          <summary>{g} <span className="mute">({items.length})</span></summary>
          {items.map((d) => (
            <div className="irow" key={d.title} title={d.tooltip ?? undefined}>
              <label>
                <span className={`ilabel ${d.title in values ? 'changed' : ''}`}>{d.title.trim()}</span>
                <Field d={d} value={values[d.title]} onChange={(v) => onChange(d.title, v)} />
              </label>
            </div>
          ))}
        </details>
      ))}
    </div>
  )
}
