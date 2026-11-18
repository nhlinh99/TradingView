import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { Flow } from './Chart'

type Props = {
  flow: Flow
  setF: (patch: Partial<Flow>) => void
  symbol: string
  isVn: boolean
}

const OFF: Partial<Flow> = {
  footprint: false, heatmap: false, dom: false, zones: false, bubbles: false, iceberg: false, vpvr: false, delta: false, cvd: 'off', gex: false,
}
const PRESETS: { id: string; label: string; hint: string; patch: Partial<Flow> }[] = [
  { id: 'clean', label: 'Sạch', hint: 'Chỉ nến và volume', patch: OFF },
  { id: 'footprint', label: 'Footprint', hint: 'Ô bid x ask, delta, CVD', patch: { ...OFF, footprint: true, delta: true, cvd: 'day', fpMode: 'bidask' } },
  { id: 'bookmap', label: 'Bookmap', hint: 'Heatmap, chấm volume, iceberg', patch: { ...OFF, heatmap: true, dom: true, zones: true, bubbles: true, iceberg: true, heatMode: 'bookmap', bestLines: true, strip: true, heatLo: 15, heatHi: 90 } },
  { id: 'profile', label: 'Profile', hint: 'VPVR và delta', patch: { ...OFF, vpvr: true, delta: true } },
]

function Switch({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean }) {
  return (
    <label className={`sw ${disabled ? 'dis' : ''}`}>
      <input type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" aria-hidden="true"><span className="knob" /></span>
      <span className="swtext"><b>{label}</b>{hint && <small>{hint}</small>}</span>
    </label>
  )
}

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { v: T; l: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => <button key={o.v} className={o.v === value ? 'on' : ''} aria-pressed={o.v === value} onClick={() => onChange(o.v)}>{o.l}</button>)}
    </div>
  )
}

function Slider({ label, value, min, max, step, unit, onChange, format }: { label: string; value: number; min: number; max: number; step: number; unit?: string; onChange: (v: number) => void; format?: (v: number) => string }) {
  return (
    <label className="sl">
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} />
      <output>{format ? format(value) : `${value}${unit ?? ''}`}</output>
    </label>
  )
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return <section className="fgroup"><h3>{title}</h3>{children}</section>
}

