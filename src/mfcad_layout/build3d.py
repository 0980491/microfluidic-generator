"""Turn a routed layout into the three plates.

`build_model` describes every cavity as a *feature* -- a pipe, a chamber, a
seat pocket, a needle port, a bolt hole -- tagged with its plate and its net.
The same list feeds two things: `make_plates` cuts it out of three blocks
with manifold3d to make the STL files, and the 3D viewer draws it, so what
you see is what gets printed.

The cell is the printed matrix cell, feature for feature (see `stack.py`):

    middle plate   supply drops into the row valve's first seat; a link on
                   level 1 joins the two valves across the link row; the
                   column valve's outlet runs to a riser under the dome
    bottom plate   one tapered control chamber under each valve, fed at its
                   centre by its line
    top plate      the dome window
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import struct

import numpy as np

from .model import SUPPLY, Layout, resolve_lines
from .route import Routing
from .stack import PROUD, STACK, Stack

PLATES = ("bottom", "middle", "top")


@dataclass
class Feature:
    plate: str
    net: str
    kind: str          # pipe, chamber, pocket, port, hole, nut, window
    data: dict


@dataclass
class Model:
    width: float
    length: float
    thickness: dict                 # plate -> mm
    z0: dict                        # plate -> z of its lower face
    features: list[Feature]
    routing: Routing
    lines: dict                     # actuator -> (row line, col line)
    windows: dict                   # actuator -> (x, y, d)
    bolts: list                     # (x, y)
    stack: Stack = STACK
    report: list[str] = field(default_factory=list)
    actuation: str = "pressure"

    def nets(self, plate):
        return sorted({f.net for f in self.features if f.plate == plate})


# ------------------------------------------------------------------ model
def build_model(lay: Layout, routing: Routing, st: Stack = STACK) -> Model:
    if not routing.ok:
        raise ValueError("the layout is not routed")
    R = lay.rules
    Tb, Tm, Tt = routing.bottom_t, st.middle_t(lay.actuation, R.bowl_depth), st.top_thickness(lay.actuation)
    feats: list[Feature] = []
    lines = resolve_lines(lay)
    windows = {}
    for a in lay.actuators:
        P = a.local
        h = st.col / 2.0
        z1 = st.level1
        mid, out = f"{a.name}.mid", f"{a.name}.out"
        for net, (lx, ly) in ((SUPPLY, (h, 0.0)), (mid, (h, st.seat_gap)),
                              (mid, (-h, st.seat_gap)), (out, (-h, 0.0))):
            feats.append(Feature("middle", net, "pocket", {"at": P(lx, ly)}))
        lk = [(*P(h, st.seat_gap), -PROUD), (*P(h, st.seat_gap), z1),
              (*P(-h, st.seat_gap), z1), (*P(-h, st.seat_gap), -PROUD)]
        feats.append(Feature("middle", mid, "pipe", {"points": lk, "d": st.d, "bend": st.bend}))
        ot = [(*P(-h, 0.0), -PROUD), (*P(-h, 0.0), z1), (*P(0.0, 0.0), z1)]
        feats.append(Feature("middle", out, "pipe", {"points": ot, "d": st.d, "bend": st.bend}))
        feats.append(Feature("middle", out, "pipe", {
            "points": [(a.x, a.y, z1 - 0.2), (a.x, a.y, Tm + PROUD)], "d": st.d, "bend": 0.0}))
        row, col = lines[a.name]
        for net, lx in ((col, -h), (row, h)):
            w, l = (st.chamber_l, st.chamber_w) if a.rotation % 180 == 0 else (st.chamber_w, st.chamber_l)
            feats.append(Feature("bottom", net, "chamber",
                                 {"at": P(lx, st.chamber_dy), "w": w, "l": l, "depth": st.chamber_depth}))
        if lay.actuation == "vacuum":
            # the bowl the membrane is pulled into, on the riser, under the window
            feats.append(Feature("middle", out, "bowl", {"at": (a.x, a.y), "d": R.window_d,
                                                         "depth": R.bowl_depth, "z": Tm}))
        windows[a.name] = (a.x, a.y, R.window_d)
        feats.append(Feature("top", f"{a.name}.window", "window",
                             {"at": (a.x, a.y), "d": R.window_d, "z0": Tm, "z1": Tm + Tt}))
    for name, nr in routing.nets.items():
        for path in nr.paths:
            feats.append(Feature(nr.plate, name, "pipe", {"points": path, "d": st.d, "bend": 0.0,
                                                           "route": True}))
        if nr.port:
            p = nr.port
            feats.append(Feature(nr.plate, name, "port", {
                "start": p.start, "dir": p.direction, "depth": p.depth, "end": p.end,
                "face": p.face}))
    bolts = [(b.x, b.y) for b in lay.bolts]
    z0 = {"bottom": -Tb, "middle": 0.0, "top": Tm}
    th = {"bottom": Tb, "middle": Tm, "top": Tt}
    for i, (x, y) in enumerate(bolts):
        for plate in PLATES:
            feats.append(Feature(plate, f"bolt{i + 1}", "hole", {
                "at": (x, y), "d": R.bolt_d, "z0": z0[plate], "z1": z0[plate] + th[plate]}))
        feats.append(Feature("bottom", f"bolt{i + 1}", "nut", {
            "at": (x, y), "af": R.nut_af, "depth": st.nut_depth, "z": -Tb}))
    m = Model(lay.width, lay.length, th, z0, feats, routing, lines, windows, bolts, st,
              actuation=lay.actuation)
    m.report = _report(lay, m)
    return m


# --------------------------------------------------------------- solids
def _m3():
    try:
        import manifold3d
    except ImportError as e:            # pragma: no cover - shown in the GUI
        raise RuntimeError("3D export needs the manifold3d package: "
                           "pip install manifold3d") from e
    return manifold3d


def _frame(origin, direction):
    z = np.asarray(direction, float)
    z = z / np.linalg.norm(z)
    a = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = np.cross(a, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.column_stack([x, y, z, np.asarray(origin, float)])


def _cyl(m3, a, b, r, seg, r2=None):
    a, b = np.asarray(a, float), np.asarray(b, float)
    h = float(np.linalg.norm(b - a))
    c = m3.Manifold.cylinder(h, r, r if r2 is None else r2, seg)
    return c.transform(_frame(a, b - a))


def _sphere(m3, p, r, seg):
    return m3.Manifold.sphere(r, seg).translate(tuple(float(v) for v in p))


def densify(path, radius: float, n: int = 8):
    """Round each interior corner of a polyline with a tangent arc (as
    mfcad's `pipe` does)."""
    pts = [np.asarray(p, float) for p in path]
    if len(pts) < 3 or radius <= 0:
        return pts
    out = [pts[0]]
    for p0, p1, p2 in zip(pts, pts[1:], pts[2:]):
        v0, v2 = p0 - p1, p2 - p1
        l0, l2 = np.linalg.norm(v0), np.linalg.norm(v2)
        u0, u2 = v0 / l0, v2 / l2
        th = math.acos(float(np.clip(np.dot(u0, u2), -1.0, 1.0)))
        if th < 1e-6 or abs(th - math.pi) < 1e-6:
            out.append(p1)
            continue
        t = min(radius / math.tan(th / 2.0), 0.499 * l0, 0.499 * l2)
        re = t * math.tan(th / 2.0)
        a, b = p1 + u0 * t, p1 + u2 * t
        bis = (u0 + u2) / np.linalg.norm(u0 + u2)
        c = p1 + bis * (re / math.sin(th / 2.0))
        va, vb = a - c, b - c
        ang = math.acos(float(np.clip(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)), -1, 1)))
        axis = np.cross(va, vb)
        axis /= np.linalg.norm(axis)
        for i in range(n + 1):
            f = ang * i / n
            # Rodrigues
            v = va * math.cos(f) + np.cross(axis, va) * math.sin(f) + axis * np.dot(axis, va) * (1 - math.cos(f))
            out.append(c + v)
    out.append(pts[-1])
    return out


