// Route the control lines and the supply between freely placed actuators.
// A port of the desktop program's route.py, kept step for step identical
// (same grid, same costs, same tie-breaking) so both give the same channels.
//
// Bottom plate: one net per control line. Every chamber on the line gets a drop
// at its centre, the drops are joined into a tree, and the tree is joined to a
// needle inlet on a side face. Lines run on levels below the chambers; two
// lines cross by taking different levels. Middle plate: the supply, on its own
// level above the valve channels, avoiding every dome riser.

import { SUPPLY, lineMembers } from './model.js';
import { PROUD, STACK } from './stack.js';

const EPS = 1e-3;
const FACE_DIR = { left: [1, 0], right: [-1, 0], front: [0, 1], back: [0, -1] };
const TURN = 1.0;
const VIA = 2.0;
const MAX_LEVELS = 3;

class RouteError extends Error {}

const round4 = (v) => Math.round(v * 1e4) / 1e4;

function axis(length, must, step) {
  const m = [...new Set([...must].map(round4))].filter((v) => v >= -1e-9 && v <= length + 1e-9).sort((a, b) => a - b);
  const out = new Set(m);
  for (let k = 0; k * step <= length + 1e-9; k++) {
    const v = round4(k * step);
    // nearest must values
    let lo = 0, hi = m.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (m[mid] < v) lo = mid + 1; else hi = mid; }
    const near = [m[lo - 1], m[lo]].filter((x) => x !== undefined);
    if (near.every((x) => Math.abs(v - x) > 0.12)) out.add(v);
  }
  out.add(round4(length));
  return Float64Array.from([...out].sort((a, b) => a - b));
}

