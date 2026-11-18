import type { ReactElement } from 'react'
import type { ISeriesApi } from 'lightweight-charts'
import { FIBX_LEVELS, FIB_LEVELS, distToSegment, type Bar, type DrawKind, type DrawPoint } from './logic'

/** Registry công cụ vẽ: mỗi công cụ khai báo số điểm neo, cách vẽ và cách bấm trúng. Thêm công cụ mới chỉ cần thêm một mục vào REGISTRY. */

export type Pt = { x: number; y: number }
export type Geo = {
  s: ISeriesApi<'Candlestick'>
  times: number[]
  x: (time: number) => number
  time: (px: number) => number
  idx: (time: number) => number
}
export type Env = {
  ctx: CanvasRenderingContext2D
  g: Geo
  plotW: number
  h: number
  step: number
  ink: string
  dark: boolean
  bars: Bar[]
  preview: boolean
}
export type HitEnv = { g: Geo; bars: Bar[]; step: number; plotW: number }
export type Handle = Pt & { set: (pts: DrawPoint[], np: DrawPoint) => DrawPoint[] }

export type Group = 'line' | 'fib' | 'pitchfork' | 'gann' | 'position' | 'measure' | 'shape' | 'text'
export const GROUP_LABEL: Record<Group, string> = { line: 'Đường', fib: 'Fibonacci', pitchfork: 'Pitchfork', gann: 'Gann', position: 'Vị thế', measure: 'Đo', shape: 'Hình và bút', text: 'Chữ và ghi chú' }

export type ToolDef = {
  group: Group
  label: string
  title: string
  icon: ReactElement
  /** số điểm neo; brush có số điểm tuỳ ý (min..max) */
  min: number
  max: number
  /** true: hình dạng hộp, có 4 góc làm tay nắm */
  box?: boolean
  /** false: không có tay nắm, chỉ di chuyển cả hình (brush) */
  noHandles?: boolean
  /** true: hỏi người dùng nội dung văn bản khi vẽ xong */
  ask?: boolean
  /** true: dùng màu mức riêng, bỏ qua màu người dùng chọn */
  ownColors?: boolean
  draw: (e: Env, P: Pt[], D: DrawPoint[], text?: string) => void
  /** khoảng cách (px) từ điểm bấm tới hình; Infinity nếu không trúng */
  hit: (e: HitEnv, S: Pt[], D: DrawPoint[], px: number, py: number) => number
}

// ---------- tiện ích ----------

export const FIB_COLORS: Record<number, string> = {
  0: '#787b86', 0.236: '#f23645', 0.382: '#ff9800', 0.5: '#4caf50', 0.618: '#089981', 0.786: '#00bcd4', 1: '#787b86',
  1.272: '#9c27b0', 1.414: '#e91e63', 1.618: '#2962ff', 2: '#089981', 2.618: '#f23645', 3.618: '#9c27b0', 4.236: '#e91e63',
}
export const fmtPrice = (p: number) => p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: p < 1 ? 6 : 2 })
const fmtDiff = (d: number) => Math.abs(d).toFixed(Math.abs(d) < 1 ? 4 : 2)

export function fmtDuration(secs: number): string {
  secs = Math.abs(secs)
  if (secs >= 86400) return `${Math.floor(secs / 86400)}n ${Math.floor((secs % 86400) / 3600)}g`
  if (secs >= 3600) return `${Math.floor(secs / 3600)}g ${Math.floor((secs % 3600) / 60)}p`
  return `${Math.floor(secs / 60)}p`
}

const dot = (ctx: CanvasRenderingContext2D, p: Pt, r = 3) => { ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill() }
const seg = (ctx: CanvasRenderingContext2D, a: Pt, b: Pt) => { ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke() }
const dots = (ctx: CanvasRenderingContext2D, P: Pt[]) => { for (const p of P) dot(ctx, p) }

/** Điểm cách a một đoạn L theo hướng a -> b (để kéo dài tia ra ngoài khung vẽ; phần ngoài bị cắt). */
function far(a: Pt, b: Pt, L = 8000): Pt {
  const dx = b.x - a.x; const dy = b.y - a.y; const len = Math.hypot(dx, dy)
  return len < 1e-6 ? b : { x: a.x + (dx / len) * L, y: a.y + (dy / len) * L }
}
function distLine(px: number, py: number, a: Pt, b: Pt): number {
  const dx = b.x - a.x; const dy = b.y - a.y; const len = Math.hypot(dx, dy)
  return len < 1e-6 ? Math.hypot(px - a.x, py - a.y) : Math.abs(dy * (px - a.x) - dx * (py - a.y)) / len
}
const inBox = (px: number, py: number, a: Pt, b: Pt, pad = 6) =>
  px >= Math.min(a.x, b.x) - pad && px <= Math.max(a.x, b.x) + pad && py >= Math.min(a.y, b.y) - pad && py <= Math.max(a.y, b.y) + pad

/** Nhãn hai dòng, màu nền bg, căn giữa quanh cx, trên đỉnh y; luôn nằm trong khung. */
function tag(e: Env, l1: string, l2: string | null, cx: number, y: number, bg: string) {
  const { ctx } = e
  ctx.save()
  ctx.setLineDash([]); ctx.shadowBlur = 0
  ctx.font = 'bold 12px system-ui, sans-serif'
  const w1 = ctx.measureText(l1).width
  ctx.font = '11px system-ui, sans-serif'
  const w2 = l2 ? ctx.measureText(l2).width : 0
  const tw = Math.max(w1, w2) + 16
  const th = l2 ? 38 : 24
  const bx = Math.min(Math.max(cx - tw / 2, 2), Math.max(2, e.plotW - tw - 2))
  const by = Math.min(Math.max(y, 2), Math.max(2, e.h - th - 2))
  ctx.globalAlpha = 0.95; ctx.fillStyle = bg; ctx.fillRect(bx, by, tw, th); ctx.globalAlpha = 1
  ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.font = 'bold 12px system-ui, sans-serif'
  ctx.fillText(l1, bx + tw / 2, by + (l2 ? 11 : 12))
  if (l2) { ctx.font = '11px system-ui, sans-serif'; ctx.fillText(l2, bx + tw / 2, by + 27) }
  ctx.restore()
}

const UP = '#26a69a'
const DOWN = '#ef5350'

function measureTexts(e: Env, a: DrawPoint, b: DrawPoint) {
  const diff = b.price - a.price
  const pct = a.price !== 0 ? (diff / a.price) * 100 : 0
  const nb = Math.round(e.g.idx(b.time) - e.g.idx(a.time))
  const sign = diff >= 0 ? '+' : '−'
  return {
    up: diff >= 0,
    l1: `${sign}${Math.abs(pct).toFixed(2)}%   ${sign}${fmtDiff(diff)}`,
    l2: `${Math.abs(nb)} nến · ${fmtDuration(b.time - a.time)}`,
  }
}

function drawFib(e: Env, levels: number[], priceOf: (lv: number) => number, x0: number, x1: number) {
  const { ctx, g } = e
  const ys = levels.map((lv) => g.s.priceToCoordinate(priceOf(lv)))
  ctx.lineWidth = 1; ctx.shadowBlur = 0
  for (let i = 0; i < levels.length - 1; i++) {
    const ya = ys[i]; const yb = ys[i + 1]
    if (ya === null || yb === null) continue
    ctx.fillStyle = FIB_COLORS[levels[i + 1]] ?? '#787b86'
    ctx.globalAlpha = 0.12
    ctx.fillRect(x0, Math.min(ya, yb), x1 - x0, Math.abs(yb - ya))
  }
  ctx.globalAlpha = 1
  ctx.font = '11px system-ui, sans-serif'; ctx.textBaseline = 'middle'
  levels.forEach((lv, i) => {
    const y = ys[i]
    if (y === null) return
    const col = FIB_COLORS[lv] ?? '#787b86'
    ctx.strokeStyle = col; ctx.fillStyle = col; ctx.setLineDash(e.preview ? [5, 4] : [])
    seg(ctx, { x: x0, y }, { x: x1, y })
    const label = `${lv} (${fmtPrice(priceOf(lv))})`
    const inside = x0 < ctx.measureText(label).width + 12   // sát mép trái thì ghi nhãn bên trong
    ctx.textAlign = inside ? 'left' : 'right'
    const lx = inside ? x0 + 4 : x0 - 5
    ctx.lineJoin = 'round'; ctx.lineWidth = 3; ctx.strokeStyle = e.dark ? 'rgba(19,23,34,0.85)' : 'rgba(255,255,255,0.85)'   // viền nền để chữ đọc được trên nến
    ctx.strokeText(label, lx, y)
    ctx.fillText(label, lx, y)
  })
  ctx.setLineDash([])
}

