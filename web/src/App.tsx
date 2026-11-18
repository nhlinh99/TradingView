import { useCallback, useEffect, useRef, useState } from 'react'
import Chart, { type Flow } from './Chart'
import IndicatorDock from './IndicatorDock'
import IndicatorLegend from './IndicatorLegend'
import IndicatorPicker from './IndicatorPicker'
import { useIndicators, visibleResults } from './indicators'
import FlowMenu from './FlowMenu'
import SymbolSearch from './SymbolSearch'
import AlertsPanel from './AlertsPanel'
import { SyncBus } from './sync'
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
    heatMode: pref('heatMode', 'bookmap', ['intensity', 'side', 'bookmap']) as Flow['heatMode'],
    heatLo: Number(pref('heatLo', '5', ['0', '5', '10', '20', '30', '40', '50'])),
    heatHi: Number(pref('heatHi', '100', ['40', '50', '60', '70', '80', '90', '100'])),
    bestLines: pref('bestLines', '1', ['0', '1']) === '1',
    strip: pref('strip', '1', ['0', '1']) === '1',
    dotScale: Number(pref('dotScale', '100', ['50', '75', '100', '150', '200', '300'])),
    dotMin: Number(pref('dotMin', '0', ['0', '2', '5', '10', '20'])),
    iceberg: pref('iceberg', '0', ['0', '1']) === '1',
    fpMode: pref('fpMode', 'bidask', ['bidask', 'delta', 'volume', 'profile']) as Flow['fpMode'],
  }))
  const setF = (patch: Partial<Flow>) => setFlow((f) => {
    const n = { ...f, ...patch }
    savePref('delta', n.delta ? '1' : '0'); savePref('cvd', n.cvd); savePref('footprint', n.footprint ? '1' : '0'); savePref('ratio', String(n.ratio)); savePref('vpvr', n.vpvr ? '1' : '0'); savePref('heatmap', n.heatmap ? '1' : '0'); savePref('bubbles', n.bubbles ? '1' : '0'); savePref('gex', n.gex ? '1' : '0'); savePref('heatMode', n.heatMode); savePref('heatLo', String(n.heatLo)); savePref('heatHi', String(n.heatHi)); savePref('bestLines', n.bestLines ? '1' : '0'); savePref('strip', n.strip ? '1' : '0'); savePref('dotScale', String(n.dotScale)); savePref('dotMin', String(n.dotMin)); savePref('iceberg', n.iceberg ? '1' : '0'); savePref('fpMode', n.fpMode)
    return n
  })
  const [layout, setLayout] = useState(() => Number(pref('layout', '1', ['1', '2', '4'])))
  const [cells, setCells] = useState<{ symbol: string; tf: string }[]>(() => {
    try { const j = JSON.parse(localStorage.getItem('cells') ?? '[]'); return Array.isArray(j) ? j : [] } catch { return [] }
  })
  const sync = useRef(new SyncBus())
  const [dragOver, setDragOver] = useState<string | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [replay, setReplay] = useState<number | null>(null)
  const [total, setTotal] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(2)
  const ind = useIndicators(symbol, tf)
  const [selectedInd, setSelectedInd] = useState<string | null>(null)
  const [alertsOpen, setAlertsOpen] = useState(() => pref('alertsOpen', '0', ['0', '1']) === '1')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [dockOpen, setDockOpen] = useState(() => pref('dockOpen', '0', ['0', '1']) === '1')
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
  useEffect(() => { setReplay(null); setPlaying(false) }, [symbol, tf])
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
  const pickSymbol = (s: string) => {
    if (!watch.includes(s)) void update([...watch, s])
    choose(s)
    setSearchOpen(false)
  }
  // phím tắt: / hoặc Ctrl+K tìm symbol; [ ] đổi khung; T đổi giao diện; ? xem danh sách phím
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const typing = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setSearchOpen(true); return }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === '/') { e.preventDefault(); setSearchOpen(true) }
      else if (e.key === '?') { setHelpOpen((v) => !v) }
      else if (e.key.toLowerCase() === 'i') { e.preventDefault(); setPickerOpen(true) }
      else if (e.key === 'Escape') { setHelpOpen(false) }
      else if (e.key === '[' || e.key === ']') {
        const i = TIMEFRAMES.indexOf(tf as (typeof TIMEFRAMES)[number])
        const n = TIMEFRAMES[Math.max(0, Math.min(TIMEFRAMES.length - 1, i + (e.key === ']' ? 1 : -1)))]
        setTf(n); savePref('tf', n)
      } else if (e.key.toLowerCase() === 't') {
        setTheme((t) => { const n = t === 'dark' ? 'light' : 'dark'; savePref('theme', n); return n })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tf])
  const onState = useCallback((s: StreamState) => setState(s), [])

  if (err && !symbol) return <main className="page"><p className="status bad" role="alert">Lỗi: {err}</p></main>

  return (
    <div className="app">
      <aside className="side" aria-label="Danh sách theo dõi">
        <h2>Theo dõi</h2>
        <ul>
          {watch.map((s) => (
            <li key={s} className={`${s === symbol ? 'on' : ''} ${dragOver === s ? 'over' : ''}`} draggable
              onDragStart={(e) => { e.dataTransfer.setData('text/plain', s); e.dataTransfer.effectAllowed = 'move' }}
              onDragOver={(e) => { e.preventDefault(); setDragOver(s) }}
              onDragLeave={() => setDragOver((d) => (d === s ? null : d))}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(null)
                const from = e.dataTransfer.getData('text/plain')
                if (!from || from === s || !watch.includes(from)) return
                const next = watch.filter((x) => x !== from)
                next.splice(next.indexOf(s), 0, from)
                void update(next)
              }}>
              <span className="grip" aria-hidden="true" title="Kéo để sắp xếp">⋮⋮</span>
              <button className="sym" onClick={() => choose(s)} aria-current={s === symbol}>{s}</button>
              <button className="x" onClick={() => remove(s)} aria-label={`Bỏ ${s}`} disabled={watch.length <= 1}>×</button>
            </li>
          ))}
        </ul>
        <button className="addsym" onClick={() => setSearchOpen(true)} title="Tìm hoặc thêm symbol (phím /)">+ Tìm / thêm <kbd>/</kbd></button>
        <button className="addsym help" onClick={() => setHelpOpen(true)} title="Phím tắt (phím ?)">Phím tắt <kbd>?</kbd></button>
      </aside>

      <section className="main">
        <header className="bar">
          <div className="titlebox">
            <h1>{symbol || '...'}</h1>
            <span className={`live ${state}`} role="status" data-testid="stream-state">{STATE_LABEL[state]}</span>
          </div>
          <div className="seg tfs" role="group" aria-label="Khung thời gian">
            {TIMEFRAMES.map((t) => (
              <button key={t} className={t === tf ? 'on' : ''} aria-pressed={t === tf}
                onClick={() => { setTf(t); savePref('tf', t) }}>{t}</button>
            ))}
          </div>
          <FlowMenu flow={flow} setF={setF} symbol={symbol} isVn={all.find((s) => s.symbol === symbol)?.source === 'vn'} />
          <div className="seg" role="group" aria-label="Bố cục">
            {[1, 2, 4].map((n) => (
              <button key={n} className={layout === n ? 'on' : ''} aria-pressed={layout === n} title={`${n} biểu đồ`}
                onClick={() => { setLayout(n); savePref('layout', String(n)) }}>{n === 1 ? '▢' : n === 2 ? '◫' : '▦'}</button>
            ))}
          </div>
          <div className="spacer" />
          <label className="tz" title="Múi giờ hiển thị">
            <select aria-label="Múi giờ" value={tz} onChange={(e) => { setTz(e.target.value); savePref('tz', e.target.value) }}>
              {TIMEZONES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </label>
          <div className="seg" role="group" aria-label="Công cụ">
            <button aria-pressed={replay !== null} title="Phát lại từng nến" onClick={() => { setPlaying(false); setReplay((r) => (r === null ? Math.max(2, total - 100) : null)) }}>Replay</button>
            <button aria-pressed={alertsOpen} title="Cảnh báo giá" onClick={() => { const n = !alertsOpen; setAlertsOpen(n); savePref('alertsOpen', n ? '1' : '0') }}>Cảnh báo</button>
            <button aria-pressed={pickerOpen} aria-haspopup="dialog" title="Thêm chỉ báo (phím I)" onClick={() => setPickerOpen(true)}>
              Chỉ báo{ind.list.length > 0 && <span className="badge">{ind.list.length}</span>}
            </button>
          </div>
          <button className="iconbtn" aria-label="Đổi giao diện sáng/tối" title={theme === 'dark' ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
            onClick={() => { const n = theme === 'dark' ? 'light' : 'dark'; setTheme(n); savePref('theme', n) }}>
            {theme === 'dark' ? '☀' : '☾'}
          </button>
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
        {symbol === 'XAUUSD' && (
          <p className="srcnote">Bookmap, chấm volume và iceberg của XAUUSD lấy từ sổ lệnh và lệnh khớp của hợp đồng XAUUSDT (Binance), dịch giá theo chênh lệch hiện tại giữa hai mã. Đây là ước lượng, không phải sổ lệnh của vàng spot. Cuối tuần thị trường gốc nghỉ nhưng hợp đồng vẫn khớp lệnh.</p>
        )}
        {symbol === 'XAUUSDT' && (
          <p className="srcnote">Volume và orderflow của hợp đồng Binance (XAUUSDT, tính theo oz), không phải COMEX. Cuối tuần thị trường gốc nghỉ nhưng hợp đồng vẫn khớp lệnh.</p>
        )}
        {symbol && (
          <div className={`cells cells-${layout}`}>
            <div className="cell">
              <Chart symbol={symbol} tf={tf} tz={tz} flow={flow} pines={visibleResults(ind.list, ind.runs, tf)} indLegend={<IndicatorLegend list={ind.list} runs={ind.runs} onToggle={ind.toggle} onRemove={ind.remove} tf={tf}
                onPatch={(id, p, rerun) => ind.update(id, p, rerun ?? false)} onDuplicate={(id) => { ind.duplicate(id) }}
                onEdit={(id) => { setSelectedInd(id); setDockOpen(true); savePref('dockOpen', '1') }}
                onAdd={() => setPickerOpen(true)} />} replay={replay} onTotal={setTotal} sync={sync.current} cellId={0} theme={theme} onState={onState} />
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
                <Chart key={`${c.symbol}|${c.tf}`} symbol={c.symbol} tf={c.tf} tz={tz} flow={flow} pines={[]} replay={null} onTotal={() => {}} sync={sync.current} cellId={i + 1} theme={theme} onState={() => {}} />
              </div>
            ))}
          </div>
        )}
        {err && <p className="status bad" role="alert">{err}</p>}
        {alertsOpen && symbol && <AlertsPanel symbol={symbol} lastPrice={null} />}
        {dockOpen && symbol && (
          <IndicatorDock symbol={symbol} tf={tf} list={ind.list} runs={ind.runs} library={ind.library}
            selected={selectedInd ?? ind.list[0]?.id ?? null} onSelect={setSelectedInd} onAdd={ind.add} onUpdate={ind.update}
            onToggle={ind.toggle} onRemove={ind.remove} onSave={ind.saveToLibrary} onDeleteLib={ind.removeFromLibrary}
            onClose={() => { setDockOpen(false); savePref('dockOpen', '0') }} />
        )}
      </section>
      {pickerOpen && (
        <IndicatorPicker library={ind.library} list={ind.list} fav={ind.fav} onToggleFav={ind.toggleFav}
          onAdd={(src, name) => { const id = ind.add(src, name); setSelectedInd(id); return id }}
          onClose={() => setPickerOpen(false)} onOpenEditor={() => { setDockOpen(true); savePref('dockOpen', '1') }} />
      )}
      {searchOpen && <SymbolSearch all={all} watch={watch} current={symbol} onPick={pickSymbol} onClose={() => setSearchOpen(false)} />}
      {helpOpen && (
        <div className="modal" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setHelpOpen(false) }}>
          <div className="palette help" role="dialog" aria-label="Phím tắt">
            <h2>Phím tắt</h2>
            <dl>
              <dt><kbd>/</kbd> hoặc <kbd>Ctrl</kbd>+<kbd>K</kbd></dt><dd>Tìm hoặc thêm symbol</dd>
              <dt><kbd>[</kbd> <kbd>]</kbd></dt><dd>Khung thời gian nhỏ hơn / lớn hơn</dd>
              <dt><kbd>T</kbd></dt><dd>Đổi giao diện sáng/tối</dd>
              <dt><kbd>I</kbd></dt><dd>Mở hộp thêm chỉ báo (tìm, bấm để thêm, mũi tên và Enter)</dd>
              <dt><kbd>?</kbd></dt><dd>Mở hoặc đóng bảng này</dd>
              <dt><kbd>Esc</kbd></dt><dd>Đóng bảng đang mở</dd>
              <dt><kbd>Ctrl</kbd>+<kbd>Enter</kbd></dt><dd>Áp dụng mã đang sửa trong bảng chỉ báo</dd>
            </dl>
          </div>
        </div>
      )}
    </div>
  )
}