class Plane {
  constructor(lay, st, nl, mustX, mustY) {
    this.lay = lay; this.st = st; this.nl = nl;
    this.W = lay.width; this.L = lay.length;
    this.xs = axis(this.W, mustX, 0.5);
    this.ys = axis(this.L, mustY, 0.5);
    this.nx = this.xs.length; this.ny = this.ys.length;
    this.nxy = this.nx * this.ny;
    this.n = nl * this.nxy;
  }
  node(k, i, j) { return (k * this.nx + i) * this.ny + j; }
  kij(nid) {
    const k = Math.floor(nid / this.nxy), rem = nid - k * this.nxy;
    const i = Math.floor(rem / this.ny);
    return [k, i, rem - i * this.ny];
  }
  ix(x) { return this._idx(this.xs, x); }
  iy(y) { return this._idx(this.ys, y); }
  _idx(a, v) {
    let best = 0;
    for (let i = 1; i < a.length; i++) if (Math.abs(a[i] - v) < Math.abs(a[best] - v)) best = i;
    if (Math.abs(a[best] - v) > 1e-3) throw new RouteError(`${v} is not on the grid`);
    return best;
  }
  // distance from every node to the side faces (and corner key), skipping one
  edgeRoom(skipFace) {
    const { nx, ny, xs, ys, W, L } = this;
    const out = new Float64Array(nx * ny);
    const ck = this.st.corner_key;
    for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
      let d = Infinity;
      const x = xs[i], y = ys[j];
      if (skipFace !== 'left') d = Math.min(d, x);
      if (skipFace !== 'right') d = Math.min(d, W - x);
      if (skipFace !== 'front') d = Math.min(d, y);
      if (skipFace !== 'back') d = Math.min(d, L - y);
      d = Math.min(d, (x + (L - y) - ck) / Math.SQRT2);
      out[i * ny + j] = d;
    }
    return out;
  }
  fieldPoint(f, x, y, sub) {
    const { nx, ny, xs, ys } = this;
    for (let i = 0; i < nx; i++) {
      const dx = xs[i] - x;
      for (let j = 0; j < ny; j++) {
        const v = Math.hypot(dx, ys[j] - y) - sub;
        if (v < f[i * ny + j]) f[i * ny + j] = v;
      }
    }
  }
  fieldSeg(f, x0, y0, x1, y1, sub) {
    const { nx, ny, xs, ys } = this;
    const dx = x1 - x0, dy = y1 - y0, ll = dx * dx + dy * dy;
    if (ll < 1e-12) return this.fieldPoint(f, x0, y0, sub);
    for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
      const X = xs[i], Y = ys[j];
      let t = ((X - x0) * dx + (Y - y0) * dy) / ll;
      t = t < 0 ? 0 : t > 1 ? 1 : t;
      const v = Math.hypot(X - (x0 + t * dx), Y - (y0 + t * dy)) - sub;
      if (v < f[i * ny + j]) f[i * ny + j] = v;
    }
  }
  heuristic(targets) {
    const { nl, nx, ny, xs, ys, st } = this;
    const h = new Float64Array(this.n).fill(Infinity);
    const per = st.level_step + VIA;
    for (const t of targets) {
      const [tk, ti, tj] = this.kij(t);
      const tx = xs[ti], ty = ys[tj];
      for (let k = 0; k < nl; k++) {
        const add = Math.abs(k - tk) * per;
        for (let i = 0; i < nx; i++) {
          const ax = Math.abs(xs[i] - tx);
          const base = (k * nx + i) * ny;
          for (let j = 0; j < ny; j++) {
            const v = (ax + Math.abs(ys[j] - ty)) + add;
            if (v < h[base + j]) h[base + j] = v;
          }
        }
      }
    }
    return h;
  }
  // cheapest path from any source to any target over free nodes (node ids)
  astar(free, sources, targets, h) {
    const { nx, ny, nl, xs, ys, nxy } = this;
    const total = nl * nxy;
    const g = new Map(), parent = new Map();
    const heap = new Heap();
    for (const s of sources) {
      const sid = s * 6 + 5;
      g.set(sid, 0); parent.set(sid, -1);
      heap.push(h[s], 0, sid);
    }
    const tset = targets instanceof Set ? targets : new Set(targets);
    const step = this.st.level_step + VIA;
    while (heap.size) {
      const [, gc, sid] = heap.pop();
      if (gc > (g.has(sid) ? g.get(sid) : Infinity) + 1e-12) continue;
      const nid = Math.floor(sid / 6), d = sid - nid * 6;
      if (tset.has(nid)) {
        const out = [];
        let s = sid;
        while (s !== -1) { out.push(Math.floor(s / 6)); s = parent.get(s); }
        out.reverse();
        return out.filter((n, i) => i === 0 || n !== out[i - 1]);
      }
      const k = Math.floor(nid / nxy), rem = nid - k * nxy;
      const i = Math.floor(rem / ny), j = rem - i * ny;
      const relax = (m, ng, nd) => {
        const mid = m * 6 + nd;
        if (ng < (g.has(mid) ? g.get(mid) : Infinity) - 1e-12) {
          g.set(mid, ng); parent.set(mid, sid);
          heap.push(ng + h[m], ng, mid);
        }
      };
      for (let nd = 0; nd < 5; nd++) {
        let m, cost;
        if (nd === 0) { if (i + 1 >= nx) continue; m = nid + ny; cost = xs[i + 1] - xs[i]; }
        else if (nd === 1) { if (i === 0) continue; m = nid - ny; cost = xs[i] - xs[i - 1]; }
        else if (nd === 2) { if (j + 1 >= ny) continue; m = nid + 1; cost = ys[j + 1] - ys[j]; }
        else if (nd === 3) { if (j === 0) continue; m = nid - 1; cost = ys[j] - ys[j - 1]; }
        else {
          for (const mm of [nid + nxy, nid - nxy])
            if (mm >= 0 && mm < total && free[mm]) relax(mm, gc + step, 4);
          continue;
        }
        if (!free[m]) continue;
        relax(m, gc + cost + (d < 4 && d !== nd ? TURN : 0), nd);
      }
    }
    return null;
  }
}

// binary heap ordered like Python tuples (f, g, sid)
class Heap {
  constructor() { this.a = []; }
  get size() { return this.a.length; }
  static less(x, y) { return x[0] < y[0] || (x[0] === y[0] && (x[1] < y[1] || (x[1] === y[1] && x[2] < y[2]))); }
  push(f, g, s) {
    const a = this.a; a.push([f, g, s]);
    let i = a.length - 1;
    while (i > 0) { const p = (i - 1) >> 1; if (!Heap.less(a[i], a[p])) break; [a[i], a[p]] = [a[p], a[i]]; i = p; }
  }
  pop() {
    const a = this.a, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && Heap.less(a[l], a[m])) m = l;
        if (r < a.length && Heap.less(a[r], a[m])) m = r;
        if (m === i) break;
        [a[i], a[m]] = [a[m], a[i]]; i = m;
      }
    }
    return top;
  }
}

