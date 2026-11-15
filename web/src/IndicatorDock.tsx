import { useEffect, useMemo, useRef, useState } from 'react'
import { createAlert } from './api'
import Icon from './Icons'
import InputsForm from './InputsForm'
import { StyleForm, VisibilityForm } from './StyleForm'
import { highlightPine } from './logic'
import { NEW_SCRIPT, isStrategy, type Indicator, type LibraryScript, type RunState } from './indicators'

type Props = {
  symbol: string
  tf: string
  list: Indicator[]
  runs: Record<string, RunState>
  library: LibraryScript[]
  selected: string | null
  onSelect: (id: string | null) => void
  onAdd: (source: string, name?: string) => string
  onUpdate: (id: string, patch: Partial<Indicator>, rerun?: boolean) => void
  onToggle: (id: string) => void
  onRemove: (id: string) => void
  onSave: (name: string, source: string) => void
  onDeleteLib: (name: string) => void
  onClose?: () => void
}

const STAT: Record<string, string> = { loading: 'Đang chạy', error: 'Lỗi', ok: 'Đã chạy', idle: '' }
const MIN_H = 220
const loadH = () => { try { const n = Number(localStorage.getItem('dockH')); return Number.isFinite(n) && n >= MIN_H ? n : 360 } catch { return 360 } }
const maxH = () => Math.round(window.innerHeight * 0.8)

type Tab = 'inputs' | 'style' | 'vis' | 'bt' | 'stats'

/**
 * Bảng quản lý chỉ báo. Trái: chỉ báo đang dùng và thư viện. Giữa: trình soạn mã có số dòng. Phải: tham số, backtest, thống kê.
 * Kéo thanh trên cùng để đổi chiều cao, nhấp đúp để mở rộng hoặc thu lại.
 */
