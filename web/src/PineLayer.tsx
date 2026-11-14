import { useEffect, type MutableRefObject } from 'react'
import {
  HistogramSeries, LineSeries, LineStyle, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type SeriesMarker, type Time, type UTCTimestamp,
} from 'lightweight-charts'
import type { PineResult } from './api'

type Props = {
  result: PineResult | null
  chart: MutableRefObject<IChartApi | null>
  candles: MutableRefObject<ISeriesApi<'Candlestick'> | null>
  version: number
}

const hex = (c: string | null | undefined, fallback: string) => (c ? c : fallback)
const t = (ms: number) => (ms / 1000) as UTCTimestamp

/** Vẽ kết quả script Pine lên biểu đồ: plot (đường/cột), plotshape (marker), hline, và lệnh của strategy. */
export default function PineLayer({ result, chart, candles, version }: Props) {
  useEffect(() => {
    const c = chart.current
    const main = candles.current
    if (!c || !main || !result) return
    const series: ISeriesApi<'Line' | 'Histogram'>[] = []
    const lines: IPriceLine[] = []
    const markerSets: { detach: () => void }[] = []
    const overlay = result.meta.overlay
    // indicator không overlay: mỗi script một pane mới ở cuối
    const pane = overlay ? 0 : c.panes().length

    for (const p of result.plots) {
      const colorOf = (i: number) => hex(p.colors[i], '#2962FF')
      if (p.style === 'columns' || p.style === 'histogram') {
        const s = c.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, title: p.title }, pane)
        s.setData(result.times.flatMap((ms, i) => (p.values[i] === null ? [] : [{ time: t(ms), value: p.values[i] as number, color: colorOf(i) }])))
        series.push(s)
      } else {
        const s = c.addSeries(LineSeries, {
          color: colorOf(p.colors.findIndex((x) => x) >= 0 ? p.colors.findIndex((x) => x) : 0), lineWidth: Math.max(1, Math.min(4, p.linewidth)) as 1 | 2 | 3 | 4,
          priceLineVisible: false, lastValueVisible: false, title: p.title,
          lineStyle: p.style === 'circles' || p.style === 'cross' ? LineStyle.Dotted : LineStyle.Solid,
        }, pane)
        // màu thay đổi theo nến được hỗ trợ bằng cách cho từng điểm một màu
        s.setData(result.times.flatMap((ms, i) => (p.values[i] === null ? [] : [{ time: t(ms), value: p.values[i] as number, color: colorOf(i) }])))
        series.push(s)
      }
    }
    if (!overlay && result.plots.length > 0) c.panes()[pane]?.setStretchFactor(0.25)

    const markers: SeriesMarker<Time>[] = []
    for (const sh of result.shapes) {
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
      if (h.price !== null) lines.push(main.createPriceLine({ price: h.price, color: hex(h.color, '#787B86'), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: h.title }))
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
