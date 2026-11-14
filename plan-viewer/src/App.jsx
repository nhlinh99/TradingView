import React, { useMemo, useState, useEffect, useCallback } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ReactFlow, Background, Controls, Handle, Position, BaseEdge, EdgeLabelRenderer,
  getSmoothStepPath, applyNodeChanges, MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './styles.css';
import { components, edges as edgeDefs, phases, layout, lanes, freeMatrix, storage, history, historyLimits } from './data.js';

const CLS = { free: ['Miễn phí', 'b-free'], maybe: ['Miễn phí, chưa chắc', 'b-unverified'], paid: ['Trả phí', 'b-paid'], none: ['Không có', 'b-none'] };

const BADGES = { free: 'Miễn phí', paid: 'Trả phí', unverified: 'Chưa xác minh' };
const COLORS = { request: '#1476ff', data: '#ff791f' };

function Card({ data }) {
  const c = data.c;
  return (
    <div className={`card k-${c.kind} ${data.dim ? 'dim' : ''} ${data.current ? 'current' : ''} ${data.selected ? 'sel' : ''}`}>
      {['l-t', 'l-s'].map(id => <Handle key={id} id={id} type={id.endsWith('t') ? 'target' : 'source'} position={Position.Left} />)}
      {['r-t', 'r-s'].map(id => <Handle key={id} id={id} type={id.endsWith('t') ? 'target' : 'source'} position={Position.Right} />)}
      {['t-t', 't-s'].map(id => <Handle key={id} id={id} type={id.endsWith('t') ? 'target' : 'source'} position={Position.Top} />)}
      {['b-t', 'b-s'].map(id => <Handle key={id} id={id} type={id.endsWith('t') ? 'target' : 'source'} position={Position.Bottom} />)}
      <div className="card-title">{c.label}</div>
      <div className="card-sub">{c.sub}</div>
      {c.badge && <span className={`badge b-${c.badge}`}>{BADGES[c.badge]}</span>}
    </div>
  );
}

function Lane({ data }) {
  return <div className="lane" style={{ width: data.w, height: data.h }}><span>{data.label}</span></div>;
}

function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }) {
  const [path, lx, ly] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 14 });
  const color = COLORS[data.kind];
  const animate = data.loop && !data.reduced && !data.dim;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={`url(#arrow-${data.kind})`}
        style={{ stroke: color, strokeWidth: 2, strokeDasharray: data.kind === 'data' ? '6 5' : undefined, opacity: data.dim ? 0.15 : 0.9 }} />
      {animate && [0, 1].map(p => (
        <path key={p} className="flow-pulse" d="M -5 -4 L 1 0 L -5 4" fill="none" stroke={color}
          strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          style={{ offsetPath: `path('${path}')`, offsetRotate: 'auto', animationDelay: `${-p * 1.5}s` }} aria-hidden="true" />
      ))}
      <EdgeLabelRenderer>
        <div className={`edge-label ${data.dim ? 'dim' : ''}`} hidden={!data.label}
          style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}>{data.label}</div>
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes = { card: Card, lane: Lane };
const edgeTypes = { flow: FlowEdge };

function useReducedMotion() {
  const [r, setR] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const m = matchMedia('(prefers-reduced-motion: reduce)');
    const h = e => setR(e.matches);
    m.addEventListener('change', h);
    return () => m.removeEventListener('change', h);
  }, []);
  return r;
}

