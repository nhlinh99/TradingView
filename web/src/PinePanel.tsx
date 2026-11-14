import { useEffect, useState } from 'react'
import { createAlert, fetchPineExamples, runPine, type PineResult } from './api'

type Props = {
  symbol: string
  tf: string
  onResult: (r: PineResult | null) => void
}

const DEFAULT_SRC = `//@version=5
indicator("My MA", overlay=true)
len = input.int(20, "Length", minval=1)
plot(ta.sma(close, len), "SMA", color=color.orange)
`

function load(key: string, fallback: string) {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}
function save(key: string, v: string) {
  try { localStorage.setItem(key, v) } catch { /* bị chặn: bỏ qua */ }
}

/** Trình soạn script Pine (ô văn bản) và nút "Add to chart". Ô nhập tham số được tạo từ lời gọi input.* của script. */
export default function PinePanel({ symbol, tf, onResult }: Props) {
  const [src, setSrc] = useState(() => load('pine.src', DEFAULT_SRC))
  const [examples, setExamples] = useState<{ name: string; source: string }[]>([])
  const [res, setRes] = useState<PineResult | null>(null)
  const [inputs, setInputs] = useState<Record<string, unknown>>({})
  const [err, setErr] = useState<{ message: string; line?: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => { fetchPineExamples().then(setExamples).catch(() => setExamples([])) }, [])

  const run = async (over: Record<string, unknown> = inputs) => {
    setBusy(true)
    try {
      const r = await runPine(src, symbol, tf, over)
      setRes(r)
      setErr(null)
      onResult(r)
    } catch (e) {
      const d = (e as { detail?: { message?: string; line?: number } }).detail
      setErr({ message: d?.message ?? String(e), line: d?.line })
    } finally {
      setBusy(false)
    }
  }
  const remove = () => { setRes(null); setErr(null); onResult(null) }
  const st = res?.strategy

  return (
    <section className="pine" aria-label="Pine Script">
      <div className="pine-bar">
        <select aria-label="Script mẫu" value="" onChange={(e) => {
          const ex = examples.find((x) => x.name === e.target.value)
          if (ex) { setSrc(ex.source); save('pine.src', ex.source); setInputs({}); remove() }
        }}>
          <option value="">Script mẫu...</option>
          {examples.map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
        </select>
        <button className="primary" onClick={() => void run()} disabled={busy}>{busy ? 'Đang chạy...' : 'Add to chart'}</button>
        <button onClick={remove} disabled={!res}>Gỡ khỏi chart</button>
        {res && res.alerts.length > 0 && (
          <button onClick={() => {
            void createAlert(symbol, { type: 'pine', source: src, tf, title: res.alerts[0].title, once: false })
              .then(() => setNote(`Đã tạo cảnh báo "${res.alerts[0].title}". Tiến trình nền sẽ gửi thông báo khi nến đóng thoả điều kiện.`))
              .catch((e: unknown) => setErr({ message: JSON.stringify((e as { detail?: unknown }).detail ?? e) }))
          }}>Tạo cảnh báo từ script</button>
        )}
        <span className="mute">{symbol} · {tf}</span>
      </div>
      <div className="pine-body">
        <textarea
          aria-label="Mã Pine" spellCheck={false} value={src}
          onChange={(e) => { setSrc(e.target.value); save('pine.src', e.target.value) }}
          onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); void run() } }}
        />
        <div className="pine-side">
          {note && <p className="mute">{note}</p>}
          {err && <p className="status bad" role="alert">{err.line ? `Dòng ${err.line}: ` : ''}{err.message}</p>}
          {res && res.inputs.length > 0 && (
            <div className="pine-inputs">
              <b>Tham số</b>
              {res.inputs.map((d) => (
                <label key={d.title}>{d.title}
                  {d.type === 'bool' ? (
                    <input type="checkbox" checked={Boolean(inputs[d.title] ?? d.default)}
                      onChange={(e) => { const n = { ...inputs, [d.title]: e.target.checked }; setInputs(n); void run(n) }} />
                  ) : (
                    <input type={d.type === 'int' || d.type === 'float' ? 'number' : 'text'} value={String(inputs[d.title] ?? d.default ?? '')}
                      step={d.type === 'float' ? (d.step ?? 0.1) : 1} min={d.minval} max={d.maxval}
                      onChange={(e) => setInputs({ ...inputs, [d.title]: d.type === 'int' || d.type === 'float' ? Number(e.target.value) : e.target.value })}
                      onBlur={() => void run()} />
                  )}
                </label>
              ))}
            </div>
          )}
          {st && (
            <table className="pine-stats">
              <tbody>
                <tr><td>Lãi ròng</td><td>{st.net_profit.toFixed(2)}</td></tr>
                <tr><td>Số lệnh đã đóng</td><td>{st.closed_trades}</td></tr>
                <tr><td>Tỉ lệ thắng</td><td>{(st.win_rate * 100).toFixed(1)}%</td></tr>
                <tr><td>Sụt vốn tối đa</td><td>{(st.max_drawdown * 100).toFixed(1)}%</td></tr>
              </tbody>
            </table>
          )}
          {res && res.alerts.length > 0 && (
            <p className="mute">Cảnh báo: {res.alerts.map((a) => `${a.title} (${a.bars.length} lần)`).join(', ')}</p>
          )}
        </div>
      </div>
    </section>
  )
}
