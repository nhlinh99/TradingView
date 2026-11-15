import { useState } from 'react'
import type { PineResult } from './api'
import { PALETTE, parseColor, rgba } from './colors'
import { TIMEFRAMES } from './logic'
import type { Dash, Indicator, PlotStyle } from './indicators'

type Patch = (patch: Partial<Indicator>) => void
type Props = { ind: Indicator; result: PineResult | undefined; onPatch: Patch }

const WIDTHS = [1, 2, 3, 4]
const DASHES: { id: Dash; label: string }[] = [{ id: 'solid', label: 'Liền' }, { id: 'dashed', label: 'Gạch' }, { id: 'dotted', label: 'Chấm' }]

type Row = { key: string; title: string; base: string | null; width?: number; dash?: Dash; kind: 'line' | 'fill' | 'mark' }

/** Phần tử có thể chỉnh của một chỉ báo, lấy từ kết quả chạy: màu gốc là màu script đặt (màu đầu tiên khác rỗng). */
function rowsOf(r: PineResult): { group: string; rows: Row[] }[] {
  const first = (cs: (string | null)[]) => cs.find((c) => c) ?? null
  const groups = [
    { group: 'Đường và cột', rows: r.plots.map((p, i): Row => ({ key: `plot:${i}`, title: p.title || `Plot ${i + 1}`, base: first(p.colors), width: p.linewidth, kind: 'line' })) },
    { group: 'Đường ngang', rows: r.hlines.map((h, i): Row => ({ key: `hline:${i}`, title: h.title || `Mức ${h.price ?? ''}`, base: h.color, width: 1, dash: 'dashed', kind: 'line' })) },
    { group: 'Tín hiệu', rows: r.shapes.map((s, i): Row => ({ key: `shape:${i}`, title: s.title || `Tín hiệu ${i + 1}`, base: first(s.colors), kind: 'mark' })) },
    { group: 'Tô giữa hai đường', rows: (r.fills ?? []).map((f, i): Row => ({ key: `fill:${i}`, title: f.title || `Vùng ${i + 1}`, base: first(f.colors), kind: 'fill' })) },
    { group: 'Tô nền', rows: r.bgcolors.map((b, i): Row => ({ key: `bg:${i}`, title: `Nền ${i + 1}`, base: first(b.colors), kind: 'fill' })) },
    { group: 'Nến vẽ thêm', rows: (r.candles ?? []).map((c, i): Row => ({ key: `candle:${i}`, title: c.title || `Nến ${i + 1}`, base: null, kind: 'mark' })) },
  ]
  return groups.filter((g) => g.rows.length > 0)
}

function ColorPanel({ base, st, onChange }: { base: string | null; st: PlotStyle; onChange: (p: PlotStyle) => void }) {
  const cur = parseColor(st.color) ?? parseColor(base) ?? { hex: '#2962FF', a: 1 }
  const opacity = st.opacity ?? (st.color ? 1 : cur.a)
  const set = (hex: string) => onChange({ ...st, color: hex, opacity: st.opacity ?? cur.a })
  return (
    <div className="clrpanel">
      <div className="swatches" role="listbox" aria-label="Bảng màu">
        {PALETTE.map((c) => (
          <button key={c} role="option" aria-selected={cur.hex === c} className={cur.hex === c ? 'on' : ''} style={{ background: c }} title={c} aria-label={c} onClick={() => set(c)} />
        ))}
      </div>
      <div className="clrrow">
        <label>Màu tuỳ ý <input type="color" value={cur.hex.toLowerCase()} onChange={(e) => set(e.target.value.toUpperCase())} /></label>
        <label className="op">Độ đục
          <input type="range" min={0} max={100} value={Math.round(opacity * 100)} onChange={(e) => onChange({ ...st, color: st.color ?? cur.hex, opacity: Number(e.target.value) / 100 })} aria-label="Độ đục" />
          <output>{Math.round(opacity * 100)}%</output>
        </label>
      </div>
    </div>
  )
}

