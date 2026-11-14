import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'

type Member = { el: HTMLElement; chart: IChartApi; series: ISeriesApi<'Candlestick'>; closeAt: (time: number) => number | null }

/**
 * Đồng bộ nhiều biểu đồ: cuộn/zoom theo thời gian (khác khung thời gian vẫn khớp vì đồng bộ theo mốc thời gian, không theo chỉ số nến)
 * và đường crosshair. `busy` chặn vòng lặp khi biểu đồ A đặt khoảng nhìn cho B rồi B lại báo ngược về A.
 */
export class SyncBus {
  private members = new Map<number, Member>()
  private busy = false
  private lastUser = new Map<number, number>()

  register(id: number, m: Member): () => void {
    this.members.set(id, m)
    // chỉ lan truyền thay đổi do người dùng thao tác trên chính biểu đồ này; nạp dữ liệu hay fitContent ở ô khác không được kéo các ô còn lại
    const touch = () => this.lastUser.set(id, Date.now())
    const evs = ['pointerdown', 'wheel', 'keydown', 'touchstart'] as const
    evs.forEach((e) => m.el.addEventListener(e, touch, { passive: true }))
    const onRange = (range: { from: Time; to: Time } | null) => {
      if (this.busy || !range || Date.now() - (this.lastUser.get(id) ?? 0) > 1500) return
      this.busy = true
      try {
        for (const [oid, o] of this.members) {
          if (oid === id) continue
          try { o.chart.timeScale().setVisibleRange(range) } catch { /* biểu đồ kia chưa có dữ liệu cho khoảng này */ }
        }
      } finally {
        this.busy = false
      }
    }
    const onCross = (p: { time?: Time }) => {
      if (this.busy) return
      this.busy = true
      try {
        for (const [oid, o] of this.members) {
          if (oid === id) continue
          try {
            if (p.time === undefined) o.chart.clearCrosshairPosition()
            else {
              const px = o.closeAt(p.time as number)
              if (px !== null) o.chart.setCrosshairPosition(px, p.time, o.series)
              else o.chart.clearCrosshairPosition()
            }
          } catch { /* bỏ qua */ }
        }
      } finally {
        this.busy = false
      }
    }
    m.chart.timeScale().subscribeVisibleTimeRangeChange(onRange)
    m.chart.subscribeCrosshairMove(onCross)
    return () => {
      this.members.delete(id)
      evs.forEach((e) => m.el.removeEventListener(e, touch))
      try {
        m.chart.timeScale().unsubscribeVisibleTimeRangeChange(onRange)
        m.chart.unsubscribeCrosshairMove(onCross)
      } catch { /* biểu đồ đã bị huỷ */ }
    }
  }
}
