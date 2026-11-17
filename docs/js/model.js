// The layout: a plate, actuators and bolts on it, the rules, and the lines.
// Same file format as the desktop program (.mfl, JSON). Millimetres, origin at
// the plate's bottom-left corner, x right, y up, seen from the top plate.

export const FORMAT = 'mfcad-layout';
export const VERSION = 1;
export const SUPPLY = 'S';
export const FACES = ['auto', 'left', 'right', 'front', 'back'];

export const CELL = Object.freeze({
  col: 6.0, seat_gap: 3.2, pocket_d: 2.4, chamber_l: 3.8, chamber_w: 7.0,
  chamber_dy: 1.6, footprint_dy: 0.7, wall: 1.2,
});

export const RULE_FIELDS = [
  ['pitch_x', 'Actuator footprint X', 'Width of the area one actuator owns. Two actuators side by side sit at least this far apart (the matrix pitch).'],
  ['pitch_y', 'Actuator footprint Y', 'Height of the area one actuator owns (the matrix pitch).'],
  ['act_gap', 'Extra gap between actuators', 'Added between two footprints. 0 = packed like the matrices.'],
  ['act_edge', 'Actuator to plate edge', 'From a footprint to the plate edge.'],
  ['window_d', 'Dome window diameter', 'Hole in the top plate the membrane balloons through.'],
  ['bolt_d', 'Bolt hole diameter', 'Clearance hole, through all plates.'],
  ['nut_af', 'Nut pocket across flats', 'Hex pocket in the bottom plate.'],
  ['bolt_edge', 'Bolt to plate edge', 'Bolt centre to the plate edge.'],
  ['bolt_spacing', 'Bolt to bolt', 'Bolt centre to bolt centre.'],
  ['bolt_window', 'Bolt hole to dome window', 'Wall between a bolt hole and a window: the membrane is clamped there.'],
  ['bolt_feature', 'Bolt hole to chamber / seat', 'Wall between a bolt hole and a control chamber or a valve seat (0.7 on the printed matrices).'],
  ['needle_depth', 'Needle bore, line inlets', 'How far the dispensing needle goes into a row/column inlet before it lands on the stop (3D only).'],
  ['supply_depth', 'Needle bore, supply inlet', 'The same for the supply inlet in the middle plate (3D only).'],
];

export const PROVEN = Object.freeze({
  pitch_x: 14.0, pitch_y: 11.9, act_gap: 0.0, act_edge: 4.8, window_d: 7.0,
  bolt_d: 3.8, nut_af: 5.9, bolt_edge: 4.8, bolt_spacing: 8.0, bolt_window: 2.0,
  bolt_feature: 0.7, needle_depth: 7.0, supply_depth: 8.0,
});

export function ruleFloors(rules) {
  const c = CELL;
  const spanX = c.col + c.chamber_l;
  const up = c.chamber_dy + c.chamber_w / 2 - c.footprint_dy;
  const down = rules.window_d / 2 + c.footprint_dy;
  const r2 = (v) => Math.round(v * 100) / 100;
  return {
    pitch_x: r2(Math.max(spanX, rules.window_d) + c.wall),
    pitch_y: r2(2 * Math.max(up, down) + c.wall),
    window_d: 1.0, bolt_d: 1.0, nut_af: rules.bolt_d, needle_depth: 2.0, supply_depth: 2.0,
  };
}

export function rot(x, y, deg) {
  deg = ((deg % 360) + 360) % 360;
  if (deg === 0) return [x, y];
  if (deg === 90) return [-y, x];
  if (deg === 180) return [-x, -y];
  if (deg === 270) return [y, -x];
  const a = deg * Math.PI / 180;
  return [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];
}

function rect(cx, cy, w, h, ox, oy, deg) {
  const xs = [], ys = [];
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
    const [px, py] = rot(cx + sx * w / 2, cy + sy * h / 2, deg);
    xs.push(ox + px); ys.push(oy + py);
  }
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

const r4 = (v) => Math.round(v * 1e4) / 1e4;

