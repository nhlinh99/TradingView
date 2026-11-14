import { useEffect, useState } from 'react'

type Health = { status: string; duckdb?: string; data_dir?: string; detail?: string }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    fetch('/api/health', { signal: ctrl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json() as Promise<Health>
      })
      .then(setHealth)
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setError(String(e))
      })
    return () => ctrl.abort()
  }, [])

  let line: string
  let cls = 'wait'
  if (error) {
    line = `Không gọi được server: ${error}`
    cls = 'bad'
  } else if (!health) {
    line = 'Đang kiểm tra server...'
  } else if (health.status === 'ok') {
    line = 'server OK'
    cls = 'ok'
  } else {
    line = `Server lỗi cấu hình: ${health.detail ?? health.status}`
    cls = 'bad'
  }

  return (
    <main>
      <h1>Chart cá nhân</h1>
      <p className={`status ${cls}`} data-testid="server-status" role="status">
        {line}
      </p>
      {health?.status === 'ok' && (
        <dl>
          <dt>DuckDB</dt>
          <dd>{health.duckdb}</dd>
          <dt>Thư mục dữ liệu</dt>
          <dd>{health.data_dir}</dd>
        </dl>
      )}
    </main>
  )
}
