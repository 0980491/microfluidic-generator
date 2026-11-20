// mfcad Layout in the browser: the 2D editor, the panels, and the generate /
// export flow. The routing and the geometry are the same as the desktop
// program (route.js, geometry.js are ports checked against it).

import * as drc from './drc.js';
import { mix, palette } from './colors.js';
import { Actuator, Bolt, FACES, Layout, PROVEN, RULE_FIELDS, SUPPLY, defaultPitch, lineMembers,
  matrix, resolveLines, ruleFloors } from './model.js';
import { drawingSvg, membraneSvg } from './svg.js';

const $ = (id) => document.getElementById(id);
const fmt = (v) => String(+(+v).toFixed(3));
const LINE_NAME = /^[A-Za-z0-9_\-.']{1,12}$/;
const STORE = 'mfcad-layout:autosave';
const LINES_TEXT = {
  pressure: 'Every actuator sits on two lines: its <b>row line</b> (supply-side valve) and its <b>column line</b> (dome-side valve). Pressurising a line closes its valves, so an actuator inflates while both of its lines are vented. Names are automatic, like a keyboard matrix; select an actuator to put it on another line. Pick the face each inlet comes out on.',
  vacuum: 'Every actuator sits on two lines: its <b>row line</b> (supply-side valve) and its <b>column line</b> (dome-side valve). Under vacuum a valve stays shut until its line has a stronger vacuum than the supply, so an actuator is pulled in while both of its lines are under vacuum. Names are automatic, like a keyboard matrix; select an actuator to put it on another line. Pick the face each inlet comes out on.',
};
const HINTS = {
  select: 'Click to select, Shift+click to add, drag to move or box-select. Arrows nudge, R rotates, Del deletes.',
  actuator: 'Click to place an actuator (its dome centre). R rotates it. Esc to stop.',
  bolt: 'Click to place a bolt. Esc to stop.',
  matrix: 'Click to place the matrix (first dome at the cursor). R rotates. Esc to stop.',
};

const S = {
  lay: new Layout(), name: 'layout', dirty: false, undo: [], redo: [], sel: new Set(),
  tool: 'select', placeRot: 0, mspec: null, cursor: null, drag: null, errors: [], bad: new Set(),
  scale: 8, ox: 0, oy: 0, fitted: false, lines: {}, pal: {},
  routing: null, model: null, routingSig: null, wasm: null, viewer: null, view: 'layout',
};

// ============================================================ canvas setup
const canvas = $('plate');
const ctx = canvas.getContext('2d');
let C = {};          // colours from CSS
function readColors() {
  const cs = getComputedStyle(document.documentElement);
  for (const k of ['canvas', 'plate', 'plate-line', 'shadow', 'grid-minor', 'grid-major', 'axis', 'accent', 'bad', 'muted', 'text'])
    C[k] = cs.getPropertyValue(`--${k}`).trim();
}
function resize() {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(r.width * dpr));
  canvas.height = Math.max(1, Math.round(r.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (!S.userView && r.width > 50) fitView(); else redraw();
}
const W2S = (x, y) => [S.ox + x * S.scale, S.oy - y * S.scale];
const S2W = (sx, sy) => [(sx - S.ox) / S.scale, (S.oy - sy) / S.scale];
const snap = (v) => (S.lay.grid > 0 ? +(Math.round(v / S.lay.grid) * S.lay.grid).toFixed(6) : v);
const cw = () => canvas.getBoundingClientRect().width;
const ch = () => canvas.getBoundingClientRect().height;

function fitView() {
  const W = S.lay.width, L = S.lay.length;
  S.scale = Math.max(Math.min((cw() - 110) / W, (ch() - 110) / L), 0.5);
  S.ox = (cw() - W * S.scale) / 2 + 10;
  S.oy = ch() - (ch() - L * S.scale) / 2 + 6;
  redraw();
}
function zoom(f, at) {
  S.userView = true;
  const [sx, sy] = at || [cw() / 2, ch() / 2];
  const [wx, wy] = S2W(sx, sy);
  S.scale = Math.min(Math.max(S.scale * f, 0.5), 400);
  S.ox = sx - wx * S.scale; S.oy = sy + wy * S.scale;
  redraw();
}

// ================================================================ state
const snapshot = () => JSON.stringify(S.lay.toDict());
const sig = () => { const d = S.lay.toDict(); delete d.editor; return JSON.stringify(d); };
function push(snap) { S.undo.push(snap ?? snapshot()); if (S.undo.length > 300) S.undo.shift(); S.redo = []; }
function changed(msg) { S.dirty = true; refresh(); if (msg) say(msg); autosave(); }
const routesCurrent = () => S.routing !== null && S.routingSig === sig();
function autosave() { try { localStorage.setItem(STORE, JSON.stringify({ name: S.name, lay: S.lay.toDict() })); } catch { /* private mode */ } }

function refresh() {
  S.errors = drc.check(S.lay);
  S.bad = new Set(S.errors.flatMap((v) => v.items));
  S.sel = new Set([...S.sel].filter((n) => S.lay.get(n)));
  S.lines = resolveLines(S.lay);
  S.pal = palette(Object.values(S.lines).flat());
  document.title = `${S.name}${S.dirty ? ' •' : ''} — mfcad Layout`;
  $('p-w').value = fmt(S.lay.width); $('p-l').value = fmt(S.lay.length);
  $('snap').value = String(S.lay.grid);
  if ($('snap').value !== String(S.lay.grid)) { const o = new Option(String(S.lay.grid)); $('snap').add(o); $('snap').value = String(S.lay.grid); }
  const nl = new Set(Object.values(S.lines).flat()).size;
  $('plate-info').textContent = `${S.lay.actuators.length} actuators on ${nl} lines, ${S.lay.bolts.length} bolts. Origin at the bottom-left corner, seen from the top plate.`;
  document.querySelectorAll('[data-act-mode]').forEach((b) => b.classList.toggle('on', b.dataset.actMode === S.lay.actuation));
  $('lines-text').innerHTML = LINES_TEXT[S.lay.actuation];
  fillChecks(); fillProps(); fillLines();
  $('tab-3d').textContent = S.routing && !routesCurrent() ? '3D view (out of date)' : '3D view';
  redraw();
}
function restore(json) { S.lay = Layout.fromDict(JSON.parse(json)); S.dirty = true; refresh(); autosave(); }
function doUndo() { if (!S.undo.length) return say('Nothing to undo.'); S.redo.push(snapshot()); restore(S.undo.pop()); say('Undone.'); }
function doRedo() { if (!S.redo.length) return say('Nothing to redo.'); S.undo.push(snapshot()); restore(S.redo.pop()); say('Redone.'); }
function say(msg, bad = false) { const s = $('status'); s.textContent = msg; s.className = bad ? 'bad' : ''; }

// ================================================================ drawing
function poly(pts, fill, stroke, width = 1, dash = null) {
  ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath();
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.setLineDash(dash || []); ctx.stroke(); ctx.setLineDash([]); }
}
function rectW([x0, y0, x1, y1], rad, fill, stroke, width = 1, dash = null) {
  const [a, b] = W2S(x0, y1), [c, d] = W2S(x1, y0);
  ctx.beginPath(); ctx.roundRect(a, b, c - a, d - b, Math.min(rad, (c - a) / 2, (d - b) / 2));
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.setLineDash(dash || []); ctx.stroke(); ctx.setLineDash([]); }
}
function circleW(x, y, r, fill, stroke, width = 1) {
  const [sx, sy] = W2S(x, y);
  ctx.beginPath(); ctx.arc(sx, sy, Math.max(r * S.scale, 0.5), 0, Math.PI * 2);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.stroke(); }
}
function text(t, x, y, color, font = '600 12px Inter, system-ui, sans-serif', align = 'center', base = 'top') {
  ctx.fillStyle = color; ctx.font = font; ctx.textAlign = align; ctx.textBaseline = base; ctx.fillText(t, x, y);
}
function line(x0, y0, x1, y1, color, width = 1, dash = null, cap = 'butt') {
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
  ctx.strokeStyle = color; ctx.lineWidth = width; ctx.lineCap = cap; ctx.setLineDash(dash || []); ctx.stroke(); ctx.setLineDash([]); ctx.lineCap = 'butt';
}

