import { useEffect, type MutableRefObject } from 'react'
import {
  CandlestickSeries, HistogramSeries, LineSeries, LineStyle, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type SeriesMarker, type Time, type UTCTimestamp,
} from 'lightweight-charts'
import type { PineResult } from './api'
import { tfMs } from './logic'

type Props = {
  result: PineResult | null
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  version: number
}

const hex = (c: string | null | undefined, fallback: string) => (c ? c : fallback)
const t = (ms: number) => (ms / 1000) as UTCTimestamp
/** Thời điểm (ms) của chỉ số i; i vượt nến cuối thì ngoại suy theo bước của khung (cho plot có offset). */
const timeAt = (times: number[], i: number, stepMs: number) => (i < times.length ? times[i] : times[times.length - 1] + (i - times.length + 1) * stepMs)

/** Vẽ kết quả script Pine lên biểu đồ: plot (đường/cột), plotshape (marker), hline, và lệnh của strategy. */
export default function PineLayer({ result, chart, candles, version }: Props) {
  useEffect(() => {
    const c = chart.current
    const main = candles.current
    if (!c || !main || !result) return
    const series: ISeriesApi<'Line' | 'Histogram' | 'Candlestick'>[] = []
    const lines: IPriceLine[] = []
    const markerSets: { detach: () => void }[] = []
    const overlay = result.meta.overlay
    const stepMs = tfMs(result.tf)
    const idx = (n: number) => Array.from({ length: n }, (_, i) => timeAt(result.times, i, stepMs))
    // indicator không overlay: mỗi script một pane mới ở cuối
    const pane = overlay ? 0 : c.panes().length

    const lastLabel = !!result.scaleLabels
    const dashOf = (d: string | undefined, fallback: LineStyle) => (d === 'dashed' ? LineStyle.Dashed : d === 'dotted' ? LineStyle.Dotted : d === 'solid' ? LineStyle.Solid : fallback)
    for (const p of result.plots) {
      if (p.hidden) continue
      const colorOf = (i: number) => hex(p.colors[i], '#2962FF')
      if (p.style === 'columns' || p.style === 'histogram') {
        const s = c.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: lastLabel, title: p.title }, pane)
        s.setData(idx(p.values.length).flatMap((ms, i) => (p.values[i] === null ? [] : [{ time: t(ms), value: p.values[i] as number, color: colorOf(i) }])))
        series.push(s)
      } else {
        const s = c.addSeries(LineSeries, {
          color: colorOf(p.colors.findIndex((x) => x) >= 0 ? p.colors.findIndex((x) => x) : 0), lineWidth: Math.max(1, Math.min(4, p.linewidth)) as 1 | 2 | 3 | 4,
          priceLineVisible: false, lastValueVisible: lastLabel,
          lineStyle: dashOf(p.dash, p.style === 'circles' || p.style === 'cross' ? LineStyle.Dotted : LineStyle.Solid),
        }, pane)
        // màu thay đổi theo nến được hỗ trợ bằng cách cho từng điểm một màu
        s.setData(idx(p.values.length).flatMap((ms, i) => (p.values[i] === null ? [] : [{ time: t(ms), value: p.values[i] as number, color: colorOf(i) }])))
        series.push(s)
      }
    }
    if (!overlay && result.plots.length > 0) c.panes()[pane]?.setStretchFactor(0.25)

    // bgcolor: cột cao hết vùng giá, nằm trên thang giá riêng (ẩn) để không làm méo thang giá của nến
    if (overlay) {
      for (const bg of result.bgcolors) {
        if (bg.hidden) continue
        const data = result.times.flatMap((ms, i) => (bg.colors[i] ? [{ time: t(ms), value: 1, color: bg.colors[i] as string }] : []))
        if (data.length === 0) continue
        const s = c.addSeries(HistogramSeries, { priceScaleId: 'pine-bg', priceLineVisible: false, lastValueVisible: false, base: 0 }, 0)
        c.priceScale('pine-bg').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false })
        s.setData(data)
        series.push(s)
      }
    }

    // plotcandle/plotbar: nến vẽ riêng chồng lên nến của biểu đồ (thường dùng để tô lại màu nến)
    if (overlay) {
      for (const cd of result.candles ?? []) {
        const data = result.times.flatMap((ms, i) => {
          const v = cd.ohlc[i]
          return v ? [{ time: t(ms), open: v[0], high: v[1], low: v[2], close: v[3], color: cd.color[i] ?? '#888', wickColor: cd.wick[i] ?? '#888', borderColor: cd.border[i] ?? '#888' }] : []
        })
        if (data.length === 0) continue
        const s = c.addSeries(CandlestickSeries, { priceLineVisible: false, lastValueVisible: false }, 0)
        s.setData(data)
        series.push(s)
      }
    }

    const markers: SeriesMarker<Time>[] = []
    for (const sh of result.shapes) {
      if (sh.hidden) continue
      sh.values.forEach((on, i) => {
        if (!on) return
        const up = sh.location === 'belowbar' || sh.shape.includes('up')
        markers.push({
          time: t(result.times[i]), position: sh.location === 'belowbar' ? 'belowBar' : 'aboveBar',
          shape: sh.shape.includes('circle') ? 'circle' : up ? 'arrowUp' : 'arrowDown',
          color: hex(sh.colors[i], '#2962FF'), text: sh.text || undefined,
        })
      })
    }
    const st = result.strategy
    if (st) {
      for (const tr of st.trades) {
        markers.push({ time: t(tr.entry_time), position: tr.dir === 'long' ? 'belowBar' : 'aboveBar', shape: tr.dir === 'long' ? 'arrowUp' : 'arrowDown', color: '#26a69a', text: tr.id })
        markers.push({ time: t(tr.exit_time), position: tr.dir === 'long' ? 'aboveBar' : 'belowBar', shape: tr.dir === 'long' ? 'arrowDown' : 'arrowUp', color: '#ef5350', text: tr.pnl.toFixed(0) })
      }
    }
    if (markers.length > 0 && overlay) {
      markers.sort((a, b) => (a.time as number) - (b.time as number))
      markerSets.push(createSeriesMarkers(main, markers))
    }
    for (const h of result.hlines) {
      if (h.price !== null && !h.hidden) lines.push(main.createPriceLine({ price: h.price, color: hex(h.color, '#787B86'), lineWidth: Math.max(1, Math.min(4, h.width ?? 1)) as 1 | 2 | 3 | 4, lineStyle: dashOf(h.dash, LineStyle.Dashed), axisLabelVisible: true, title: h.title }))
    }
    if (st && st.equity.length > 0) {
      const eq = c.addSeries(LineSeries, { color: '#f0b90b', lineWidth: 2, priceLineVisible: false, title: 'Equity' }, c.panes().length)
      eq.setData(result.times.flatMap((ms, i) => (st.equity[i] === null ? [] : [{ time: t(ms), value: st.equity[i] as number }])))
      series.push(eq)
      c.panes()[c.panes().length - 1]?.setStretchFactor(0.25)
    }

    return () => {
      markerSets.forEach((m) => m.detach())
      lines.forEach((l) => main.removePriceLine(l))
      series.forEach((s) => { try { c.removeSeries(s) } catch { /* biểu đồ đã bị huỷ */ } })
    }
  }, [result, chart, candles, version])

  return null
}