class PlateRouter {
  constructor(lay, st, plate, nets, nl, levelsZ, statics, bottomT) {
    Object.assign(this, { lay, st, plate, nets, nl, levelsZ, statics, bottomT });
    const mustX = [], mustY = [];
    const r = st.r, pr = st.port_r;
    for (const n of nets) {
      for (const [x, y] of n.terminals) { mustX.push(x); mustY.push(y); }
      const c = n.depth + st.neck_len;
      mustX.push(c, lay.width - c); mustY.push(c, lay.length - c);
    }
    for (const [x, y, rad, nut] of statics)
      for (const rs of [r, pr]) for (const rr of [rad, nut || rad]) {
        const q = rr + st.wall + rs;
        mustX.push(x - q, x + q); mustY.push(y - q, y + q);
      }
    for (const rs of [r, pr]) {
      const q = rs + st.edge_wall;
      mustX.push(q, lay.width - q); mustY.push(q, lay.length - q);
    }
    const p = this.p = new Plane(lay, st, nl, mustX, mustY);
    this.field = new Map();
    for (const n of nets) {
      const f = Array.from({ length: nl }, () => new Float64Array(p.nxy).fill(Infinity));
      for (const [x, y] of n.terminals) p.fieldPoint(f[0], x, y, r);
      this.field.set(n.name, f);
    }
    this.statik = new Map();
    for (const rs of [r, pr]) {
      const per = [];
      for (let k = 0; k < nl; k++) {
        const room = new Float64Array(p.nxy).fill(Infinity);
        for (const [x, y, rad, nut] of statics) {
          const rr = nut && this.nut(k, rs) ? nut : rad;
          p.fieldPoint(room, x, y, rr + st.wall);
        }
        per.push(room);
      }
      this.statik.set(rs, per);
    }
  }
  nut(k, rs) { return this.plate === 'bottom' && this.st.nut_level(k, this.nl, rs); }
  room(net, rs, skipFace) {
    const st = this.st, p = this.p;
    const edge = p.edgeRoom(skipFace);
    const out = [];
    for (let k = 0; k < this.nl; k++) {
      const s = this.statik.get(rs)[k];
      const room = new Float64Array(p.nxy);
      for (let q = 0; q < p.nxy; q++) room[q] = Math.min(s[q], edge[q] - st.edge_wall);
      for (const [m, f] of this.field) {
        if (m === net) continue;
        const fk = f[k];
        for (let q = 0; q < p.nxy; q++) { const v = fk[q] - st.wall; if (v < room[q]) room[q] = v; }
      }
      out.push(room);
    }
    return out;
  }
  route(n) {
    const st = this.st, p = this.p;
    const room = this.room(n.name, st.r);
    const free = new Uint8Array(p.n);
    room.forEach((rk, k) => { for (let q = 0; q < p.nxy; q++) free[k * p.nxy + q] = rk[q] >= st.r - EPS ? 1 : 0; });
    const tnodes = n.terminals.map(([x, y]) => p.node(0, p.ix(x), p.iy(y)));
    n.terminals.forEach(([x, y], idx) => {
      if (!free[tnodes[idx]])
        throw new RouteError(`${n.name}: the feed at (${x.toFixed(2)}, ${y.toFixed(2)}) has no room (too close to a bolt or another line)`);
    });
    const tree = new Set([tnodes[0]]);
    const paths = [];
    let remaining = new Set(tnodes.slice(1));
    const left = () => [...remaining].filter((t) => !tree.has(t));
    while (left().length) {
      remaining = new Set(left());
      const path = p.astar(free, tree, remaining, p.heuristic(remaining));
      if (!path) throw new RouteError(`${n.name}: no room to join all its actuators`);
      paths.push(path);
      for (const q of path) tree.add(q);
    }
    let port = null;
    if (n.face !== null) {
      const [pt, path] = this.port(n, tree, free);
      port = pt; paths.push(path);
    }
    return this.toRoute(n, tnodes, paths, port);
  }
  port(n, tree, free) {
    const st = this.st, p = this.p, lay = this.lay;
    const faces = n.face !== 'auto' ? [n.face] : ['left', 'right', 'front', 'back'];
    const clen = n.depth + st.neck_len;
    const slope = (st.port_r - st.r) / st.lead_len;
    const cands = new Map();
    for (const face of faces) {
      const proom = this.room(n.name, st.port_r, face);
      for (let k = 0; k < this.nl; k++) {
        if (this.plate === 'bottom' && st.level_z(k) + st.port_r + st.floor > this.bottomT + 1e-9) continue;
        const pr = proom[k];
        if (face === 'left' || face === 'right') {
          const ie = p.ix(face === 'left' ? clen : lay.width - clen);
          const xFace = face === 'left' ? 0 : lay.width;
          const [i0, i1] = face === 'left' ? [0, ie] : [ie, p.nx - 1];
          for (let j = 0; j < p.ny; j++) {
            let ok = true;
            for (let i = i0; i <= i1 && ok; i++) {
              const need = Math.max(st.r, st.port_r - slope * Math.abs(p.xs[i] - xFace));
              if (!(pr[i * p.ny + j] >= need - EPS)) ok = false;
            }
            if (ok) cands.set(p.node(k, ie, j), [face, k, [xFace, p.ys[j]]]);
          }
        } else {
          const je = p.iy(face === 'front' ? clen : lay.length - clen);
          const yFace = face === 'front' ? 0 : lay.length;
          const [j0, j1] = face === 'front' ? [0, je] : [je, p.ny - 1];
          for (let i = 0; i < p.nx; i++) {
            let ok = true;
            for (let j = j0; j <= j1 && ok; j++) {
              const need = Math.max(st.r, st.port_r - slope * Math.abs(p.ys[j] - yFace));
              if (!(pr[i * p.ny + j] >= need - EPS)) ok = false;
            }
            if (ok) cands.set(p.node(k, i, je), [face, k, [p.xs[i], yFace]]);
          }
        }
      }
    }
    for (const c of [...cands.keys()]) if (!free[c]) cands.delete(c);
    const where = n.face !== 'auto' ? n.face : 'any face';
    if (!cands.size) throw new RouteError(`${n.name}: no straight run free for its needle inlet on ${where}`);
    const path = p.astar(free, tree, new Set(cands.keys()), p.heuristic([...cands.keys()]));
    if (!path) throw new RouteError(`${n.name}: can't reach an inlet on ${where}`);
    const [face, k, [sx, sy]] = cands.get(path[path.length - 1]);
    const z = this.levelsZ[k];
    const [dx, dy] = FACE_DIR[face];
    const [, i, j] = p.kij(path[path.length - 1]);
    return [{ net: n.name, plate: this.plate, face, start: [sx, sy, z], direction: [dx, dy, 0],
      depth: n.depth, end: [p.xs[i], p.ys[j], z] }, path];
  }
  toRoute(n, tnodes, paths, port) {
    const st = this.st, p = this.p, r = st.r;
    const rt = { name: n.name, plate: this.plate, members: n.members, paths: [], port: null, levels: new Set(), length: 0 };
    const f = Array.from({ length: this.nl }, () => new Float64Array(p.nxy).fill(Infinity));
    for (const path of paths) {
      const pts = path.map((nid) => p.kij(nid));
      const keep = [pts[0]];
      for (let q = 0; q + 2 < pts.length; q++) {
        const [a, b, c] = [pts[q], pts[q + 1], pts[q + 2]];
        const d1 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], d2 = [c[0] - b[0], c[1] - b[1], c[2] - b[2]];
        if (d1[0] !== d2[0] || d1[1] !== d2[1] || d1[2] !== d2[2]) keep.push(b);
      }
      if (pts.length > 1) keep.push(pts[pts.length - 1]);
      rt.paths.push(keep.map(([k, i, j]) => [p.xs[i], p.ys[j], this.levelsZ[k]]));
      for (let q = 0; q + 1 < keep.length; q++) {
        const [k0, i0, j0] = keep[q], [k1, i1, j1] = keep[q + 1];
        const [x0, y0, x1, y1] = [p.xs[i0], p.ys[j0], p.xs[i1], p.ys[j1]];
        for (let k = Math.min(k0, k1); k <= Math.max(k0, k1); k++) p.fieldSeg(f[k], x0, y0, x1, y1, r);
        rt.length += Math.hypot(x1 - x0, y1 - y0) + Math.abs(this.levelsZ[k1] - this.levelsZ[k0]);
      }
      for (const [k] of pts) rt.levels.add(k);
    }
    const zFace = this.plate === 'bottom' ? PROUD : -PROUD;
    for (const t of tnodes) {
      const [, i, j] = p.kij(t);
      const x = p.xs[i], y = p.ys[j];
      rt.paths.push([[x, y, zFace], [x, y, this.levelsZ[0]]]);
      p.fieldPoint(f[0], x, y, r);
    }
    if (port) {
      const kk = this.levelsZ.indexOf(port.start[2]);
      const [sx, sy] = port.start, [ex, ey] = port.end, [dx, dy] = port.direction;
      const mx = sx + dx * (st.lead_len + 0.5), my = sy + dy * (st.lead_len + 0.5);
      p.fieldSeg(f[kk], sx, sy, ex, ey, r);
      p.fieldSeg(f[kk], sx, sy, mx, my, st.port_r);
      for (const k of [kk - 1, kk + 1]) if (k >= 0 && k < this.nl) p.fieldSeg(f[k], sx, sy, mx, my, r);
      rt.port = port;
    }
    this.field.set(n.name, f);
    n.route = rt;
    return rt;
  }
}

