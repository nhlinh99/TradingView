import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  applyTrade, barFromRow, decimalsFromTick, formatTime, mergeOlder, tfMs, tickLabel, type Bar, type Trade,
} from './logic.ts'

const bar = (time: number, p = 100): Bar => ({ time, open: p, high: p, low: p, close: p, volume: 1, buy: 1, sell: 0 })
const trade = (ts: number, p: number, q = 1, m = false, id = 1): Trade => ({ ts, id, p, q, m })

test('tfMs', () => {
  assert.equal(tfMs('1s'), 1000)
  assert.equal(tfMs('15m'), 900_000)
  assert.equal(tfMs('4h'), 14_400_000)
  assert.equal(tfMs('1d'), 86_400_000)
  for (const bad of ['', 'm', '0m', '1x', '-1m', '1.5m']) assert.throws(() => tfMs(bad))
})

test('decimalsFromTick', () => {
  assert.equal(decimalsFromTick(0.1), 1)
  assert.equal(decimalsFromTick(0.01), 2)
  assert.equal(decimalsFromTick(1), 0)
  assert.equal(decimalsFromTick(0.05), 2)
  assert.equal(decimalsFromTick(0.001), 3)
})

test('barFromRow converts ms to seconds', () => {
  assert.deepEqual(barFromRow([60_000, 1, 2, 0.5, 1.5, 10, 4, 6]),
    { time: 60, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10, buy: 4, sell: 6 })
})

test('applyTrade updates the current bar', () => {
  const bars = [bar(60, 100)]
  const b = applyTrade(bars, 60_000, trade(70_000, 105, 2, true))!
  assert.equal(bars.length, 1)
  assert.deepEqual(b, { time: 60, open: 100, high: 105, low: 100, close: 105, volume: 3, buy: 1, sell: 2 })
  applyTrade(bars, 60_000, trade(80_000, 95, 1, false))
  assert.deepEqual([bars[0].high, bars[0].low, bars[0].close, bars[0].buy, bars[0].sell], [105, 95, 95, 2, 2])
})

test('applyTrade opens a new bar when the bucket advances, even across a gap', () => {
  const bars = [bar(60)]
  const b = applyTrade(bars, 60_000, trade(300_500, 110, 3, false))!
  assert.equal(bars.length, 2)
  assert.deepEqual(b, { time: 300, open: 110, high: 110, low: 110, close: 110, volume: 3, buy: 3, sell: 0 })
})

test('applyTrade ignores trades older than the last bar and handles an empty array', () => {
  const bars = [bar(120)]
  assert.equal(applyTrade(bars, 60_000, trade(70_000, 1)), null)
  assert.equal(bars[0].volume, 1)
  const empty: Bar[] = []
  assert.ok(applyTrade(empty, 1000, trade(5_500, 7)))
  assert.equal(empty[0].time, 5)
})

test('applyTrade works for a daily timeframe on UTC boundaries', () => {
  const day = 86_400_000
  const bars: Bar[] = []
  applyTrade(bars, day, trade(day + 5, 1))
  applyTrade(bars, day, trade(2 * day - 1, 2))
  applyTrade(bars, day, trade(2 * day, 3))
  assert.deepEqual(bars.map((b) => b.time), [86_400, 172_800])
})

test('mergeOlder dedupes and keeps ascending order', () => {
  const merged = mergeOlder([bar(30), bar(40)], [bar(10), bar(20), bar(30)])
  assert.deepEqual(merged.map((b) => b.time), [10, 20, 30, 40])
})

test('formatTime respects the time zone', () => {
  const t = Date.UTC(2026, 10, 10, 0, 0, 0) / 1000
  assert.equal(formatTime(t, 'UTC'), '10/11/2026, 00:00')
  assert.equal(formatTime(t, 'Asia/Ho_Chi_Minh'), '10/11/2026, 07:00')
  assert.equal(formatTime(t + 5, 'UTC', true), '10/11/2026, 00:00:05')
})

test('tickLabel', () => {
  const t = Date.UTC(2026, 10, 10, 13, 5, 7) / 1000
  assert.equal(tickLabel(t, 'UTC', 60_000), '13:05')
  assert.equal(tickLabel(t, 'UTC', 1000), '13:05:07')
  assert.equal(tickLabel(t, 'UTC', 86_400_000), '10/11')
})

import { cvdSeries, delta, imbalance, profileStats, type Cell } from './logic.ts'

test('delta and CVD, with and without daily reset', () => {
  const b = (time: number, buy: number, sell: number): Bar => ({ time, open: 1, high: 1, low: 1, close: 1, volume: buy + sell, buy, sell })
  const bars = [b(86400 - 60, 3, 1), b(86400, 1, 4), b(86400 + 60, 2, 0)]
  assert.equal(delta(bars[1]), -3)
  assert.deepEqual(cvdSeries(bars, 'none'), [2, -1, 1])
  assert.deepEqual(cvdSeries(bars, 'day'), [2, -3, -1])
})