def _stadium(w, l, n=32):
    r = min(w, l) / 2.0
    hx, hy = (w / 2.0 - r, 0.0) if w >= l else (0.0, l / 2.0 - r)
    pts = []
    if w >= l:
        for k in range(n + 1):
            a = -math.pi / 2 + math.pi * k / n
            pts.append((hx + r * math.cos(a), r * math.sin(a)))
        for k in range(n + 1):
            a = math.pi / 2 + math.pi * k / n
            pts.append((-hx + r * math.cos(a), r * math.sin(a)))
    else:
        for k in range(n + 1):
            a = math.pi * k / n
            pts.append((r * math.cos(a), hy + r * math.sin(a)))
        for k in range(n + 1):
            a = math.pi + math.pi * k / n
            pts.append((r * math.cos(a), -hy + r * math.sin(a)))
    return pts


def feature_solid(m3, f: Feature, st: Stack = STACK, fine: bool = True):
    seg = 32 if fine else 12
    M = m3.Manifold
    d = f.data
    if f.kind == "pipe":
        r = d["d"] / 2.0
        pts = densify(d["points"], d.get("bend", 0.0), 8 if fine else 3)
        parts = [_cyl(m3, a, b, r, seg) for a, b in zip(pts, pts[1:]) if np.linalg.norm(b - a) > 1e-9]
        joints = pts[1:-1] if not d.get("route") else pts
        parts += [_sphere(m3, p, r, seg) for p in joints]
        return M.batch_boolean(parts, m3.OpType.Add)
    if f.kind == "pocket":
        x, y = d["at"]
        r, dep = st.pocket_d / 2.0, st.relief_depth
        ball = _sphere(m3, (x, y, dep / 2.0), r, 48 if fine else 16)
        slab = M.cube((2 * r + 2, 2 * r + 2, dep + PROUD)).translate((x - r - 1, y - r - 1, -PROUD))
        cone = M.cylinder(r, r, 0.0, 48 if fine else 16).translate((x, y, dep))
        return (ball ^ slab) + cone
    if f.kind == "chamber":
        x, y = d["at"]
        w, l, dep = d["w"], d["l"], d["depth"]
        sw, sl = w - 2 * dep, l - 2 * dep
        if min(sw, sl) <= 0.1:
            sw = sl = 0.1
        top = [(x + u, y + v, 0.02) for u, v in _stadium(w, l)]
        bot = [(x + u, y + v, -dep) for u, v in _stadium(sw, sl)]
        lower = M.hull_points(np.array(top + bot))
        over = M.extrude(m3.CrossSection([[(x + u, y + v) for u, v in _stadium(w, l)]]), PROUD)
        return lower + over
    if f.kind == "port":
        s = np.asarray(d["start"], float)
        u = np.asarray(d["dir"], float)
        dep = d["depth"]
        rb = st.bore_d / 2.0
        slope = (st.port_r - rb) / st.lead_len
        bore = _cyl(m3, s - u * 1.0, s + u * dep, rb, seg)
        funnel = _cyl(m3, s - u * 0.5, s + u * st.lead_len, st.port_r + slope * 0.5, seg, rb)
        neck = _cyl(m3, s + u * (dep - 0.1), s + u * (dep + st.neck_len), st.needle_stop / 2.0, seg)
        a = s + u * (dep + st.neck_len - 0.1)
        e = np.asarray(d["end"], float)
        parts = [bore, funnel, neck]
        if np.dot(e - a, u) > 1e-6:
            parts += [_cyl(m3, a, e, st.r, seg), _sphere(m3, e, st.r, seg)]
        return M.batch_boolean(parts, m3.OpType.Add)
    if f.kind == "bowl":
        # spherical cap: diameter d at the top face z, `depth` deep, plus
        # radial bleed grooves following the surface
        x, y = d["at"]
        a, h, z = d["d"] / 2.0, d["depth"], d["z"]
        R = (a * a + h * h) / (2.0 * h)
        cz = z - h + R
        s48 = 64 if fine else 20
        slab = M.cube((2 * R + 4, 2 * R + 4, h + PROUD + 0.1)).translate((x - R - 2, y - R - 2, z - h - 0.1))
        parts = [_sphere(m3, (x, y, cz), R, s48) ^ slab]
        big = _sphere(m3, (x, y, cz), R + st.bleed_d, s48)
        rim = M.cylinder(h + st.bleed_d + PROUD + 1, a - 0.3, a - 0.3, s48).translate(
            (x, y, z - h - st.bleed_d - 0.5))
        for k in range(st.bleeds):
            ang = 2 * math.pi * k / st.bleeds + math.pi / 2
            bar = M.cube((a, st.bleed_w, h + st.bleed_d + PROUD + 1)).translate(
                (0.0, -st.bleed_w / 2, z - h - st.bleed_d - 0.5))
            bar = bar.rotate((0.0, 0.0, math.degrees(ang))).translate((x, y, 0.0))
            parts.append(big ^ bar ^ rim)
        return M.batch_boolean(parts, m3.OpType.Add)
    if f.kind in ("hole", "window"):
        x, y = d["at"]
        return _cyl(m3, (x, y, d["z0"] - PROUD), (x, y, d["z1"] + PROUD), d["d"] / 2.0,
                    96 if f.kind == "window" and fine else seg)
    if f.kind == "nut":
        x, y = d["at"]
        cr = d["af"] / math.sqrt(3.0)
        hexa = [(x + cr * math.cos(math.radians(30 + 60 * k)),
                 y + cr * math.sin(math.radians(30 + 60 * k))) for k in range(6)]
        return M.extrude(m3.CrossSection([hexa]), d["depth"] + PROUD).translate((0, 0, d["z"] - PROUD))
    raise ValueError(f.kind)