function makeNets(lay, st) {
  const acts = new Map(lay.actuators.map((a) => [a.name, a]));
  const lines = [];
  for (const [name, members] of lineMembers(lay)) {
    const pts = members.map(([an, which]) => { const [colFeed, rowFeed] = acts.get(an).feeds(); return which === 'row' ? rowFeed : colFeed; });
    lines.push({ name, plate: 'bottom', members, terminals: pts, face: lay.faces[name] ?? 'auto', depth: lay.rules.needle_depth, route: null });
  }
  const sup = { name: SUPPLY, plate: 'middle', members: lay.actuators.map((a) => [a.name, 'supply']),
    terminals: lay.actuators.map((a) => a.local(st.col / 2, 0)), face: lay.faces[SUPPLY] ?? 'front',
    depth: lay.rules.supply_depth, route: null };
  return [lines, sup];
}

const pyLess = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// Route every line and the supply. progress(text) is called as it goes.
export function routeLayout(lay, st = STACK, progress = () => {}) {
  const out = { ok: false, levels: 0, bottom_t: 0, nets: new Map(), problems: [], notes: [] };
  if (!lay.actuators.length) { out.problems.push('There are no actuators to connect.'); return out; }
  const R = lay.rules;
  const nutR = R.nut_af / Math.sqrt(3);
  const bolts = lay.bolts.map((b) => [b.x, b.y, R.bolt_d / 2, nutR]);
  const [lines, sup] = makeNets(lay, st);

  progress('Routing the supply…');
  const risers = lay.actuators.map((a) => [a.x, a.y, st.r, null]);
  const mid = new PlateRouter(lay, st, 'middle', [sup], 1, [st.level2],
    [...bolts.map(([x, y, rad]) => [x, y, rad, null]), ...risers], 0);
  try { mid.route(sup); } catch (e) { if (!(e instanceof RouteError)) throw e; out.problems.push(e.message); return out; }
  out.nets.set(SUPPLY, sup.route);

  let last = null;
  for (let nl = 1; nl <= MAX_LEVELS; nl++) {
    const Tb = st.bottom_t(nl);
    const zs = Array.from({ length: nl }, (_, k) => -st.level_z(k));
    const order = [...lines].sort((a, b) => (b.terminals.length - a.terminals.length) || pyLess(a.name, b.name));
    for (let attempt = 0; attempt <= lines.length; attempt++) {
      progress(`Routing ${lines.length} lines on ${nl} level${nl > 1 ? 's' : ''}${attempt ? ` (try ${attempt + 1})` : ''}…`);
      const pr = new PlateRouter(lay, st, 'bottom', lines, nl, zs, bolts, Tb);
      let failed = null;
      for (const n of order) {
        try { pr.route(n); } catch (e) { if (!(e instanceof RouteError)) throw e; failed = n; last = e.message; break; }
      }
      if (!failed) {
        out.ok = true; out.levels = nl; out.bottom_t = Tb;
        for (const n of lines) out.nets.set(n.name, n.route);
        out.notes.push(`${lines.length} control lines on ${nl} level(s); bottom plate ${Tb} mm`);
        return out;
      }
      if (order[0] === failed) break;
      order.splice(order.indexOf(failed), 1);
      order.unshift(failed);
    }
  }
  out.problems.push(last || 'Could not route the lines.');
  return out;
}