function App() {
  const [view, setView] = useState('all'); // 'all' hoặc id phase
  const [selected, setSelected] = useState('collector');
  const [loop, setLoop] = useState(true);
  const reduced = useReducedMotion();
  const [pos, setPos] = useState(layout);
  const [rfNodes, setRfNodes] = useState([]);

  const phaseIdx = view === 'all' ? phases.length - 1 : phases.findIndex(p => p.id === view);
  const active = useMemo(() => {
    const s = new Set();
    phases.slice(0, phaseIdx + 1).forEach(p => p.add.forEach(i => s.add(i)));
    return s;
  }, [phaseIdx]);
  const current = useMemo(() => new Set(view === 'all' ? [] : phases[phaseIdx].add), [view, phaseIdx]);

  const built = useMemo(() => {
    const laneNodes = lanes.map(l => ({ id: l.id, type: 'lane', position: { x: l.x, y: l.y }, data: l,
      draggable: false, selectable: false, zIndex: -1, style: { width: l.w, height: l.h } }));
    const cards = Object.keys(components).map(id => ({
      id, type: 'card', position: pos[id], zIndex: 1,
      data: { c: components[id], dim: !active.has(id), current: current.has(id), selected: selected === id },
    }));
    return [...laneNodes, ...cards];
  }, [active, current, selected, pos]);

  useEffect(() => { setRfNodes(prev => built.map(n => { const o = prev.find(p => p.id === n.id); return o ? { ...n, position: o.position, measured: o.measured } : n; })); }, [built]);

  const onNodesChange = useCallback(ch => {
    setRfNodes(ns => applyNodeChanges(ch, ns));
    ch.forEach(c => { if (c.type === 'position' && c.position && components[c.id]) setPos(p => ({ ...p, [c.id]: c.position })); });
  }, []);

  const rfEdges = edgeDefs.map(e => ({
    id: e.id, source: e.s, target: e.t, sourceHandle: e.sh, targetHandle: e.th, type: 'flow', zIndex: 2,
    data: { kind: e.kind, label: e.label, loop, reduced, dim: !(active.has(e.s) && active.has(e.t)) },
  }));

  const c = components[selected];
  const ph = view === 'all' ? null : phases[phaseIdx];

  return (
    <div className="page">
      <header>
        <h1>Chart cá nhân kiểu TradingView</h1>
        <p>Dữ liệu đi từ nguồn, qua collector, vào kho, qua server, rồi lên chart. Chọn một phase để xem thứ gì xuất hiện ở bước đó. Bấm vào một khối để đọc giải thích.</p>
      </header>

      <div className="tabs" role="tablist" aria-label="Chọn phase">
        <button role="tab" aria-selected={view === 'all'} className={view === 'all' ? 'on' : ''} onClick={() => setView('all')}>Tổng quan</button>
        {phases.map(p => (
          <button key={p.id} role="tab" aria-selected={view === p.id} className={view === p.id ? 'on' : ''}
            onClick={() => { setView(p.id); setSelected(p.add[0]); }} title={p.title}>{p.tab}</button>
        ))}
      </div>

      <div className="toolbar">
        <div className="legend">
          <span><i className="sw req" /> Yêu cầu và phản hồi</span>
          <span><i className="sw dat" /> Dòng dữ liệu</span>
          <span><i className="sw cur" /> Mới ở phase này</span>
        </div>
        <label className="toggle">
          <input type="checkbox" checked={loop && !reduced} disabled={reduced} onChange={e => setLoop(e.target.checked)} />
          Mũi tên chuyển động
        </label>
      </div>

      <div className="canvas">
        <svg width="0" height="0" style={{ position: 'absolute' }}>
          <defs>
            {Object.entries(COLORS).map(([k, col]) => (
              <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill={col} />
              </marker>
            ))}
          </defs>
        </svg>
        <ReactFlow nodes={rfNodes} edges={rfEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
          onNodesChange={onNodesChange} onNodeClick={(_, n) => components[n.id] && setSelected(n.id)}
          fitView fitViewOptions={{ padding: 0.04 }} minZoom={0.3} maxZoom={1.6}
          nodesConnectable={false} proOptions={{ hideAttribution: true }}>
          <Background color="#fff" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <p className="note">Chuyển động chỉ cho thấy hướng dữ liệu. Nó không biểu diễn tốc độ, độ trễ hay thứ tự thật của các bước.</p>

      <section className={`detail ${ph ? '' : 'solo'}`}>
        {ph && (
          <div className="phase-box">
            <h2>{ph.tab}: {ph.title}</h2>
            <p>{ph.sum}</p>
            <p><b>Nghiệm thu:</b> {ph.ok}</p>
          </div>
        )}
        <div className="comp-box">
          <h2>{c.label} <small>{c.sub}</small>{c.badge && <span className={`badge b-${c.badge}`}>{BADGES[c.badge]}</span>}</h2>
          <dl>
            <dt>Chức năng</dt><dd>{c.what}</dd>
            <dt>Cách hoạt động</dt><dd>{c.how}</dd>
            <dt>Điểm mạnh</dt><dd>{c.pros}</dd>
            <dt>Điểm yếu</dt><dd>{c.cons}</dd>
            <dt>Lý do chọn</dt><dd>{c.why}</dd>
          </dl>
        </div>
      </section>

      <section className="matrix">
        <h2>Dữ liệu lịch sử để backtest</h2>
        <table>
          <thead><tr><th>Dữ liệu</th><th>Symbol</th><th>Từ ngày</th><th>Chi phí</th><th>Dùng cho</th></tr></thead>
          <tbody>
            {history.map(r => (
              <tr key={r.d + r.s}><td>{r.d}</td><td>{r.s}</td><td>{r.from}</td>
                <td><span className={`badge ${CLS[r.c][1]}`}>{r.c === 'maybe' ? CLS.maybe[0] : r.c === 'free' ? 'Miễn phí' : r.c === 'paid' ? 'Trả phí hoặc tự ghi' : 'Chưa có'}</span></td>
                <td>{r.use}</td></tr>
            ))}
          </tbody>
        </table>
        <h3 className="sub">Giới hạn khi backtest</h3>
        <ul className="rules">{historyLimits.map(r => <li key={r}>{r}</li>)}</ul>
      </section>

      <section className="matrix storage">
        <h2>Dung lượng lưu trữ</h2>
        <p className="lead">Số đo từ một ngày dữ liệu Binance thật. Ngày biến động mạnh có thể gấp 2 đến 3 lần.</p>
        <table>
          <thead><tr><th>Một ngày</th><th>BTCUSDT</th><th>XAUUSDT</th></tr></thead>
          <tbody>
            {storage.perDay.map(r => (
              <tr key={r.k}><td>{r.k}</td><td>{r.btc} MB</td><td>{r.xau} MB</td></tr>
            ))}
          </tbody>
        </table>
        <h3>Dài hạn (BTC + XAUUSDT)</h3>
        <div className="bars" role="table" aria-label="Dung lượng dài hạn theo cách lưu">
          {storage.plans.map((p, i) => {
            const w = v => Math.max(3, (Math.log10(v * 10) / Math.log10(2600)) * 100);
            return (
              <div key={p.k} className={`bar-row ${i === 2 ? 'best' : ''}`} role="row">
                <div className="bar-name" role="cell">{p.k}</div>
                <div className="bar-cell" role="cell">
                  <div className="bar" style={{ width: w(p.y5) + '%' }} /><span>5 năm: {p.y5} GB</span>
                </div>
                <div className="bar-cell" role="cell">
                  <div className="bar b1" style={{ width: w(p.y1) + '%' }} /><span>1 năm: {p.y1} GB</span>
                </div>
                <div className="bar-note" role="cell">{p.note}</div>
              </div>
            );
          })}
        </div>
        <p className="note">Thanh vẽ theo thang logarit, vì chênh lệch giữa các cách lưu lên tới 100 lần.</p>
        <h3>Cách thu gọn</h3>
        <ul className="rules">{storage.rules.map(r => <li key={r}>{r}</li>)}</ul>
        <p className="warn">{storage.depthNote}</p>
      </section>

      <section className="matrix">
        <h2>Phần nào miễn phí, phần nào không</h2>
        <table>
          <thead><tr><th>Tính năng</th><th>Chi phí</th><th>Ghi chú</th></tr></thead>
          <tbody>
            {freeMatrix.map(r => (
              <tr key={r.f}><td>{r.f}</td><td><span className={`badge ${CLS[r.c][1]}`}>{CLS[r.c][0]}</span></td><td>{r.n}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