def _key(m3, W, L, c, z0, t):
    tri = [(-1.0, L - c - 1.0), (c + 1.0, L + 1.0), (-1.0, L + 1.0)]
    return m3.Manifold.extrude(m3.CrossSection([tri]), t + 2.0).translate((0, 0, z0 - 1.0))


def make_plates(model: Model, progress=None, check=True):
    """The three plates as manifold3d solids, in the assembly frame, and a
    list of problems found by the checks (empty when all is well)."""
    say = progress or (lambda s: None)
    m3 = _m3()
    st = model.stack
    W, L = model.width, model.length
    plates, problems = {}, []
    for plate in PLATES:
        say(f"Cutting the {plate} plate…")
        by_net: dict[str, list] = {}
        for f in model.features:
            if f.plate == plate:
                by_net.setdefault(f.net, []).append(feature_solid(m3, f, st))
        nets = {n: m3.Manifold.batch_boolean(v, m3.OpType.Add) for n, v in by_net.items()}
        z0, t = model.z0[plate], model.thickness[plate]
        block = m3.Manifold.cube((W, L, t)).translate((0.0, 0.0, z0))
        cuts = m3.Manifold.batch_boolean(list(nets.values()), m3.OpType.Add)
        body = block - cuts - _key(m3, W, L, st.corner_key, z0, t)
        plates[plate] = body
        if check:
            say(f"Checking the {plate} plate…")
            problems += _check_plate(m3, plate, nets, cuts, block)
    return plates, problems