export class Actuator {
  constructor(name, x, y, rotation = 0, rowLine = '', colLine = '') {
    Object.assign(this, { name, x, y, rotation, rowLine, colLine });
  }
  get kind() { return 'actuator'; }
  footprint(rules) { return rect(0, CELL.footprint_dy, rules.pitch_x, rules.pitch_y, this.x, this.y, this.rotation); }
  window(rules) { return [this.x, this.y, rules.window_d / 2]; }
  seats() {
    const out = [];
    for (const lx of [-CELL.col / 2, CELL.col / 2]) for (const ly of [0, CELL.seat_gap]) {
      const [dx, dy] = rot(lx, ly, this.rotation);
      out.push([this.x + dx, this.y + dy, CELL.pocket_d / 2]);
    }
    return out;
  }
  // [column valve, row valve]
  chambers() {
    return [-CELL.col / 2, CELL.col / 2].map((lx) =>
      rect(lx, CELL.chamber_dy, CELL.chamber_l, CELL.chamber_w, this.x, this.y, this.rotation));
  }
  // chamber feed points: [column valve, row valve]
  feeds() { return [-CELL.col / 2, CELL.col / 2].map((lx) => this.local(lx, CELL.chamber_dy)); }
  local(lx, ly) { const [dx, dy] = rot(lx, ly, this.rotation); return [this.x + dx, this.y + dy]; }
  corners(rules) { const [x0, y0, x1, y1] = this.footprint(rules); return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]; }
  toDict() {
    const d = { name: this.name, x: r4(this.x), y: r4(this.y), rotation: this.rotation };
    if (this.rowLine) d.row_line = this.rowLine;
    if (this.colLine) d.col_line = this.colLine;
    return d;
  }
}

export class Bolt {
  constructor(name, x, y) { Object.assign(this, { name, x, y }); }
  get kind() { return 'bolt'; }
  toDict() { return { name: this.name, x: r4(this.x), y: r4(this.y) }; }
}

export class Layout {
  constructor(o = {}) {
    this.width = o.width ?? 60;
    this.length = o.length ?? 50;
    this.rules = { ...PROVEN, ...(o.rules || {}) };
    this.actuators = o.actuators || [];
    this.bolts = o.bolts || [];
    this.grid = o.grid ?? 0.5;
    this.faces = o.faces || {};
  }
  items() { return [...this.actuators, ...this.bolts]; }
  get(name) { return this.items().find((it) => it.name === name) || null; }
  nextName(prefix) {
    const used = new Set(this.items().map((it) => it.name));
    let n = 1;
    while (used.has(`${prefix}${n}`)) n++;
    return `${prefix}${n}`;
  }
  remove(names) {
    const s = new Set(names);
    this.actuators = this.actuators.filter((a) => !s.has(a.name));
    this.bolts = this.bolts.filter((b) => !s.has(b.name));
  }
  toDict() {
    const lines = {};
    for (const k of Object.keys(this.faces).sort()) if (this.faces[k] !== 'auto') lines[k] = { face: this.faces[k] };
    return {
      format: FORMAT, version: VERSION, units: 'mm',
      plate: { width: r4(this.width), length: r4(this.length) },
      construction: '3 rigid plates (top, middle, bottom) + 2 membranes; actuator = mfcad matrix cell (2 NO valves in series + dome)',
      rules: { ...this.rules },
      editor: { grid: this.grid },
      actuators: this.actuators.map((a) => a.toDict()),
      bolts: this.bolts.map((b) => b.toDict()),
      lines,
    };
  }
  static fromDict(d) {
    if (!d || d.format !== FORMAT) throw new Error('not an mfcad layout file');
    if (Number(d.version || 0) > VERSION) throw new Error(`made by a newer version (file v${d.version})`);
    const rules = { ...PROVEN };
    for (const [k, v] of Object.entries(d.rules || {})) if (k in PROVEN) rules[k] = Number(v);
    const acts = (d.actuators || []).map((a) => new Actuator(String(a.name), Number(a.x), Number(a.y),
      ((Number(a.rotation || 0) % 360) + 360) % 360, String(a.row_line || '').trim(), String(a.col_line || '').trim()));
    const bolts = (d.bolts || []).map((b) => new Bolt(String(b.name), Number(b.x), Number(b.y)));
    const names = [...acts, ...bolts].map((it) => it.name);
    if (new Set(names).size !== names.length) throw new Error('two items share a name');
    const faces = {};
    for (const [k, v] of Object.entries(d.lines || {})) if (FACES.includes(v.face)) faces[k] = v.face;
    return new Layout({ width: Number(d.plate.width), length: Number(d.plate.length), rules,
      actuators: acts, bolts, grid: Number((d.editor || {}).grid ?? 0.5), faces });
  }
  copy() { return Layout.fromDict(JSON.parse(JSON.stringify(this.toDict()))); }
}

