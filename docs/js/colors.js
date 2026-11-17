// One colour per net, shared by the editor, the 3D view and the drawings.
import { SUPPLY, compareLines, lineKey } from './model.js';

const ROWS = ['#e8590c', '#d6336c', '#f59f00', '#c2255c', '#fd7e14', '#e64980', '#fab005', '#a61e4d'];
const COLS = ['#1c7ed6', '#0ca678', '#7048e8', '#1098ad', '#4c6ef5', '#37b24d', '#ae3ec9', '#0b7285'];
const OTHER = ['#5c940d', '#862e9c', '#364fc7', '#c92a2a', '#087f5b', '#e67700'];
export const SUPPLY_COLOR = '#2b8a3e';
export const CELL_MID = '#9775fa';
export const CELL_OUT = '#339af0';
export const BOLT = '#868e96';

export function palette(lines) {
  const out = { [SUPPLY]: SUPPLY_COLOR };
  const counts = [0, 0, 0];
  for (const name of [...new Set(lines)].sort(compareLines)) {
    if (name === SUPPLY) continue;
    const rank = lineKey(name)[0];
    const pal = [ROWS, COLS, OTHER][rank];
    out[name] = pal[counts[rank]++ % pal.length];
  }
  return out;
}

export function netColor(net, pal) {
  if (pal[net]) return pal[net];
  if (net.endsWith('.mid')) return CELL_MID;
  if (net.endsWith('.out') || net.endsWith('.window')) return CELL_OUT;
  return BOLT;
}

export function mix(c1, c2, t) {
  const a = [1, 3, 5].map((i) => parseInt(c1.slice(i, i + 2), 16));
  const b = [1, 3, 5].map((i) => parseInt(c2.slice(i, i + 2), 16));
  return '#' + a.map((x, i) => Math.round(x + (b[i] - x) * t).toString(16).padStart(2, '0')).join('');
}