/** Tab "Kiểu dáng": bật tắt, màu, độ đục, độ dày và nét của từng đường, mức, tín hiệu và vùng tô. Không chạy lại script. */
export function StyleForm({ ind, result, onPatch }: Props) {
  const [open, setOpen] = useState<string | null>(null)
  const style = ind.style ?? {}
  if (!result) return <p className="mute">Chạy script trước để chỉnh kiểu dáng.</p>
  const groups = rowsOf(result)
  const change = (key: string, p: PlotStyle) => {
    const next = { ...style }
    if (Object.keys(p).length === 0 || (Object.keys(p).length === 1 && p.visible === true)) delete next[key]
    else next[key] = p
    onPatch({ style: next })
  }
  if (groups.length === 0) return <p className="mute">Script này không vẽ đường hay vùng tô nào để chỉnh.</p>
  const changed = Object.keys(style).length
  return (
    <div className="styleform">
      {changed > 0 && <button className="linkbtn" onClick={() => { onPatch({ style: {} }); setOpen(null) }}>Đặt lại {changed} thay đổi về mặc định</button>}
      {groups.map((g) => (
        <section key={g.group}>
          <h4>{g.group}</h4>
          {g.rows.map((row) => {
            const st = style[row.key] ?? {}
            const eff = parseColor(st.color) ?? parseColor(row.base)
            const on = st.visible !== false
            return (
              <div key={row.key} className={`srow ${on ? '' : 'off'}`}>
                <div className="sline">
                  <input type="checkbox" role="switch" checked={on} aria-label={`Hiện ${row.title}`}
                    onChange={(e) => change(row.key, { ...st, visible: e.target.checked })} />
                  <span className={`sname ${row.key in style ? 'changed' : ''}`} title={row.title}>{row.title}</span>
                  {row.kind !== 'mark' || row.base ? (
                    <button className="swatch" aria-expanded={open === row.key} aria-label={`Màu của ${row.title}`} title="Đổi màu"
                      style={{ background: eff ? rgba(eff.hex, st.opacity ?? eff.a) : 'transparent' }} onClick={() => setOpen(open === row.key ? null : row.key)} />
                  ) : null}
                  {row.kind === 'line' && (
                    <>
                      <select value={st.width ?? row.width ?? 1} aria-label={`Độ dày ${row.title}`} onChange={(e) => change(row.key, { ...st, width: Number(e.target.value) })}>
                        {WIDTHS.map((w) => <option key={w} value={w}>{w}px</option>)}
                      </select>
                      <select value={st.dash ?? row.dash ?? 'solid'} aria-label={`Nét ${row.title}`} onChange={(e) => change(row.key, { ...st, dash: e.target.value as Dash })}>
                        {DASHES.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
                      </select>
                    </>
                  )}
                </div>
                {open === row.key && <ColorPanel base={row.base} st={st} onChange={(p) => change(row.key, p)} />}
              </div>
            )
          })}
        </section>
      ))}
    </div>
  )
}

/** Tab "Hiển thị": chỉ hiện ở những khung nào, và nhãn giá trị trên thang giá. */
export function VisibilityForm({ ind, onPatch }: Omit<Props, 'result'>) {
  const all = !ind.tfs || ind.tfs.length === 0
  const set = (tf: string, on: boolean) => {
    const cur = new Set(ind.tfs && ind.tfs.length > 0 ? ind.tfs : TIMEFRAMES)
    if (on) cur.add(tf); else cur.delete(tf)
    const next = TIMEFRAMES.filter((t) => cur.has(t))
    onPatch({ tfs: next.length === TIMEFRAMES.length ? undefined : next })
  }
  return (
    <div className="visform">
      <h4>Khung thời gian</h4>
      <p className="mute fine">Bỏ chọn khung nào thì chỉ báo ẩn khi bạn xem khung đó.</p>
      <div className="tfgrid">
        {TIMEFRAMES.map((t) => {
          const on = all || (ind.tfs as string[]).includes(t)
          return <label key={t} className={on ? 'on' : ''}><input type="checkbox" checked={on} onChange={(e) => set(t, e.target.checked)} />{t}</label>
        })}
      </div>
      {!all && <button className="linkbtn" onClick={() => onPatch({ tfs: undefined })}>Hiện ở mọi khung</button>}
      <h4>Thang giá</h4>
      <label className="swrow">
        <span>Nhãn giá trị cuối trên thang giá</span>
        <input type="checkbox" role="switch" checked={!!ind.scaleLabels} onChange={(e) => onPatch({ scaleLabels: e.target.checked })} />
      </label>
    </div>
  )
}