let pending = false;
function redraw() { if (!pending) { pending = true; requestAnimationFrame(draw); } }
function draw() {
  pending = false;
  const W = S.lay.width, L = S.lay.length, R = S.lay.rules;
  ctx.fillStyle = C.canvas; ctx.fillRect(0, 0, cw(), ch());
  const [x0, y0] = W2S(0, L), [x1, y1] = W2S(W, 0);
  ctx.fillStyle = mix(C.shadow, C.canvas, 0.5); ctx.fillRect(x0 + 6, y0 + 6, x1 - x0, y1 - y0);
  ctx.fillStyle = C.shadow; ctx.fillRect(x0 + 3, y0 + 3, x1 - x0, y1 - y0);
  ctx.fillStyle = C.plate; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
  drawGrid(W, L);
  for (const [e, dash] of [[R.act_edge, [4, 3]], [R.bolt_edge, [1, 3]]])
    if (2 * e < Math.min(W, L)) {
      const [a0, b0] = W2S(e, L - e), [a1, b1] = W2S(W - e, e);
      ctx.strokeStyle = '#c5ccd5'; ctx.lineWidth = 1; ctx.setLineDash(dash); ctx.strokeRect(a0, b0, a1 - a0, b1 - b0); ctx.setLineDash([]);
    }
  ctx.strokeStyle = C['plate-line']; ctx.lineWidth = 1.5; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
  text(`${fmt(W)} × ${fmt(L)} mm`, x0, y0 - 18, C.muted, '600 13px Inter, system-ui, sans-serif', 'left');
  for (const a of S.lay.actuators) drawAct(a, state(a.name), null, true);
  if (routesCurrent()) drawRoutes();
  for (const a of S.lay.actuators) drawAct(a, state(a.name));
  for (const b of S.lay.bolts) drawBolt(b, state(b.name));
  drawGhost();
  if (S.drag?.kind === 'band') {
    const [bx, by] = S.drag.start, [ex, ey] = S.drag.now;
    ctx.strokeStyle = C.accent; ctx.lineWidth = 1.5; ctx.setLineDash([3, 2]); ctx.strokeRect(bx, by, ex - bx, ey - by); ctx.setLineDash([]);
  }
  if (!S.lay.actuators.length && !S.lay.bolts.length && S.tool === 'select') {
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    text('An empty plate', cx, cy - 22, '#6b7785', '700 18px Inter, system-ui, sans-serif');
    text('Press A to place an actuator, M for a whole matrix, B for a bolt.', cx, cy + 6, '#6b7785', '13px Inter, system-ui, sans-serif');
  }
}
const state = (n) => (S.bad.has(n) ? 'error' : S.sel.has(n) ? 'selected' : 'normal');

function drawGrid(W, L) {
  const s = S.scale;
  const step = [S.lay.grid, 0.5, 1, 2, 5, 10, 20, 50].find((v) => v >= S.lay.grid && v * s >= 8) || 50;
  const major = [10, 20, 50, 100].find((v) => v * s >= 30) || 100;
  for (let i = 0; i * step <= W + 1e-9; i++) { const [sx, a] = W2S(i * step, 0); const [, b] = W2S(0, L); line(sx, a, sx, b, C['grid-minor']); }
  for (let j = 0; j * step <= L + 1e-9; j++) { const [a, sy] = W2S(0, j * step); const [b] = W2S(W, 0); line(a, sy, b, sy, C['grid-minor']); }
  for (let k = 0; k * major <= W + 1e-9; k++) {
    const [sx, a] = W2S(k * major, 0); const [, b] = W2S(0, L);
    line(sx, a, sx, b, C['grid-major']); text(fmt(k * major), sx, a + 5, C.axis, '11px Inter, system-ui, sans-serif');
  }
  for (let k = 0; k * major <= L + 1e-9; k++) {
    const [a, sy] = W2S(0, k * major); const [b] = W2S(W, 0);
    line(a, sy, b, sy, C['grid-major']); text(fmt(k * major), a - 7, sy, C.axis, '11px Inter, system-ui, sans-serif', 'right', 'middle');
  }
}