test('diagonal imbalance at 3:1', () => {
  const cells: Cell[] = [
    { price: 100, buy: 1, sell: 2 },
    { price: 101, buy: 6, sell: 1 }, // buy 6 vs sell below 2 -> 3:1 buy imbalance
    { price: 102, buy: 1, sell: 9 }, // sell 9 vs buy above? none above -> null
  ]
  assert.equal(imbalance(cells, 1, 1, 3), 'buy')
  assert.equal(imbalance(cells, 0, 1, 3), null)
  assert.equal(imbalance(cells, 1, 1, 4), null)
  const c2: Cell[] = [{ price: 100, buy: 2, sell: 1 }, { price: 101, buy: 1, sell: 7 }]
  assert.equal(imbalance(c2, 1, 1, 3), null) // sell side needs a buy cell ABOVE
  const c3: Cell[] = [{ price: 100, buy: 1, sell: 1 }, { price: 99, buy: 0, sell: 3 }]
  assert.equal(imbalance(c3, 1, 1, 3), 'sell') // sell 3 at 99 vs buy 1 at 100 above: 3:1
})

test('profile POC and value area', () => {
  const cells: Cell[] = [10, 20, 100, 30, 5].map((v, i) => ({ price: 100 + i, buy: v / 2, sell: v / 2 }))
  const p = profileStats(cells, 0.7)!
  assert.equal(p.poc, 102)
  assert.ok(p.val <= 102 && p.vah >= 102)
  assert.equal(profileStats([]), null)
})

import { heatColor, timeToIndex } from './logic.ts'

test('timeToIndex interpolates, extrapolates, handles gaps', () => {
  const t = [0, 60, 120, 300] // khuyết 180 và 240
  assert.equal(timeToIndex(t, 60, 60), 1)
  assert.equal(timeToIndex(t, 90, 60), 1.5)
  assert.equal(timeToIndex(t, 210, 60), 2.5) // trong khoảng trống: nội suy giữa hai nến kề
  assert.equal(timeToIndex(t, -60, 60), -1)
  assert.equal(timeToIndex(t, 360, 60), 4)
  assert.equal(timeToIndex([], 5, 60), 0)
})

test('heatColor clamps and is monotone in alpha', () => {
  assert.deepEqual(heatColor(0), [0, 0, 0, 0])
  assert.equal(heatColor(5)[3], heatColor(1)[3])
  assert.ok(heatColor(0.9)[3] > heatColor(0.2)[3])
  assert.equal(heatColor(-1)[3], 0)
})

import { distToSegment, indexToTime } from './logic.ts'

test('indexToTime inverts timeToIndex, including gaps and extrapolation', () => {
  const t = [0, 60, 120, 300]
  for (const x of [0, 60, 90, 210, 300, 360, -60]) assert.ok(Math.abs(indexToTime(t, timeToIndex(t, x, 60), 60) - x) < 1e-9, String(x))
  assert.equal(indexToTime(t, 5, 60), 420)
  assert.equal(indexToTime([], 3, 60), 0)
})

test('distToSegment', () => {
  assert.equal(distToSegment(5, 5, 0, 0, 10, 0), 5)
  assert.equal(distToSegment(-3, 4, 0, 0, 10, 0), 5)   // gần đầu mút
  assert.equal(distToSegment(1, 1, 2, 2, 2, 2), Math.SQRT2) // đoạn suy biến thành điểm
})

import { bucketStartMs } from './logic.ts'

test('week and month timeframes: names, bucket boundaries, live trades', () => {
  assert.equal(tfMs('1w'), 7 * 86_400_000)
  assert.equal(tfMs('1M'), 30 * 86_400_000)
  assert.equal(tfMs('1m'), 60_000)                                  // m thường vẫn là phút
  const ms = (s: string) => Date.parse(s)
  assert.equal(bucketStartMs('1w', ms('2026-11-12T05:00:00Z')), ms('2026-11-09T00:00:00Z'))   // thứ Năm -> thứ Hai
  assert.equal(bucketStartMs('1w', ms('2026-11-09T00:00:00Z')), ms('2026-11-09T00:00:00Z'))
  assert.equal(bucketStartMs('1w', ms('2026-11-08T23:59:59Z')), ms('2026-11-02T00:00:00Z'))   // Chủ nhật thuộc tuần trước
  assert.equal(bucketStartMs('1M', ms('2026-11-30T23:00:00Z')), ms('2026-11-01T00:00:00Z'))
  assert.equal(bucketStartMs('1M', ms('2026-12-01T00:00:00Z')), ms('2026-12-01T00:00:00Z'))
  assert.equal(bucketStartMs('5m', ms('2026-11-12T05:07:30Z')), ms('2026-11-12T05:05:00Z'))
  const bars: Bar[] = []
  const t = (ts: number, p: number) => ({ ts, id: 1, p, q: 1, m: false })
  applyTrade(bars, tfMs('1w'), t(ms('2026-11-10T10:00:00Z'), 100), '1w')
  applyTrade(bars, tfMs('1w'), t(ms('2026-11-14T10:00:00Z'), 110), '1w')       // cùng tuần: gộp vào một nến
  applyTrade(bars, tfMs('1w'), t(ms('2026-11-16T00:00:00Z'), 105), '1w')       // thứ Hai kế tiếp: nến mới
  assert.equal(bars.length, 2)
  assert.equal(bars[0].time, ms('2026-11-09T00:00:00Z') / 1000)
  assert.equal(bars[0].high, 110)
})