def _check_plate(m3, plate, nets, cuts, block):
    """Every net is its own sealed cavity, and no two are thinner apart than
    the cell's own proven walls."""
    out = []
    inside = cuts ^ block
    found = len(inside.decompose())
    # a net may legitimately be cut in two by the plate faces? No: every net
    # is one connected cavity, so the count must match.
    if found != len(nets):
        out.append(f"{plate} plate: the cavities form {found} separate volumes, expected "
                   f"{len(nets)} -- two nets touch. Do not print this.")
    names = list(nets)
    boxes = {n: nets[n].bounding_box() for n in names}
    worst = (math.inf, None, None)
    for i, a in enumerate(names):
        ba = boxes[a]
        for b in names[i + 1:]:
            bb = boxes[b]
            if (ba[0] > bb[3] + 1.5 or bb[0] > ba[3] + 1.5 or ba[1] > bb[4] + 1.5
                    or bb[1] > ba[4] + 1.5 or ba[2] > bb[5] + 1.5 or bb[2] > ba[5] + 1.5):
                continue
            if a.startswith("bolt") and b.startswith("bolt"):
                continue
            g = (nets[a] ^ block).min_gap(nets[b] ^ block, 1.5)
            if g < worst[0]:
                worst = (g, a, b)
            if g < 0.65:
                out.append(f"{plate} plate: only {g:.2f} mm between {a} and {b}")
    _check_plate.last_worst[plate] = worst
    return out


_check_plate.last_worst = {}


# ----------------------------------------------------------------- export
def print_pose(plate: str, solid, model: Model):
    """Contact face down, by rotation or translation only (never mirrored):
    the bottom plate turns over so its chambers face the bed; the middle
    plate already has its seat face at z = 0; the top plate drops to z = 0."""
    if plate == "bottom":
        rot = np.array([[1.0, 0, 0, 0], [0, -1.0, 0, model.length], [0, 0, -1.0, 0]])
        return solid.transform(rot)
    if plate == "top":
        return solid.translate((0.0, 0.0, -model.z0["top"]))
    return solid


def write_stl(solid, path) -> int:
    mesh = solid.to_mesh()
    v = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    t = np.asarray(mesh.tri_verts, dtype=np.int64)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1.0
    n /= ln[:, None]
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3),
                                  ("c", "<f4", 3), ("attr", "<u2")])
    rec["n"], rec["a"], rec["b"], rec["c"] = n, a, b, c
    with open(path, "wb") as fh:
        fh.write(b"mfcad-layout".ljust(80, b" "))
        fh.write(struct.pack("<I", len(t)))
        fh.write(rec.tobytes())
    return len(t)