function drawAct(a, st, ghostOk = null, under = false) {
  const R = S.lay.rules, ghost = ghostOk !== null;
  let ln = { error: C.bad, selected: C.accent }[st] || null;
  if (ghost) ln = ghostOk ? '#2f9e44' : C.bad;
  const [row, col] = S.lines[a.name] || ['', ''];
  if (under || ghost) {
    rectW(a.footprint(R), 6, ghost ? null : '#fafbfd', ln || '#b5bdc7', st !== 'normal' || ghost ? 2 : 1, st === 'normal' && !ghost ? [4, 3] : null);
    a.chambers().forEach((c, i) => {
      const base = S.pal[i === 0 ? col : row] || '#adb5bd';
      rectW(c, 3, ghost ? null : mix(base, '#ffffff', 0.62), ln || base, 1.2);
    });
    if (!ghost) return;
  }
  for (const [sx, sy, sr] of a.seats()) circleW(sx, sy, sr, ghost ? null : '#ffffff', ln || '#5c6773', 1);
  const [wx, wy, wr] = a.window(R);
  circleW(wx, wy, wr, ghost ? null : '#d0ebff', ln || '#1c7ed6', st !== 'normal' || ghost ? 2.2 : 1.4);
  if (S.lay.actuation === 'vacuum' && !ghost) {
    const [sx, sy] = W2S(wx, wy);
    ctx.beginPath(); ctx.arc(sx, sy, wr * 0.62 * S.scale, 0, Math.PI * 2);
    ctx.strokeStyle = ln || '#1c7ed6'; ctx.lineWidth = 1; ctx.setLineDash([3, 2]); ctx.stroke(); ctx.setLineDash([]);
  }
  circleW(wx, wy, 0.9, ln || '#1c7ed6', null);
  if (S.scale >= 4 && !ghost) {
    const [sx, sy] = W2S(wx, wy - wr - 0.3);
    text(a.name, sx, sy + 2, ln || '#1864ab', '700 12px Inter, system-ui, sans-serif');
    if (S.scale >= 6) {
      text(row, sx - 4, sy + 17, S.pal[row] || C.muted, '600 11px Inter, system-ui, sans-serif', 'right');
      text('·', sx, sy + 17, '#8a94a0', '11px Inter, system-ui, sans-serif');
      text(col, sx + 4, sy + 17, S.pal[col] || C.muted, '600 11px Inter, system-ui, sans-serif', 'left');
    }
  }
}

function drawBolt(b, st, ghostOk = null) {
  const R = S.lay.rules, ghost = ghostOk !== null;
  let ln = { error: C.bad, selected: C.accent }[st] || null;
  if (ghost) ln = ghostOk ? '#2f9e44' : C.bad;
  const cr = R.nut_af / Math.sqrt(3);
  poly([0, 1, 2, 3, 4, 5].map((k) => { const ang = (30 + 60 * k) * Math.PI / 180; return W2S(b.x + cr * Math.cos(ang), b.y + cr * Math.sin(ang)); }),
    null, ln || '#9aa3ad', 1, [2, 2]);
  circleW(b.x, b.y, R.bolt_d / 2, ghost ? null : '#ffffff', ln || '#2b333b', st !== 'normal' || ghost ? 2.2 : 1.5);
  circleW(b.x, b.y, 0.35, ln || '#2b333b', null);
  if (S.scale >= 6 && !ghost) { const [sx, sy] = W2S(b.x, b.y - R.bolt_d / 2 - 0.3); text(b.name, sx, sy + 2, ln || '#6b7785', '11px Inter, system-ui, sans-serif'); }
}

function drawRoutes() {
  const st = S.model.stack;
  const pal = palette([...S.routing.nets.keys()]);
  for (const [name, nr] of S.routing.nets) {
    const col = pal[name] || '#868e96';
    for (const p of nr.paths) for (let i = 0; i + 1 < p.length; i++) {
      const [x0, y0, z0] = p[i], [x1, y1] = p[i + 1];
      if (Math.abs(x0 - x1) < 1e-9 && Math.abs(y0 - y1) < 1e-9) continue;
      const deep = nr.plate === 'bottom' && Math.abs(z0) > st.ctrl_z + 0.1;
      const w = Math.max(st.d * S.scale * (deep ? 0.85 : 0.55), 2);
      const [a, b] = W2S(x0, y0), [c, d] = W2S(x1, y1);
      line(a, b, c, d, mix(col, '#ffffff', deep ? 0.55 : 0.1), w, nr.plate === 'middle' ? [6, 4] : null, 'round');
    }
    if (nr.port) {
      const [a, b] = W2S(...nr.port.start.slice(0, 2)), [c, d] = W2S(...nr.port.end.slice(0, 2));
      line(a, b, c, d, col, Math.max(st.port_r * 1.2 * S.scale, 3));
      const [dx, dy] = nr.port.direction;
      text(name, a - dx * 16, b + dy * 16, col, '700 13px Inter, system-ui, sans-serif', 'center', 'middle');
    }
  }
}

function ghostItems() {
  if (!S.cursor) return [[], []];
  const t = S.tool;
  let x = snap(S.cursor[0]), y = snap(S.cursor[1]);
  if (t === 'actuator' || t === 'matrix') {
    const [fx, fy] = new Actuator('p', 0, 0, S.placeRot).footprint(S.lay.rules);
    x = +(snap(S.cursor[0] + fx) - fx).toFixed(6);
    y = +(snap(S.cursor[1] + fy) - fy).toFixed(6);
  }
  if (t === 'actuator') return [[new Actuator('new', x, y, S.placeRot)], []];
  if (t === 'bolt') return [[], [new Bolt('new', x, y)]];
  if (t === 'matrix' && S.mspec) {
    const [rows, cols, px, py, cb] = S.mspec;
    const [acts, pts] = matrix(rows, cols, S.lay.rules, px, py, S.placeRot, [x, y], cb);
    acts.forEach((a, k) => { a.name = `new${k}`; });
    const keep = pts.filter((p) => !S.lay.bolts.some((b) => Math.hypot(p[0] - b.x, p[1] - b.y) < 0.01));
    return [acts, keep.map(([bx, by], k) => new Bolt(`newb${k}`, bx, by))];
  }
  return [[], []];
}
function drawGhost() {
  const [acts, bolts] = ghostItems();
  if (!acts.length && !bolts.length) return;
  if (acts.length) {
    const ok = !drc.placement(S.lay, acts).length;
    for (const a of acts) drawAct(a, 'normal', ok);
    for (const b of bolts) drawBolt(b, 'normal', ok && !drc.placement(S.lay, [b]).length);
  } else {
    const errs = drc.placement(S.lay, bolts);
    drawBolt(bolts[0], 'normal', !errs.length);
    if (errs.length) say(errs[0].message, true);
  }
}

// ================================================================= events
function hit(wx, wy) {
  const R = S.lay.rules, tol = 6 / S.scale;
  for (const b of [...S.lay.bolts].reverse()) if (Math.hypot(wx - b.x, wy - b.y) <= Math.max(R.bolt_d / 2, tol)) return b.name;
  for (const a of [...S.lay.actuators].reverse()) { const [x0, y0, x1, y1] = a.footprint(R); if (x0 <= wx && wx <= x1 && y0 <= wy && wy <= y1) return a.name; }
  return null;
}
const pos = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };

canvas.addEventListener('contextmenu', (e) => e.preventDefault());
canvas.addEventListener('pointerdown', (e) => {
  canvas.focus();
  canvas.setPointerCapture(e.pointerId);
  const [px, py] = pos(e);
  if (e.button === 1 || e.button === 2) { S.pan = [px, py, S.ox, S.oy]; return; }
  const [wx, wy] = S2W(px, py);
  if (S.tool !== 'select') return place(wx, wy);
  const name = hit(wx, wy);
  if (!name) {
    if (!e.shiftKey) S.sel.clear();
    S.drag = { kind: 'band', start: [px, py], now: [px, py], shift: e.shiftKey };
    fillProps(); return redraw();
  }
  if (e.shiftKey) { if (S.sel.has(name)) S.sel.delete(name); else S.sel.add(name); }
  else if (!S.sel.has(name)) S.sel = new Set([name]);
  const orig = new Map([...S.sel].map((n) => [n, [S.lay.get(n).x, S.lay.get(n).y]]));
  S.drag = { kind: 'move', start: [wx, wy], orig, snap: snapshot(), moved: false };
  fillProps(); redraw();
});
canvas.addEventListener('pointermove', (e) => {
  const [px, py] = pos(e);
  if (S.pan) { const [x, y, ox, oy] = S.pan; S.ox = ox + px - x; S.oy = oy + py - y; S.userView = true; return redraw(); }
  S.cursor = S2W(px, py);
  $('coords').textContent = `x ${S.cursor[0].toFixed(2).padStart(7)}   y ${S.cursor[1].toFixed(2).padStart(7)} mm`;
  const d = S.drag;
  if (!d) { if (S.tool !== 'select') { say(HINTS[S.tool]); redraw(); } return; }
  if (d.kind === 'band') { d.now = [px, py]; return redraw(); }
  const dx = snap(S.cursor[0] - d.start[0]), dy = snap(S.cursor[1] - d.start[1]);
  for (const [n, [x, y]] of d.orig) { const it = S.lay.get(n); it.x = +(x + dx).toFixed(6); it.y = +(y + dy).toFixed(6); }
  d.moved = !!(dx || dy);
  const moving = [...d.orig.keys()].map((n) => S.lay.get(n));
  const errs = drc.placement(S.lay, moving);
  S.bad = new Set([...errs.flatMap((v) => v.items), ...S.errors.filter((v) => !v.items.some((n) => d.orig.has(n))).flatMap((v) => v.items)]);
  say(errs.length ? errs[0].message : `Moving ${moving.length} item(s) by ${fmt(dx)}, ${fmt(dy)} mm`, !!errs.length);
  redraw();
});
canvas.addEventListener('pointerup', (e) => {
  if (S.pan) { S.pan = null; return; }
  const d = S.drag; S.drag = null;
  if (!d) return;
  if (d.kind === 'band') {
    const [x0, y0] = S2W(...d.start), [x1, y1] = S2W(...pos(e));
    const [lx, hx, ly, hy] = [Math.min(x0, x1), Math.max(x0, x1), Math.min(y0, y1), Math.max(y0, y1)];
    const picked = S.lay.items().filter((it) => lx <= it.x && it.x <= hx && ly <= it.y && it.y <= hy).map((it) => it.name);
    S.sel = d.shift ? new Set([...S.sel, ...picked]) : new Set(picked);
    fillProps(); return redraw();
  }
  if (!d.moved) return refresh();
  const moving = [...d.orig.keys()].map((n) => S.lay.get(n));
  const errs = drc.placement(S.lay, moving);
  if (errs.length) {
    for (const [n, [x, y]] of d.orig) { const it = S.lay.get(n); it.x = x; it.y = y; }
    refresh(); return say(`Can't go there: ${errs[0].message}`, true);
  }
  push(d.snap); changed(`Moved ${moving.length} item(s).`);
});
canvas.addEventListener('pointerleave', () => { S.cursor = null; if (S.tool !== 'select') redraw(); });
canvas.addEventListener('wheel', (e) => { e.preventDefault(); zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, pos(e)); }, { passive: false });

function setTool(t) {
  if (t === 'matrix') return openMatrix();
  S.tool = t;
  document.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === t));
  canvas.style.cursor = t === 'select' ? 'default' : 'crosshair';
  say(HINTS[t]); redraw();
}