/** Bảng "Chỉ báo": gom mọi công tắc orderflow vào một chỗ, có mẫu dựng sẵn, nhóm theo mục đích, và tuỳ chọn chỉ hiện khi bật tính năng. */
export default function FlowMenu({ flow, setF, symbol, isVn }: Props) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  const active = [flow.footprint && 'Footprint', flow.heatmap && 'Heatmap', flow.zones && 'Vùng', flow.dom && 'DOM', flow.bubbles && 'Chấm', flow.iceberg && 'Iceberg', flow.vpvr && 'VPVR', flow.delta && 'Delta', flow.cvd !== 'off' && 'CVD', flow.gex && 'GEX'].filter(Boolean) as string[]
  const noFlow = isVn ? 'Cổ phiếu VN không có dữ liệu tick và sổ lệnh sâu' : undefined
  const preset = PRESETS.find((p) => Object.entries(p.patch).every(([k, v]) => (flow as Record<string, unknown>)[k] === v))

  return (
    <div className="flowmenu" ref={box}>
      <button className={`menubtn ${active.length ? 'has' : ''}`} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)}>
        Orderflow{active.length > 0 && <span className="badge">{active.length}</span>}<span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Orderflow">
          <div className="presets" role="group" aria-label="Mẫu dựng sẵn">
            {PRESETS.map((p) => (
              <button key={p.id} title={p.hint} className={preset?.id === p.id ? 'on' : ''} onClick={() => setF(p.patch)}>{p.label}</button>
            ))}
          </div>

          <Group title="Orderflow">
            <Switch checked={flow.footprint} onChange={(v) => setF({ footprint: v })} label="Footprint" hint="Khối lượng mua/bán từng mức giá trong nến. Phóng to nến để thấy chữ." disabled={isVn} />
            {flow.footprint && !isVn && (
              <div className="opt">
                <Seg label="Kiểu footprint" value={flow.fpMode} onChange={(v) => setF({ fpMode: v })}
                  options={[{ v: 'bidask', l: 'Bid x Ask' }, { v: 'delta', l: 'Delta' }, { v: 'volume', l: 'Volume' }, { v: 'profile', l: 'Profile' }]} />
                <Slider label="Imbalance" value={flow.ratio} min={2} max={5} step={1} format={(v) => `${v}:1`} onChange={(v) => setF({ ratio: v })} />
              </div>
            )}
            <Switch checked={flow.heatmap} onChange={(v) => setF({ heatmap: v })} label="Heatmap thanh khoản" hint="Lệnh chờ trong sổ lệnh theo thời gian (chỉ từ lúc bắt đầu thu thập)." disabled={isVn} />
            {flow.heatmap && !isVn && (
              <div className="opt">
                <Seg label="Màu heatmap" value={flow.heatMode} onChange={(v) => setF({ heatMode: v })}
                  options={[{ v: 'bookmap', l: 'Bookmap' }, { v: 'intensity', l: 'Cường độ' }, { v: 'side', l: 'Mua/Bán' }]} />
                <Slider label="Cắt thấp (ẩn nhiễu)" value={flow.heatLo} min={0} max={50} step={5} unit="%" onChange={(v) => setF({ heatLo: v })} />
                <Slider label="Cắt cao" value={flow.heatHi} min={40} max={100} step={5} unit="%" onChange={(v) => setF({ heatHi: v })} />
                <Switch checked={flow.bestLines} onChange={(v) => setF({ bestLines: v })} label="Đường bid/ask tốt nhất" />
                <Switch checked={flow.strip} onChange={(v) => setF({ strip: v })} label="Dải volume mua/bán" />
              </div>
            )}
            <Switch checked={flow.dom} onChange={(v) => setF({ dom: v })} label="Bảng độ sâu (DOM)" hint="Cột thanh khoản chờ ở từng mức giá, sát trục giá bên phải: bid xanh, ask đỏ, ghi số ở các mức lớn nhất, cập nhật mỗi 2 giây." disabled={isVn} />
            <Switch checked={flow.zones} onChange={(v) => setF({ zones: v })} label="Vùng thanh khoản (rút lệnh)" hint="Mỗi lệnh chờ lớn là một thanh kéo dài từ lúc xuất hiện đến lúc biến mất. Dấu ✕ là bị rút lệnh, ▶ là bị khớp, thanh mờ dần là còn hiệu lực." disabled={isVn} />
            {flow.zones && !isVn && (
              <div className="opt">
                <Slider label="Ngưỡng lệnh chờ" value={flow.zoneMin} min={10} max={80} step={10} unit="%" onChange={(v) => setF({ zoneMin: v })} />
              </div>
            )}
            <Switch checked={flow.bubbles} onChange={(v) => setF({ bubbles: v })} label="Chấm volume" hint="Lệnh khớp lớn: vòng đặc là một lệnh, vòng rỗng là nhiều lệnh gộp." disabled={isVn} />
            {flow.bubbles && !isVn && (
              <div className="opt">
                <Slider label="Cỡ chấm" value={flow.dotScale} min={50} max={300} step={25} unit="%" onChange={(v) => setF({ dotScale: v })} />
                <Slider label="Ẩn chấm nhỏ" value={flow.dotMin} min={0} max={20} step={1} format={(v) => (v === 0 ? 'Tắt' : `< ${v}%`)} onChange={(v) => setF({ dotMin: v })} />
              </div>
            )}
            <Switch checked={flow.iceberg} onChange={(v) => setF({ iceberg: v })} label="Iceberg (ước lượng)" hint="Độ tin cậy thấp; chỉ hiện 40 dấu hiệu lớn nhất." disabled={isVn} />
            <Switch checked={flow.vpvr} onChange={(v) => setF({ vpvr: v })} label="Volume profile (VPVR)" hint="Phân bố volume theo giá, kèm POC, VAH, VAL." />
          </Group>

          <Group title="Pane phụ">
            <Switch checked={flow.delta} onChange={(v) => setF({ delta: v })} label="Delta" hint="Mua chủ động trừ bán chủ động mỗi nến." disabled={isVn} />
            <div className="row">
              <span>CVD</span>
              <Seg label="CVD" value={flow.cvd} onChange={(v) => setF({ cvd: v })} options={[{ v: 'off', l: 'Tắt' }, { v: 'none', l: 'Liên tục' }, { v: 'day', l: 'Theo ngày' }]} />
            </div>
          </Group>

          <Group title="Dữ liệu ngoài">
            <Switch checked={flow.gex} onChange={(v) => setF({ gex: v })} label="GEX quyền chọn" hint={symbol === 'BTCUSDT' ? 'Deribit, OI trễ ~8 giờ. Gamma flip, call wall, put wall.' : 'Chỉ có cho BTCUSDT.'} disabled={symbol !== 'BTCUSDT'} />
          </Group>
          {noFlow && <p className="fnote">{noFlow}.</p>}
        </div>
      )}
    </div>
  )
}