export function defaultPitch(rules, rotation = 0) {
  const fw = rules.pitch_x + rules.act_gap, fh = rules.pitch_y + rules.act_gap;
  return rotation % 180 ? [fh, fw] : [fw, fh];
}

export function matrix(rows, cols, rules, pitchX = null, pitchY = null, rotation = 0, origin = [0, 0], cornerBolts = true) {
  const [fw, fh] = defaultPitch(rules, rotation);
  const px = pitchX ?? fw, py = pitchY ?? fh;
  const acts = [];
  let n = 1;
  for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++)
    acts.push(new Actuator(`A${n++}`, origin[0] + i * px, origin[1] + j * py, ((rotation % 360) + 360) % 360));
  const pts = [];
  if (cornerBolts) for (const a of acts) for (const p of a.corners(rules))
    if (pts.every((q) => Math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-6)) pts.push(p);
  return [acts, pts];
}

// (row line, column line) of every actuator. Automatic names work like a
// keyboard matrix: domes at the same height (within tol) share a row line,
// R1.. from the top; domes in the same vertical share a column line, C1.. from
// the left. Only actuators left on automatic are numbered.
export function resolveLines(lay, tol = 1.0) {
  const groups = (vals, reverse) => {
    const order = [...new Set(vals)].sort((a, b) => (reverse ? b - a : a - b));
    const names = new Map();
    let n = 0, last = null;
    for (const v of order) {
      if (last === null || Math.abs(v - last) > tol) { n++; last = v; }
      names.set(v, n);
    }
    return names;
  };
  const rows = groups(lay.actuators.filter((a) => !a.rowLine).map((a) => a.y), true);
  const cols = groups(lay.actuators.filter((a) => !a.colLine).map((a) => a.x), false);
  const out = {};
  for (const a of lay.actuators)
    out[a.name] = [a.rowLine || `R${rows.get(a.y)}`, a.colLine || `C${cols.get(a.x)}`];
  return out;
}

export function lineKey(name) {
  const m = /^([A-Za-z]*)(\d*)(.*)$/.exec(name);
  const [pre, num, rest] = m ? [m[1], m[2], m[3]] : [name, '', ''];
  const rank = { R: 0, C: 1 }[pre.toUpperCase()] ?? 2;
  return [rank, pre, num ? parseInt(num, 10) : -1, rest];
}

export function compareLines(a, b) {
  const ka = lineKey(a), kb = lineKey(b);
  for (let i = 0; i < 4; i++) {
    if (ka[i] < kb[i]) return -1;
    if (ka[i] > kb[i]) return 1;
  }
  return 0;
}

// line -> [[actuator, 'row'|'col']], in line order
export function lineMembers(lay) {
  const out = new Map();
  const lines = resolveLines(lay);
  for (const a of lay.actuators) {
    const name = a.name, [r, c] = lines[name];
    if (!out.has(r)) out.set(r, []);
    out.get(r).push([name, 'row']);
    if (!out.has(c)) out.set(c, []);
    out.get(c).push([name, 'col']);
  }
  return new Map([...out.entries()].sort((a, b) => compareLines(a[0], b[0])));
}