// ================================================================ editing
function place(wx, wy) {
  S.cursor = [wx, wy];
  const [acts, bolts] = ghostItems();
  if (acts.length) {
    const errs = drc.placement(S.lay, acts);
    if (errs.length) return say(`Can't place there: ${errs[0].message}`, true);
    push();
    for (const a of acts) { a.name = S.lay.nextName('A'); S.lay.actuators.push(a); }
    const [added, skipped] = addBolts(bolts.map((b) => [b.x, b.y]));
    let msg = `Placed ${acts.length} actuator(s)` + (bolts.length ? ` and ${added} bolt(s)` : '');
    if (skipped) msg += `; skipped ${skipped} bolt(s) that broke a rule`;
    S.sel = new Set(acts.map((a) => a.name));
    return changed(msg + '.');
  }
  if (bolts.length) {
    const errs = drc.placement(S.lay, bolts);
    if (errs.length) return say(`Can't place there: ${errs[0].message}`, true);
    push();
    const b = bolts[0]; b.name = S.lay.nextName('B'); S.lay.bolts.push(b);
    S.sel = new Set([b.name]); changed(`Placed ${b.name}.`);
  }
}
function addBolts(points) {
  let added = 0, skipped = 0;
  for (const [x, y] of points) {
    if (S.lay.bolts.some((b) => Math.hypot(x - b.x, y - b.y) < 0.01)) continue;
    const b = new Bolt(S.lay.nextName('B'), +x.toFixed(6), +y.toFixed(6));
    if (drc.placement(S.lay, [b]).length) { skipped++; continue; }
    S.lay.bolts.push(b); added++;
  }
  return [added, skipped];
}
function cornerBolts() {
  const sel = S.lay.actuators.filter((a) => S.sel.has(a.name));
  const acts = sel.length ? sel : S.lay.actuators;
  if (!acts.length) return say('Place some actuators first.', true);
  push();
  const [added, skipped] = addBolts(acts.flatMap((a) => a.corners(S.lay.rules)));
  if (!added) S.undo.pop();
  changed(`Corner bolts for ${sel.length ? 'selected' : 'all'} actuators: added ${added}${skipped ? `, skipped ${skipped} that broke a rule` : ''}.`);
}
function rotate() {
  if (S.tool === 'actuator' || S.tool === 'matrix') { S.placeRot = (S.placeRot + 90) % 360; say(`Rotation ${S.placeRot}°`); return redraw(); }
  const acts = S.lay.actuators.filter((a) => S.sel.has(a.name));
  if (!acts.length) return say("Select actuators to rotate (bolts don't rotate).");
  const snap0 = snapshot();
  acts.forEach((a) => { a.rotation = (a.rotation + 90) % 360; });
  const errs = drc.placement(S.lay, acts);
  if (errs.length) { acts.forEach((a) => { a.rotation = (a.rotation + 270) % 360; }); return say(`Can't rotate: ${errs[0].message}`, true); }
  push(snap0); changed(`Rotated ${acts.length} actuator(s).`);
}
function nudge(dx, dy, big) {
  if (!S.sel.size) return;
  const step = (big ? 10 : 1) * (S.lay.grid || 0.1);
  const moving = [...S.sel].map((n) => S.lay.get(n));
  const snap0 = snapshot();
  moving.forEach((it) => { it.x = +(it.x + dx * step).toFixed(6); it.y = +(it.y + dy * step).toFixed(6); });
  const errs = drc.placement(S.lay, moving);
  if (errs.length) { moving.forEach((it) => { it.x = +(it.x - dx * step).toFixed(6); it.y = +(it.y - dy * step).toFixed(6); }); return say(`Can't move there: ${errs[0].message}`, true); }
  push(snap0); changed();
}
function del() { if (!S.sel.size) return; push(); const n = S.sel.size; S.lay.remove(S.sel); S.sel.clear(); changed(`Deleted ${n} item(s).`); }
function selectAll() { S.sel = new Set(S.lay.items().map((it) => it.name)); fillProps(); redraw(); }
function applyPlate() {
  const w = parseFloat($('p-w').value), l = parseFloat($('p-l').value);
  if (!(w > 0 && l > 0)) return say('Plate size must be two positive numbers.', true);
  if (w === S.lay.width && l === S.lay.length) return;
  push(); S.lay.width = w; S.lay.length = l; changed(`Plate ${fmt(w)} × ${fmt(l)} mm.`); fitView();
}
function fitPlate() {
  const R = S.lay.rules;
  const boxes = [...S.lay.actuators.map((a) => { const b = a.footprint(R); return [b[0] - R.act_edge, b[1] - R.act_edge, b[2] + R.act_edge, b[3] + R.act_edge]; }),
    ...S.lay.bolts.map((b) => [b.x - R.bolt_edge, b.y - R.bolt_edge, b.x + R.bolt_edge, b.y + R.bolt_edge])];
  if (!boxes.length) return say('Nothing on the plate to fit.', true);
  const x0 = Math.min(...boxes.map((b) => b[0])), y0 = Math.min(...boxes.map((b) => b[1]));
  const x1 = Math.max(...boxes.map((b) => b[2])), y1 = Math.max(...boxes.map((b) => b[3]));
  push();
  for (const it of S.lay.items()) { it.x = +(it.x - x0).toFixed(6); it.y = +(it.y - y0).toFixed(6); }
  S.lay.width = Math.ceil((x1 - x0) * 10 - 1e-6) / 10; S.lay.length = Math.ceil((y1 - y0) * 10 - 1e-6) / 10;
  changed(`Plate fitted: ${fmt(S.lay.width)} × ${fmt(S.lay.length)} mm.`); fitView();
}
function setActuation(mode) {
  if (mode === S.lay.actuation) return;
  push(); S.lay.actuation = mode;
  changed(mode === 'vacuum' ? 'Negative pressure: each window gets a bowl in the middle plate; see File → Shortcuts and help.' : 'Positive pressure: the domes inflate.');
}
function setFace(lineName, face) {
  if ((S.lay.faces[lineName] ?? (lineName === SUPPLY ? 'front' : 'auto')) === face) return;
  push(); S.lay.faces[lineName] = face; changed(`${lineName === SUPPLY ? 'Supply' : lineName} inlet: ${face} face.`);
}
function resetLines() {
  if (!S.lay.actuators.some((a) => a.rowLine || a.colLine)) return say('Every line name is already automatic.');
  push(); S.lay.actuators.forEach((a) => { a.rowLine = a.colLine = ''; }); changed('Line names reset to automatic.');
}