import { stackedImbalance } from './logic.ts'

test('heatColor ramp: black to red, side tints, alpha grows', () => {
  const lo = heatColor(0.02)
  const hi = heatColor(1)
  assert.ok(hi[0] > 200 && hi[1] < 100 && hi[2] < 100)               // cao nhất: đỏ
  assert.ok(lo[0] < 40 && lo[1] < 40)                                // thấp: gần đen/xanh
  const mid = heatColor(Math.pow(0.5, 1 / 0.8))                       // giữa thang màu (sau hiệu chỉnh gamma 0.8): trắng, cả ba kênh cao
  assert.ok(mid[0] > 200 && mid[1] > 200 && mid[2] > 200)
  const bid = heatColor(0.8, 'bid')
  const ask = heatColor(0.8, 'ask')
  assert.ok(bid[1] > bid[0] && bid[1] > bid[2])                       // xanh lá
  assert.ok(ask[2] > ask[1] && ask[0] > ask[1])                       // tím
  assert.ok(heatColor(1)[3] > heatColor(0.1)[3])
})

test('stackedImbalance needs 3 consecutive same-side diagonal imbalances', () => {
  // buy imbalance ở p nếu buy[p] >= 3 * sell[p-1]
  const cells = [
    { price: 100, buy: 1, sell: 1 }, { price: 101, buy: 4, sell: 1 }, { price: 102, buy: 4, sell: 1 },
    { price: 103, buy: 4, sell: 1 }, { price: 104, buy: 1, sell: 5 },
  ]
  const r = stackedImbalance(cells, 1, 3)
  assert.deepEqual(r, { side: 'buy', from: 101, to: 103 })
  assert.equal(stackedImbalance(cells.slice(0, 3), 1, 3), null)   // chỉ 2 mức liên tiếp
  assert.equal(stackedImbalance([], 1, 3), null)
})

import { applyCutoff, bestBidAsk } from './logic.ts'

test('applyCutoff clamps and rescales like Bookmap cutoffs', () => {
  assert.equal(applyCutoff(0.1, 0.2, 0.8), 0)
  assert.equal(applyCutoff(0.9, 0.2, 0.8), 1)
  assert.ok(Math.abs(applyCutoff(0.5, 0.2, 0.8) - 0.5) < 1e-12)
  assert.equal(applyCutoff(0.3, 0.5, 0.5), 0)
  assert.equal(applyCutoff(0.7, 0.5, 0.5), 1)
})

test('bestBidAsk picks highest bid and lowest ask per time bucket', () => {
  const rows = [
    [100, 99, 5, 0], [100, 98, 3, 0], [100, 101, 0, 4], [100, 102, 0, 9],
    [200, 99.5, 2, 0], [200, 100.5, 0, 1],
  ]
  const m = bestBidAsk(rows, 1)
  assert.deepEqual(m.get(100), { bid: 100, ask: 101 })        // bid cao nhất 99 + bucket 1; ask thấp nhất 101
  assert.deepEqual(m.get(200), { bid: 100.5, ask: 100.5 })
  assert.deepEqual(bestBidAsk([[1, 10, 0, 0]], 1).get(1), { bid: null, ask: null })
})

import { highlightPine } from './logic.ts'

test('highlightPine round-trips the source and classifies tokens', () => {
  const src = '//@version=5\nindicator("x", overlay=true)\nlen = input.int(20, "L")\nif close > ta.sma(close, len) // up\n    plot(1.5e3, color=#ff0000)\n'
  const toks = highlightPine(src)
  assert.equal(toks.map((t) => t.text).join(''), src)
  const kinds = (k: string) => toks.filter((t) => t.kind === k).map((t) => t.text)
  assert.deepEqual(kinds('comment'), ['//@version=5', '// up'])
  assert.deepEqual(kinds('string'), ['"x"', '"L"'])
  assert.deepEqual(kinds('keyword'), ['true', 'if'])
  assert.ok(kinds('func').includes('input.int') && kinds('func').includes('ta.sma') && kinds('func').includes('indicator') && kinds('func').includes('plot'))
  assert.ok(kinds('number').includes('20') && kinds('number').includes('1.5e3'))
  assert.deepEqual(kinds('const'), ['#ff0000'])
  assert.equal(highlightPine('').length, 0)
})
