import { useCallback, useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, createChart,
  type IChartApi, type ISeriesApi, type UTCTimestamp,
} from 'lightweight-charts'
import { fetchBars, openStream, type PineResult, type StreamState } from './api'
import Footprint from './Footprint'
import Profile from './Profile'
import Heatmap from './Heatmap'
import Bubbles from './Bubbles'
import Gex from './Gex'
import PineLayer from './PineLayer'
import {
  applyTrade, cvdSeries, delta, barFromRow, decimalsFromTick, formatTime, formatVolume, mergeOlder, tfMs, tickLabel,
  type Bar, type Trade,
} from './logic'

const PALETTE = {
  light: { bg: '#ffffff', text: '#1b2430', line: '#d9e0ea', grid: '#eef1f5', up: '#0b8f5b', down: '#d1362f' },
  dark: { bg: '#131722', text: '#d1d4dc', line: '#2a2e39', grid: '#1e222d', up: '#26a69a', down: '#ef5350' },
}
const volColor = (b: Bar, up: string, down: string) => (b.close >= b.open ? up + '88' : down + '88')

export type Flow = { delta: boolean; cvd: 'off' | 'none' | 'day'; footprint: boolean; vpvr: boolean; heatmap: boolean; bubbles: boolean; gex: boolean; ratio: number }
type Props = { symbol: string; tf: string; tz: string; flow: Flow; pine: PineResult | null; theme: 'light' | 'dark'; onState: (s: StreamState) => void }
type Legend = { time: number; bar: Bar } | null