/** Hồi quy tuyến tính của giá đóng cửa giữa hai mốc thời gian. */
function regress(bars: Bar[], D: DrawPoint[]) {
  const t0 = Math.min(D[0].time, D[1].time); const t1 = Math.max(D[0].time, D[1].time)
  const pts = bars.filter((b) => b.time >= t0 && b.time <= t1)
  const n = pts.length
  if (n < 2) return null
  let sx = 0; let sy = 0; let sxx = 0; let sxy = 0
  pts.forEach((b, i) => { sx += i; sy += b.close; sxx += i * i; sxy += i * b.close })
  const den = n * sxx - sx * sx
  const slope = den === 0 ? 0 : (n * sxy - sx * sy) / den
  const icpt = (sy - slope * sx) / n
  let ss = 0
  pts.forEach((b, i) => { const r = b.close - (icpt + slope * i); ss += r * r })
  return { ta: pts[0].time, tb: pts[n - 1].time, pa: icpt, pb: icpt + slope * (n - 1), sd: Math.sqrt(ss / n) }
}
function regressScreen(e: { g: Geo; bars: Bar[] }, D: DrawPoint[]) {
  const r = regress(e.bars, D)
  if (!r) return null
  const ya = e.g.s.priceToCoordinate(r.pa); const yb = e.g.s.priceToCoordinate(r.pb)
  const yu = e.g.s.priceToCoordinate(r.pa + 2 * r.sd); const yl = e.g.s.priceToCoordinate(r.pa - 2 * r.sd)
  if (ya === null || yb === null || yu === null || yl === null) return null
  const a = { x: e.g.x(r.ta), y: ya }; const b = { x: e.g.x(r.tb), y: yb }
  return { a, b, off: yu - ya, offL: yl - ya }
}


function pointInPoly(px: number, py: number, S: Pt[]): boolean {
  let inside = false
  for (let i = 0, j = S.length - 1; i < S.length; j = i++) {
    if ((S[i].y > py) !== (S[j].y > py) && px < ((S[j].x - S[i].x) * (py - S[i].y)) / (S[j].y - S[i].y) + S[i].x) inside = !inside
  }
  return inside
}
function polyDist(px: number, py: number, S: Pt[], closed: boolean): number {
  let best = Infinity
  const n = S.length
  for (let i = 1; i < n; i++) best = Math.min(best, distToSegment(px, py, S[i - 1].x, S[i - 1].y, S[i].x, S[i].y))
  if (closed && n > 2) best = Math.min(best, distToSegment(px, py, S[n - 1].x, S[n - 1].y, S[0].x, S[0].y))
  return best
}

/** Hộp ghi chú nhiều dòng: kích thước theo nội dung. */
const NOTE_FONT = '12px system-ui, sans-serif'
function noteLines(text: string): string[] { return (text || ' ').split('\n').slice(0, 8) }
function noteBox(e: Env, text: string, x: number, y: number) {
  const lines = noteLines(text)
  let w = 40
  e.ctx.save(); e.ctx.font = NOTE_FONT
  for (const l of lines) w = Math.max(w, e.ctx.measureText(l).width)
  e.ctx.restore()
  return { x, y, w: w + 16, h: lines.length * 16 + 10 }
}
/** Khi bấm chọn không có ctx: ước lượng bề rộng theo số ký tự của dòng dài nhất. Nội dung văn bản nằm ở payload.text, nhưng hit chỉ nhận điểm neo nên dùng cỡ trung bình. */
function noteBoxHit(_e: HitEnv, _D: DrawPoint[], x: number, y: number) { return { x, y, w: 140, h: 28 } }
function drawNoteText(e: Env, text: string, b: { x: number; y: number; w: number; h: number }) {
  e.ctx.save()
  e.ctx.setLineDash([]); e.ctx.shadowBlur = 0
  e.ctx.fillStyle = e.ink; e.ctx.font = NOTE_FONT; e.ctx.textAlign = 'left'; e.ctx.textBaseline = 'middle'
  noteLines(text).forEach((l, i) => e.ctx.fillText(l, b.x + 8, b.y + 13 + i * 16))
  e.ctx.restore()
}

/** Vị thế Long/Short: điểm 1 là giá vào, điểm 2 là cắt lỗ, điểm 3 là chốt lời. Hiện lợi nhuận, rủi ro và tỉ lệ R:R. */
function positionTool(isLong: boolean): ToolDef {
  return {
    group: 'position', label: isLong ? 'Vị thế Long' : 'Vị thế Short',
    title: `${isLong ? 'Long' : 'Short'}: bấm giá vào, giá cắt lỗ rồi giá chốt lời`,
    icon: isLong ? I.long : I.short, min: 3, max: 3, ownColors: true,
    draw: (e, P, D) => {
      const { ctx } = e
      const x0 = P[0].x
      const x1 = Math.min(e.plotW, Math.max(x0 + 120, ...P.map((p) => p.x)))
      const entry = D[0].price
      const sgn = isLong ? 1 : -1
      const zone = (yTo: number, color: string) => {
        ctx.save(); ctx.fillStyle = color; ctx.globalAlpha = 0.18
        ctx.fillRect(x0, Math.min(P[0].y, yTo), x1 - x0, Math.abs(yTo - P[0].y)); ctx.restore()
      }
      const label = (txt: string, yEdge: number, above: boolean, color: string) => {
        ctx.save(); ctx.setLineDash([]); ctx.shadowBlur = 0; ctx.fillStyle = color
        ctx.font = '11px system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
        ctx.fillText(txt, x0 + 6, yEdge + (above ? -8 : 8)); ctx.restore()
      }
      const pctOf = (p: number) => (entry !== 0 ? ((p - entry) / entry) * 100 : 0)
      let reward = NaN
      let risk = NaN
      if (P.length >= 2) {
        zone(P[1].y, DOWN)
        const stop = D[1].price
        risk = sgn * (entry - stop)
        ctx.strokeStyle = DOWN; ctx.lineWidth = 1; seg(ctx, { x: x0, y: P[1].y }, { x: x1, y: P[1].y })
        label(`Cắt lỗ ${fmtPrice(stop)}  (${pctOf(stop).toFixed(2)}%)`, P[1].y, P[1].y < P[0].y, DOWN)
      }
      if (P.length === 3) {
        zone(P[2].y, UP)
        const target = D[2].price
        reward = sgn * (target - entry)
        ctx.strokeStyle = UP; ctx.lineWidth = 1; seg(ctx, { x: x0, y: P[2].y }, { x: x1, y: P[2].y })
        label(`Chốt lời ${fmtPrice(target)}  (${pctOf(target) >= 0 ? '+' : ''}${pctOf(target).toFixed(2)}%)`, P[2].y, P[2].y < P[0].y, UP)
      }
      ctx.strokeStyle = e.ink; ctx.lineWidth = 1.5; seg(ctx, { x: x0, y: P[0].y }, { x: x1, y: P[0].y })
      ctx.fillStyle = e.ink; dots(ctx, P)
      if (P.length === 3 && risk > 0 && reward > 0) {
        tag(e, `R:R 1 : ${(reward / risk).toFixed(2)}`, `${isLong ? 'Long' : 'Short'} ${fmtPrice(entry)}`, (x0 + x1) / 2, P[0].y - 19, reward >= risk ? UP : DOWN)
      } else if (P.length === 3) {
        tag(e, 'Điểm không hợp lệ', isLong ? 'Long: cắt lỗ < vào < chốt lời' : 'Short: chốt lời < vào < cắt lỗ', (x0 + x1) / 2, P[0].y - 19, '#787b86')
      }
    },
    hit: (e, S, _D, px, py) => {
      const x0 = S[0].x
      const x1 = Math.min(e.plotW, Math.max(x0 + 120, ...S.map((p) => p.x)))
      const ys = S.map((p) => p.y)
      return px >= x0 - 6 && px <= x1 + 6 && py >= Math.min(...ys) - 6 && py <= Math.max(...ys) + 6 ? 0 : Infinity
    },
  }
}


