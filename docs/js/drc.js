// Design-rule checks: what may sit where (same rules as the desktop program).
import { Actuator, Bolt } from './model.js';

const EPS = 1e-6;

function circleRect(cx, cy, r, [x0, y0, x1, y1]) {
  const dx = Math.max(x0 - cx, 0, cx - x1), dy = Math.max(y0 - cy, 0, cy - y1);
  if (dx === 0 && dy === 0) return -r - Math.min(cx - x0, x1 - cx, cy - y0, y1 - cy);
  return Math.hypot(dx, dy) - r;
}

export function footprintGap(a, b, rules) {
  const fa = a.footprint(rules), fb = b.footprint(rules);
  return Math.max(Math.max(fa[0], fb[0]) - Math.min(fa[2], fb[2]), Math.max(fa[1], fb[1]) - Math.min(fa[3], fb[3]));
}

// [wall to the window, wall to the nearest chamber or seat]
export function boltWalls(bolt, act, rules) {
  const r = rules.bolt_d / 2;
  const [wx, wy, wr] = act.window(rules);
  const w = Math.hypot(bolt.x - wx, bolt.y - wy) - r - wr;
  const f = Math.min(...act.seats().map(([sx, sy, sr]) => Math.hypot(bolt.x - sx, bolt.y - sy) - r - sr),
    ...act.chambers().map((ch) => circleRect(bolt.x, bolt.y, r, ch)));
  return [w, f];
}

const v = (rule, message, items) => ({ rule, message, items });

function pair(a, b, rules) {
  if (a instanceof Bolt && b instanceof Actuator) [a, b] = [b, a];
  if (a instanceof Actuator && b instanceof Actuator) {
    const g = footprintGap(a, b, rules);
    if (g < -EPS) return v('actuator overlap', `${a.name} and ${b.name} overlap`, [a.name, b.name]);
    if (g < rules.act_gap - EPS) return v('actuator gap', `${a.name}–${b.name}: ${g.toFixed(2)} mm apart, the gap is ${rules.act_gap}`, [a.name, b.name]);
    return null;
  }
  if (a instanceof Actuator && b instanceof Bolt) {
    const [fx0, fy0, fx1, fy1] = a.footprint(rules);
    const reach = rules.bolt_d / 2 + Math.max(rules.bolt_window, rules.bolt_feature) + 0.1;
    if (!(fx0 - reach <= b.x && b.x <= fx1 + reach && fy0 - reach <= b.y && b.y <= fy1 + reach)) return null;
    const [w, f] = boltWalls(b, a, rules);
    if (w < rules.bolt_window - EPS)
      return v('bolt to window', `${b.name} is ${w < 0 ? 'on' : `${w.toFixed(2)} mm from`} ${a.name}'s dome window (needs ${rules.bolt_window})`, [a.name, b.name]);
    if (f < rules.bolt_feature - EPS)
      return v('bolt to valve', `${b.name} ${f < 0 ? 'cuts into' : `is ${f.toFixed(2)} mm from`} ${a.name}'s valves (needs ${rules.bolt_feature})`, [a.name, b.name]);
    return null;
  }
  const d = Math.hypot(a.x - b.x, a.y - b.y);
  if (d < rules.bolt_spacing - EPS) return v('bolt spacing', `${a.name}–${b.name}: ${d.toFixed(2)} mm apart (needs ${rules.bolt_spacing})`, [a.name, b.name]);
  return null;
}

function edge(it, lay) {
  const R = lay.rules;
  let e, m;
  if (it instanceof Actuator) {
    const [x0, y0, x1, y1] = it.footprint(R);
    e = R.act_edge; m = Math.min(x0, y0, lay.width - x1, lay.length - y1);
  } else {
    e = R.bolt_edge; m = Math.min(it.x, it.y, lay.width - it.x, lay.length - it.y);
  }
  if (m < e - EPS) return v('edge', `${it.name} is ${m < 0 ? 'outside the plate' : `${m.toFixed(2)} mm from the plate edge`} (needs ${e})`, [it.name]);
  return null;
}

export function check(lay) {
  const out = [], items = lay.items();
  items.forEach((a, i) => {
    const e = edge(a, lay); if (e) out.push(e);
    for (const b of items.slice(i + 1)) { const p = pair(a, b, lay.rules); if (p) out.push(p); }
  });
  return out;
}

export function placement(lay, moving, ignore = []) {
  const skip = new Set([...ignore, ...moving.map((it) => it.name)]);
  const others = lay.items().filter((it) => !skip.has(it.name));
  const out = [];
  moving.forEach((a, i) => {
    const e = edge(a, lay); if (e) out.push(e);
    for (const b of [...others, ...moving.slice(i + 1)]) { const p = pair(a, b, lay.rules); if (p) out.push(p); }
  });
  return out;
}

export function describeClearance(lay, it) {
  const R = lay.rules, parts = [];
  if (it instanceof Actuator) {
    const gaps = lay.actuators.filter((a) => a.name !== it.name).map((a) => [footprintGap(it, a, R), a.name]);
    const walls = lay.bolts.map((b) => [Math.min(...boltWalls(b, it, R)), b.name]);
    if (gaps.length) { const [g, n] = gaps.sort((a, b) => a[0] - b[0])[0]; parts.push(`nearest actuator ${Math.max(g, 0).toFixed(2)} mm (${n})`); }
    if (walls.length) { const [w, n] = walls.sort((a, b) => a[0] - b[0])[0]; parts.push(`nearest bolt wall ${w.toFixed(2)} mm (${n})`); }
    return parts.join('; ') || 'alone on the plate';
  }
  const near = lay.actuators.map((a) => [boltWalls(it, a, R), a.name]);
  if (near.length) {
    const [[w, f], n] = near.sort((a, b) => Math.min(...a[0]) - Math.min(...b[0]))[0];
    parts.push(`to ${n}: window wall ${w.toFixed(2)}, valve wall ${f.toFixed(2)} mm`);
  }
  const bs = lay.bolts.filter((b) => b.name !== it.name).map((b) => [Math.hypot(it.x - b.x, it.y - b.y), b.name]);
  if (bs.length) { const [d, n] = bs.sort((a, b) => a[0] - b[0])[0]; parts.push(`nearest bolt ${d.toFixed(2)} mm (${n})`); }
  return parts.join('; ') || 'alone on the plate';
}