export default function IndicatorDock({ symbol, tf, list, runs, library, selected, onSelect, onAdd, onUpdate, onToggle, onRemove, onSave, onDeleteLib, onClose }: Props) {
  const [q, setQ] = useState('')
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('inputs')
  const [h, setH] = useState(loadH)
  const [caret, setCaret] = useState({ line: 1, col: 1 })
  const hl = useRef<HTMLPreElement>(null)
  const gut = useRef<HTMLPreElement>(null)
  const sel = list.find((i) => i.id === selected) ?? null
  const run = sel ? runs[sel.id] : undefined
  const res = run?.result
  const strat = !!sel && isStrategy(sel.source)

  // đổi chỉ báo đang chọn thì nạp mã của nó vào ô soạn
  useEffect(() => { setDraft(sel?.source ?? ''); setNote(null); setTab('inputs') }, [sel?.id])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (tab === 'bt' && !strat) setTab('inputs') }, [tab, strat])
  useEffect(() => { try { localStorage.setItem('dockH', String(h)) } catch { /* bỏ qua */ } }, [h])

  const shownLib = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return library.filter((l) => !needle || l.name.toLowerCase().includes(needle))
  }, [library, q])
  const dirty = !!sel && draft !== sel.source
  const apply = () => { if (sel) onUpdate(sel.id, { source: draft }) }
  const st = res?.strategy
  const lines = useMemo(() => draft.split('\n').length, [draft])
  const errLine = run?.status === 'error' ? run.error?.line ?? null : null
  const gutter = useMemo(() => Array.from({ length: lines }, (_, i) => i + 1), [lines])

  const drag = (e: React.PointerEvent) => {
    e.preventDefault()
    const y0 = e.clientY
    const h0 = h
    const move = (m: PointerEvent) => setH(Math.min(maxH(), Math.max(MIN_H, h0 + (y0 - m.clientY))))
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const big = h >= maxH() - 8
  const updateCaret = (el: HTMLTextAreaElement) => {
    const before = el.value.slice(0, el.selectionStart)
    const nl = before.lastIndexOf('\n')
    setCaret({ line: before.split('\n').length, col: before.length - nl })
  }
  const add = (source: string) => { const id = onAdd(source); onSelect(id) }

  return (
    <section className="dock" style={{ height: h }} aria-label="Quản lý chỉ báo">
      <div className="dock-grip" role="separator" aria-orientation="horizontal" aria-label="Kéo để đổi chiều cao bảng chỉ báo"
        tabIndex={0} onPointerDown={drag} onDoubleClick={() => setH(big ? 360 : maxH())}
        onKeyDown={(e) => { if (e.key === 'ArrowUp') setH((v) => Math.min(maxH(), v + 40)); else if (e.key === 'ArrowDown') setH((v) => Math.max(MIN_H, v - 40)) }}>
        <span />
      </div>
      {onClose && <button className="dock-close" onClick={onClose} aria-label="Đóng bảng chỉ báo" title="Đóng (phím I)"><Icon name="x" size={16} /></button>}
      <div className="dock-body">
        <aside className="dock-left">
          <h3>Trên biểu đồ <span className="count">{list.length}</span></h3>
          <ul className="dlist">
            {list.length === 0 && <li className="empty">Chưa có chỉ báo. Chọn một script trong thư viện.</li>}
            {list.map((i) => (
              <li key={i.id} className={`${i.id === selected ? 'on' : ''} ${i.visible ? '' : 'off'}`}>
                <button className="ibtn" aria-pressed={i.visible} title={i.visible ? 'Ẩn khỏi biểu đồ' : 'Hiện trên biểu đồ'}
                  aria-label={`${i.visible ? 'Ẩn' : 'Hiện'} ${i.name}`} onClick={() => onToggle(i.id)}><Icon name={i.visible ? 'eye' : 'eyeoff'} /></button>
                <button className="name" onClick={() => onSelect(i.id)} title={i.name}>
                  <span className={`sdot ${runs[i.id]?.status ?? 'idle'}`} /><span className="nm">{i.name}</span>
                  {runs[i.id]?.status === 'error' && <em>lỗi</em>}
                </button>
                <button className="ibtn danger" title="Xoá khỏi biểu đồ" aria-label={`Xoá ${i.name}`} onClick={() => { onRemove(i.id); if (selected === i.id) onSelect(null) }}><Icon name="x" size={14} /></button>
              </li>
            ))}
          </ul>
          <h3>Thư viện</h3>
          <input className="isearch" type="search" placeholder="Tìm script..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Tìm script trong thư viện" />
          <ul className="dlist lib">
            {shownLib.map((l) => (
              <li key={`${l.mine}-${l.name}`}>
                <button className="name" title="Thêm vào biểu đồ" onClick={() => add(l.source)}>
                  {l.mine && <span className="star"><Icon name="star" size={13} /></span>}
                  <span className="nm">{l.name.replace(/_/g, ' ')}</span>
                  <em className={isStrategy(l.source) ? 'tag strat' : 'tag'}>{isStrategy(l.source) ? 'chiến lược' : 'chỉ báo'}</em>
                </button>
                <button className="ibtn accent" title="Thêm vào biểu đồ" aria-label={`Thêm ${l.name}`} onClick={() => add(l.source)}><Icon name="plus" size={14} /></button>
                {l.mine && <button className="ibtn danger" title="Xoá khỏi thư viện của bạn" aria-label={`Xoá ${l.name} khỏi thư viện`} onClick={() => onDeleteLib(l.name)}><Icon name="trash" size={14} /></button>}
              </li>
            ))}
            {shownLib.length === 0 && <li className="empty">Không có script nào khớp.</li>}
          </ul>
          <button className="newbtn" onClick={() => add(NEW_SCRIPT)}><Icon name="plus" size={14} /> Script mới</button>
        </aside>

        <div className="dock-mid">
          {!sel ? (
            <div className="dock-empty">
              <p><b>Chọn một chỉ báo để sửa mã và tham số</b></p>
              <p className="mute">Bấm một script trong thư viện để thêm vào biểu đồ. Mỗi chỉ báo chạy riêng và có thể ẩn, chỉnh tham số, sửa hoặc xoá bất cứ lúc nào.</p>
            </div>
          ) : (
            <>
              <div className="dhead">
                <div className="dtitle">
                  <b className="dname" title={sel.name}>{sel.name}</b>
                  <span className={`pill ${run?.status ?? 'idle'}`}>{STAT[run?.status ?? 'idle']}</span>
                  <span className="mute ctx">{symbol} · {tf}</span>
                </div>
                <div className="dact">
                  <button className="primary" onClick={apply} disabled={!dirty && run?.status !== 'error'} title="Chạy lại script (Ctrl+Enter)">
                    <Icon name="play" size={13} /> {dirty ? 'Áp dụng' : 'Đã áp dụng'}
                  </button>
                  <button onClick={() => { onSave(sel.name, draft); setNote(`Đã lưu "${sel.name}" vào thư viện của bạn.`) }} title="Lưu vào thư viện của bạn"><Icon name="save" size={14} /><span className="lbl">Lưu</span></button>
                  {res && res.alerts.length > 0 && (
                    <button title="Tạo cảnh báo từ alertcondition của script" onClick={() => {
                      void createAlert(symbol, { type: 'pine', source: sel.source, tf, title: res.alerts[0].title, once: false })
                        .then(() => setNote(`Đã tạo cảnh báo "${res.alerts[0].title}". Tiến trình nền gửi thông báo khi nến đóng thoả điều kiện.`))
                        .catch((e: unknown) => setNote(`Không tạo được cảnh báo: ${JSON.stringify((e as { detail?: unknown }).detail ?? e)}`))
                    }}><Icon name="bell" size={14} /><span className="lbl">Cảnh báo</span></button>
                  )}
                  <button className="ibtn" title={big ? 'Thu nhỏ bảng' : 'Mở rộng bảng'} aria-label={big ? 'Thu nhỏ bảng' : 'Mở rộng bảng'} onClick={() => setH(big ? 360 : maxH())}><Icon name={big ? 'shrink' : 'expand'} size={14} /></button>
                </div>
              </div>
              {note && <p className="dnote" role="status">{note}</p>}
              {run?.status === 'error' && <p className="status bad errbox" role="alert">{run.error?.line ? `Dòng ${run.error.line}: ` : ''}{run.error?.message}</p>}
              <div className="editor">
                <pre className="gut" aria-hidden="true" ref={gut}>
                  {gutter.map((n) => <span key={n} className={n === errLine ? 'ln err' : n === caret.line ? 'ln cur' : 'ln'}>{n}{'\n'}</span>)}
                </pre>
                <pre className="hl" aria-hidden="true" ref={hl}>
                  {highlightPine(draft).map((t, i) => <span key={i} className={`tk-${t.kind}`}>{t.text}</span>)}
                  {'\n'}
                </pre>
                <textarea className="code" aria-label="Mã Pine" spellCheck={false} wrap="off" value={draft}
                  onScroll={(e) => {
                    const t = e.currentTarget
                    if (hl.current) { hl.current.scrollTop = t.scrollTop; hl.current.scrollLeft = t.scrollLeft }
                    if (gut.current) gut.current.scrollTop = t.scrollTop
                  }}
                  onChange={(e) => { setDraft(e.target.value); updateCaret(e.target) }}
                  onKeyUp={(e) => updateCaret(e.currentTarget)} onClick={(e) => updateCaret(e.currentTarget)}
                  onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); apply() } }} />
              </div>
              <div className="edstatus"><span>Dòng {caret.line}, cột {caret.col}</span><span>{lines} dòng</span><span>Pine · Ctrl+Enter để chạy</span></div>
            </>
          )}
        </div>

        <aside className="dock-right">
          {sel && (
            <>
              <div className="tabs" role="tablist" aria-label="Thiết lập chỉ báo">
                {([['inputs', 'Tham số'], ['style', 'Kiểu dáng'], ['vis', 'Hiển thị'], ...(strat ? [['bt', 'Backtest'], ['stats', 'Kết quả']] : [])] as [Tab, string][]).map(([id, label]) => (
                  <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>{label}</button>
                ))}
              </div>
              <div className="tabbody">
                {tab === 'inputs' && (
                  <InputsForm defs={res?.inputs ?? []} values={sel.inputs}
                    onChange={(t, v) => onUpdate(sel.id, { inputs: { ...sel.inputs, [t]: v } })}
                    onReset={() => onUpdate(sel.id, { inputs: {} })} />
                )}
                {tab === 'style' && <StyleForm ind={sel} result={res} onPatch={(p) => onUpdate(sel.id, p, false)} />}
                {tab === 'vis' && <VisibilityForm ind={sel} onPatch={(p) => onUpdate(sel.id, p, false)} />}
                {tab === 'bt' && strat && (
                  <div className="btform">
                    <div className="irow"><label><span className="ilabel">Vốn ban đầu</span><input type="number" value={sel.bt.capital} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, capital: e.target.value } }, false)} onBlur={() => onUpdate(sel.id, {})} /></label></div>
                    <div className="irow"><label><span className="ilabel">Phí mỗi lần khớp (%)</span><input type="number" step="0.01" value={sel.bt.fee} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, fee: e.target.value } }, false)} onBlur={() => onUpdate(sel.id, {})} /></label></div>
                    <div className="irow"><label><span className="ilabel">Trượt giá (tick)</span><input type="number" value={sel.bt.slip} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, slip: e.target.value } }, false)} onBlur={() => onUpdate(sel.id, {})} /></label></div>
                    <div className="irow"><label><span className="ilabel">Từ ngày</span><input type="date" value={sel.bt.from} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, from: e.target.value } })} /></label></div>
                    <div className="irow"><label><span className="ilabel">Đến ngày</span><input type="date" value={sel.bt.to} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, to: e.target.value } })} /></label></div>
                    <p className="mute fine">Tối đa 5000 nến mỗi lần. Lệnh khớp ở giá mở của nến kế tiếp, không có stop hoặc limit, không mô phỏng thanh khoản.</p>
                  </div>
                )}
                {tab === 'stats' && strat && (
                  st ? (
                    <>
                      <div className="kpis">
                        <div><small>Lãi ròng</small><b className={st.net_profit >= 0 ? 'up' : 'down'}>{st.net_profit.toFixed(2)}</b></div>
                        <div><small>Vốn cuối</small><b>{(st.equity[st.equity.length - 1] ?? st.initial_capital).toFixed(2)}</b></div>
                        <div><small>Tỉ lệ thắng</small><b>{(st.win_rate * 100).toFixed(1)}%</b></div>
                        <div><small>Sụt vốn tối đa</small><b className="down">{(st.max_drawdown * 100).toFixed(1)}%</b></div>
                        <div><small>Lệnh đã đóng</small><b>{st.closed_trades}</b></div>
                      </div>
                      {st.trades.length > 0 && (
                        <table className="pine-stats trades">
                          <thead><tr><th>Hướng</th><th>Vào</th><th>Lãi</th></tr></thead>
                          <tbody>{st.trades.slice(-30).map((t, i) => (
                            <tr key={i}><td>{t.dir}</td><td>{new Date(t.entry_time).toISOString().slice(5, 16).replace('T', ' ')}</td>
                              <td className={t.pnl >= 0 ? 'up' : 'down'}>{t.pnl.toFixed(2)}</td></tr>
                          ))}</tbody>
                        </table>
                      )}
                    </>
                  ) : <p className="mute">Chưa có kết quả. Áp dụng script để chạy backtest.</p>
                )}
                {res && res.alerts.length > 0 && <p className="mute fine">Cảnh báo trong script: {res.alerts.map((a) => `${a.title} (${a.bars.length} lần)`).join(', ')}</p>}
              </div>
            </>
          )}
        </aside>
      </div>
    </section>
  )
}
