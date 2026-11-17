// Turn a routed layout into the three plates (port of build3d.py).
// buildModel describes every cavity as a feature tagged with its plate and
// net; the same list is cut out of three blocks with manifold (STL files) and
// drawn by the 3D view, so what you see is what gets printed.

import { SUPPLY, resolveLines } from './model.js';
import { PROUD, STACK } from './stack.js';

export const PLATES = ['bottom', 'middle', 'top'];

export function buildModel(lay, routing, st = STACK) {
  if (!routing.ok) throw new Error('the layout is not routed');
  const R = lay.rules;
  const Tb = routing.bottom_t, Tm = st.mid_t, Tt = st.top_t;
  const feats = [];
  const F = (plate, net, kind, data) => feats.push({ plate, net, kind, data });
  const lines = resolveLines(lay);
  const windows = {};
  for (const a of lay.actuators) {
    const P = (lx, ly) => a.local(lx, ly);
    const h = st.col / 2, z1 = st.level1;
    const mid = `${a.name}.mid`, out = `${a.name}.out`;
    for (const [net, [lx, ly]] of [[SUPPLY, [h, 0]], [mid, [h, st.seat_gap]], [mid, [-h, st.seat_gap]], [out, [-h, 0]]])
      F('middle', net, 'pocket', { at: P(lx, ly) });
    F('middle', mid, 'pipe', { points: [[...P(h, st.seat_gap), -PROUD], [...P(h, st.seat_gap), z1],
      [...P(-h, st.seat_gap), z1], [...P(-h, st.seat_gap), -PROUD]], d: st.d, bend: st.bend });
    F('middle', out, 'pipe', { points: [[...P(-h, 0), -PROUD], [...P(-h, 0), z1], [...P(0, 0), z1]], d: st.d, bend: st.bend });
    F('middle', out, 'pipe', { points: [[a.x, a.y, z1 - 0.2], [a.x, a.y, Tm + PROUD]], d: st.d, bend: 0 });
    const [row, col] = lines[a.name];
    for (const [net, lx] of [[col, -h], [row, h]]) {
      const [w, l] = a.rotation % 180 === 0 ? [st.chamber_l, st.chamber_w] : [st.chamber_w, st.chamber_l];
      F('bottom', net, 'chamber', { at: P(lx, st.chamber_dy), w, l, depth: st.chamber_depth });
    }
    windows[a.name] = [a.x, a.y, R.window_d];
    F('top', `${a.name}.window`, 'window', { at: [a.x, a.y], d: R.window_d, z0: Tm, z1: Tm + Tt });
  }
  for (const [name, nr] of routing.nets) {
    for (const path of nr.paths) F(nr.plate, name, 'pipe', { points: path, d: st.d, bend: 0, route: true });
    if (nr.port) {
      const p = nr.port;
      F(nr.plate, name, 'port', { start: p.start, dir: p.direction, depth: p.depth, end: p.end, face: p.face });
    }
  }
  const bolts = lay.bolts.map((b) => [b.x, b.y]);
  const z0 = { bottom: -Tb, middle: 0, top: Tm };
  const th = { bottom: Tb, middle: Tm, top: Tt };
  bolts.forEach(([x, y], i) => {
    for (const plate of PLATES) F(plate, `bolt${i + 1}`, 'hole', { at: [x, y], d: R.bolt_d, z0: z0[plate], z1: z0[plate] + th[plate] });
    F('bottom', `bolt${i + 1}`, 'nut', { at: [x, y], af: R.nut_af, depth: st.nut_depth, z: -Tb });
  });
  const m = { width: lay.width, length: lay.length, thickness: th, z0, features: feats, routing, lines, windows, bolts, stack: st };
  m.report = report(lay, m);
  return m;
}

// ------------------------------------------------------------------ solids
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => Math.hypot(a[0], a[1], a[2]);
const unit = (a) => mul(a, 1 / norm(a));

