import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icons'
import { NEW_SCRIPT, isStrategy, scriptName, type Indicator, type LibraryScript } from './indicators'

type Props = {
  library: LibraryScript[]
  list: Indicator[]
  fav: string[]
  onToggleFav: (name: string) => void
  onAdd: (source: string, name?: string) => string
  onClose: () => void
  onOpenEditor: () => void
}

type Section = 'all' | 'fav' | 'mine' | 'ind' | 'strat'
const NAV: { id: Section; label: string; group: string }[] = [
  { id: 'all', label: 'Tất cả', group: 'Thư viện' },
  { id: 'fav', label: 'Yêu thích', group: 'Thư viện' },
  { id: 'mine', label: 'Script của tôi', group: 'Thư viện' },
  { id: 'ind', label: 'Chỉ báo có sẵn', group: 'Có sẵn' },
  { id: 'strat', label: 'Chiến lược có sẵn', group: 'Có sẵn' },
]

/** Tô sáng phần khớp với từ khoá tìm kiếm trong tên. */
function Hit({ text, q }: { text: string; q: string }) {
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1
  if (i < 0) return <>{text}</>
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>
}

/**
 * Hộp thoại thêm chỉ báo: ô tìm kiếm tự focus, thanh phân loại bên trái, danh sách bên phải. Bấm một dòng để thêm vào biểu đồ mà không đóng hộp,
 * nên thêm được nhiều chỉ báo liền nhau. Mũi tên chọn dòng, Enter thêm, Esc đóng.
 */
export default function IndicatorPicker({ library, list, fav, onToggleFav, onAdd, onClose, onOpenEditor }: Props) {
  const [q, setQ] = useState('')
  const [section, setSection] = useState<Section>('all')
  const [active, setActive] = useState(0)
  const [toast, setToast] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const box = useRef<HTMLUListElement>(null)

  useEffect(() => { input.current?.focus() }, [])
  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 2200)
    return () => window.clearTimeout(t)
  }, [toast])

  const items = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return library.filter((l) => {
      const name = l.name.replace(/_/g, ' ')
      if (needle && !name.toLowerCase().includes(needle)) return false
      if (section === 'fav') return fav.includes(l.name)
      if (section === 'mine') return l.mine
      if (section === 'ind') return !l.mine && !isStrategy(l.source)
      if (section === 'strat') return !l.mine && isStrategy(l.source)
      return true
    })
  }, [library, q, section, fav])
  const counts = useMemo(() => {
    const m = new Map<string, number>()
    for (const i of list) m.set(i.name, (m.get(i.name) ?? 0) + 1)
    return m
  }, [list])

  useEffect(() => { setActive(0) }, [q, section])
  useEffect(() => { box.current?.querySelector('li.on')?.scrollIntoView({ block: 'nearest' }) }, [active, items.length])

  const add = (l: LibraryScript) => { onAdd(l.source); setToast(`Đã thêm "${scriptName(l.source)}" vào biểu đồ`) }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    else if (e.key === 'Enter' && items[active]) { e.preventDefault(); add(items[active]) }
  }
  const groups = [...new Set(NAV.map((n) => n.group))]

  return (
    <div className="modal" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="picker" role="dialog" aria-modal="true" aria-label="Thêm chỉ báo" onKeyDown={onKey}>
        <header>
          <h2>Thêm chỉ báo và chiến lược</h2>
          <button className="ibtn" onClick={onClose} aria-label="Đóng" title="Đóng (Esc)"><Icon name="x" size={16} /></button>
        </header>
        <div className="psearch">
          <input ref={input} type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm theo tên script..." aria-label="Tìm script" />
        </div>
        <div className="pbody">
          <nav aria-label="Phân loại">
            {groups.map((g) => (
              <div key={g}>
                <h3>{g}</h3>
                {NAV.filter((n) => n.group === g).map((n) => (
                  <button key={n.id} className={section === n.id ? 'on' : ''} aria-current={section === n.id} onClick={() => setSection(n.id)}>
                    {n.label}
                    {n.id === 'fav' && fav.length > 0 && <span className="count">{fav.length}</span>}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <ul ref={box} className="plist" role="listbox" aria-label="Danh sách script">
            {items.map((l, i) => {
              const n = counts.get(scriptName(l.source)) ?? 0
              const isFav = fav.includes(l.name)
              return (
                <li key={`${l.mine}-${l.name}`} role="option" aria-selected={i === active} className={i === active ? 'on' : ''}
                  onMouseMove={() => { if (active !== i) setActive(i) }}>
                  <button className="pitem" onClick={() => add(l)} title="Thêm vào biểu đồ">
                    <span className="pname"><Hit text={l.name.replace(/_/g, ' ')} q={q.trim()} /></span>
                    <em className={isStrategy(l.source) ? 'tag strat' : 'tag'}>{isStrategy(l.source) ? 'chiến lược' : 'chỉ báo'}</em>
                    {l.mine && <em className="tag mine">của tôi</em>}
                    {n > 0 && <span className="added" title={`Đang có ${n} trên biểu đồ`}>✓ {n > 1 ? `×${n}` : ''}</span>}
                  </button>
                  <button className={`ibtn star ${isFav ? 'on' : ''}`} aria-pressed={isFav} aria-label={`${isFav ? 'Bỏ' : 'Thêm'} ${l.name} ${isFav ? 'khỏi' : 'vào'} yêu thích`}
                    title={isFav ? 'Bỏ yêu thích' : 'Thêm vào yêu thích'} onClick={() => onToggleFav(l.name)}><Icon name="star" size={15} /></button>
                </li>
              )
            })}
            {items.length === 0 && (
              <li className="pempty">
                {section === 'fav' && !q ? 'Chưa có script yêu thích. Bấm ngôi sao ở một script để ghim nó vào đây.' : 'Không có script nào khớp.'}
              </li>
            )}
          </ul>
        </div>
        <footer>
          <button onClick={() => { onAdd(NEW_SCRIPT); onClose(); onOpenEditor() }}><Icon name="plus" size={14} /> Script mới</button>
          <button onClick={() => { onClose(); onOpenEditor() }}><Icon name="code" size={14} /> Soạn mã</button>
          <span className="ptoast" role="status">{toast}</span>
          <span className="phint"><kbd>↑</kbd> <kbd>↓</kbd> chọn · <kbd>Enter</kbd> thêm · <kbd>Esc</kbd> đóng</span>
        </footer>
      </div>
    </div>
  )
}