const FIB_CH_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618, 2.618]
const FIB_TIME_NUMBERS = [0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]
const FIB_FAN_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786, 1]
const FIB_RING_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618, 2.618]
const GANN_RATIOS: [number, number][] = [[1, 8], [1, 4], [1, 3], [1, 2], [1, 1], [2, 1], [3, 1], [4, 1], [8, 1]]

/** Chữ nhỏ có viền nền để đọc được trên nến. */
function label(e: Env, text: string, x: number, y: number, color: string, align: CanvasTextAlign) {
  const { ctx } = e
  ctx.save()
  ctx.setLineDash([]); ctx.shadowBlur = 0
  ctx.font = '11px system-ui, sans-serif'; ctx.textAlign = align; ctx.textBaseline = 'middle'
  ctx.lineJoin = 'round'; ctx.lineWidth = 3; ctx.strokeStyle = e.dark ? 'rgba(19,23,34,0.85)' : 'rgba(255,255,255,0.85)'
  ctx.strokeText(text, x, y)
  ctx.fillStyle = color; ctx.fillText(text, x, y)
  ctx.restore()
}

/** Pitchfork Andrews / Schiff / Schiff cải tiến. Điểm 1 là gốc, điểm 2 và 3 là hai đỉnh/đáy kế tiếp; đường giữa đi từ gốc qua trung điểm đoạn 2-3. */
function pitchforkTool(variant: 'andrews' | 'schiff' | 'mschiff'): ToolDef {
  const names = { andrews: 'Pitchfork', schiff: 'Schiff pitchfork', mschiff: 'Modified Schiff' }
  const origin = (P: Pt[]): Pt => variant === 'andrews' ? P[0]
    : variant === 'schiff' ? { x: P[0].x, y: (P[0].y + P[1].y) / 2 }
      : { x: (P[0].x + P[1].x) / 2, y: (P[0].y + P[1].y) / 2 }
  const geom = (P: Pt[]) => {
    const o = origin(P)
    const m = { x: (P[1].x + P[2].x) / 2, y: (P[1].y + P[2].y) / 2 }
    return Math.hypot(m.x - o.x, m.y - o.y) < 1e-6 ? null : { o, m, dir: { x: m.x - o.x, y: m.y - o.y } }
  }
  const ray = (a: Pt, d: Pt): Pt => far(a, { x: a.x + d.x, y: a.y + d.y })
  return {
    group: 'pitchfork', label: names[variant],
    title: `${names[variant]}: bấm điểm gốc rồi hai điểm đỉnh/đáy kế tiếp`,
    icon: variant === 'andrews' ? I.pitchfork : variant === 'schiff' ? I.schiff : I.mschiff, min: 3, max: 3,
    draw: (e, P) => {
      const { ctx } = e
      if (P.length < 3) { seg(ctx, P[0], P[1]); dots(ctx, P); return }
      const g = geom(P)
      if (!g) return
      const fb = ray(P[1], g.dir); const fc = ray(P[2], g.dir)
      ctx.save(); ctx.globalAlpha = 0.07
      ctx.beginPath(); ctx.moveTo(P[1].x, P[1].y); ctx.lineTo(P[2].x, P[2].y); ctx.lineTo(fc.x, fc.y); ctx.lineTo(fb.x, fb.y); ctx.closePath(); ctx.fill()
      ctx.restore()
      seg(ctx, g.o, ray(g.o, g.dir)); seg(ctx, P[1], fb); seg(ctx, P[2], fc)
      ctx.save(); ctx.setLineDash([4, 4]); ctx.globalAlpha = 0.7; seg(ctx, P[0], P[1]); seg(ctx, P[1], P[2]); ctx.restore()
      dots(ctx, P)
    },
    hit: (_e, S, _D, px, py) => {
      const g = geom(S)
      if (!g) return Infinity
      const f1 = ray(g.o, g.dir); const f2 = ray(S[1], g.dir); const f3 = ray(S[2], g.dir)
      return Math.min(distToSegment(px, py, g.o.x, g.o.y, f1.x, f1.y), distToSegment(px, py, S[1].x, S[1].y, f2.x, f2.y),
        distToSegment(px, py, S[2].x, S[2].y, f3.x, f3.y), distToSegment(px, py, S[1].x, S[1].y, S[2].x, S[2].y))
    },
  }
}

// ---------- biểu tượng ----------

const I = {
  trend: <><circle cx="5" cy="17" r="2" /><circle cx="17" cy="5" r="2" /><path d="M6.5 15.5L15.5 6.5" /></>,
  ray: <><circle cx="5" cy="17" r="2" /><path d="M6.5 15.5L20 2M16 2h4v4" /></>,
  hray: <><circle cx="5" cy="11" r="2" /><path d="M7 11h13M16 8l4 3-4 3" /></>,
  xline: <><circle cx="8" cy="14" r="1.8" /><circle cx="14" cy="8" r="1.8" /><path d="M2 20L20 2" /></>,
  hline: <path d="M2 11h18M2 11l3-3M2 11l3 3" />,
  vline: <path d="M11 2v18M11 2l-3 3M11 2l3 3" />,
  cross: <path d="M2 11h18M11 2v18" />,
  info: <><circle cx="5" cy="17" r="2" /><circle cx="17" cy="5" r="2" /><path d="M6.5 15.5L15.5 6.5M10 15h7v4h-7z" /></>,
  angle: <path d="M3 18L19 6M3 18h16M9 18a6 6 0 0 0-2-4.5" />,
  arrow: <path d="M4 18L18 4M18 4h-7M18 4v7" />,
  channel: <path d="M3 14L15 6M3 20L15 12M3 14v6M15 6v6" />,
  regression: <path d="M3 16L19 7M3 12L19 3M3 20L19 11" />,
  rect: <rect x="4" y="6" width="14" height="10" rx="1" />,
  brush: <path d="M4 18c3-1 3-4 6-5s4-2 6-6l2-2M4 18c-.5 1-.5 1.5-.2 2" />,
  fib: <path d="M3 4h16M3 9h16M3 13h16M3 18h16" />,
  fibx: <><path d="M3 4h16M3 9h16M3 14h16" /><path d="M4 19l4-5 4 2 6-10" /></>,
  ruler: <><rect x="2" y="8" width="18" height="6" rx="1" /><path d="M6 8v3M10 8v4M14 8v3M18 8v4" /></>,
  daterange: <path d="M4 3v16M18 3v16M4 11h14M4 11l3-2.5M4 11l3 2.5M18 11l-3-2.5M18 11l-3 2.5" />,
  pricerange: <path d="M3 4h16M3 18h16M11 4v14M11 4l-2.5 3M11 4l2.5 3M11 18l-2.5-3M11 18l2.5-3" />,
  text: <path d="M5 5h12M11 5v12M8 17h6" />,
  long: <><path d="M3 11h16" /><path d="M3 3h16v8H3z" /><path d="M3 11h16v7H3z" opacity=".5" /></>,
  short: <><path d="M3 11h16" /><path d="M3 4h16v7H3z" opacity=".5" /><path d="M3 11h16v8H3z" /></>,
  circle: <circle cx="11" cy="11" r="7" />,
  ellipse: <ellipse cx="11" cy="11" rx="8" ry="5" />,
  triangle: <path d="M11 4l8 14H3z" />,
  polyline: <path d="M3 17l5-9 5 6 6-10" />,
  note: <path d="M4 4h14v10H11l-4 4v-4H4z" />,
  callout: <><path d="M10 4h9v7h-9z" /><path d="M10 9L3 18" /></>,
  pricelabel: <path d="M3 8h11l5 3-5 3H3z" />,
  flag: <path d="M6 19V3M6 4h11l-3 4 3 4H6" />,
  fibchannel: <path d="M3 17L17 9M3 13L17 5M3 9l8-4.5M3 20L17 12" />,
  fibtime: <path d="M4 3v16M8 3v16M12 3v16M20 3v16M16 3v16" />,
  fibfan: <path d="M3 18L19 4M3 18L19 8M3 18L19 12M3 18L19 16" />,
  fibcircle: <><circle cx="11" cy="11" r="3" /><circle cx="11" cy="11" r="6" /><circle cx="11" cy="11" r="9" /></>,
  fibarc: <path d="M5 17a4 4 0 0 1 8-4M3 20a8 8 0 0 1 16-6M2 21a12 12 0 0 1 19-9" />,
  pitchfork: <path d="M3 19L18 7M7 6l11 1M3 13l12-9M10 20L19 11" />,
  schiff: <path d="M5 15L19 5M7 4l12 2M3 12l11-8M9 20L19 10" />,
  mschiff: <path d="M6 13L19 5M8 3l11 3M4 11l10-8M10 19L19 9" />,
  gannfan: <path d="M3 19L19 3M3 19L19 9M3 19L19 14M3 19L14 3M3 19L9 3" />,
  gannbox: <><rect x="3" y="3" width="16" height="16" /><path d="M3 3l16 16M19 3L3 19M3 11h16M11 3v16" /></>,
}