// ============================================================ side panels
function fillProps() {
  const items = [...S.sel].sort().map((n) => S.lay.get(n)).filter(Boolean);
  const one = items.length === 1 ? items[0] : null;
  const isAct = one instanceof Actuator;
  for (const id of ['s-name', 's-x', 's-y', 'btn-sel']) $(id).disabled = !one;
  for (const id of ['s-rot', 's-row', 's-col']) $(id).disabled = !isAct;
  const names = [...new Set(Object.values(S.lines).flat())].sort();
  $('line-names').innerHTML = ['auto', ...names].map((n) => `<option value="${n}">`).join('');
  if (one) {
    $('s-name').value = one.name; $('s-x').value = fmt(one.x); $('s-y').value = fmt(one.y);
    $('s-rot').value = isAct ? String(one.rotation) : '0';
    const [row, col] = S.lines[one.name] || ['', ''];
    $('s-row').value = isAct ? one.rowLine : ''; $('s-row').placeholder = isAct ? `auto (${row})` : '';
    $('s-col').value = isAct ? one.colLine : ''; $('s-col').placeholder = isAct ? `auto (${col})` : '';
    let info = `${one.kind[0].toUpperCase()}${one.kind.slice(1)}: ${drc.describeClearance(S.lay, one)}`;
    if (isAct) { const [x0, y0, x1, y1] = one.footprint(S.lay.rules); info += `. Footprint ${fmt(x0)}…${fmt(x1)} × ${fmt(y0)}…${fmt(y1)} mm; X, Y is the dome centre.`; }
    $('sel-info').textContent = info;
  } else {
    for (const id of ['s-name', 's-x', 's-y', 's-row', 's-col']) { $(id).value = ''; $(id).placeholder = ''; }
    $('sel-info').textContent = items.length ? `${items.length} items selected. Drag or use the arrows to move them.` : 'Nothing selected. Click a part on the plate.';
  }
}
function applyProps() {
  if (S.sel.size !== 1) return;
  const it = S.lay.get([...S.sel][0]);
  const x = parseFloat($('s-x').value), y = parseFloat($('s-y').value);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return say('X and Y must be numbers.', true);
  const name = $('s-name').value.trim();
  if (!name) return say("A name can't be empty.", true);
  if (name !== it.name && S.lay.get(name)) return say(`${name} is already used.`, true);
  let lines = null;
  if (it instanceof Actuator) {
    lines = [];
    for (const id of ['s-row', 's-col']) {
      const v = $(id).value.trim();
      if (!v || v.startsWith('auto')) lines.push('');
      else if (v === SUPPLY) return say(`'${SUPPLY}' is the supply; pick another line name.`, true);
      else if (!LINE_NAME.test(v)) return say("Line names: up to 12 letters, digits, _ - . or '", true);
      else lines.push(v);
    }
  }
  const snap0 = snapshot();
  const old = [it.x, it.y, it.rotation];
  it.x = x; it.y = y;
  if (it instanceof Actuator) it.rotation = parseInt($('s-rot').value, 10);
  const errs = drc.placement(S.lay, [it]);
  if (errs.length) { [it.x, it.y] = old; if (it instanceof Actuator) it.rotation = old[2]; fillProps(); return say(`Can't: ${errs[0].message}`, true); }
  it.name = name;
  if (lines) [it.rowLine, it.colLine] = lines;
  S.sel = new Set([name]);
  if (snap0 !== snapshot()) { push(snap0); changed(`${name} updated.`); }
}
let linesKey = null;
function fillLines() {
  const members = lineMembers(S.lay);
  const key = JSON.stringify([[...members].map(([n, m]) => [n, m.length]), S.lay.faces, S.pal]);
  $('supply-face').value = S.lay.faces[SUPPLY] ?? 'front';
  if (key === linesKey) return;
  linesKey = key;
  const body = $('lines-body');
  body.innerHTML = '';
  if (!members.size) { body.innerHTML = '<tr><td colspan="4" class="muted">No actuators yet.</td></tr>'; return; }
  for (const [name, mem] of members) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><i style="background:${S.pal[name] || '#adb5bd'}"></i></td><td><b></b></td><td title=""></td><td></td>`;
    tr.children[1].firstChild.textContent = name;
    tr.children[2].textContent = mem.length;
    tr.children[2].title = mem.map(([a]) => a).join(', ');
    const sel = document.createElement('select');
    sel.innerHTML = FACES.map((f) => `<option>${f}</option>`).join('');
    sel.value = S.lay.faces[name] ?? 'auto';
    sel.addEventListener('change', () => setFace(name, sel.value));
    tr.children[3].appendChild(sel);
    body.appendChild(tr);
  }
}
function fillChecks() {
  const n = S.errors.length, ul = $('checks');
  ul.innerHTML = '';
  S.errors.forEach((v) => {
    const li = document.createElement('li'); li.textContent = v.message;
    li.addEventListener('click', () => { S.sel = new Set(v.items); fillProps(); redraw(); });
    ul.appendChild(li);
  });
  const head = $('check-head'), pill = $('pill');
  const t = n ? `✗ ${n} problem${n > 1 ? 's' : ''}` : '✓ Every rule holds';
  head.textContent = t; head.className = `check-head ${n ? 'bad' : 'good'}`;
  pill.textContent = t; pill.className = `pill ${n ? 'bad' : 'good'}`;
  $('tab-checks').textContent = n ? `Checks (${n})` : 'Checks';
}
function sideTab(name) {
  document.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
  $('tab-props').hidden = name !== 'props'; $('tab-lines').hidden = name !== 'lines'; $('tab-checks-pane').hidden = name !== 'checks';
}

// ================================================================ dialogs
function openMatrix() {
  const d = $('dlg-matrix');
  $('m-rot').value = String(S.placeRot); $('m-msg').textContent = '';
  const defaults = () => {
    if ($('m-packed').checked) { const [a, b] = defaultPitch(S.lay.rules, +$('m-rot').value); $('m-px').value = fmt(a); $('m-py').value = fmt(b); }
    $('m-px').disabled = $('m-py').disabled = $('m-packed').checked;
  };
  $('m-rot').onchange = defaults; $('m-packed').onchange = defaults; defaults();
  $('m-ok').onclick = (e) => {
    const r = parseInt($('m-rows').value, 10), c = parseInt($('m-cols').value, 10);
    const a = parseFloat($('m-px').value), b = parseFloat($('m-py').value);
    if (!(r >= 1 && c >= 1 && a > 0 && b > 0)) { e.preventDefault(); $('m-msg').textContent = 'Rows, columns and pitches must be positive numbers.'; return; }
    S.mspec = [r, c, a, b, $('m-bolts').checked]; S.placeRot = +$('m-rot').value;
  };
  d.onclose = () => {
    if (d.returnValue === 'ok' && S.mspec) {
      S.tool = 'matrix';
      document.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === 'matrix'));
      canvas.style.cursor = 'crosshair'; say(HINTS.matrix); canvas.focus();
    }
  };
  d.returnValue = ''; d.showModal();
}
function openRules() {
  const d = $('dlg-rules'), body = $('rules-body');
  body.innerHTML = '';
  for (const [k, label, help] of RULE_FIELDS) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td></td><td><input data-k="${k}" inputmode="decimal"></td><td class="muted">${fmt(PROVEN[k])}</td>`;
    tr.children[0].textContent = label;
    const inp = tr.querySelector('input'); inp.value = fmt(S.lay.rules[k]);
    inp.addEventListener('focus', () => { $('rules-help').textContent = help; });
    body.appendChild(tr);
  }
  $('rules-msg').textContent = ''; $('rules-help').textContent = '';
  let confirmed = false;
  $('rules-reset').onclick = () => { body.querySelectorAll('input').forEach((i) => { i.value = fmt(PROVEN[i.dataset.k]); }); $('rules-msg').textContent = ''; };
  $('rules-ok').onclick = (e) => {
    const vals = {};
    for (const i of body.querySelectorAll('input')) {
      const v = parseFloat(i.value);
      if (!Number.isFinite(v)) { e.preventDefault(); $('rules-msg').textContent = 'Every value must be a number.'; return; }
      vals[i.dataset.k] = v;
    }
    const nw = { ...S.lay.rules, ...vals }, floors = ruleFloors(nw);
    const bad = Object.entries(vals).filter(([k, v]) => v < (floors[k] ?? 0) || (v <= 0 && k !== 'act_gap')).map(([k]) => `${k} must be ≥ ${floors[k] ?? 0}`);
    if (vals.act_gap < 0) bad.push("act_gap can't be negative");
    if (vals.bowl_depth > vals.window_d / 2 + 1e-9) bad.push("the bowl can't be deeper than half the window (a hemisphere)");
    if (bad.length) { e.preventDefault(); $('rules-msg').textContent = bad.join('; '); return; }
    const below = RULE_FIELDS.filter(([k]) => vals[k] < PROVEN[k] - 1e-9 && k !== 'bolt_d' && k !== 'nut_af').map(([, l]) => l);
    if (below.length && !confirmed) { e.preventDefault(); confirmed = true; $('rules-msg').textContent = `Below the printed matrices (untested): ${below.join(', ')}. Press OK again to use them anyway.`; return; }
    if (JSON.stringify(nw) !== JSON.stringify(S.lay.rules)) {
      push(); S.lay.rules = nw;
      const n = drc.check(S.lay).length;
      changed('Rules changed.' + (n ? ` ${n} problem(s) now.` : ''));
    }
  };
  d.showModal();
}
function message(title, html) { $('msg-title').textContent = title; $('msg-body').innerHTML = html; $('dlg-msg').showModal(); }
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function help() {
  message('Shortcuts and help', `
  <p><b>V</b> select · <b>A</b> actuator · <b>B</b> bolt · <b>M</b> matrix · <b>R</b> rotate · <b>Del</b> delete · <b>Esc</b> back to select<br>
  Arrows nudge (Shift ×10) · Wheel zoom · Right or middle drag pan · <b>F</b> fit<br>
  <b>Ctrl+Z / Ctrl+Y</b> undo / redo · <b>Ctrl+A</b> select all · <b>Ctrl+S</b> save · <b>Ctrl+G</b> generate 3D · <b>Ctrl+E</b> export STL</p>
  <p><b>The logic.</b> Each actuator is supply → valve 1 (row line) → valve 2 (column line) → membrane. Rows are named R1, R2… from the top,
  columns C1, C2… from the left; give an actuator another line name to wire it however you like. Pick the mode in Properties → Actuation.</p>
  <p><b>Positive pressure.</b> Pressurising a line closes every valve it feeds, so with the supply on an actuator inflates only while
  both of its lines are vented, the way a keyboard matrix picks one key.</p>
  <p><b>Negative pressure (vacuum).</b> The middle plate gets a bowl under every window and the membrane is pulled down into it, so it
  can't burst. The valves flip: the vacuum in a channel pulls its valve shut, so a valve stays closed while its line is vented and opens
  when its line has a stronger vacuum than the supply. Run the supply at a weaker vacuum and the lines at full vacuum; an actuator is
  pulled in while both of its lines are under vacuum. To release, vent the supply with the lines still under vacuum. (Reasoned from the
  valve design; test it on a small matrix first.)</p>
  <p><b>Generate 3D</b> routes every line through the bottom plate (crossing lines take different levels) and the supply through the
  middle plate, and shows them inside the plates. <b>Export STL</b> downloads a zip with the three plates (already face down for
  printing), the membrane template, a drawing of the channels and a README saying which inlet is which.</p>
  <p class="muted">Everything runs in your browser; nothing is uploaded. Your last layout is kept in this browser. Same file format
  (.mfl) as the desktop program: <a href="https://github.com/0980491/microfluidic-generator">github.com/0980491/microfluidic-generator</a>.</p>`);
}

