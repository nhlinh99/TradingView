import { useEffect, useMemo, useRef, useState } from 'react'
import { createAlert } from './api'
import InputsForm from './InputsForm'
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
}

const STAT: Record<string, string> = { loading: 'Đang chạy', error: 'Lỗi', ok: 'Đã chạy', idle: '' }

/**
 * Bảng quản lý chỉ báo: trái là danh sách đang dùng và thư viện (tìm, thêm một chạm), giữa là trình soạn mã,
 * phải là tham số, backtest và thống kê của chỉ báo đang chọn. Thêm bao nhiêu chỉ báo cũng được, mỗi cái chạy độc lập.
 */
export default function IndicatorDock({ symbol, tf, list, runs, library, selected, onSelect, onAdd, onUpdate, onToggle, onRemove, onSave, onDeleteLib }: Props) {
  const [q, setQ] = useState('')
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const hl = useRef<HTMLPreElement>(null)
  const sel = list.find((i) => i.id === selected) ?? null
  const run = sel ? runs[sel.id] : undefined
  const res = run?.result

  // đổi chỉ báo đang chọn thì nạp mã của nó vào ô soạn
  useEffect(() => { setDraft(sel?.source ?? ''); setNote(null) }, [sel?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  const shownLib = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return library.filter((l) => !needle || l.name.toLowerCase().includes(needle))
  }, [library, q])
  const dirty = !!sel && draft !== sel.source
  const apply = () => { if (sel) onUpdate(sel.id, { source: draft }) }
  const st = res?.strategy

  return (
    <section className="dock" aria-label="Quản lý chỉ báo">
      <aside className="dock-left">
        <h3>Trên biểu đồ <span className="mute">({list.length})</span></h3>
        <ul className="dlist">
          {list.length === 0 && <li className="mute empty">Chưa có chỉ báo. Thêm từ thư viện bên dưới.</li>}
          {list.map((i) => (
            <li key={i.id} className={i.id === selected ? 'on' : ''}>
              <button className="eye" aria-pressed={i.visible} aria-label={`${i.visible ? 'Ẩn' : 'Hiện'} ${i.name}`} onClick={() => onToggle(i.id)}>{i.visible ? '👁' : '⌀'}</button>
              <button className="name" onClick={() => onSelect(i.id)} title={i.name}>
                <span className={`sdot ${runs[i.id]?.status ?? 'idle'}`} />{i.name}
                {runs[i.id]?.status === 'error' && <em>lỗi</em>}
              </button>
              <button className="x" aria-label={`Xoá ${i.name}`} onClick={() => { onRemove(i.id); if (selected === i.id) onSelect(null) }}>×</button>
            </li>
          ))}
        </ul>
        <h3>Thư viện</h3>
        <input className="isearch" type="search" placeholder="Tìm script..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Tìm script trong thư viện" />
        <ul className="dlist lib">
          {shownLib.map((l) => (
            <li key={`${l.mine}-${l.name}`}>
              <button className="name" title="Thêm vào biểu đồ" onClick={() => { const id = onAdd(l.source); onSelect(id) }}>
                {l.mine ? '★ ' : ''}{l.name.replace(/_/g, ' ')}
              </button>
              <button className="add" aria-label={`Thêm ${l.name}`} onClick={() => { const id = onAdd(l.source); onSelect(id) }}>+</button>
              {l.mine && <button className="x" aria-label={`Xoá ${l.name} khỏi thư viện`} onClick={() => onDeleteLib(l.name)}>×</button>}
            </li>
          ))}
          {shownLib.length === 0 && <li className="mute empty">Không có script nào khớp.</li>}
        </ul>
        <button className="newbtn" onClick={() => { const id = onAdd(NEW_SCRIPT); onSelect(id) }}>+ Script mới</button>
      </aside>

      <div className="dock-mid">
        {!sel ? (
          <div className="dock-empty">
            <p><b>Chọn một chỉ báo để sửa mã và tham số</b></p>
            <p className="mute">Bấm một script trong Thư viện để thêm vào biểu đồ. Có thể thêm nhiều chỉ báo cùng lúc; mỗi chỉ báo chạy riêng và có thể ẩn, chỉnh tham số, sửa hoặc xoá bất cứ lúc nào.</p>
          </div>
        ) : (
          <>
            <div className="pine-bar">
              <b className="dname">{sel.name}</b>
              <span className={`pill ${run?.status ?? 'idle'}`}>{STAT[run?.status ?? 'idle']}</span>
              <button className="primary" onClick={apply} disabled={!dirty && run?.status !== 'error'}>{dirty ? 'Áp dụng (Ctrl+Enter)' : 'Đã áp dụng'}</button>
              <button onClick={() => { onSave(sel.name, draft); setNote(`Đã lưu "${sel.name}" vào thư viện của bạn.`) }}>Lưu vào thư viện</button>
              {res && res.alerts.length > 0 && (
                <button onClick={() => {
                  void createAlert(symbol, { type: 'pine', source: sel.source, tf, title: res.alerts[0].title, once: false })
                    .then(() => setNote(`Đã tạo cảnh báo "${res.alerts[0].title}". Tiến trình nền gửi thông báo khi nến đóng thoả điều kiện.`))
                    .catch((e: unknown) => setNote(`Không tạo được cảnh báo: ${JSON.stringify((e as { detail?: unknown }).detail ?? e)}`))
                }}>Tạo cảnh báo</button>
              )}
              <span className="mute">{symbol} · {tf}</span>
            </div>
            {note && <p className="mute dnote">{note}</p>}
            {run?.status === 'error' && <p className="status bad" role="alert">{run.error?.line ? `Dòng ${run.error.line}: ` : ''}{run.error?.message}</p>}
            <div className="editor">
              <pre className="hl" aria-hidden="true" ref={hl}>
                {highlightPine(draft).map((t, i) => <span key={i} className={`tk-${t.kind}`}>{t.text}</span>)}
                {'\n'}
              </pre>
              <textarea className="code" aria-label="Mã Pine" spellCheck={false} value={draft}
                onScroll={(e) => { if (hl.current) { hl.current.scrollTop = e.currentTarget.scrollTop; hl.current.scrollLeft = e.currentTarget.scrollLeft } }}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); apply() } }} />
            </div>
          </>
        )}
      </div>

      <aside className="dock-right">
        {sel && (
          <>
            <h3>Tham số</h3>
            <InputsForm defs={res?.inputs ?? []} values={sel.inputs}
              onChange={(t, v) => onUpdate(sel.id, { inputs: { ...sel.inputs, [t]: v } })}
              onReset={() => onUpdate(sel.id, { inputs: {} })} />
            {isStrategy(sel.source) && (
              <>
                <h3>Backtest</h3>
                <div className="irow"><label><span className="ilabel">Vốn ban đầu</span><input type="number" value={sel.bt.capital} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, capital: e.target.value } }, false)} onBlur={() => onUpdate(sel.id, {})} /></label></div>
                <div className="irow"><label><span className="ilabel">Phí mỗi lần khớp (%)</span><input type="number" step="0.01" value={sel.bt.fee} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, fee: e.target.value } }, false)} onBlur={() => onUpdate(sel.id, {})} /></label></div>
                <div className="irow"><label><span className="ilabel">Trượt giá (tick)</span><input type="number" value={sel.bt.slip} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, slip: e.target.value } }, false)} onBlur={() => onUpdate(sel.id, {})} /></label></div>
                <div className="irow"><label><span className="ilabel">Từ ngày</span><input type="date" value={sel.bt.from} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, from: e.target.value } })} /></label></div>
                <div className="irow"><label><span className="ilabel">Đến ngày</span><input type="date" value={sel.bt.to} onChange={(e) => onUpdate(sel.id, { bt: { ...sel.bt, to: e.target.value } })} /></label></div>
                <p className="mute">Tối đa 5000 nến mỗi lần. Lệnh khớp ở giá mở của nến kế tiếp; không stop/limit, không mô phỏng thanh khoản.</p>
              </>
            )}
            {st && (
              <>
                <table className="pine-stats"><tbody>
                  <tr><td>Vốn cuối</td><td>{(st.equity[st.equity.length - 1] ?? st.initial_capital).toFixed(2)}</td></tr>
                  <tr><td>Lãi ròng</td><td>{st.net_profit.toFixed(2)}</td></tr>
                  <tr><td>Lệnh đã đóng</td><td>{st.closed_trades}</td></tr>
                  <tr><td>Tỉ lệ thắng</td><td>{(st.win_rate * 100).toFixed(1)}%</td></tr>
                  <tr><td>Sụt vốn tối đa</td><td>{(st.max_drawdown * 100).toFixed(1)}%</td></tr>
                </tbody></table>
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
            )}
            {res && res.alerts.length > 0 && <p className="mute">Cảnh báo trong script: {res.alerts.map((a) => `${a.title} (${a.bars.length} lần)`).join(', ')}</p>}
          </>
        )}
      </aside>
    </section>
  )
}
