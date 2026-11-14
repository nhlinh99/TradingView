import { useCallback, useEffect, useState } from 'react'
import Chart, { type Flow } from './Chart'
import { fetchSymbols, fetchWatchlist, saveWatchlist, type StreamState, type SymbolInfo } from './api'
import { TIMEFRAMES, TIMEZONES } from './logic'

// Cài đặt nhỏ của người xem: nhớ trong trình duyệt, không có thì dùng mặc định.
function pref(key: string, fallback: string, allowed: readonly string[]): string {
  try {
    const v = localStorage.getItem(key)
    return v && allowed.includes(v) ? v : fallback
  } catch {
    return fallback
  }
}
function savePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* bị chặn: bỏ qua */
  }
}

const STATE_LABEL: Record<StreamState, string> = {
  connecting: 'Đang kết nối', connected: 'Trực tiếp', reconnecting: 'Mất kết nối, đang nối lại',
}

export default function App() {
  const [all, setAll] = useState<SymbolInfo[]>([])
  const [watch, setWatch] = useState<string[]>([])
  const [symbol, setSymbol] = useState('')
  const [tf, setTf] = useState(() => pref('tf', '1m', TIMEFRAMES))
  const [tz, setTz] = useState(() => pref('tz', 'UTC', TIMEZONES.map((t) => t.id)))
  const [theme, setTheme] = useState(() =>
    pref('theme', window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', ['light', 'dark']) as 'light' | 'dark')
  const [flow, setFlow] = useState<Flow>(() => ({
    delta: pref('delta', '0', ['0', '1']) === '1',
    cvd: pref('cvd', 'off', ['off', 'none', 'day']) as Flow['cvd'],
    footprint: pref('footprint', '0', ['0', '1']) === '1',
    gex: pref('gex', '0', ['0', '1']) === '1',
    bubbles: pref('bubbles', '0', ['0', '1']) === '1',
    heatmap: pref('heatmap', '0', ['0', '1']) === '1',
    vpvr: pref('vpvr', '0', ['0', '1']) === '1',
    ratio: Number(pref('ratio', '3', ['2', '3', '4', '5'])),
  }))
  const setF = (patch: Partial<Flow>) => setFlow((f) => {
    const n = { ...f, ...patch }
    savePref('delta', n.delta ? '1' : '0'); savePref('cvd', n.cvd); savePref('footprint', n.footprint ? '1' : '0'); savePref('ratio', String(n.ratio)); savePref('vpvr', n.vpvr ? '1' : '0'); savePref('heatmap', n.heatmap ? '1' : '0'); savePref('bubbles', n.bubbles ? '1' : '0'); savePref('gex', n.gex ? '1' : '0')
    return n
  })
  const [state, setState] = useState<StreamState>('connecting')
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([fetchSymbols(), fetchWatchlist()])
      .then(([s, w]) => {
        setAll(s)
        setWatch(w)
        const saved = pref('symbol', w[0] ?? '', w)
        setSymbol(saved || w[0] || '')
      })
      .catch((e: unknown) => setErr(String(e)))
  }, [])

  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  const choose = (s: string) => { setSymbol(s); savePref('symbol', s) }
  const update = async (next: string[]) => {
    try {
      setWatch(await saveWatchlist(next))
    } catch (e) {
      setErr(String(e))
    }
  }
  const remove = (s: string) => {
    const next = watch.filter((x) => x !== s)
    if (next.length === 0) return // luôn giữ ít nhất một symbol
    void update(next)
    if (s === symbol) choose(next[0])
  }
  const addable = all.filter((s) => !watch.includes(s.symbol))
  const onState = useCallback((s: StreamState) => setState(s), [])

  if (err && !symbol) return <main className="page"><p className="status bad" role="alert">Lỗi: {err}</p></main>

  return (
    <div className="app">
      <aside className="side" aria-label="Danh sách theo dõi">
        <h2>Theo dõi</h2>
        <ul>
          {watch.map((s) => (
            <li key={s} className={s === symbol ? 'on' : ''}>
              <button className="sym" onClick={() => choose(s)} aria-current={s === symbol}>{s}</button>
              <button className="x" onClick={() => remove(s)} aria-label={`Bỏ ${s}`} disabled={watch.length <= 1}>×</button>
            </li>
          ))}
        </ul>
        {addable.length > 0 && (
          <select aria-label="Thêm symbol" value="" onChange={(e) => e.target.value && void update([...watch, e.target.value])}>
            <option value="">+ Thêm symbol</option>
            {addable.map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol}</option>)}
          </select>
        )}
      </aside>

      <section className="main">
        <header className="bar">
          <h1>{symbol || '...'}</h1>
          <div className="tfs" role="group" aria-label="Khung thời gian">
            {TIMEFRAMES.map((t) => (
              <button key={t} className={t === tf ? 'on' : ''} aria-pressed={t === tf}
                onClick={() => { setTf(t); savePref('tf', t) }}>{t}</button>
            ))}
          </div>
          <label className="tz">Múi giờ
            <select value={tz} onChange={(e) => { setTz(e.target.value); savePref('tz', e.target.value) }}>
              {TIMEZONES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </label>
          <div className="opts" role="group" aria-label="Orderflow">
            <label><input type="checkbox" checked={flow.footprint} onChange={(e) => setF({ footprint: e.target.checked })} />Footprint</label>
            <label><input type="checkbox" checked={flow.heatmap} onChange={(e) => setF({ heatmap: e.target.checked })} />Heatmap</label>
            <label><input type="checkbox" checked={flow.bubbles} onChange={(e) => setF({ bubbles: e.target.checked })} />Bong bóng</label>
            <label><input type="checkbox" checked={flow.gex} onChange={(e) => setF({ gex: e.target.checked })} />GEX</label>
            <label><input type="checkbox" checked={flow.vpvr} onChange={(e) => setF({ vpvr: e.target.checked })} />VPVR</label>
            <label><input type="checkbox" checked={flow.delta} onChange={(e) => setF({ delta: e.target.checked })} />Delta</label>
            <label>CVD
              <select value={flow.cvd} onChange={(e) => setF({ cvd: e.target.value as Flow['cvd'] })} aria-label="CVD">
                <option value="off">Tắt</option><option value="none">Liên tục</option><option value="day">Reset theo ngày</option>
              </select>
            </label>
            {flow.footprint && (
              <label>Imbalance
                <select value={flow.ratio} onChange={(e) => setF({ ratio: Number(e.target.value) })} aria-label="Ngưỡng imbalance">
                  {[2, 3, 4, 5].map((r) => <option key={r} value={r}>{r}:1</option>)}
                </select>
              </label>
            )}
          </div>
          <button className="themebtn" aria-label="Đổi giao diện sáng/tối"
            onClick={() => { const n = theme === 'dark' ? 'light' : 'dark'; setTheme(n); savePref('theme', n) }}>
            {theme === 'dark' ? 'Sáng' : 'Tối'}
          </button>
          <span className={`live ${state}`} role="status" data-testid="stream-state">{STATE_LABEL[state]}</span>
        </header>
        {symbol.startsWith('XAU') && (
          <p className="srcnote">Volume và orderflow của hợp đồng Binance (XAUUSDT, tính theo oz), không phải COMEX. Cuối tuần thị trường gốc nghỉ nhưng hợp đồng vẫn khớp lệnh.</p>
        )}
        {symbol && <Chart symbol={symbol} tf={tf} tz={tz} flow={flow} theme={theme} onState={onState} />}
        {err && <p className="status bad" role="alert">{err}</p>}
      </section>
    </div>
  )
}
