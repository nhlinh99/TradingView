import { useCallback, useEffect, useState } from 'react'
import { createAlert, deleteAlert, fetchAlertEvents, fetchAlerts, setAlertEnabled, type AlertEvent, type AlertItem } from './api'

type Props = { symbol: string; lastPrice: number | null }

/** Tạo và quản lý cảnh báo giá. Việc kiểm tra và gửi thông báo do tiến trình nền `collector.alerts` làm, không cần mở trang này. */
export default function AlertsPanel({ symbol, lastPrice }: Props) {
  const [items, setItems] = useState<AlertItem[]>([])
  const [events, setEvents] = useState<AlertEvent[]>([])
  const [kind, setKind] = useState<'price>=' | 'price<=' | 'cross'>('price>=')
  const [value, setValue] = useState('')
  const [once, setOnce] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setItems(await fetchAlerts())
      setEvents(await fetchAlertEvents())
      setErr(null)
    } catch (e) { setErr(String(e)) }
  }, [])
  useEffect(() => {
    void reload()
    const t = window.setInterval(() => void reload(), 15_000)
    return () => window.clearInterval(t)
  }, [reload])

  const add = async () => {
    const v = Number(value)
    if (!Number.isFinite(v)) { setErr('Nhập mức giá là một số'); return }
    const condition = kind === 'cross' ? { type: 'cross', level: v, dir: 'any', once } : { type: 'price', op: kind === 'price>=' ? '>=' : '<=', value: v, once }
    try {
      await createAlert(symbol, condition)
      setValue('')
      await reload()
    } catch (e) { setErr((e as { detail?: unknown }).detail ? JSON.stringify((e as { detail: unknown }).detail) : String(e)) }
  }

  return (
    <section className="alerts" aria-label="Cảnh báo">
      <div className="pine-bar">
        <b>Cảnh báo {symbol}</b>
        <select aria-label="Loại cảnh báo" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="price>=">Giá lên tới</option>
          <option value="price<=">Giá xuống tới</option>
          <option value="cross">Giá cắt mức</option>
        </select>
        <input aria-label="Mức giá" type="number" step="any" value={value} placeholder={lastPrice ? String(lastPrice) : 'giá'} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void add() }} />
        <label className="chk"><input type="checkbox" checked={once} onChange={(e) => setOnce(e.target.checked)} />Một lần</label>
        <button className="primary" onClick={() => void add()}>Tạo cảnh báo</button>
        <span className="mute">Thông báo gửi bởi tiến trình nền (desktop, Telegram nếu có khoá trong .env)</span>
      </div>
      {err && <p className="status bad" role="alert">{err}</p>}
      <div className="alerts-body">
        <table className="pine-stats">
          <tbody>
            {items.length === 0 && <tr><td className="mute">Chưa có cảnh báo.</td></tr>}
            {items.map((a) => (
              <tr key={a.id}>
                <td>{a.text}{a.condition.triggered_at ? ' · đã bắn' : ''}</td>
                <td><label className="chk"><input type="checkbox" checked={a.enabled} onChange={(e) => void setAlertEnabled(a.id, e.target.checked).then(reload)} />Bật</label></td>
                <td><button onClick={() => void deleteAlert(a.id).then(reload)}>Xoá</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mute">
          {events.slice(0, 5).map((e) => (
            <div key={e.id}>{new Date(e.ts).toLocaleString()} · {e.message} · gửi: {e.sent || 'không kênh nào'}</div>
          ))}
        </div>
      </div>
    </section>
  )
}