// ---------- các công cụ ----------

export const REGISTRY: Record<DrawKind, ToolDef> = {
  trend: {
    group: 'line', label: 'Đường xu hướng', title: 'Đường xu hướng: bấm hai điểm', icon: I.trend, min: 2, max: 2,
    draw: (e, P) => { seg(e.ctx, P[0], P[1]); dots(e.ctx, P) },
    hit: (_e, S, _D, px, py) => distToSegment(px, py, S[0].x, S[0].y, S[1].x, S[1].y),
  },
  ray: {
    group: 'line', label: 'Tia', title: 'Tia: đi qua hai điểm, kéo dài về phía điểm thứ hai', icon: I.ray, min: 2, max: 2,
    draw: (e, P) => { seg(e.ctx, P[0], far(P[0], P[1])); dots(e.ctx, P) },
    hit: (_e, S, _D, px, py) => { const f = far(S[0], S[1]); return distToSegment(px, py, S[0].x, S[0].y, f.x, f.y) },
  },
  hray: {
    group: 'line', label: 'Tia ngang', title: 'Tia ngang: bấm một điểm, kéo dài sang phải', icon: I.hray, min: 1, max: 1,
    draw: (e, P) => { seg(e.ctx, P[0], { x: e.plotW, y: P[0].y }); dots(e.ctx, P) },
    hit: (_e, S, _D, px, py) => (px >= S[0].x - 6 ? Math.abs(py - S[0].y) : Infinity),
  },
  xline: {
    group: 'line', label: 'Đường thẳng', title: 'Đường thẳng kéo dài hai phía: bấm hai điểm', icon: I.xline, min: 2, max: 2,
    draw: (e, P) => {
      const dx = P[1].x - P[0].x
      if (Math.abs(dx) < 1e-6) seg(e.ctx, { x: P[0].x, y: 0 }, { x: P[0].x, y: e.h })
      else { const m = (P[1].y - P[0].y) / dx; seg(e.ctx, { x: 0, y: P[0].y - m * P[0].x }, { x: e.plotW, y: P[0].y + m * (e.plotW - P[0].x) }) }
      dots(e.ctx, P)
    },
    hit: (_e, S, _D, px, py) => distLine(px, py, S[0], S[1]),
  },
  hline: {
    group: 'line', label: 'Đường ngang', title: 'Đường ngang: bấm một điểm', icon: I.hline, min: 1, max: 1,
    draw: (e, P, D) => {
      seg(e.ctx, { x: 0, y: P[0].y }, { x: e.plotW, y: P[0].y })
      e.ctx.font = '11px system-ui, sans-serif'; e.ctx.textAlign = 'left'; e.ctx.textBaseline = 'bottom'
      e.ctx.fillText(String(D[0].price), 6, P[0].y - 2)
    },
    hit: (_e, S, _D, _px, py) => Math.abs(py - S[0].y),
  },
  vline: {
    group: 'line', label: 'Đường dọc', title: 'Đường dọc: bấm một điểm', icon: I.vline, min: 1, max: 1,
    draw: (e, P) => seg(e.ctx, { x: P[0].x, y: 0 }, { x: P[0].x, y: e.h }),
    hit: (_e, S, _D, px) => Math.abs(px - S[0].x),
  },
  cross: {
    group: 'line', label: 'Đường chữ thập', title: 'Đường chữ thập: bấm một điểm', icon: I.cross, min: 1, max: 1,
    draw: (e, P) => { seg(e.ctx, { x: 0, y: P[0].y }, { x: e.plotW, y: P[0].y }); seg(e.ctx, { x: P[0].x, y: 0 }, { x: P[0].x, y: e.h }); dots(e.ctx, P) },
    hit: (_e, S, _D, px, py) => Math.min(Math.abs(px - S[0].x), Math.abs(py - S[0].y)),
  },
  info: {
    group: 'line', label: 'Info line', title: 'Info line: đường xu hướng kèm % thay đổi, chênh giá, số nến', icon: I.info, min: 2, max: 2,
    draw: (e, P, D) => {
      seg(e.ctx, P[0], P[1]); dots(e.ctx, P)
      const m = measureTexts(e, D[0], D[1])
      const ang = (Math.atan2(-(P[1].y - P[0].y), P[1].x - P[0].x) * 180) / Math.PI
      tag(e, m.l1, `${m.l2} · ${ang.toFixed(0)}°`, P[1].x, P[1].y + (m.up ? -48 : 10), m.up ? UP : DOWN)
    },
    hit: (_e, S, _D, px, py) => distToSegment(px, py, S[0].x, S[0].y, S[1].x, S[1].y),
  },
  angle: {
    group: 'line', label: 'Góc xu hướng', title: 'Góc xu hướng: đường kèm góc so với phương ngang', icon: I.angle, min: 2, max: 2,
    draw: (e, P) => {
      const { ctx } = e
      seg(ctx, P[0], P[1]); dots(ctx, P)
      const len = Math.max(40, Math.abs(P[1].x - P[0].x))
      ctx.save(); ctx.setLineDash([4, 4]); ctx.globalAlpha = 0.7
      seg(ctx, P[0], { x: P[0].x + (P[1].x >= P[0].x ? len : -len), y: P[0].y }); ctx.restore()
      const ang = Math.atan2(-(P[1].y - P[0].y), Math.abs(P[1].x - P[0].x))
      const deg = (ang * 180) / Math.PI
      const dir = P[1].x >= P[0].x ? 1 : -1
      ctx.save(); ctx.setLineDash([]); ctx.beginPath()
      ctx.arc(P[0].x, P[0].y, 28, dir > 0 ? 0 : Math.PI, dir > 0 ? -ang : Math.PI + ang, dir > 0 ? ang > 0 : ang < 0)
      ctx.stroke()
      ctx.font = 'bold 12px system-ui, sans-serif'; ctx.textBaseline = 'middle'; ctx.textAlign = dir > 0 ? 'left' : 'right'
      ctx.fillText(`${deg.toFixed(1)}°`, P[0].x + dir * 34, P[0].y - Math.sign(deg) * 10)
      ctx.restore()
    },
    hit: (_e, S, _D, px, py) => distToSegment(px, py, S[0].x, S[0].y, S[1].x, S[1].y),
  },
  arrow: {
    group: 'line', label: 'Mũi tên', title: 'Mũi tên: bấm hai điểm', icon: I.arrow, min: 2, max: 2,
    draw: (e, P) => {
      const { ctx } = e
      seg(ctx, P[0], P[1])
      const a = Math.atan2(P[1].y - P[0].y, P[1].x - P[0].x)
      ctx.beginPath(); ctx.moveTo(P[1].x, P[1].y)
      ctx.lineTo(P[1].x - 12 * Math.cos(a - 0.4), P[1].y - 12 * Math.sin(a - 0.4))
      ctx.lineTo(P[1].x - 12 * Math.cos(a + 0.4), P[1].y - 12 * Math.sin(a + 0.4)); ctx.closePath(); ctx.fill()
    },
    hit: (_e, S, _D, px, py) => distToSegment(px, py, S[0].x, S[0].y, S[1].x, S[1].y),
  },
  channel: {
    group: 'line', label: 'Kênh song song', title: 'Kênh song song: bấm hai điểm của cạnh đầu, rồi điểm thứ ba cho cạnh kia', icon: I.channel, min: 3, max: 3,
    draw: (e, P) => {
      const { ctx } = e
      seg(ctx, P[0], P[1])
      if (P.length === 3) {
        const dx = P[1].x - P[0].x
        const m = Math.abs(dx) < 1e-6 ? 0 : (P[1].y - P[0].y) / dx
        const dy = P[2].y - (P[0].y + m * (P[2].x - P[0].x))
        const a = { x: P[0].x, y: P[0].y + dy }; const b = { x: P[1].x, y: P[1].y + dy }
        ctx.save(); ctx.globalAlpha = 0.1
        ctx.beginPath(); ctx.moveTo(P[0].x, P[0].y); ctx.lineTo(P[1].x, P[1].y); ctx.lineTo(b.x, b.y); ctx.lineTo(a.x, a.y); ctx.closePath(); ctx.fill()
        ctx.restore()
        seg(ctx, a, b)
        ctx.save(); ctx.setLineDash([4, 4]); ctx.globalAlpha = 0.7
        seg(ctx, { x: P[0].x, y: P[0].y + dy / 2 }, { x: P[1].x, y: P[1].y + dy / 2 }); ctx.restore()
      }
      dots(ctx, P)
    },
    hit: (_e, S, _D, px, py) => {
      const dx = S[1].x - S[0].x
      const m = Math.abs(dx) < 1e-6 ? 0 : (S[1].y - S[0].y) / dx
      const dy = S[2].y - (S[0].y + m * (S[2].x - S[0].x))
      return Math.min(distToSegment(px, py, S[0].x, S[0].y, S[1].x, S[1].y),
        distToSegment(px, py, S[0].x, S[0].y + dy, S[1].x, S[1].y + dy))
    },
  },
  regression: {
    group: 'line', label: 'Kênh hồi quy', title: 'Kênh hồi quy tuyến tính: bấm hai mốc thời gian, tính trên giá đóng cửa (±2σ)', icon: I.regression, min: 2, max: 2,
    draw: (e, P, D) => {
      const r = regressScreen(e, D)
      if (!r) { seg(e.ctx, P[0], P[1]); return }
      const { ctx } = e
      ctx.save(); ctx.globalAlpha = 0.1
      ctx.beginPath(); ctx.moveTo(r.a.x, r.a.y + r.off); ctx.lineTo(r.b.x, r.b.y + r.off); ctx.lineTo(r.b.x, r.b.y + r.offL); ctx.lineTo(r.a.x, r.a.y + r.offL); ctx.closePath(); ctx.fill()
      ctx.restore()
      seg(ctx, r.a, r.b)
      ctx.save(); ctx.setLineDash([5, 4])
      seg(ctx, { x: r.a.x, y: r.a.y + r.off }, { x: r.b.x, y: r.b.y + r.off })
      seg(ctx, { x: r.a.x, y: r.a.y + r.offL }, { x: r.b.x, y: r.b.y + r.offL }); ctx.restore()
    },
    hit: (e, S, D, px, py) => {
      const r = regressScreen(e, D)
      return r ? distToSegment(px, py, r.a.x, r.a.y, r.b.x, r.b.y) : distToSegment(px, py, S[0].x, S[0].y, S[1].x, S[1].y)
    },
  },
  rect: {
    group: 'shape', label: 'Hộp', title: 'Hình chữ nhật: bấm hai góc', icon: I.rect, min: 2, max: 2, box: true,
    draw: (e, P) => {
      const x = Math.min(P[0].x, P[1].x); const y = Math.min(P[0].y, P[1].y)
      const w = Math.abs(P[1].x - P[0].x); const h = Math.abs(P[1].y - P[0].y)
      e.ctx.save(); e.ctx.globalAlpha = 0.12; e.ctx.fillRect(x, y, w, h); e.ctx.restore()
      e.ctx.strokeRect(x, y, w, h)
    },
    hit: (_e, S, _D, px, py) => (inBox(px, py, S[0], S[1]) ? 0 : Infinity),
  },
  brush: {
    group: 'shape', label: 'Bút vẽ', title: 'Bút vẽ tự do: giữ chuột và kéo', icon: I.brush, min: 2, max: 400, noHandles: true,
    draw: (e, P) => {
      const { ctx } = e
      ctx.lineJoin = 'round'; ctx.lineCap = 'round'
      ctx.beginPath(); ctx.moveTo(P[0].x, P[0].y)
      for (let i = 1; i < P.length; i++) ctx.lineTo(P[i].x, P[i].y)
      ctx.stroke()
    },
    hit: (_e, S, _D, px, py) => {
      let best = Infinity
      for (let i = 1; i < S.length; i++) best = Math.min(best, distToSegment(px, py, S[i - 1].x, S[i - 1].y, S[i].x, S[i].y))
      return best
    },
  },
  fib: {
    group: 'fib', label: 'Fib retracement', title: 'Fibonacci retracement: bấm hai điểm', icon: I.fib, min: 2, max: 2, box: true, ownColors: true,
    draw: (e, P, D) => {
      const [a, b] = D
      const x0 = Math.min(P[0].x, P[1].x); const x1 = Math.max(P[0].x, P[1].x, x0 + 60)
      drawFib(e, FIB_LEVELS, (lv) => b.price + (a.price - b.price) * lv, x0, x1)
      e.ctx.strokeStyle = '#787b86'; e.ctx.lineWidth = 1; e.ctx.setLineDash([4, 4])
      seg(e.ctx, P[0], P[1]); e.ctx.setLineDash([])
    },
    hit: (_e, S, _D, px, py) => (inBox(px, py, S[0], S[1]) ? 0 : Infinity),
  },
  fibx: {
    group: 'fib', label: 'Fib mở rộng', title: 'Fibonacci mở rộng theo xu hướng: bấm ba điểm A, B, C', icon: I.fibx, min: 3, max: 3, ownColors: true,
    draw: (e, P, D) => {
      const { ctx } = e
      ctx.strokeStyle = '#787b86'; ctx.lineWidth = 1; ctx.setLineDash([4, 4])
      ctx.beginPath(); ctx.moveTo(P[0].x, P[0].y); ctx.lineTo(P[1].x, P[1].y); if (P.length === 3) ctx.lineTo(P[2].x, P[2].y); ctx.stroke(); ctx.setLineDash([])
      if (P.length === 3) {
        const [pa, pb, pc] = D
        const x0 = P[2].x
        const x1 = Math.min(e.plotW, x0 + Math.max(160, Math.abs(P[2].x - P[0].x)))   // chiều dài hữu hạn, không kéo hết mép phải
        drawFib(e, FIBX_LEVELS, (lv) => pc.price + (pb.price - pa.price) * lv, x0, x1)
      }
      ctx.fillStyle = '#787b86'; dots(ctx, P)
    },
    hit: (e, S, D, px, py) => {
      const [pa, pb, pc] = D
      const x1 = Math.min(e.plotW, S[2].x + Math.max(160, Math.abs(S[2].x - S[0].x)))
      let dist = Math.min(distToSegment(px, py, S[0].x, S[0].y, S[1].x, S[1].y), distToSegment(px, py, S[1].x, S[1].y, S[2].x, S[2].y))
      for (const lv of FIBX_LEVELS) {
        const y = e.g.s.priceToCoordinate(pc.price + (pb.price - pa.price) * lv)
        if (y !== null && px >= S[2].x - 6 && px <= x1) dist = Math.min(dist, Math.abs(py - y))
      }
      return dist
    },
  },
  ruler: {
    group: 'measure', label: 'Thước', title: 'Thước đo: % thay đổi, chênh giá, số nến', icon: I.ruler, min: 2, max: 2, box: true, ownColors: true,
    draw: (e, P, D) => {
      const { ctx } = e
      const m = measureTexts(e, D[0], D[1])
      const rc = m.up ? UP : DOWN
      const x = Math.min(P[0].x, P[1].x); const y = Math.min(P[0].y, P[1].y)
      const rw = Math.abs(P[1].x - P[0].x); const rh = Math.abs(P[1].y - P[0].y)
      ctx.strokeStyle = rc; ctx.fillStyle = rc
      ctx.save(); ctx.globalAlpha = 0.14; ctx.fillRect(x, y, rw, rh); ctx.restore()
      ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeRect(x, y, rw, rh); ctx.restore()
      seg(ctx, P[0], P[1])
      const ang = Math.atan2(P[1].y - P[0].y, P[1].x - P[0].x)
      ctx.beginPath(); ctx.moveTo(P[1].x, P[1].y)
      ctx.lineTo(P[1].x - 9 * Math.cos(ang - 0.4), P[1].y - 9 * Math.sin(ang - 0.4))
      ctx.lineTo(P[1].x - 9 * Math.cos(ang + 0.4), P[1].y - 9 * Math.sin(ang + 0.4)); ctx.closePath(); ctx.fill()
      tag(e, m.l1, m.l2, x + rw / 2, m.up ? y - 46 : y + rh + 8, rc)
    },
    hit: (_e, S, _D, px, py) => (inBox(px, py, S[0], S[1]) ? 0 : Infinity),
  },
  daterange: {
    group: 'measure', label: 'Khoảng ngày', title: 'Khoảng ngày: số nến và thời lượng giữa hai mốc', icon: I.daterange, min: 2, max: 2, box: true, ownColors: true,
    draw: (e, P, D) => {
      const { ctx } = e
      const x0 = Math.min(P[0].x, P[1].x); const x1 = Math.max(P[0].x, P[1].x)
      ctx.strokeStyle = '#2962ff'; ctx.fillStyle = '#2962ff'
      ctx.save(); ctx.globalAlpha = 0.1; ctx.fillRect(x0, 0, x1 - x0, e.h); ctx.restore()
      seg(ctx, { x: x0, y: 0 }, { x: x0, y: e.h }); seg(ctx, { x: x1, y: 0 }, { x: x1, y: e.h })
      const ym = (P[0].y + P[1].y) / 2
      seg(ctx, { x: x0, y: ym }, { x: x1, y: ym })
      const nb = Math.abs(Math.round(e.g.idx(D[1].time) - e.g.idx(D[0].time)))
      tag(e, `${nb} nến`, fmtDuration(D[1].time - D[0].time), (x0 + x1) / 2, ym - 44, '#2962ff')
    },
    hit: (_e, S, _D, px, py) => {
      const x0 = Math.min(S[0].x, S[1].x); const x1 = Math.max(S[0].x, S[1].x)
      const ym = (S[0].y + S[1].y) / 2
      return Math.min(Math.abs(px - x0), Math.abs(px - x1), px >= x0 && px <= x1 ? Math.abs(py - ym) : Infinity)
    },
  },
  pricerange: {
    group: 'measure', label: 'Khoảng giá', title: 'Khoảng giá: chênh giá và % giữa hai mức', icon: I.pricerange, min: 2, max: 2, box: true, ownColors: true,
    draw: (e, P, D) => {
      const { ctx } = e
      const m = measureTexts(e, D[0], D[1])
      const rc = m.up ? UP : DOWN
      const x0 = Math.min(P[0].x, P[1].x); const x1 = Math.max(P[0].x, P[1].x, Math.min(P[0].x, P[1].x) + 40)
      const y0 = Math.min(P[0].y, P[1].y); const y1 = Math.max(P[0].y, P[1].y)
      ctx.strokeStyle = rc; ctx.fillStyle = rc
      ctx.save(); ctx.globalAlpha = 0.12; ctx.fillRect(x0, y0, x1 - x0, y1 - y0); ctx.restore()
      seg(ctx, { x: x0, y: y0 }, { x: x1, y: y0 }); seg(ctx, { x: x0, y: y1 }, { x: x1, y: y1 })
      const xm = (x0 + x1) / 2
      seg(ctx, { x: xm, y: y0 }, { x: xm, y: y1 })
      tag(e, m.l1.split('   ')[0], m.l1.split('   ')[1], xm, m.up ? y0 - 46 : y1 + 8, rc)
    },
    hit: (_e, S, _D, px, py) => {
      const x0 = Math.min(S[0].x, S[1].x); const x1 = Math.max(S[0].x, S[1].x, Math.min(S[0].x, S[1].x) + 40)
      return inBox(px, py, { x: x0, y: S[0].y }, { x: x1, y: S[1].y }) ? 0 : Infinity
    },
  },
  long: positionTool(true),
  short: positionTool(false),
  circle: {
    group: 'shape', label: 'Hình tròn', title: 'Hình tròn: bấm tâm rồi một điểm trên đường tròn', icon: I.circle, min: 2, max: 2,
    draw: (e, P) => {
      const r = Math.hypot(P[1].x - P[0].x, P[1].y - P[0].y)
      e.ctx.beginPath(); e.ctx.arc(P[0].x, P[0].y, r, 0, Math.PI * 2)
      e.ctx.save(); e.ctx.globalAlpha = 0.12; e.ctx.fill(); e.ctx.restore(); e.ctx.stroke()
      dots(e.ctx, [P[0]])
    },
    hit: (_e, S, _D, px, py) => {
      const r = Math.hypot(S[1].x - S[0].x, S[1].y - S[0].y)
      const d = Math.hypot(px - S[0].x, py - S[0].y)
      return d <= r ? 0 : d - r
    },
  },
  ellipse: {
    group: 'shape', label: 'Ellipse', title: 'Ellipse: bấm hai góc của hình chữ nhật bao', icon: I.ellipse, min: 2, max: 2, box: true,
    draw: (e, P) => {
      const cx = (P[0].x + P[1].x) / 2; const cy = (P[0].y + P[1].y) / 2
      const a = Math.max(1, Math.abs(P[1].x - P[0].x) / 2); const b = Math.max(1, Math.abs(P[1].y - P[0].y) / 2)
      e.ctx.beginPath(); e.ctx.ellipse(cx, cy, a, b, 0, 0, Math.PI * 2)
      e.ctx.save(); e.ctx.globalAlpha = 0.12; e.ctx.fill(); e.ctx.restore(); e.ctx.stroke()
    },
    hit: (_e, S, _D, px, py) => {
      const cx = (S[0].x + S[1].x) / 2; const cy = (S[0].y + S[1].y) / 2
      const a = Math.max(1, Math.abs(S[1].x - S[0].x) / 2); const b = Math.max(1, Math.abs(S[1].y - S[0].y) / 2)
      const n = Math.hypot((px - cx) / a, (py - cy) / b)
      return n <= 1 ? 0 : (n - 1) * Math.min(a, b)
    },
  },
  triangle: {
    group: 'shape', label: 'Tam giác', title: 'Tam giác: bấm ba đỉnh', icon: I.triangle, min: 3, max: 3,
    draw: (e, P) => {
      e.ctx.beginPath(); e.ctx.moveTo(P[0].x, P[0].y)
      for (let i = 1; i < P.length; i++) e.ctx.lineTo(P[i].x, P[i].y)
      if (P.length === 3) {
        e.ctx.closePath()
        e.ctx.save(); e.ctx.globalAlpha = 0.12; e.ctx.fill(); e.ctx.restore()
      }
      e.ctx.stroke()
    },
    hit: (_e, S, _D, px, py) => (pointInPoly(px, py, S) ? 0 : polyDist(px, py, S, true)),
  },
  polyline: {
    group: 'shape', label: 'Đường gấp khúc', title: 'Đường gấp khúc: bấm từng điểm, bấm đúp hoặc Enter để kết thúc (tối đa 50 điểm)', icon: I.polyline, min: 2, max: 50,
    draw: (e, P) => {
      e.ctx.lineJoin = 'round'
      e.ctx.beginPath(); e.ctx.moveTo(P[0].x, P[0].y)
      for (let i = 1; i < P.length; i++) e.ctx.lineTo(P[i].x, P[i].y)
      e.ctx.stroke(); dots(e.ctx, P)
    },
    hit: (_e, S, _D, px, py) => polyDist(px, py, S, false),
  },
  note: {
    group: 'text', label: 'Ghi chú', title: 'Ghi chú: hộp chữ có nền, bấm một điểm', icon: I.note, min: 1, max: 1, ask: true,
    draw: (e, P, _D, text) => {
      const b = noteBox(e, text ?? '', P[0].x, P[0].y)
      e.ctx.save(); e.ctx.globalAlpha = 0.16; e.ctx.fillRect(b.x, b.y, b.w, b.h); e.ctx.restore()
      e.ctx.strokeRect(b.x, b.y, b.w, b.h)
      drawNoteText(e, text ?? '', b)
    },
    hit: (e, S, D, px, py) => {
      const b = noteBoxHit(e, D, S[0].x, S[0].y)
      return px >= b.x - 4 && px <= b.x + b.w + 4 && py >= b.y - 4 && py <= b.y + b.h + 4 ? 0 : Infinity
    },
  },
  callout: {
    group: 'text', label: 'Chú thích', title: 'Chú thích: bấm điểm cần chỉ, rồi vị trí hộp chữ', icon: I.callout, min: 2, max: 2, ask: true,
    draw: (e, P, _D, text) => {
      const b = noteBox(e, text ?? '', P[1].x, P[1].y)
      const tx = Math.min(Math.max(P[0].x, b.x), b.x + b.w); const ty = Math.min(Math.max(P[0].y, b.y), b.y + b.h)
      seg(e.ctx, P[0], { x: tx, y: ty })
      dot(e.ctx, P[0], 3.5)
      e.ctx.save(); e.ctx.globalAlpha = 0.16; e.ctx.fillRect(b.x, b.y, b.w, b.h); e.ctx.restore()
      e.ctx.strokeRect(b.x, b.y, b.w, b.h)
      drawNoteText(e, text ?? '', b)
    },
    hit: (e, S, D, px, py) => {
      const b = noteBoxHit(e, D, S[1].x, S[1].y)
      const inside = px >= b.x - 4 && px <= b.x + b.w + 4 && py >= b.y - 4 && py <= b.y + b.h + 4
      return inside ? 0 : distToSegment(px, py, S[0].x, S[0].y, b.x + b.w / 2, b.y + b.h / 2)
    },
  },
  pricelabel: {
    group: 'text', label: 'Nhãn giá', title: 'Nhãn giá: ghi giá tại điểm bấm', icon: I.pricelabel, min: 1, max: 1,
    draw: (e, P, D) => {
      const col = e.ctx.strokeStyle as string
      tag(e, fmtPrice(D[0].price), null, P[0].x, P[0].y - 34, col)
      e.ctx.fillStyle = col; e.ctx.beginPath(); e.ctx.moveTo(P[0].x - 5, P[0].y - 10); e.ctx.lineTo(P[0].x + 5, P[0].y - 10); e.ctx.lineTo(P[0].x, P[0].y); e.ctx.closePath(); e.ctx.fill()
    },
    hit: (_e, S, _D, px, py) => (Math.abs(px - S[0].x) <= 30 && py >= S[0].y - 36 && py <= S[0].y + 4 ? 0 : Infinity),
  },
  flag: {
    group: 'text', label: 'Cờ', title: 'Cờ đánh dấu: bấm một điểm', icon: I.flag, min: 1, max: 1,
    draw: (e, P) => {
      const { ctx } = e
      seg(ctx, P[0], { x: P[0].x, y: P[0].y - 30 })
      ctx.beginPath(); ctx.moveTo(P[0].x, P[0].y - 30); ctx.lineTo(P[0].x + 18, P[0].y - 30); ctx.lineTo(P[0].x + 13, P[0].y - 24); ctx.lineTo(P[0].x + 18, P[0].y - 18); ctx.lineTo(P[0].x, P[0].y - 18); ctx.closePath(); ctx.fill()
    },
    hit: (_e, S, _D, px, py) => (px >= S[0].x - 6 && px <= S[0].x + 20 && py >= S[0].y - 32 && py <= S[0].y + 2 ? 0 : Infinity),
  },
  fibchannel: {
    group: 'fib', label: 'Fib channel', title: 'Fib channel: bấm hai điểm của cạnh gốc, rồi điểm xác định bề rộng kênh', icon: I.fibchannel, min: 3, max: 3, ownColors: true,
    draw: (e, P) => {
      const { ctx } = e
      ctx.lineWidth = 1
      const dx = P[1].x - P[0].x
      const m = Math.abs(dx) < 1e-6 ? 0 : (P[1].y - P[0].y) / dx
      ctx.strokeStyle = '#787b86'; ctx.setLineDash([4, 4]); seg(ctx, P[0], P[1]); ctx.setLineDash([])
      if (P.length < 3) return
      const off = P[2].y - (P[0].y + m * (P[2].x - P[0].x))
      FIB_CH_LEVELS.forEach((lv, i) => {
        const a = { x: P[0].x, y: P[0].y + off * lv }; const b = { x: P[1].x, y: P[1].y + off * lv }
        if (i > 0) {
          const pa = { x: P[0].x, y: P[0].y + off * FIB_CH_LEVELS[i - 1] }; const pb = { x: P[1].x, y: P[1].y + off * FIB_CH_LEVELS[i - 1] }
          ctx.save(); ctx.fillStyle = FIB_COLORS[lv] ?? '#787b86'; ctx.globalAlpha = 0.1
          ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.lineTo(b.x, b.y); ctx.lineTo(a.x, a.y); ctx.closePath(); ctx.fill(); ctx.restore()
        }
        ctx.strokeStyle = FIB_COLORS[lv] ?? '#787b86'; ctx.setLineDash(e.preview ? [5, 4] : [])
        seg(ctx, a, b)
        label(e, String(lv), b.x + 4, b.y, FIB_COLORS[lv] ?? '#787b86', 'left')
      })
      ctx.setLineDash([])
    },
    hit: (_e, S, _D, px, py) => {
      const dx = S[1].x - S[0].x
      const m = Math.abs(dx) < 1e-6 ? 0 : (S[1].y - S[0].y) / dx
      const off = S[2].y - (S[0].y + m * (S[2].x - S[0].x))
      let best = Infinity
      for (const lv of FIB_CH_LEVELS) best = Math.min(best, distToSegment(px, py, S[0].x, S[0].y + off * lv, S[1].x, S[1].y + off * lv))
      return best
    },
  },
  fibtime: {
    group: 'fib', label: 'Fib time zones', title: 'Vùng thời gian Fibonacci: bấm hai điểm, khoảng cách là một đơn vị', icon: I.fibtime, min: 2, max: 2, ownColors: true,
    draw: (e, P) => {
      const { ctx } = e
      const u = P[1].x - P[0].x
      ctx.lineWidth = 1
      if (Math.abs(u) < 2) return
      for (const n of FIB_TIME_NUMBERS) {
        const x = P[0].x + n * u
        if (x > e.plotW + 2 || x < -2) { if (n > 0) break; continue }
        ctx.strokeStyle = n === 0 ? '#787b86' : '#2962ff'; ctx.setLineDash(n === 0 ? [4, 4] : [])
        ctx.save(); ctx.globalAlpha = 0.8; seg(ctx, { x, y: 0 }, { x, y: e.h }); ctx.restore()
        label(e, String(n), x + 3, 12, '#2962ff', 'left')
      }
      ctx.setLineDash([])
    },
    hit: (e, S, _D, px) => {
      const u = S[1].x - S[0].x
      if (Math.abs(u) < 2) return Infinity
      let best = Infinity
      for (const n of FIB_TIME_NUMBERS) { const x = S[0].x + n * u; if (x >= -2 && x <= e.plotW + 2) best = Math.min(best, Math.abs(px - x)) }
      return best
    },
  },
  fibfan: {
    group: 'fib', label: 'Fib fan', title: 'Quạt kháng cự tốc độ Fibonacci: bấm điểm gốc và điểm cuối', icon: I.fibfan, min: 2, max: 2, ownColors: true,
    draw: (e, P) => {
      const { ctx } = e
      const dy = P[1].y - P[0].y
      ctx.lineWidth = 1
      if (Math.abs(P[1].x - P[0].x) < 1e-6) return
      ctx.strokeStyle = '#787b86'; ctx.setLineDash([4, 4]); seg(ctx, P[0], P[1]); ctx.setLineDash([])
      for (const lv of FIB_FAN_LEVELS) {
        const t = { x: P[1].x, y: P[0].y + dy * lv }
        const col = FIB_COLORS[lv] ?? '#787b86'
        ctx.strokeStyle = col; ctx.fillStyle = col
        seg(ctx, P[0], far(P[0], t))
        label(e, String(lv), t.x + 4, t.y, col, 'left')
      }
    },
    hit: (_e, S, _D, px, py) => {
      if (Math.abs(S[1].x - S[0].x) < 1e-6) return Infinity
      const dy = S[1].y - S[0].y
      let best = Infinity
      for (const lv of FIB_FAN_LEVELS) { const f = far(S[0], { x: S[1].x, y: S[0].y + dy * lv }); best = Math.min(best, distToSegment(px, py, S[0].x, S[0].y, f.x, f.y)) }
      return best
    },
  },
  fibcircle: {
    group: 'fib', label: 'Fib circles', title: 'Vòng tròn Fibonacci: bấm tâm và một điểm xác định bán kính', icon: I.fibcircle, min: 2, max: 2, ownColors: true,
    draw: (e, P) => {
      const { ctx } = e
      const r = Math.hypot(P[1].x - P[0].x, P[1].y - P[0].y)
      ctx.lineWidth = 1
      ctx.strokeStyle = '#787b86'; ctx.setLineDash([4, 4]); seg(ctx, P[0], P[1]); ctx.setLineDash([])
      for (const lv of FIB_RING_LEVELS) {
        const col = FIB_COLORS[lv] ?? '#787b86'
        ctx.strokeStyle = col
        ctx.beginPath(); ctx.arc(P[0].x, P[0].y, r * lv, 0, Math.PI * 2); ctx.stroke()
        label(e, String(lv), P[0].x + r * lv + 3, P[0].y, col, 'left')
      }
    },
    hit: (_e, S, _D, px, py) => {
      const r = Math.hypot(S[1].x - S[0].x, S[1].y - S[0].y)
      const d = Math.hypot(px - S[0].x, py - S[0].y)
      let best = Infinity
      for (const lv of FIB_RING_LEVELS) best = Math.min(best, Math.abs(d - r * lv))
      return best
    },
  },
  fibarc: {
    group: 'fib', label: 'Fib arcs', title: 'Cung tròn Fibonacci: bấm tâm và điểm hướng ra, các cung mở về phía điểm thứ hai', icon: I.fibarc, min: 2, max: 2, ownColors: true,
    draw: (e, P) => {
      const { ctx } = e
      const r = Math.hypot(P[1].x - P[0].x, P[1].y - P[0].y)
      const ang = Math.atan2(P[1].y - P[0].y, P[1].x - P[0].x)
      ctx.lineWidth = 1
      ctx.strokeStyle = '#787b86'; ctx.setLineDash([4, 4]); seg(ctx, P[0], P[1]); ctx.setLineDash([])
      for (const lv of FIB_RING_LEVELS) {
        const col = FIB_COLORS[lv] ?? '#787b86'
        ctx.strokeStyle = col
        ctx.beginPath(); ctx.arc(P[0].x, P[0].y, r * lv, ang - Math.PI / 2, ang + Math.PI / 2); ctx.stroke()
        label(e, String(lv), P[0].x + Math.cos(ang) * r * lv + 3, P[0].y + Math.sin(ang) * r * lv, col, 'left')
      }
    },
    hit: (_e, S, _D, px, py) => {
      const r = Math.hypot(S[1].x - S[0].x, S[1].y - S[0].y)
      const ang = Math.atan2(S[1].y - S[0].y, S[1].x - S[0].x)
      const vx = px - S[0].x; const vy = py - S[0].y
      if (vx * Math.cos(ang) + vy * Math.sin(ang) < 0) return Infinity
      const d = Math.hypot(vx, vy)
      let best = Infinity
      for (const lv of FIB_RING_LEVELS) best = Math.min(best, Math.abs(d - r * lv))
      return best
    },
  },
  pitchfork: pitchforkTool('andrews'),
  schiff: pitchforkTool('schiff'),
  mschiff: pitchforkTool('mschiff'),
  gannfan: {
    group: 'gann', label: 'Gann fan', title: 'Quạt Gann: bấm điểm gốc và một điểm xác định đường 1×1', icon: I.gannfan, min: 2, max: 2,
    draw: (e, P) => {
      const { ctx } = e
      const dy = P[1].y - P[0].y
      if (Math.abs(P[1].x - P[0].x) < 1e-6) return
      for (const [a, b] of GANN_RATIOS) {
        const r = a / b
        const t = { x: P[1].x, y: P[0].y + dy * r }
        const main = a === b
        ctx.save(); ctx.globalAlpha = main ? 1 : 0.65; ctx.lineWidth = main ? 2 : 1
        seg(ctx, P[0], far(P[0], t)); ctx.restore()
        label(e, `${a}×${b}`, t.x + 4, t.y, ctx.strokeStyle as string, 'left')
      }
      dots(ctx, P)
    },
    hit: (_e, S, _D, px, py) => {
      if (Math.abs(S[1].x - S[0].x) < 1e-6) return Infinity
      const dy = S[1].y - S[0].y
      let best = Infinity
      for (const [a, b] of GANN_RATIOS) { const f = far(S[0], { x: S[1].x, y: S[0].y + dy * (a / b) }); best = Math.min(best, distToSegment(px, py, S[0].x, S[0].y, f.x, f.y)) }
      return best
    },
  },
  gannbox: {
    group: 'gann', label: 'Gann box', title: 'Hộp Gann: bấm hai góc đối diện', icon: I.gannbox, min: 2, max: 2, box: true,
    draw: (e, P) => {
      const { ctx } = e
      const x0 = Math.min(P[0].x, P[1].x); const x1 = Math.max(P[0].x, P[1].x)
      const y0 = Math.min(P[0].y, P[1].y); const y1 = Math.max(P[0].y, P[1].y)
      ctx.save(); ctx.globalAlpha = 0.06; ctx.fillRect(x0, y0, x1 - x0, y1 - y0); ctx.globalAlpha = 0.35; ctx.lineWidth = 1
      for (let i = 1; i < 8; i++) {
        const x = x0 + ((x1 - x0) * i) / 8; const y = y0 + ((y1 - y0) * i) / 8
        seg(ctx, { x, y: y0 }, { x, y: y1 }); seg(ctx, { x: x0, y }, { x: x1, y })
      }
      ctx.restore()
      seg(ctx, { x: x0, y: y0 }, { x: x1, y: y1 }); seg(ctx, { x: x1, y: y0 }, { x: x0, y: y1 })
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0)
    },
    hit: (_e, S, _D, px, py) => (inBox(px, py, S[0], S[1]) ? 0 : Infinity),
  },
  text: {
    group: 'text', label: 'Chữ', title: 'Văn bản: bấm một điểm', icon: I.text, min: 1, max: 1,
    draw: (e, P, _D, text) => {
      const { ctx } = e
      ctx.fillStyle = e.ink
      ctx.font = '13px system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
      ctx.fillText(text ?? '', P[0].x, P[0].y)
    },
    hit: (_e, S, _D, px, py) => Math.hypot(px - S[0].x - 20, py - S[0].y),
  },
}

export const KINDS = Object.keys(REGISTRY) as DrawKind[]
export const GROUP_ORDER: Group[] = ['line', 'fib', 'pitchfork', 'gann', 'position', 'measure', 'shape', 'text']

/** Các tay nắm của một hình: hình dạng hộp có 4 góc, còn lại là các điểm neo. Kéo tay nắm đổi các điểm neo tương ứng. */
export function handlesFor(kind: DrawKind, P: Pt[]): Handle[] {
  const def = REGISTRY[kind]
  if (def.noHandles) return []
  if (def.box && P.length === 2) {
    const li = P[0].x <= P[1].x ? 0 : 1
    const ti = P[0].y <= P[1].y ? 0 : 1
    const out: Handle[] = []
    for (const left of [true, false]) {
      for (const top of [true, false]) {
        const xi = left ? li : 1 - li
        const yi = top ? ti : 1 - ti
        out.push({
          x: P[xi].x, y: P[yi].y,
          set: (pts, np) => pts.map((p, i) => ({ time: i === xi ? np.time : p.time, price: i === yi ? np.price : p.price })),
        })
      }
    }
    return out
  }
  return P.map((q, k) => ({ ...q, set: (pts, np) => pts.map((p, i) => (i === k ? np : p)) }))
}
