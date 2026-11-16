"""Route the control lines and the supply between freely placed actuators.

The matrices had their channels drawn by hand. Here the actuators can be
anywhere, so the channels are found by a maze router:

* Bottom plate: one net per control line (R1, C2, ...). Every chamber on the
  line gets a drop at its centre, the drops are joined into a tree, and the
  tree is joined to a needle inlet on a side face. Lines run on control
  levels below the chambers (level 0 passes under other chambers with a floor
  between, level 1 under level 0, ...), so two lines cross by taking
  different levels, as the rows and columns of the 3x3 do.
* Middle plate: the supply, on its own level above the valve channels,
  dropping into every actuator's first seat and avoiding every dome riser.

The grid is rectilinear with lines at 0.5 mm plus every coordinate that
matters (feeds, risers, bolt clearances), so a straight run through a gap that
is exactly wide enough is found. Clearances are the printed ones: a side wall
of 1.2 mm between channels of different nets, between a channel and a bolt
hole, and around the needle ports, which are wider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math

import numpy as np

from .model import SUPPLY, Layout, line_members, resolve_lines
from .stack import PROUD, STACK, Stack

EPS = 1e-3           # mm: rounding, not a clearance
FACE_DIR = {"left": (1.0, 0.0), "right": (-1.0, 0.0), "front": (0.0, 1.0), "back": (0.0, -1.0)}
TURN = 1.0           # mm of extra cost per bend: straight runs win ties
VIA = 2.0            # extra cost of changing level
MAX_LEVELS = 3


@dataclass
class Port:
    net: str
    plate: str
    face: str
    start: tuple[float, float, float]      # on the face
    direction: tuple[float, float, float]  # into the plate
    depth: float                           # needle bore
    end: tuple[float, float, float]        # where the channel carries on

    @property
    def along(self) -> float:
        """Position along its face, from the face's left end seen from
        outside... kept simple: x for front/back faces, y for left/right."""
        return self.start[0] if self.face in ("front", "back") else self.start[1]


@dataclass
class NetRoute:
    name: str
    plate: str                                   # 'bottom' or 'middle'
    members: list[tuple[str, str]]               # (actuator, 'row'/'col'/'supply')
    paths: list[list[tuple[float, float, float]]] = field(default_factory=list)
    port: Port | None = None
    levels: set[int] = field(default_factory=set)
    length: float = 0.0


@dataclass
class Routing:
    ok: bool
    levels: int = 0
    bottom_t: float = 0.0
    nets: dict[str, NetRoute] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class RouteError(Exception):
    pass


# ----------------------------------------------------------------- geometry
def _seg_dist(X, Y, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    ll = dx * dx + dy * dy
    if ll < 1e-12:
        return np.hypot(X - x0, Y - y0)
    t = np.clip(((X - x0) * dx + (Y - y0) * dy) / ll, 0.0, 1.0)
    return np.hypot(X - (x0 + t * dx), Y - (y0 + t * dy))


def _axis(length: float, must, step: float) -> np.ndarray:
    must = sorted({round(m, 4) for m in must if -1e-9 <= m <= length + 1e-9})
    out = set(must)
    k = 0
    while k * step <= length + 1e-9:
        v = round(k * step, 4)
        i = np.searchsorted(must, v) if must else 0
        near = [must[j] for j in (i - 1, i) if 0 <= j < len(must)]
        if all(abs(v - m) > 0.12 for m in near):
            out.add(v)
        k += 1
    out.add(round(length, 4))
    return np.array(sorted(out))


class _Plane:
    """One plate's routing grid: `nl` levels of an nx x ny rectilinear grid."""

    def __init__(self, lay: Layout, st: Stack, nl: int, must_x, must_y):
        self.lay, self.st, self.nl = lay, st, nl
        self.W, self.L = lay.width, lay.length
        self.xs = _axis(self.W, must_x, 0.5)
        self.ys = _axis(self.L, must_y, 0.5)
        self.nx, self.ny = len(self.xs), len(self.ys)
        self.X, self.Y = np.meshgrid(self.xs, self.ys, indexing="ij")
        self.n = nl * self.nx * self.ny

    def node(self, k, i, j):
        return (k * self.nx + i) * self.ny + j

    def kij(self, nid):
        k, rem = divmod(nid, self.nx * self.ny)
        i, j = divmod(rem, self.ny)
        return k, i, j

    def ix(self, x):
        i = int(np.argmin(np.abs(self.xs - x)))
        if abs(self.xs[i] - x) > 1e-3:
            raise RouteError(f"x={x} is not on the grid")
        return i

    def iy(self, y):
        j = int(np.argmin(np.abs(self.ys - y)))
        if abs(self.ys[j] - y) > 1e-3:
            raise RouteError(f"y={y} is not on the grid")
        return j

    def edge_room(self, skip_face=None):
        """Distance from each node to the nearest side face (and the corner
        key chamfer), leaving out `skip_face`."""
        d = [np.full((self.nx, self.ny), np.inf)]
        if skip_face != "left":
            d.append(self.X)
        if skip_face != "right":
            d.append(self.W - self.X)
        if skip_face != "front":
            d.append(self.Y)
        if skip_face != "back":
            d.append(self.L - self.Y)
        d.append((self.X + (self.L - self.Y) - self.st.corner_key) / math.sqrt(2.0))
        return np.minimum.reduce(d)

    # -- search --------------------------------------------------------
    def astar(self, free: list, sources, targets, h: list):
        """Cheapest path from any source node to any target node over free
        nodes. `free` and `h` are flat lists over nodes. Returns node ids."""
        nx, ny, nl = self.nx, self.ny, self.nl
        xs, ys = self.xs.tolist(), self.ys.tolist()
        nxy = nx * ny
        INF = float("inf")
        g = {}
        parent = {}
        heap = []
        for s in sources:
            sid = s * 6 + 5
            g[sid] = 0.0
            parent[sid] = None
            heapq.heappush(heap, (h[s], 0.0, sid))
        targets = set(targets)
        while heap:
            f, gc, sid = heapq.heappop(heap)
            if gc > g.get(sid, INF) + 1e-12:
                continue
            nid, d = divmod(sid, 6)
            if nid in targets:
                out = []
                while sid is not None:
                    out.append(sid // 6)
                    sid = parent[sid]
                out.reverse()
                return [n for i, n in enumerate(out) if i == 0 or n != out[i - 1]]
            k, rem = divmod(nid, nxy)
            i, j = divmod(rem, ny)
            for nd in range(5):
                if nd == 0:
                    if i + 1 >= nx:
                        continue
                    m, cost = nid + ny, xs[i + 1] - xs[i]
                elif nd == 1:
                    if i == 0:
                        continue
                    m, cost = nid - ny, xs[i] - xs[i - 1]
                elif nd == 2:
                    if j + 1 >= ny:
                        continue
                    m, cost = nid + 1, ys[j + 1] - ys[j]
                elif nd == 3:
                    if j == 0:
                        continue
                    m, cost = nid - 1, ys[j] - ys[j - 1]
                else:
                    # change level: one step down or up
                    for m in (nid + nxy, nid - nxy):
                        if 0 <= m < nl * nxy and free[m]:
                            ng = gc + self.st.level_step + VIA
                            mid = m * 6 + 4
                            if ng < g.get(mid, INF) - 1e-12:
                                g[mid] = ng
                                parent[mid] = sid
                                heapq.heappush(heap, (ng + h[m], ng, mid))
                    continue
                if not free[m]:
                    continue
                ng = gc + cost + (TURN if d < 4 and d != nd else 0.0)
                mid = m * 6 + nd
                if ng < g.get(mid, INF) - 1e-12:
                    g[mid] = ng
                    parent[mid] = sid
                    heapq.heappush(heap, (ng + h[m], ng, mid))
        return None

    def heuristic(self, target_nodes) -> list:
        ks, iis, jjs = zip(*(self.kij(t) for t in target_nodes))
        tx = self.xs[list(iis)]
        ty = self.ys[list(jjs)]
        tk = np.array(ks)
        best = np.full((self.nl, self.nx, self.ny), np.inf)
        K = np.arange(self.nl)[:, None, None]
        for x, y, k in zip(tx, ty, tk):
            dxy = np.abs(self.X - x) + np.abs(self.Y - y)
            best = np.minimum(best, dxy[None, :, :] + np.abs(K - k) * (self.st.level_step + VIA))
        return best.ravel().tolist()


# ------------------------------------------------------------------ router
class _NetState:
    def __init__(self, name, plate, members, terminals, face, depth):
        self.name, self.plate, self.members = name, plate, members
        self.terminals = terminals          # [(x, y)]
        self.face, self.depth = face, depth
        self.route: NetRoute | None = None


def _corridor_len(st: Stack, depth: float) -> float:
    return depth + st.neck_len


class _PlateRouter:
    """Routes the nets of one plate on `nl` levels."""

    def __init__(self, lay, st, plate, nets, nl, levels_z, static, bottom_t):
        self.lay, self.st, self.plate, self.nl = lay, st, plate, nl
        self.nets = nets
        self.levels_z = levels_z            # z of each level (world)
        self.static = static                # [(x, y, radius, nut_radius_or_None)]
        self.bottom_t = bottom_t
        must_x, must_y = set(), set()
        r, pr = st.r, st.port_r
        for n in nets:
            for x, y in n.terminals:
                must_x.add(x)
                must_y.add(y)
            c = _corridor_len(st, n.depth)
            must_x |= {c, lay.width - c}
            must_y |= {c, lay.length - c}
        for x, y, rad, nut in static:
            for rs in (r, pr):
                for rr in (rad, nut or rad):
                    q = rr + st.wall + rs
                    must_x |= {x - q, x + q}
                    must_y |= {y - q, y + q}
        for rs in (r, pr):
            q = rs + st.edge_wall
            must_x |= {q, lay.width - q}
            must_y |= {q, lay.length - q}
        self.p = _Plane(lay, st, nl, must_x, must_y)
        p = self.p
        # every net's clearance field: distance to its geometry minus the
        # geometry's radius, per level. Feeds are reserved from the start.
        self.field = {}
        for n in nets:
            f = [np.full((p.nx, p.ny), np.inf) for _ in range(nl)]
            for x, y in n.terminals:
                f[0] = np.minimum(f[0], np.hypot(p.X - x, p.Y - y) - r)
            self.field[n.name] = f
        # static room per level: how big a channel may be at each node before
        # it comes within a wall of a bolt (or its nut), a riser, or an edge
        self._static = {}
        for rs in (r, pr):
            per = []
            for k in range(nl):
                room = np.full((p.nx, p.ny), np.inf)
                for x, y, rad, nut in static:
                    rr = nut if (nut and self._nut(k, rs)) else rad
                    room = np.minimum(room, np.hypot(p.X - x, p.Y - y) - rr - st.wall)
                per.append(room)
            self._static[rs] = per

    def _nut(self, k, rs):
        if self.plate != "bottom":
            return False
        return self.st.nut_level(k, self.nl, rs)

    def _room(self, net, rs, skip_face=None):
        """Per level: the largest channel radius each node can take for
        `net`, given everything already there. `rs` picks which levels count
        as reaching the nut pockets."""
        st, p = self.st, self.p
        edge = p.edge_room(skip_face) - st.edge_wall
        out = []
        for k in range(self.nl):
            room = np.minimum(self._static[rs][k], edge)
            for m, f in self.field.items():
                if m != net:
                    room = np.minimum(room, f[k] - st.wall)
            out.append(room)
        return out

    def route(self, n: _NetState) -> NetRoute:
        st, p = self.st, self.p
        room = self._room(n.name, st.r)
        free = (np.stack(room) >= st.r - EPS).ravel().tolist()
        tnodes = [p.node(0, p.ix(x), p.iy(y)) for x, y in n.terminals]
        for (x, y), t in zip(n.terminals, tnodes):
            if not free[t]:
                raise RouteError(f"{n.name}: the feed at ({x:.2f}, {y:.2f}) has no room "
                                 f"(too close to a bolt or another line)")
        tree = {tnodes[0]}
        paths = []
        remaining = set(tnodes[1:])
        while remaining - tree:
            remaining -= tree
            path = p.astar(free, tree, remaining, p.heuristic(remaining))
            if path is None:
                raise RouteError(f"{n.name}: no room to join all its actuators")
            paths.append(path)
            tree |= set(path)
        port = None
        if n.face is not None:
            port, path = self._port(n, tree, free)
            paths.append(path)
        return self._to_route(n, tnodes, paths, port)

    def _port(self, n, tree, free):
        st, p = self.st, self.p
        faces = [n.face] if n.face != "auto" else ["left", "right", "front", "back"]
        clen = _corridor_len(st, n.depth)
        # radius of the bore at each distance from the face: the funnel
        # narrows from the mouth to the bore over lead_len
        slope = (st.port_r - st.r) / st.lead_len
        cands = {}
        for face in faces:
            proom = self._room(n.name, st.port_r, skip_face=face)
            for k in range(self.nl):
                if self.plate == "bottom" and st.level_z(k) + st.port_r + st.floor > self.bottom_t + 1e-9:
                    continue
                pr_ = proom[k]
                if face in ("left", "right"):
                    x_in = clen if face == "left" else self.lay.width - clen
                    ie = p.ix(x_in)
                    x_face = 0.0 if face == "left" else self.lay.width
                    need = np.maximum(st.r, st.port_r - slope * np.abs(p.xs - x_face))
                    span = slice(0, ie + 1) if face == "left" else slice(ie, p.nx)
                    ok = np.all(pr_[span, :] >= need[span, None] - EPS, axis=0)
                    for j in np.nonzero(ok)[0]:
                        cands[p.node(k, ie, int(j))] = (face, k, (x_face, float(p.ys[j])))
                else:
                    y_in = clen if face == "front" else self.lay.length - clen
                    je = p.iy(y_in)
                    y_face = 0.0 if face == "front" else self.lay.length
                    need = np.maximum(st.r, st.port_r - slope * np.abs(p.ys - y_face))
                    span = slice(0, je + 1) if face == "front" else slice(je, p.ny)
                    ok = np.all(pr_[:, span] >= need[None, span] - EPS, axis=1)
                    for i in np.nonzero(ok)[0]:
                        cands[p.node(k, int(i), je)] = (face, k, (float(p.xs[i]), y_face))
        cands = {c: v for c, v in cands.items() if free[c]}
        if not cands:
            where = n.face if n.face != "auto" else "any face"
            raise RouteError(f"{n.name}: no straight run free for its needle inlet on {where}")
        path = p.astar(free, tree, set(cands), p.heuristic(list(cands)))
        if path is None:
            where = n.face if n.face != "auto" else "any face"
            raise RouteError(f"{n.name}: can't reach an inlet on {where}")
        face, k, (sx, sy) = cands[path[-1]]
        z = self.levels_z[k]
        dx, dy = FACE_DIR[face]
        _, i, j = p.kij(path[-1])
        port = Port(n.name, self.plate, face, (sx, sy, z), (dx, dy, 0.0), n.depth,
                    (float(p.xs[i]), float(p.ys[j]), z))
        return port, path

    def _to_route(self, n, tnodes, paths, port) -> NetRoute:
        st, p = self.st, self.p
        rt = NetRoute(n.name, self.plate, n.members)
        f = [np.full((p.nx, p.ny), np.inf) for _ in range(self.nl)]
        r = st.r
        for path in paths:
            pts = [p.kij(nid) for nid in path]
            # keep the corners only
            keep = [pts[0]]
            for a, b, c in zip(pts, pts[1:], pts[2:]):
                d1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
                d2 = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
                if d1 != d2:
                    keep.append(b)
            if len(pts) > 1:
                keep.append(pts[-1])
            world = [(float(p.xs[i]), float(p.ys[j]), self.levels_z[k]) for k, i, j in keep]
            rt.paths.append(world)
            for (k0, i0, j0), (k1, i1, j1) in zip(keep, keep[1:]):
                x0, y0, x1, y1 = p.xs[i0], p.ys[j0], p.xs[i1], p.ys[j1]
                for k in range(min(k0, k1), max(k0, k1) + 1):
                    f[k] = np.minimum(f[k], _seg_dist(p.X, p.Y, x0, y0, x1, y1) - r)
                rt.length += math.hypot(x1 - x0, y1 - y0) + abs(self.levels_z[k1] - self.levels_z[k0])
            rt.levels |= {k for k, _, _ in pts}
        # the drops into the chambers (or seats) above level 0
        z_face = PROUD if self.plate == "bottom" else -PROUD
        for t in tnodes:
            k, i, j = p.kij(t)
            x, y = float(p.xs[i]), float(p.ys[j])
            rt.paths.append([(x, y, z_face), (x, y, self.levels_z[0])])
            f[0] = np.minimum(f[0], np.hypot(p.X - x, p.Y - y) - r)
        if port:
            kk = self.levels_z.index(port.start[2])
            sx, sy, _ = port.start
            ex, ey, _ = port.end
            dx, dy, _ = port.direction
            mx, my = sx + dx * (st.lead_len + 0.5), sy + dy * (st.lead_len + 0.5)
            f[kk] = np.minimum.reduce([f[kk], _seg_dist(p.X, p.Y, sx, sy, ex, ey) - r,
                                       _seg_dist(p.X, p.Y, sx, sy, mx, my) - st.port_r])
            # the funnel mouth is wider than a channel, so it also keeps the
            # levels above and below out of its first few millimetres
            for k in (kk - 1, kk + 1):
                if 0 <= k < self.nl:
                    f[k] = np.minimum(f[k], _seg_dist(p.X, p.Y, sx, sy, mx, my) - r)
            rt.port = port
        self.field[n.name] = f
        n.route = rt
        return rt

    def run(self, order):
        for n in order:
            self.route(n)


# ------------------------------------------------------------------- entry
def _nets(lay: Layout, st: Stack):
    """The bottom-plate line nets and the middle-plate supply net."""
    acts = {a.name: a for a in lay.actuators}
    lines = []
    for name, members in line_members(lay).items():
        pts = []
        for an, which in members:
            col_feed, row_feed = acts[an].feeds()
            pts.append(row_feed if which == "row" else col_feed)
        lines.append(_NetState(name, "bottom", members, pts,
                               lay.faces.get(name, "auto"), lay.rules.needle_depth))
    sup = _NetState(SUPPLY, "middle", [(a.name, "supply") for a in lay.actuators],
                    [a.local(st.col / 2.0, 0.0) for a in lay.actuators],
                    lay.faces.get(SUPPLY, "front"), lay.rules.supply_depth)
    return lines, sup


def route_layout(lay: Layout, st: Stack = STACK, progress=None) -> Routing:
    """Route every line and the supply. `progress(text)` is called as it goes."""
    say = progress or (lambda s: None)
    out = Routing(ok=False)
    if not lay.actuators:
        out.problems.append("There are no actuators to connect.")
        return out
    R = lay.rules
    nut_r = R.nut_af / math.sqrt(3.0)
    bolts = [(b.x, b.y, R.bolt_d / 2.0, nut_r) for b in lay.bolts]
    lines, sup = _nets(lay, st)

    # ---- middle plate: the supply, avoiding every riser and bolt ----
    say("Routing the supply…")
    risers = [(a.x, a.y, st.r, None) for a in lay.actuators]
    mid = _PlateRouter(lay, st, "middle", [sup], 1, [st.level2],
                       [(x, y, rad, None) for x, y, rad, _ in bolts] + risers, 0.0)
    try:
        mid.run([sup])
    except RouteError as e:
        out.problems.append(str(e))
        return out
    out.nets[SUPPLY] = sup.route

    # ---- bottom plate: the lines, on as few levels as will do ----
    last = None
    for nl in range(1, MAX_LEVELS + 1):
        Tb = st.bottom_t(nl)
        zs = [-st.level_z(k) for k in range(nl)]
        order = sorted(lines, key=lambda n: (-len(n.terminals), n.name))
        for attempt in range(len(lines) + 1):
            say(f"Routing {len(lines)} lines on {nl} level{'s' if nl > 1 else ''}"
                + (f" (try {attempt + 1})" if attempt else "") + "…")
            pr = _PlateRouter(lay, st, "bottom", lines, nl, zs, bolts, Tb)
            failed = None
            for n in order:
                try:
                    pr.route(n)
                except RouteError as e:
                    failed, last = n, str(e)
                    break
            if failed is None:
                out.ok = True
                out.levels = nl
                out.bottom_t = Tb
                for n in lines:
                    out.nets[n.name] = n.route
                out.nets = dict(sorted(out.nets.items(), key=lambda kv: kv[0] != SUPPLY))
                out.notes.append(f"{len(lines)} control lines on {nl} level(s); "
                                 f"bottom plate {Tb:g} mm")
                return out
            if order[0] is failed:
                break
            order.remove(failed)
            order.insert(0, failed)
    out.problems.append(last or "Could not route the lines.")
    return out
