import test from 'node:test'
import assert from 'node:assert/strict'
import { parseColor, rgba } from './colors.ts'

test('parseColor đọc các dạng màu của Pine', () => {
  assert.deepEqual(parseColor('#2962ff'), { hex: '#2962FF', a: 1 })
  assert.deepEqual(parseColor('#f00'), { hex: '#FF0000', a: 1 })
  assert.equal(parseColor('#00FF0080')?.hex, '#00FF00')
  assert.ok(Math.abs((parseColor('#00FF0080')?.a ?? 0) - 128 / 255) < 1e-9)
  assert.deepEqual(parseColor('rgba(255, 0, 0, 0.25)'), { hex: '#FF0000', a: 0.25 })
  assert.equal(parseColor('không phải màu'), null)
  assert.equal(parseColor(null), null)
})

test('rgba ghép màu và độ đục', () => {
  assert.equal(rgba('#FF0000', 1), '#FF0000')
  assert.equal(rgba('#FF0000', 0.5), 'rgba(255, 0, 0, 0.5)')
  assert.equal(rgba('#00ff00', 2), '#00FF00')
})