// ======================================================== 3D: generate
const prog = { open(title) { $('prog-title').textContent = title; $('prog-msg').textContent = 'Starting…'; $('dlg-progress').showModal(); },
  say(t) { $('prog-msg').textContent = t; }, close() { $('dlg-progress').close(); } };
const frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

async function loadWasm() {
  if (S.wasm) return S.wasm;
  prog.say('Loading the 3D engine…');
  const Module = (await import('manifold-3d')).default;
  const w = await Module(); w.setup();
  S.wasm = w;
  return w;
}

async function generate(then = null) {
  if (!S.lay.actuators.length) return say('Place some actuators first.', true);
  if (S.errors.length) {
    sideTab('checks');
    return message('Fix the problems first', `<p>The layout breaks ${S.errors.length} rule(s); see <b>Checks</b>. The plates can only be generated from a layout that passes.</p>`);
  }
  prog.open('Generating the plates');
  try {
    await frame();
    const { routeLayout } = await import('./route.js');
    const { buildModel } = await import('./geometry.js');
    const lay = S.lay.copy(), sg = sig();
    const r = routeLayout(lay, undefined, (t) => prog.say(t));
    if (!r.ok) {
      prog.close();
      say(`Couldn't route: ${r.problems.join('; ')}`, true);
      return message("Couldn't route the channels", `<p>${r.problems.map(esc).join('<br>')}</p><p>Things that help: more space between actuators (Rules → extra gap), fewer bolts in the way, or another inlet face for that line (Lines tab; <i>auto</i> tries every face).</p>`);
    }
    prog.say('Building the plates…'); await frame();
    const m = buildModel(lay, r);
    S.routing = r; S.model = m; S.routingSig = sg;
    await loadWasm();
    prog.say('Drawing the 3D view…'); await frame();
    if (!S.viewer) {
      const { Viewer3D } = await import('./viewer.js');
      S.viewer = new Viewer3D($('three-host'), { panel: $('panel-3d'), onExport: () => exportStl() });
    }
    await S.viewer.show(S.wasm, m, (t) => prog.say(t));
    $('empty-3d').hidden = true; $('panel-3d').hidden = false;
    prog.close();
    say(`Generated: ${r.notes.join('; ')}. Drag in the 3D view to look around.`);
    refresh();
    if (then) await then(); else setView('3d');
  } catch (err) {
    prog.close(); console.error(err);
    message('Something went wrong', `<p>${esc(err.message || err)}</p>`);
  }
}

async function exportStl() {
  if (!routesCurrent()) return generate(exportStl);
  prog.open('Exporting the plates');
  try {
    await frame();
    const w = await loadWasm();
    const { exportFiles } = await import('./export.js');
    const stem = S.name || 'layout';
    const { files, blob, problems, worst } = await exportFiles(w, S.lay.copy(), S.model, stem, (t) => prog.say(t));
    download(blob, `${stem}.zip`);
    prog.close();
    const ok = !problems.length;
    message(ok ? '✓ Ready to print' : '✗ Exported, but the checks found problems', `
      <p>Downloaded <b>${esc(stem)}.zip</b>:</p><div class="files">${files.map((f) => esc(f.name)).join('<br>')}</div>
      ${problems.map((q) => `<p class="bad">! ${esc(q)}</p>`).join('')}
      <p class="muted">${ok ? `Every line is its own sealed cavity. Thinnest wall between two nets: ${Object.entries(worst).filter(([, v]) => v[1]).map(([k, v]) => `${k} ${v[0].toFixed(2)} mm`).join(', ')}. ` : ''}
      The STLs are already contact face down. The README says which inlet is which and how to assemble.</p>`);
    say(`Exported ${files.length} files in ${stem}.zip.`);
  } catch (err) {
    prog.close(); console.error(err);
    message('Something went wrong', `<p>${esc(err.message || err)}</p>`);
  }
}

