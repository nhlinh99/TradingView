/** Màu Pine/CSS (#RGB, #RRGGBB, #RRGGBBAA, rgb(), rgba()) -> hex 6 chữ số và độ đục 0..1. Không đọc được thì trả null. */
export function parseColor(c: string | null | undefined): { hex: string; a: number } | null {
  if (!c) return null
  const s = c.trim()
  let m = /^#([0-9a-f]{3})$/i.exec(s)
  if (m) return { hex: '#' + m[1].split('').map((x) => x + x).join('').toUpperCase(), a: 1 }
  m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(s)
  if (m) return { hex: '#' + m[1].toUpperCase(), a: m[2] ? parseInt(m[2], 16) / 255 : 1 }
  m = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)(?:[\s,/]+([\d.]+%?))?\s*\)$/i.exec(s)
  if (m) {
    const h = [m[1], m[2], m[3]].map((x) => Math.max(0, Math.min(255, Number(x))).toString(16).padStart(2, '0')).join('')
    const a = m[4] === undefined ? 1 : m[4].endsWith('%') ? Number.parseFloat(m[4]) / 100 : Number(m[4])
    return { hex: '#' + h.toUpperCase(), a: Math.max(0, Math.min(1, a)) }
  }
  return null
}

/** hex 6 chữ số + độ đục -> chuỗi rgba() dùng được cho canvas và lightweight-charts. */
export function rgba(hex: string, a: number): string {
  const p = parseColor(hex)
  if (!p) return hex
  const n = parseInt(p.hex.slice(1), 16)
  const alpha = Math.max(0, Math.min(1, a))
  return alpha >= 1 ? p.hex : `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${Math.round(alpha * 100) / 100})`
}

/** Bảng màu gợi ý, theo thứ tự quen thuộc của TradingView. */
export const PALETTE = [
  '#FFFFFF', '#B2B5BE', '#787B86', '#363A45', '#000000',
  '#F23645', '#FF9800', '#FFEB3B', '#4CAF50', '#089981',
  '#00BCD4', '#2962FF', '#673AB7', '#9C27B0', '#E91E63',
]
