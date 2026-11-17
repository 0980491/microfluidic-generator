// 1:1 SVG drawings, in millimetres (y flipped so the file reads like the plate).
import { netColor, palette } from './colors.js';

const f3 = (v) => v.toFixed(3);

function svg(lay, body, caption) {
  const W = lay.width, L = lay.length;
  return [`<svg xmlns="http://www.w3.org/2000/svg" width="${f3(W)}mm" height="${f3(L)}mm" viewBox="0 0 ${f3(W)} ${f3(L)}">`,
    `<rect x="0" y="0" width="${f3(W)}" height="${f3(L)}" fill="none" stroke="black" stroke-width="0.2"/>`,
    ...body,
    `<text x="1" y="${f3(L - 1)}" font-family="sans-serif" font-size="2" fill="gray">${caption}</text>`, '</svg>', ''].join('\n');
}

export function drawingSvg(lay) {
  const R = lay.rules, L = lay.length, fy = (y) => L - y, out = [];
  for (const a of lay.actuators) {
    const [x0, y0, x1, y1] = a.footprint(R);
    out.push(`<rect x="${f3(x0)}" y="${f3(fy(y1))}" width="${f3(x1 - x0)}" height="${f3(y1 - y0)}" fill="none" stroke="#adb5bd" stroke-width="0.15" stroke-dasharray="0.8,0.5"/>`);
    for (const [c0, c1, c2, c3] of a.chambers())
      out.push(`<rect x="${f3(c0)}" y="${f3(fy(c3))}" width="${f3(c2 - c0)}" height="${f3(c3 - c1)}" fill="#dee2e6" stroke="#868e96" stroke-width="0.12"/>`);
    for (const [sx, sy, sr] of a.seats())
      out.push(`<circle cx="${f3(sx)}" cy="${f3(fy(sy))}" r="${f3(sr)}" fill="none" stroke="#495057" stroke-width="0.12"/>`);
    const [wx, wy, wr] = a.window(R);
    out.push(`<circle cx="${f3(wx)}" cy="${f3(fy(wy))}" r="${f3(wr)}" fill="#a5d8ff" fill-opacity="0.6" stroke="#1971c2" stroke-width="0.2"/>`);
    out.push(`<text x="${f3(wx)}" y="${f3(fy(wy) + 0.8)}" font-family="sans-serif" font-size="2.2" text-anchor="middle" fill="#1864ab">${a.name}</text>`);
  }
  for (const b of lay.bolts) out.push(`<circle cx="${f3(b.x)}" cy="${f3(fy(b.y))}" r="${f3(R.bolt_d / 2)}" fill="none" stroke="red" stroke-width="0.2"/>`);
  return svg(lay, out, `mfcad layout ${lay.width} x ${lay.length} mm, 1:1`);
}

export function membraneSvg(lay) {
  const R = lay.rules, L = lay.length, fy = (y) => L - y, out = [];
  for (const b of lay.bolts) out.push(`<circle cx="${f3(b.x)}" cy="${f3(fy(b.y))}" r="${f3(R.bolt_d / 2)}" fill="none" stroke="red" stroke-width="0.2"/>`);
  for (const a of lay.actuators) {
    const [wx, wy, wr] = a.window(R);
    out.push(`<circle cx="${f3(wx)}" cy="${f3(fy(wy))}" r="${f3(wr)}" fill="none" stroke="gray" stroke-width="0.15" stroke-dasharray="0.8,0.6"/>`);
  }
  return svg(lay, out, `membrane ${lay.width} x ${lay.length} mm - cut red, windows dashed - 1:1`);
}

export function channelsSvg(lay, model) {
  const R = lay.rules, L = lay.length, fy = (y) => L - y, st = model.stack, out = [];
  const pal = palette([...model.routing.nets.keys()]);
  for (const a of lay.actuators) {
    for (const [c0, c1, c2, c3] of a.chambers())
      out.push(`<rect x="${f3(c0)}" y="${f3(fy(c3))}" width="${f3(c2 - c0)}" height="${f3(c3 - c1)}" fill="none" stroke="#ced4da" stroke-width="0.12"/>`);
    const [wx, wy, wr] = a.window(R);
    out.push(`<circle cx="${f3(wx)}" cy="${f3(fy(wy))}" r="${f3(wr)}" fill="none" stroke="#a5d8ff" stroke-width="0.15"/>`);
    out.push(`<text x="${f3(wx)}" y="${f3(fy(wy) + 0.8)}" font-family="sans-serif" font-size="2" text-anchor="middle" fill="#adb5bd">${a.name}</text>`);
  }
  for (const b of lay.bolts) out.push(`<circle cx="${f3(b.x)}" cy="${f3(fy(b.y))}" r="${f3(R.bolt_d / 2)}" fill="none" stroke="#495057" stroke-width="0.2"/>`);
  for (const [name, nr] of model.routing.nets) {
    const col = netColor(name, pal);
    for (const p of nr.paths) for (let i = 0; i + 1 < p.length; i++) {
      const [x0, y0, z0] = p[i], [x1, y1] = p[i + 1];
      if (Math.abs(x0 - x1) < 1e-9 && Math.abs(y0 - y1) < 1e-9) continue;
      const k = nr.plate === 'bottom' ? Math.round((Math.abs(z0) - st.ctrl_z) / st.level_step) : 0;
      const [w, op] = k === 0 ? [st.d, 0.9] : [st.d + 0.6 * k, 0.45];
      out.push(`<line x1="${f3(x0)}" y1="${f3(fy(y0))}" x2="${f3(x1)}" y2="${f3(fy(y1))}" stroke="${col}" stroke-width="${w.toFixed(2)}" stroke-opacity="${op}" stroke-linecap="round"/>`);
    }
    if (nr.port) {
      const [sx, sy] = nr.port.start, [ex, ey] = nr.port.end;
      out.push(`<line x1="${f3(sx)}" y1="${f3(fy(sy))}" x2="${f3(ex)}" y2="${f3(fy(ey))}" stroke="${col}" stroke-width="${(st.port_r * 2).toFixed(2)}"/>`);
      out.push(`<text x="${f3(sx)}" y="${f3(fy(sy))}" font-family="sans-serif" font-size="2.6" font-weight="bold" fill="${col}">${name}</text>`);
    }
  }
  return svg(lay, out, `channels ${lay.width} x ${lay.length} mm - thick/pale = deeper - 1:1`);
}