function setView(v) {
  S.view = v;
  document.querySelectorAll('[data-view]').forEach((b) => b.classList.toggle('on', b.dataset.view === v));
  $('view-layout').hidden = v !== 'layout'; $('view-3d').hidden = v !== '3d';
  if (v === 'layout') resize(); else S.viewer?.resize();
}

// ================================================================== files
function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
function load(lay, name, msg) {
  S.lay = lay; S.name = name; S.dirty = false; S.undo = []; S.redo = []; S.sel.clear();
  S.routing = S.model = S.routingSig = null; linesKey = null;
  $('empty-3d').hidden = false; $('panel-3d').hidden = true; S.viewer?.clear();
  S.userView = false;
  refresh(); fitView(); autosave();
  if (msg) say(msg);
}
async function loadExample(file, name) {
  const res = await fetch(`examples/${file}`);
  load(Layout.fromDict(await res.json()), name, `Opened the ${name} example.`);
}
function saveFile() {
  download(new Blob([JSON.stringify(S.lay.toDict(), null, 2) + '\n'], { type: 'application/json' }), `${S.name || 'layout'}.mfl`);
  S.dirty = false; refresh(); say(`Saved ${S.name}.mfl to your downloads.`);
}
$('file-input').addEventListener('change', async (e) => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  try { load(Layout.fromDict(JSON.parse(await f.text())), f.name.replace(/\.(mfl|json)$/i, ''), `Opened ${f.name}.`); }
  catch (err) { message("Can't open", `<p>${esc(f.name)}: ${esc(err.message)}</p>`); }
});

// ================================================================= wiring
document.querySelectorAll('[data-tool]').forEach((b) => b.addEventListener('click', () => setTool(b.dataset.tool)));
document.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => sideTab(b.dataset.tab)));
document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
$('btn-rotate').onclick = rotate; $('btn-corners').onclick = cornerBolts; $('btn-fit').onclick = fitPlate; $('btn-rules').onclick = openRules;
$('btn-generate').onclick = () => generate(); $('btn-export').onclick = exportStl; $('btn-export2').onclick = exportStl;
$('btn-plate').onclick = applyPlate; $('btn-sel').onclick = applyProps; $('btn-reset-lines').onclick = resetLines;
$('pill').onclick = () => sideTab('checks');
document.querySelectorAll('[data-act-mode]').forEach((b) => b.addEventListener('click', () => setActuation(b.dataset.actMode)));
['p-w', 'p-l'].forEach((id) => $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter') applyPlate(); }));
['s-name', 's-x', 's-y', 's-row', 's-col'].forEach((id) => $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter') applyProps(); }));
$('s-rot').addEventListener('change', applyProps);
$('snap').addEventListener('change', () => { S.lay.grid = parseFloat($('snap').value); S.dirty = true; say(`Snap ${$('snap').value} mm.`); autosave(); redraw(); canvas.focus(); });
$('supply-face').innerHTML = FACES.map((f) => `<option>${f}</option>`).join('');
$('supply-face').addEventListener('change', () => setFace(SUPPLY, $('supply-face').value));
const menu = $('file-menu');
$('btn-file').onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; };
document.addEventListener('click', () => { menu.hidden = true; });
menu.addEventListener('click', (e) => {
  const act = e.target.dataset?.act;
  if (!act) return;
  menu.hidden = true;
  const confirmDrop = () => !S.dirty || confirm('Discard the changes to this layout? (Save first with File → Save.)');
  if (act === 'new' && confirmDrop()) load(new Layout(), 'layout', 'New plate.');
  if (act === 'open' && confirmDrop()) $('file-input').click();
  if (act === 'save') saveFile();
  if (act.startsWith('ex-') && confirmDrop()) loadExample({ 'ex-2x2': '2x2.mfl', 'ex-3x3': '3x3.mfl', 'ex-free': 'free.mfl' }[act], act.slice(3));
  if (act === 'svg-drawing') download(new Blob([drawingSvg(S.lay)], { type: 'image/svg+xml' }), `${S.name}_drawing.svg`);
  if (act === 'svg-membrane') download(new Blob([membraneSvg(S.lay)], { type: 'image/svg+xml' }), `${S.name}_membrane.svg`);
  if (act === 'help') help();
});
window.addEventListener('keydown', (e) => {
  const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName) || document.querySelector('dialog[open]');
  const mod = e.ctrlKey || e.metaKey;
  if (mod && !typing) {
    const k = e.key.toLowerCase();
    const map = { z: e.shiftKey ? doRedo : doUndo, y: doRedo, s: saveFile, g: () => generate(), e: exportStl, a: selectAll };
    if (map[k]) { e.preventDefault(); map[k](); }
    return;
  }
  if (typing || S.view !== 'layout') return;
  const keys = { v: () => setTool('select'), a: () => setTool('actuator'), b: () => setTool('bolt'), m: () => setTool('matrix'),
    r: rotate, f: () => { S.userView = false; fitView(); }, '+': () => zoom(1.25), '=': () => zoom(1.25), '-': () => zoom(0.8), Delete: del, Backspace: del,
    Escape: () => { if (S.tool !== 'select') setTool('select'); else { S.sel.clear(); refresh(); } } };
  const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
  if (arrows[e.key]) { e.preventDefault(); return nudge(...arrows[e.key], e.shiftKey); }
  const fn = keys[e.key] || keys[e.key.toLowerCase()];
  if (fn) { e.preventDefault(); fn(); }
});
window.addEventListener('beforeunload', () => autosave());
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readColors(); redraw(); });
new ResizeObserver(resize).observe(canvas);

// ================================================================== start
readColors();
let restored = false;
try {
  const saved = JSON.parse(localStorage.getItem(STORE) || 'null');
  if (saved?.lay) { S.lay = Layout.fromDict(saved.lay); S.name = saved.name || 'layout'; restored = true; }
} catch { /* nothing saved, or storage blocked */ }
if (restored) { refresh(); say('Restored your last layout (kept in this browser).'); }
else { loadExample('3x3.mfl', '3x3').catch(() => refresh()); }
window.mfcad = { S, refresh };   // for poking at it from the browser console
