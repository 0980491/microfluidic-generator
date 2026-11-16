"""1:1 SVG drawings of a layout, in millimetres.

* `drawing`: everything (footprints, valves, windows, bolts, names), to print
  or to show.
* `membrane`: what a membrane mould needs -- the plate outline and the bolt
  holes to cut in red, the windows dashed for reference.
"""

from __future__ import annotations

from pathlib import Path

from .model import Layout


def _svg(lay: Layout, body: list[str], caption: str) -> str:
    W, L = lay.width, lay.length
    head = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.3f}mm" height="{L:.3f}mm" '
            f'viewBox="0 0 {W:.3f} {L:.3f}">',
            f'<rect x="0" y="0" width="{W:.3f}" height="{L:.3f}" fill="none" '
            f'stroke="black" stroke-width="0.2"/>']
    tail = [f'<text x="1" y="{L - 1:.3f}" font-family="sans-serif" font-size="2" '
            f'fill="gray">{caption}</text>', "</svg>"]
    return "\n".join(head + body + tail) + "\n"


def drawing(lay: Layout, path) -> None:
    R, L = lay.rules, lay.length
    fy = lambda y: L - y
    out = []
    for a in lay.actuators:
        x0, y0, x1, y1 = a.footprint(R)
        out.append(f'<rect x="{x0:.3f}" y="{fy(y1):.3f}" width="{x1 - x0:.3f}" height="{y1 - y0:.3f}" '
                   f'fill="none" stroke="#adb5bd" stroke-width="0.15" stroke-dasharray="0.8,0.5"/>')
        for c0, c1, c2, c3 in a.chambers():
            out.append(f'<rect x="{c0:.3f}" y="{fy(c3):.3f}" width="{c2 - c0:.3f}" height="{c3 - c1:.3f}" '
                       f'fill="#dee2e6" stroke="#868e96" stroke-width="0.12"/>')
        for sx, sy, sr in a.seats():
            out.append(f'<circle cx="{sx:.3f}" cy="{fy(sy):.3f}" r="{sr:.3f}" fill="none" '
                       f'stroke="#495057" stroke-width="0.12"/>')
        wx, wy, wr = a.window(R)
        out.append(f'<circle cx="{wx:.3f}" cy="{fy(wy):.3f}" r="{wr:.3f}" fill="#a5d8ff" '
                   f'fill-opacity="0.6" stroke="#1971c2" stroke-width="0.2"/>')
        out.append(f'<text x="{wx:.3f}" y="{fy(wy) + 0.8:.3f}" font-family="sans-serif" '
                   f'font-size="2.2" text-anchor="middle" fill="#1864ab">{a.name}</text>')
    for b in lay.bolts:
        out.append(f'<circle cx="{b.x:.3f}" cy="{fy(b.y):.3f}" r="{R.bolt_d / 2:.3f}" fill="none" '
                   f'stroke="red" stroke-width="0.2"/>')
    _write(path, _svg(lay, out, f"mfcad layout {lay.width:g} x {lay.length:g} mm, 1:1"))


def membrane(lay: Layout, path) -> None:
    R, L = lay.rules, lay.length
    fy = lambda y: L - y
    out = []
    for b in lay.bolts:
        out.append(f'<circle cx="{b.x:.3f}" cy="{fy(b.y):.3f}" r="{R.bolt_d / 2:.3f}" fill="none" '
                   f'stroke="red" stroke-width="0.2"/>')
    for a in lay.actuators:
        wx, wy, wr = a.window(R)
        out.append(f'<circle cx="{wx:.3f}" cy="{fy(wy):.3f}" r="{wr:.3f}" fill="none" '
                   f'stroke="gray" stroke-width="0.15" stroke-dasharray="0.8,0.6"/>')
    _write(path, _svg(lay, out, f"membrane {lay.width:g} x {lay.length:g} mm - cut red, "
                                "windows dashed - 1:1"))


def _write(path, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def channels(lay: Layout, model, path) -> None:
    """The routed channels from the top, one colour per net: what runs where
    inside the bottom (lines) and middle (supply) plates. Thicker, paler
    strokes are deeper levels."""
    from .colors import net_color, palette
    R, L = lay.rules, lay.length
    fy = lambda y: L - y
    pal = palette(model.routing.nets)
    st = model.stack
    out = []
    for a in lay.actuators:
        for c0, c1, c2, c3 in a.chambers():
            out.append(f'<rect x="{c0:.3f}" y="{fy(c3):.3f}" width="{c2 - c0:.3f}" height="{c3 - c1:.3f}" '
                       f'fill="none" stroke="#ced4da" stroke-width="0.12"/>')
        wx, wy, wr = a.window(R)
        out.append(f'<circle cx="{wx:.3f}" cy="{fy(wy):.3f}" r="{wr:.3f}" fill="none" '
                   f'stroke="#a5d8ff" stroke-width="0.15"/>')
        out.append(f'<text x="{wx:.3f}" y="{fy(wy) + 0.8:.3f}" font-family="sans-serif" '
                   f'font-size="2" text-anchor="middle" fill="#adb5bd">{a.name}</text>')
    for b in lay.bolts:
        out.append(f'<circle cx="{b.x:.3f}" cy="{fy(b.y):.3f}" r="{R.bolt_d / 2:.3f}" fill="none" '
                   f'stroke="#495057" stroke-width="0.2"/>')
    for name, nr in model.routing.nets.items():
        col = net_color(name, pal)
        for p in nr.paths:
            for (x0, y0, z0), (x1, y1, z1) in zip(p, p[1:]):
                if abs(x0 - x1) < 1e-9 and abs(y0 - y1) < 1e-9:
                    continue
                k = round((abs(z0) - st.ctrl_z) / st.level_step) if nr.plate == "bottom" else 0
                w, op = (st.d, 0.9) if k == 0 else (st.d + 0.6 * k, 0.45)
                out.append(f'<line x1="{x0:.3f}" y1="{fy(y0):.3f}" x2="{x1:.3f}" y2="{fy(y1):.3f}" '
                           f'stroke="{col}" stroke-width="{w:.2f}" stroke-opacity="{op}" '
                           f'stroke-linecap="round"/>')
        if nr.port:
            sx, sy, _ = nr.port.start
            ex, ey, _ = nr.port.end
            out.append(f'<line x1="{sx:.3f}" y1="{fy(sy):.3f}" x2="{ex:.3f}" y2="{fy(ey):.3f}" '
                       f'stroke="{col}" stroke-width="{st.port_r * 2:.2f}"/>')
            out.append(f'<text x="{sx:.3f}" y="{fy(sy):.3f}" font-family="sans-serif" font-size="2.6" '
                       f'font-weight="bold" fill="{col}">{name}</text>')
    _write(path, _svg(lay, out, f"channels {lay.width:g} x {lay.length:g} mm - thick/pale = deeper - 1:1"))