export default function Chart({ symbol, tf, tz, flow, pine, theme, onState }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candles = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volume = useRef<ISeriesApi<'Histogram'> | null>(null)
  const bars = useRef<Bar[]>([])
  const tzRef = useRef(tz)
  const tfRef = useRef(tfMs(tf))
  const deltaS = useRef<ISeriesApi<'Histogram'> | null>(null)
  const cvdS = useRef<ISeriesApi<'Line'> | null>(null)
  const flowRef = useRef(flow)
  flowRef.current = flow
  const [version, setVersion] = useState(0)
  const [legend, setLegend] = useState<Legend>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const themeRef = useRef(theme)
  themeRef.current = theme
  tzRef.current = tz
  tfRef.current = tfMs(tf)

  // tạo biểu đồ một lần
  useEffect(() => {
    const el = box.current!
    const P = PALETTE[themeRef.current]
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: P.bg }, textColor: P.text, panes: { separatorColor: P.line } },
      grid: { vertLines: { color: P.grid }, horzLines: { color: P.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: P.line },
      timeScale: {
        borderColor: P.line, timeVisible: true, secondsVisible: false,
        tickMarkFormatter: (t: UTCTimestamp) => tickLabel(t, tzRef.current, tfRef.current),
      },
      localization: { timeFormatter: (t: UTCTimestamp) => formatTime(t, tzRef.current, true) },
    })
    const c = chart.addSeries(CandlestickSeries, {
      upColor: P.up, downColor: P.down, borderUpColor: P.up, borderDownColor: P.down, wickUpColor: P.up, wickDownColor: P.down,
    })
    const v = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false }, 1)
    chart.panes()[1]?.setStretchFactor(0.25)
    chart.subscribeCrosshairMove((p) => {
      const d = p.seriesData.get(c) as { time: number } | undefined
      if (!p.time || !d) return setLegend(null)
      const b = bars.current.find((x) => x.time === (p.time as number))
      setLegend(b ? { time: b.time, bar: b } : null)
    })
    chartRef.current = chart
    if (import.meta.env.DEV) (window as unknown as { __tvChart?: IChartApi }).__tvChart = chart // chỉ để kiểm thử trong dev
    candles.current = c
    volume.current = v
    return () => {
      chart.remove()
      chartRef.current = candles.current = volume.current = deltaS.current = cvdS.current = null
    }
  }, [])

  // vẽ lại delta/CVD từ mảng nến hiện có
  const refreshFlow = useCallback(() => {
    const P = PALETTE[themeRef.current]
    const list = bars.current
    deltaS.current?.setData(list.map((b) => ({ time: b.time as UTCTimestamp, value: delta(b), color: delta(b) >= 0 ? P.up : P.down })))
    if (cvdS.current && flowRef.current.cvd !== 'off') {
      const cv = cvdSeries(list, flowRef.current.cvd)
      cvdS.current.setData(list.map((b, i) => ({ time: b.time as UTCTimestamp, value: cv[i] })))
    }
  }, [])
  const refreshRef = useRef(refreshFlow)
  refreshRef.current = refreshFlow

  // bật/tắt pane delta và CVD
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (flow.delta && !deltaS.current) {
      deltaS.current = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'volume' } }, chart.panes().length)
    } else if (!flow.delta && deltaS.current) {
      chart.removeSeries(deltaS.current)
      deltaS.current = null
    }
    if (flow.cvd !== 'off' && !cvdS.current) {
      cvdS.current = chart.addSeries(LineSeries, { color: '#f0b90b', lineWidth: 2, priceLineVisible: false, priceFormat: { type: 'volume' } }, chart.panes().length)
    } else if (flow.cvd === 'off' && cvdS.current) {
      chart.removeSeries(cvdS.current)
      cvdS.current = null
    }
    const panes = chart.panes()
    panes.forEach((p, i) => { if (i >= 2) p.setStretchFactor(0.2) })
    refreshFlow()
  }, [flow.delta, flow.cvd, refreshFlow])

  // đổi giao diện sáng/tối
  useEffect(() => {
    const P = PALETTE[theme]
    chartRef.current?.applyOptions({
      layout: { background: { type: ColorType.Solid, color: flow.heatmap ? 'rgba(0,0,0,0)' : P.bg }, textColor: P.text, panes: { separatorColor: P.line } },
      grid: { vertLines: { color: P.grid }, horzLines: { color: P.grid } },
      rightPriceScale: { borderColor: P.line }, timeScale: { borderColor: P.line },
    })
    candles.current?.applyOptions({ upColor: flow.footprint ? 'transparent' : P.up, downColor: flow.footprint ? 'transparent' : P.down, borderUpColor: P.up, borderDownColor: P.down, wickUpColor: P.up, wickDownColor: P.down })
    volume.current?.setData(bars.current.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: volColor(b, P.up, P.down) })))
    refreshRef.current()
  }, [theme, flow.footprint, flow.heatmap])

  // đổi múi giờ: vẽ lại nhãn
  useEffect(() => {
    chartRef.current?.applyOptions({
      timeScale: { secondsVisible: tfMs(tf) < 60_000 },
      localization: { timeFormatter: (t: UTCTimestamp) => formatTime(t, tz, true) },
    })
  }, [tz, tf])

  // nạp nến và nhận lệnh khớp trực tiếp
  useEffect(() => {
    const ctrl = new AbortController()
    let ready = false
    let lastId: number | null = null
    let buffer: Trade[] = []
    let seq = 0
    const step = tfMs(tf)

    let flowTimer = 0
    const scheduleFlow = () => {
      if (flowTimer) return
      flowTimer = window.setTimeout(() => { flowTimer = 0; refreshRef.current() }, 250)
    }
    const paint = (all: Bar[], fit: boolean) => {
      candles.current?.setData(all.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })))
      volume.current?.setData(all.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: volColor(b, PALETTE[themeRef.current].up, PALETTE[themeRef.current].down) })))
      if (fit) chartRef.current?.timeScale().fitContent()
      if (import.meta.env.DEV) (window as unknown as { __tvBars?: Bar[] }).__tvBars = bars.current
      refreshRef.current()
      setVersion((v) => v + 1)
    }
    const apply = (t: Trade) => {
      if (lastId !== null && t.id <= lastId) return // đã nằm trong nến tải về
      lastId = t.id
      const b = applyTrade(bars.current, step, t)
      if (!b) return
      candles.current?.update({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })
      volume.current?.update({ time: b.time as UTCTimestamp, value: b.volume, color: volColor(b, PALETTE[themeRef.current].up, PALETTE[themeRef.current].down) })
      scheduleFlow()
    }
    const load = async () => {
      const my = ++seq
      ready = false
      buffer = [] // bắt đầu đệm lệnh khớp TRƯỚC khi gọi API, để không hở giữa nến và luồng trực tiếp
      setLoading(true)
      try {
        const j = await fetchBars(symbol, tf, 1000, undefined, ctrl.signal)
        if (my !== seq) return
        const dec = decimalsFromTick(j.tick)
        candles.current?.applyOptions({ priceFormat: { type: 'price', precision: dec, minMove: j.tick } })
        bars.current = j.bars.map(barFromRow)
        lastId = j.last_trade_id
        const first = my === 1
        paint(bars.current, first)
        ready = true
        for (const t of buffer) apply(t)
        buffer = []
        setError(null)
      } catch (e) {
        if (!ctrl.signal.aborted && my === seq) setError(String(e))
      } finally {
        if (my === seq) setLoading(false)
      }
    }

    bars.current = []
    candles.current?.setData([])
    volume.current?.setData([])
    const stop = openStream(symbol, {
      onTrade: (t) => (ready ? apply(t) : buffer.push(t)),
      onState: onState,
      onOpen: () => void load(), // gồm cả lần nối lại: nạp lại nến để vá khoảng hở
    })

    // kéo về quá khứ: nạp thêm nến cũ khi gần hết dữ liệu bên trái
    let olderBusy = false
    const onRange = async () => {
      const chart = chartRef.current
      const range = chart?.timeScale().getVisibleLogicalRange()
      if (!chart || !range || olderBusy || !ready || bars.current.length === 0 || range.from > 20) return
      olderBusy = true
      try {
        const j = await fetchBars(symbol, tf, 1000, bars.current[0].time * 1000, ctrl.signal)
        const older = j.bars.map(barFromRow)
        if (older.length === 0 || ctrl.signal.aborted) return
        const before = bars.current.length
        bars.current = mergeOlder(bars.current, older)
        const added = bars.current.length - before
        paint(bars.current, false)
        chart.timeScale().setVisibleLogicalRange({ from: range.from + added, to: range.to + added })
      } catch {
        /* lỗi tạm thời: lần cuộn sau thử lại */
      } finally {
        olderBusy = false
      }
    }
    chartRef.current?.timeScale().subscribeVisibleLogicalRangeChange(onRange)

    return () => {
      ctrl.abort()
      window.clearTimeout(flowTimer)
      stop()
      chartRef.current?.timeScale().unsubscribeVisibleLogicalRangeChange(onRange)
    }
  }, [symbol, tf, onState])

  const b = legend?.bar
  return (
    <div className="chart-wrap">
      <Heatmap on={flow.heatmap} symbol={symbol} tf={tf} chart={chartRef} candles={candles} bars={bars} version={version} />
      <div ref={box} className="chart" data-testid="chart" />
      <Bubbles on={flow.bubbles} symbol={symbol} tf={tf} chart={chartRef} candles={candles} bars={bars} version={version} />
      <PineLayer result={pine} chart={chartRef} candles={candles} version={version} />
      <Gex on={flow.gex} symbol={symbol} dark={theme === 'dark'} chart={chartRef} candles={candles} />
      <Profile on={flow.vpvr} symbol={symbol} tf={tf} dark={theme === 'dark'} chart={chartRef} candles={candles} bars={bars} version={version} />
      <Footprint on={flow.footprint} symbol={symbol} tf={tf} ratio={flow.ratio} dark={theme === 'dark'}
        chart={chartRef} candles={candles} bars={bars} version={version} />
      <div className="legend" aria-live="off">
        {b ? (
          <>
            <span>{formatTime(b.time, tz)}</span>
            <span>O <b>{b.open}</b></span><span>H <b>{b.high}</b></span>
            <span>L <b>{b.low}</b></span><span>C <b>{b.close}</b></span>
            <span>Vol <b>{formatVolume(b.volume)}</b></span>
            <span>Mua <b className="up">{formatVolume(b.buy)}</b></span>
            <span>Bán <b className="down">{formatVolume(b.sell)}</b></span>
          </>
        ) : (
          <span className="mute">{symbol} · {tf}</span>
        )}
      </div>
      {loading && <div className="overlay">Đang tải...</div>}
      {error && <div className="overlay bad" role="alert">Không tải được nến: {error}</div>}
    </div>
  )
}