function frame(origin, dir) {
  const z = unit(dir);
  const a = Math.abs(z[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
  const x = unit(cross(a, z));
  const y = cross(z, x);
  return [...x, 0, ...y, 0, ...z, 0, ...origin, 1];   // column-major
}

export function densify(path, radius, n = 8) {
  const pts = path.map((p) => [...p]);
  if (pts.length < 3 || radius <= 0) return pts;
  const out = [pts[0]];
  for (let q = 0; q + 2 < pts.length; q++) {
    const [p0, p1, p2] = [pts[q], pts[q + 1], pts[q + 2]];
    const v0 = sub(p0, p1), v2 = sub(p2, p1);
    const l0 = norm(v0), l2 = norm(v2);
    const u0 = mul(v0, 1 / l0), u2 = mul(v2, 1 / l2);
    const th = Math.acos(Math.max(-1, Math.min(1, dot(u0, u2))));
    if (th < 1e-6 || Math.abs(th - Math.PI) < 1e-6) { out.push(p1); continue; }
    const t = Math.min(radius / Math.tan(th / 2), 0.499 * l0, 0.499 * l2);
    const re = t * Math.tan(th / 2);
    const a = add(p1, mul(u0, t));
    const bis = unit(add(u0, u2));
    const c = add(p1, mul(bis, re / Math.sin(th / 2)));
    const va = sub(a, c), vb = sub(add(p1, mul(u2, t)), c);
    const ang = Math.acos(Math.max(-1, Math.min(1, dot(va, vb) / (norm(va) * norm(vb)))));
    const axis = unit(cross(va, vb));
    for (let i = 0; i <= n; i++) {
      const f = ang * i / n;
      const v = add(add(mul(va, Math.cos(f)), mul(cross(axis, va), Math.sin(f))), mul(axis, dot(axis, va) * (1 - Math.cos(f))));
      out.push(add(c, v));
    }
  }
  out.push(pts[pts.length - 1]);
  return out;
}

export function stadium(w, l, n = 32) {
  const r = Math.min(w, l) / 2, pts = [];
  if (w >= l) {
    const hx = w / 2 - r;
    for (let k = 0; k <= n; k++) { const a = -Math.PI / 2 + Math.PI * k / n; pts.push([hx + r * Math.cos(a), r * Math.sin(a)]); }
    for (let k = 0; k <= n; k++) { const a = Math.PI / 2 + Math.PI * k / n; pts.push([-hx + r * Math.cos(a), r * Math.sin(a)]); }
  } else {
    const hy = l / 2 - r;
    for (let k = 0; k <= n; k++) { const a = Math.PI * k / n; pts.push([r * Math.cos(a), hy + r * Math.sin(a)]); }
    for (let k = 0; k <= n; k++) { const a = Math.PI + Math.PI * k / n; pts.push([r * Math.cos(a), -hy + r * Math.sin(a)]); }
  }
  return pts;
}

// Owns the manifold objects made while building, so they can all be freed.
class Arena {
  constructor(wasm) { this.w = wasm; this.objs = []; }
  k(m) { this.objs.push(m); return m; }
  free() { for (const o of this.objs) { try { o.delete(); } catch { /* already gone */ } } this.objs = []; }
}

function cyl(A, a, b, r, seg, r2) {
  const h = norm(sub(b, a));
  const c = A.k(A.w.Manifold.cylinder(h, r, r2 ?? r, seg));
  return A.k(c.transform(frame(a, sub(b, a))));
}
const sphere = (A, p, r, seg) => A.k(A.k(A.w.Manifold.sphere(r, seg)).translate(p));
const union = (A, list) => (list.length === 1 ? list[0] : A.k(A.w.Manifold.union(list)));

export function featureSolid(A, f, st = STACK, fine = true) {
  const M = A.w.Manifold, d = f.data;
  const seg = fine ? 32 : 12;
  if (f.kind === 'pipe') {
    const r = d.d / 2;
    const pts = densify(d.points, d.bend || 0, fine ? 8 : 3);
    const parts = [];
    for (let i = 0; i + 1 < pts.length; i++) if (norm(sub(pts[i + 1], pts[i])) > 1e-9) parts.push(cyl(A, pts[i], pts[i + 1], r, seg));
    const joints = d.route ? pts : pts.slice(1, -1);
    for (const p of joints) parts.push(sphere(A, p, r, seg));
    return union(A, parts);
  }
  if (f.kind === 'pocket') {
    const [x, y] = d.at, r = st.pocket_d / 2, dep = st.relief_depth, s = fine ? 48 : 16;
    const ball = sphere(A, [x, y, dep / 2], r, s);
    const slab = A.k(A.k(M.cube([2 * r + 2, 2 * r + 2, dep + PROUD])).translate([x - r - 1, y - r - 1, -PROUD]));
    const cone = A.k(A.k(M.cylinder(r, r, 0, s)).translate([x, y, dep]));
    return A.k(A.k(ball.intersect(slab)).add(cone));
  }
  if (f.kind === 'chamber') {
    const [x, y] = d.at;
    let sw = d.w - 2 * d.depth, sl = d.l - 2 * d.depth;
    if (Math.min(sw, sl) <= 0.1) sw = sl = 0.1;
    const top = stadium(d.w, d.l).map(([u, v]) => [x + u, y + v, 0.02]);
    const bot = stadium(sw, sl).map(([u, v]) => [x + u, y + v, -d.depth]);
    const lower = A.k(M.hull([...top, ...bot]));
    const cs = A.k(new A.w.CrossSection([stadium(d.w, d.l).map(([u, v]) => [x + u, y + v])]));
    const over = A.k(M.extrude(cs, PROUD));
    return A.k(lower.add(over));
  }
  if (f.kind === 'port') {
    const s = d.start, u = d.dir, dep = d.depth, rb = st.bore_d / 2;
    const slope = (st.port_r - rb) / st.lead_len;
    const parts = [
      cyl(A, sub(s, u), add(s, mul(u, dep)), rb, seg),
      cyl(A, sub(s, mul(u, 0.5)), add(s, mul(u, st.lead_len)), st.port_r + slope * 0.5, seg, rb),
      cyl(A, add(s, mul(u, dep - 0.1)), add(s, mul(u, dep + st.neck_len)), st.needle_stop / 2, seg),
    ];
    const a = add(s, mul(u, dep + st.neck_len - 0.1)), e = d.end;
    if (dot(sub(e, a), u) > 1e-6) parts.push(cyl(A, a, e, st.r, seg), sphere(A, e, st.r, seg));
    return union(A, parts);
  }
  if (f.kind === 'hole' || f.kind === 'window') {
    const [x, y] = d.at;
    return cyl(A, [x, y, d.z0 - PROUD], [x, y, d.z1 + PROUD], d.d / 2, f.kind === 'window' && fine ? 96 : seg);
  }
  if (f.kind === 'nut') {
    const [x, y] = d.at, cr = d.af / Math.sqrt(3);
    const hexa = [0, 1, 2, 3, 4, 5].map((k) => { const a = (30 + 60 * k) * Math.PI / 180; return [x + cr * Math.cos(a), y + cr * Math.sin(a)]; });
    const cs = A.k(new A.w.CrossSection([hexa]));
    return A.k(A.k(M.extrude(cs, d.depth + PROUD)).translate([0, 0, d.z - PROUD]));
  }
  throw new Error(f.kind);
}

function key(A, W, L, c, z0, t) {
  const cs = A.k(new A.w.CrossSection([[[-1, L - c - 1], [c + 1, L + 1], [-1, L + 1]]]));
  return A.k(A.k(A.w.Manifold.extrude(cs, t + 2)).translate([0, 0, z0 - 1]));
}

const tick = () => new Promise((r) => setTimeout(r, 0));

// The three plates as meshes (assembly frame), and the problems the checks
// found. Every net must be its own sealed cavity; no two nets may be thinner
// apart than the cell's own proven walls.
export async function makePlates(wasm, model, { progress = () => {}, check = true, fine = true } = {}) {
  const st = model.stack, W = model.width, L = model.length;
  const plates = {}, problems = [], worst = {};
  for (const plate of PLATES) {
    progress(`Cutting the ${plate} plate…`);
    await tick();
    const A = new Arena(wasm);
    const byNet = new Map();
    for (const f of model.features) if (f.plate === plate) {
      if (!byNet.has(f.net)) byNet.set(f.net, []);
      byNet.get(f.net).push(featureSolid(A, f, st, fine));
    }
    const nets = new Map([...byNet].map(([n, v]) => [n, union(A, v)]));
    const z0 = model.z0[plate], t = model.thickness[plate];
    const block = A.k(A.k(wasm.Manifold.cube([W, L, t])).translate([0, 0, z0]));
    const cuts = union(A, [...nets.values()]);
    const body = A.k(block.subtract(cuts)).subtract(key(A, W, L, st.corner_key, z0, t));
    plates[plate] = body;            // the caller owns it
    if (check) {
      progress(`Checking the ${plate} plate…`);
      await tick();
      const inside = A.k(cuts.intersect(block));
      const parts = inside.decompose();
      parts.forEach((p) => A.k(p));
      if (parts.length !== nets.size)
        problems.push(`${plate} plate: the cavities form ${parts.length} separate volumes, expected ${nets.size} — two nets touch. Do not print this.`);
      const names = [...nets.keys()];
      const trimmed = new Map(names.map((n) => [n, A.k(nets.get(n).intersect(block))]));
      const boxes = new Map(names.map((n) => [n, nets.get(n).boundingBox()]));
      let w = [Infinity, null, null];
      names.forEach((a, i) => {
        const ba = boxes.get(a);
        for (const b of names.slice(i + 1)) {
          const bb = boxes.get(b);
          let far = false;
          for (let q = 0; q < 3; q++) if (ba.min[q] > bb.max[q] + 1.5 || bb.min[q] > ba.max[q] + 1.5) far = true;
          if (far || (a.startsWith('bolt') && b.startsWith('bolt'))) continue;
          const g = trimmed.get(a).minGap(trimmed.get(b), 1.5);
          if (g < w[0]) w = [g, a, b];
          if (g < 0.65) problems.push(`${plate} plate: only ${g.toFixed(2)} mm between ${a} and ${b}`);
        }
      });
      worst[plate] = w;
    }
    A.free();
  }
  return { plates, problems, worst };
}

// one net's cavity, trimmed to its plate (for the 3D view)
export function netSolid(wasm, model, plate, net, fine = false) {
  const A = new Arena(wasm);
  const parts = model.features.filter((f) => f.plate === plate && f.net === net).map((f) => featureSolid(A, f, model.stack, fine));
  const z0 = model.z0[plate], t = model.thickness[plate];
  const block = A.k(A.k(wasm.Manifold.cube([model.width, model.length, t])).translate([0, 0, z0]));
  const out = union(A, parts).intersect(block);
  A.free();
  return out;
}

// Contact face down, by rotation or translation only (never mirrored).
export function printPose(plate, solid, model) {
  if (plate === 'bottom') return solid.transform([1, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, 0, 0, model.length, 0, 1]);
  if (plate === 'top') return solid.translate([0, 0, -model.z0.top]);
  return solid.translate([0, 0, 0]);
}

export function stlBytes(solid, header = 'mfcad-layout') {
  const mesh = solid.getMesh();
  const np = mesh.numProp, V = mesh.vertProperties, T = mesh.triVerts;
  const n = T.length / 3;
  const buf = new ArrayBuffer(84 + 50 * n);
  const dv = new DataView(buf);
  for (let i = 0; i < Math.min(80, header.length); i++) dv.setUint8(i, header.charCodeAt(i));
  dv.setUint32(80, n, true);
  let o = 84;
  for (let t = 0; t < n; t++) {
    const p = [0, 1, 2].map((c) => { const v = T[3 * t + c] * np; return [V[v], V[v + 1], V[v + 2]]; });
    let nn = cross(sub(p[1], p[0]), sub(p[2], p[0]));
    const l = norm(nn) || 1;
    nn = mul(nn, 1 / l);
    for (const v of [nn, ...p]) for (const c of v) { dv.setFloat32(o, c, true); o += 4; }
    o += 2;
  }
  return new Uint8Array(buf);
}

export function report(lay, m) {
  const r = m.routing, T = m.thickness;
  const stack = T.bottom + T.middle + T.top;
  const lines = [...r.nets.keys()].filter((n) => n !== SUPPLY);
  const out = [
    'mfcad Layout -- 3D export', '='.repeat(25),
    `Plate ${m.width} x ${m.length} mm. Thickness: bottom ${T.bottom}, middle ${T.middle}, top ${T.top} mm (stack ${+stack.toFixed(2)} mm plus two membranes).`,
    `${lay.actuators.length} actuators, ${lay.bolts.length} M3 bolts, ${lines.length} control lines on ${r.levels} level(s).`,
    '',
    'Printing: every STL is already contact face down. Bottom: chambers face the bed. Middle: valve seats face the bed. Top: membrane side faces the bed.',
    'Assembly, from the bottom up: bottom plate (nuts in the hex pockets), membrane 1, middle plate, membrane 2, top plate. The chamfered corner goes on the same corner of every plate. Cut both membranes from the membrane template.',
    '',
    'How it works: every actuator is two normally-open valves in series between the supply and its dome. Pressurising a line closes the valve it feeds. With the supply on, a dome rises only while BOTH of its lines are vented.',
    '',
    "Inlets (needle ports; positions from the plate's bottom-left corner, seen from the top):",
  ];
  for (const [name, nr] of r.nets) {
    const p = nr.port;
    if (!p) continue;
    const coord = p.face === 'front' || p.face === 'back' ? `x = ${p.start[0].toFixed(2)}` : `y = ${p.start[1].toFixed(2)}`;
    out.push(`  ${name.padEnd(6)} ${(name === SUPPLY ? 'supply' : 'line').padEnd(6)} ${nr.plate.padEnd(6)} plate, ${p.face.padEnd(5)} face at ${coord} mm, ` +
      `${Math.abs(p.start[2]).toFixed(2)} mm ${nr.plate === 'bottom' ? 'below' : 'above'} membrane 1; needle bore ${p.depth} mm`);
  }
  out.push('', 'Lines (actuator: which valve it closes):');
  for (const [name, nr] of r.nets) {
    if (name === SUPPLY) continue;
    out.push(`  ${name.padEnd(6)} ${nr.members.map(([a, w]) => `${a} (${w === 'row' ? 'supply side' : 'dome side'})`).join(', ')}`);
  }
  return out;
}
