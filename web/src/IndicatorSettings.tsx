import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Icon from './Icons'
import InputsForm from './InputsForm'
import { StyleForm, VisibilityForm } from './StyleForm'
import type { Indicator, RunState } from './indicators'

type Props = {
  ind: Indicator
  run: RunState | undefined
  onPatch: (patch: Partial<Indicator>, rerun?: boolean) => void
  onClose: () => void
}
type Tab = 'inputs' | 'style' | 'vis'

/**
 * Hộp Cài đặt của một chỉ báo: ba tab Tham số, Kiểu dáng, Hiển thị. Thay đổi áp ngay lên biểu đồ để xem trực tiếp;
 * "Huỷ" (hoặc Esc) trả mọi thứ về lúc mở hộp, "OK" giữ lại. Nút Mặc định đặt lại tham số và kiểu dáng của script.
 */
export default function IndicatorSettings({ ind, run, onPatch, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('inputs')
  const snap = useRef({ inputs: ind.inputs, style: ind.style, tfs: ind.tfs, scaleLabels: ind.scaleLabels })
  const first = useRef<HTMLButtonElement>(null)
  const cancel = () => {
    const s = snap.current
    const inputsChanged = JSON.stringify(s.inputs) !== JSON.stringify(ind.inputs)
    onPatch({ inputs: s.inputs, style: s.style, tfs: s.tfs, scaleLabels: s.scaleLabels }, inputsChanged)
    onClose()
  }
  useEffect(() => { first.current?.focus() }, [])
  const res = run?.result
  const dirty = Object.keys(ind.inputs).length > 0 || Object.keys(ind.style ?? {}).length > 0 || !!ind.tfs || !!ind.scaleLabels

  return createPortal(
    <div className="modal" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="setdlg" role="dialog" aria-modal="true" aria-label={`Cài đặt ${ind.name}`}
        onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); cancel() } }}>
        <header>
          <h2 title={ind.name}>{ind.name}</h2>
          <button className="ibtn" onClick={cancel} aria-label="Đóng và huỷ thay đổi" title="Huỷ (Esc)"><Icon name="x" size={16} /></button>
        </header>
        <div className="tabs line" role="tablist" aria-label="Thiết lập">
          {([['inputs', 'Tham số'], ['style', 'Kiểu dáng'], ['vis', 'Hiển thị']] as [Tab, string][]).map(([id, label], i) => (
            <button key={id} ref={i === 0 ? first : undefined} role="tab" aria-selected={tab === id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
        <div className="setbody">
          {run?.status === 'error' && <p className="status bad errbox" role="alert">{run.error?.line ? `Dòng ${run.error.line}: ` : ''}{run.error?.message}</p>}
          {run?.status === 'loading' && !res && <p className="mute">Đang chạy...</p>}
          {tab === 'inputs' && <InputsForm defs={res?.inputs ?? []} values={ind.inputs} onChange={(t, v) => onPatch({ inputs: { ...ind.inputs, [t]: v } }, true)} onReset={() => onPatch({ inputs: {} }, true)} />}
          {tab === 'style' && <StyleForm ind={ind} result={res} onPatch={(p) => onPatch(p, false)} />}
          {tab === 'vis' && <VisibilityForm ind={ind} onPatch={(p) => onPatch(p, false)} />}
        </div>
        <footer>
          <button className="linkbtn" disabled={!dirty} onClick={() => onPatch({ inputs: {}, style: {}, tfs: undefined, scaleLabels: false }, Object.keys(ind.inputs).length > 0)} title="Đặt lại tham số và kiểu dáng về mặc định của script">Mặc định</button>
          <span className="sp" />
          <button onClick={cancel}>Huỷ</button>
          <button className="primary" onClick={onClose}>OK</button>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