def export(lay: Layout, model: Model, folder, stem: str = "layout", progress=None):
    """Write the three STLs (print orientation), the membrane template, the
    routing drawing and a README. Returns (written paths, problems)."""
    from . import svgexport
    say = progress or (lambda s: None)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    plates, problems = make_plates(model, progress)
    written = []
    for plate in PLATES:
        p = folder / f"{stem}_{plate}.stl"
        say(f"Writing {p.name}…")
        write_stl(print_pose(plate, plates[plate], model), p)
        written.append(p)
    p = folder / f"{stem}_membrane.svg"
    svgexport.membrane(lay, p)
    written.append(p)
    p = folder / f"{stem}_channels.svg"
    svgexport.channels(lay, model, p)
    written.append(p)
    p = folder / f"{stem}_README.txt"
    text = list(model.report)
    if problems:
        text += ["", "PROBLEMS FOUND BY THE CHECKS -- do not print until fixed:"]
        text += [f"  ! {q}" for q in problems]
    else:
        text += ["", "Checks: every net is a separate sealed cavity; thinnest wall between "
                     "two nets " + ", ".join(f"{k} {v[0]:.2f} mm" for k, v in
                                             _check_plate.last_worst.items() if v[1]) + "."]
    p.write_text("\n".join(text) + "\n", encoding="utf-8")
    written.append(p)
    return written, problems


def _report(lay: Layout, m: Model) -> list[str]:
    st = m.stack
    r = m.routing
    T = m.thickness
    stack_t = T["bottom"] + T["middle"] + T["top"]
    out = [
        "mfcad Layout -- 3D export",
        "=" * 25,
        f"Plate {m.width:g} x {m.length:g} mm. Thickness: bottom {T['bottom']:g}, "
        f"middle {T['middle']:g}, top {T['top']:g} mm (stack {stack_t:g} mm plus two membranes).",
        f"{len(lay.actuators)} actuators, {len(lay.bolts)} M3 bolts, "
        f"{len([n for n in r.nets if n != SUPPLY])} control lines on {r.levels} level(s).",
        "",
        "Printing: every STL is already contact face down. Bottom: chambers face the bed. "
        "Middle: valve seats face the bed. Top: membrane side faces the bed.",
        "Assembly, from the bottom up: bottom plate (nuts in the hex pockets), membrane 1, "
        "middle plate, membrane 2, top plate. The chamfered corner goes on the same corner "
        "of every plate. Cut both membranes from the membrane template.",
        "",
        *_how_it_works(lay, m),
        "",
        "Inlets (needle ports; positions from the plate's bottom-left corner, seen from the top):",
    ]
    for name, nr in r.nets.items():
        p = nr.port
        if not p:
            continue
        what = "supply" if name == SUPPLY else "line"
        coord = f"x = {p.start[0]:.2f}" if p.face in ("front", "back") else f"y = {p.start[1]:.2f}"
        out.append(f"  {name:<6} {what:<6} {nr.plate:<6} plate, {p.face:<5} face at {coord} mm, "
                   f"{abs(p.start[2]):.2f} mm {'below membrane 1' if nr.plate == 'bottom' else 'above membrane 1'}; "
                   f"needle bore {p.depth:g} mm")
    verb = "opens" if m.actuation == "vacuum" else "closes"
    out += ["", f"Lines (actuator: which valve it {verb}):"]
    for name, nr in r.nets.items():
        if name == SUPPLY:
            continue
        mem = ", ".join(f"{a} ({'supply side' if w == 'row' else 'dome side'})" for a, w in nr.members)
        out.append(f"  {name:<6} {mem}")
    return out


def _how_it_works(lay: Layout, m: Model) -> list[str]:
    if m.actuation != "vacuum":
        return ["Actuation: POSITIVE PRESSURE. Every actuator is two normally-open valves in series "
                "between the supply and its dome. Pressurising a line closes the valve it feeds. With "
                "the supply on, an actuator inflates only while BOTH of its lines are vented."]
    return [
        f"Actuation: NEGATIVE PRESSURE (vacuum). Under every window the middle plate has a "
        f"{lay.rules.bowl_depth:g} mm deep bowl; vacuum on the actuator pulls membrane 2 down into it, "
        f"so the travel is set by the bowl and the membrane cannot burst. Nothing pushes on the top plate, "
        f"so it is a thin {m.thickness['top']:g} mm sheet that only clamps the membrane (use washers "
        f"under the bolt heads).",
        "The valves work the other way round under vacuum: the vacuum in the channel pulls the valve "
        "membrane onto its seat, so a valve is CLOSED while its line is vented, and OPENS when its line "
        "has a STRONGER vacuum than the supply.",
        "So run two vacuum levels: the supply at a weaker vacuum (a bleed or regulator off the pump) and "
        "the lines at full vacuum. An actuator is pulled in only while BOTH of its lines are under "
        "vacuum. To release the actuators, vent the supply to air with the lines still under vacuum.",
        "The same plates also work with positive pressure (the membrane then inflates through the "
        "window as usual). The vacuum logic is reasoned from the valve design and not yet tested on a "
        "printed part: try it on a small matrix first.",
    ]
