import { useCallback, useEffect, useRef, useState } from 'react'
import Chart, { type Flow } from './Chart'
import PinePanel from './PinePanel'
import AlertsPanel from './AlertsPanel'
import { SyncBus } from './sync'
import { fetchSymbols, fetchWatchlist, saveWatchlist, type PineResult, type StreamState, type SymbolInfo } from './api'
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
  const [layout, setLayout] = useState(() => Number(pref('layout', '1', ['1', '2', '4'])))
  const [cells, setCells] = useState<{ symbol: string; tf: string }[]>(() => {
    try { const j = JSON.parse(localStorage.getItem('cells') ?? '[]'); return Array.isArray(j) ? j : [] } catch { return [] }
  })
  const sync = useRef(new SyncBus())
  const [replay, setReplay] = useState<number | null>(null)
  const [total, setTotal] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(2)
  const [pine, setPine] = useState<PineResult | null>(null)
  const [alertsOpen, setAlertsOpen] = useState(() => pref('alertsOpen', '0', ['0', '1']) === '1')
  const [pineOpen, setPineOpen] = useState(() => pref('pineOpen', '0', ['0', '1']) === '1')
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
  useEffect(() => { setPine(null); setReplay(null); setPlaying(false) }, [symbol, tf])
  useEffect(() => {
    if (!playing || replay === null) return
    const t = window.setInterval(() => setReplay((r) => (r === null ? r : Math.min(total, r + 1))), 1000 / speed)
    return () => window.clearInterval(t)
  }, [playing, speed, total, replay === null])
  useEffect(() => { if (replay !== null && replay >= total) setPlaying(false) }, [replay, total]) // kết quả Pine chỉ đúng với symbol và khung đã chạy
  // ô phụ: tự điền bằng các symbol trong watchlist khi chưa có
  const extra = Array.from({ length: Math.max(0, layout - 1) }, (_, i) => cells[i] ?? { symbol: watch[(i + 1) % Math.max(1, watch.length)] ?? symbol, tf })
  const setCell = (i: number, patch: Partial<{ symbol: string; tf: string }>) => {
    const next = extra.map((c, k) => (k === i ? { ...c, ...patch } : c))
    setCells(next)
    try { localStorage.setItem('cells', JSON.stringify(next)) } catch { /* bị chặn: bỏ qua */ }
  }
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
          <label className="tz">Layout
            <select value={layout} onChange={(e) => { setLayout(Number(e.target.value)); savePref('layout', e.target.value) }}>
              <option value={1}>1 ô</option><option value={2}>2 ô</option><option value={4}>4 ô</option>
            </select>
          </label>
          <button className="themebtn" aria-pressed={replay !== null} onClick={() => { setPlaying(false); setReplay((r) => (r === null ? Math.max(2, total - 100) : null)) }}>Replay</button>
          <button className="themebtn" aria-pressed={alertsOpen} onClick={() => { const n = !alertsOpen; setAlertsOpen(n); savePref('alertsOpen', n ? '1' : '0') }}>Cảnh báo</button>
          <button className="themebtn" aria-pressed={pineOpen} onClick={() => { const n = !pineOpen; setPineOpen(n); savePref('pineOpen', n ? '1' : '0') }}>Pine</button>
          <button className="themebtn" aria-label="Đổi giao diện sáng/tối"
            onClick={() => { const n = theme === 'dark' ? 'light' : 'dark'; setTheme(n); savePref('theme', n) }}>
            {theme === 'dark' ? 'Sáng' : 'Tối'}
          </button>
          <span className={`live ${state}`} role="status" data-testid="stream-state">{STATE_LABEL[state]}</span>
        </header>
        {replay !== null && (
          <div className="replaybar" role="group" aria-label="Phát lại nến">
            <b>Replay</b>
            <button onClick={() => setReplay((r) => Math.max(2, (r ?? 2) - 1))} aria-label="Lùi một nến">◀</button>
            <button className={playing ? 'on' : ''} onClick={() => setPlaying((p) => !p)} aria-pressed={playing}>{playing ? 'Tạm dừng' : 'Phát'}</button>
            <button onClick={() => setReplay((r) => Math.min(total, (r ?? 2) + 1))} aria-label="Tiến một nến">▶</button>
            <input type="range" aria-label="Vị trí phát lại" min={2} max={Math.max(2, total)} value={replay} onChange={(e) => setReplay(Number(e.target.value))} />
            <span className="mute">{replay}/{total} nến</span>
            <label className="chk">Tốc độ
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                {[1, 2, 5, 10, 30].map((s) => <option key={s} value={s}>{s} nến/giây</option>)}
              </select>
            </label>
            <button onClick={() => { setReplay(null); setPlaying(false) }}>Thoát</button>
          </div>
        )}
        {symbol.startsWith('XAU') && (
          <p className="srcnote">Volume và orderflow của hợp đồng Binance (XAUUSDT, tính theo oz), không phải COMEX. Cuối tuần thị trường gốc nghỉ nhưng hợp đồng vẫn khớp lệnh.</p>
        )}
        {all.find((s) => s.symbol === symbol)?.source === 'vn' && (
          <p className="srcnote">Cổ phiếu VN100 (HOSE), nến từ VNDirect, giá nghìn đồng, đã điều chỉnh. Chưa có phía mua/bán nên delta và CVD bằng 0; không có tick, chỉ có khung từ 1 phút.</p>
        )}
        {symbol && (
          <div className={`cells cells-${layout}`}>
            <div className="cell">
              <Chart symbol={symbol} tf={tf} tz={tz} flow={flow} pine={pine} replay={replay} onTotal={setTotal} sync={sync.current} cellId={0} theme={theme} onState={onState} />
            </div>
            {extra.map((c, i) => (
              <div className="cell" key={i}>
                <div className="cellbar">
                  <select aria-label={`Symbol ô ${i + 2}`} value={c.symbol} onChange={(e) => setCell(i, { symbol: e.target.value })}>
                    {all.map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol}</option>)}
                  </select>
                  <select aria-label={`Khung ô ${i + 2}`} value={c.tf} onChange={(e) => setCell(i, { tf: e.target.value })}>
                    {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <Chart key={`${c.symbol}|${c.tf}`} symbol={c.symbol} tf={c.tf} tz={tz} flow={flow} pine={null} replay={null} onTotal={() => {}} sync={sync.current} cellId={i + 1} theme={theme} onState={() => {}} />
              </div>
            ))}
          </div>
        )}
        {err && <p className="status bad" role="alert">{err}</p>}
        {alertsOpen && symbol && <AlertsPanel symbol={symbol} lastPrice={null} />}
        {pineOpen && symbol && <PinePanel key={`${symbol}|${tf}`} symbol={symbol} tf={tf} onResult={setPine} />}
      </section>
    </div>
  )
}
