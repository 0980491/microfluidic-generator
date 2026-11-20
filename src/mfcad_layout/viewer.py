"""A 3D view of the generated plates, drawn with plain Tk.

It draws the same features the STL files are cut from (`build3d.Feature`),
one colour per net, so the logic inside the plates can be followed: which
line feeds which chamber, where the supply runs, where every inlet comes out.

* X-ray (default): the plates are glass. Every channel, chamber, seat and
  window is drawn inside them.
* Solid: the plates as they come off the printer, holes and inlets showing.

Drag to orbit, right or middle drag to pan, wheel to zoom. Explode pulls the
plates apart. Click a line in the list to pick it out.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

import numpy as np

from . import theme
from .build3d import PLATES, Model, densify
from .colors import mix, net_color, palette
from .model import SUPPLY

BG = "#f3f5f8"
PLATE_TINT = {"bottom": "#dbe4ff", "middle": "#d3f9d8", "top": "#ffe8cc"}
PLATE_EDGE = {"bottom": "#4c6ef5", "middle": "#2f9e44", "top": "#e8590c"}
MEMBRANE = "#f06595"
LIGHT = np.array([-0.35, 0.55, 0.76])
LIGHT /= np.linalg.norm(LIGHT)


def _circle(c, r, normal, n=14):
    c = np.asarray(c, float)
    z = np.asarray(normal, float)
    z /= np.linalg.norm(z)
    a = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(a, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return [c + r * (math.cos(t) * x + math.sin(t) * y)
            for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]


def _stadium2d(w, l, n=6):
    r = min(w, l) / 2.0
    pts = []
    if w >= l:
        hx = w / 2.0 - r
        for k in range(n + 1):
            a = -math.pi / 2 + math.pi * k / n
            pts.append((hx + r * math.cos(a), r * math.sin(a)))
        for k in range(n + 1):
            a = math.pi / 2 + math.pi * k / n
            pts.append((-hx + r * math.cos(a), r * math.sin(a)))
    else:
        hy = l / 2.0 - r
        for k in range(n + 1):
            a = math.pi * k / n
            pts.append((r * math.cos(a), hy + r * math.sin(a)))
        for k in range(n + 1):
            a = math.pi + math.pi * k / n
            pts.append((r * math.cos(a), -hy + r * math.sin(a)))
    return pts


class Viewer3D:
    def __init__(self, parent, model: Model, title="3D view", on_export=None):
        self.m = model
        self.on_export = on_export
        self.pal = palette(model.routing.nets)
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.geometry("1180x760")
        self.top.minsize(760, 480)
        self.top.configure(bg=theme.BG)

        self.yaw, self.pitch = -32.0, 38.0
        self.scale = 8.0
        self.pan = [0.0, 0.0]
        self.explode = tk.DoubleVar(value=8.0)
        self.mode = tk.StringVar(value="xray")
        self.show = {p: tk.BooleanVar(value=True) for p in PLATES}
        self.show_membranes = tk.BooleanVar(value=True)
        self.show_bolts = tk.BooleanVar(value=True)
        self.show_names = tk.BooleanVar(value=True)
        self.focus: str | None = None
        self._pending = False
        self._drag = None

        self._prepare()
        self._ui()
        self.top.after(30, self.fit)

    # ------------------------------------------------------------ geometry
    def _prepare(self):
        """Turn features into drawable primitives in the assembly frame."""
        m, st = self.m, self.m.stack
        self.tubes = []        # (plate, net, a, b, r)
        self.polys = []        # (plate, net, [pts], kind)
        self.labels = []       # (plate, net, point, text)
        self.bolt_axes = []    # (plate, net, (x, y), r)
        for f in m.features:
            d = f.data
            if f.kind == "pipe":
                pts = densify(d["points"], d.get("bend", 0.0), 3)
                for a, b in zip(pts, pts[1:]):
                    self._tube(f.plate, f.net, a, b, d["d"] / 2.0)
            elif f.kind == "port":
                s, u = np.asarray(d["start"], float), np.asarray(d["dir"], float)
                dep = d["depth"]
                self._tube(f.plate, f.net, s, s + u * st.lead_len, st.port_r, split=False)
                self._tube(f.plate, f.net, s + u * st.lead_len, s + u * dep, st.bore_d / 2.0)
                self._tube(f.plate, f.net, s + u * dep, s + u * (dep + st.neck_len), st.needle_stop / 2.0)
                self._tube(f.plate, f.net, s + u * (dep + st.neck_len), np.asarray(d["end"], float), st.r)
                self.polys.append((f.plate, f.net, _circle(s, st.port_r, u), "mouth"))
                self.labels.append((f.plate, f.net, s - u * 2.2, f.net, -u))
            elif f.kind == "chamber":
                x, y = d["at"]
                big = [(x + u, y + v, 0.0) for u, v in _stadium2d(d["w"], d["l"])]
                small = [(x + u, y + v, -d["depth"]) for u, v in
                         _stadium2d(max(d["w"] - 2 * d["depth"], 0.2), max(d["l"] - 2 * d["depth"], 0.2))]
                self.polys.append((f.plate, f.net, small[::-1], "solid"))
                for i in range(len(big)):
                    j = (i + 1) % len(big)
                    self.polys.append((f.plate, f.net, [big[i], big[j], small[j], small[i]], "solid"))
                self.polys.append((f.plate, f.net, big, "cap"))
            elif f.kind == "pocket":
                x, y = d["at"]
                self.polys.append((f.plate, f.net, _circle((x, y, 0.02), st.pocket_d / 2.0, (0, 0, -1), 10),
                                   "solid"))
            elif f.kind == "window":
                x, y = d["at"]
                r = d["d"] / 2.0
                self.polys.append((f.plate, f.net, _circle((x, y, d["z0"]), r, (0, 0, -1), 24), "window"))
                self.polys.append((f.plate, f.net, _circle((x, y, d["z1"]), r, (0, 0, 1), 24), "ring"))
            elif f.kind == "bowl":
                x, y = d["at"]
                a, h, z = d["d"] / 2.0, d["depth"], d["z"]
                R = (a * a + h * h) / (2.0 * h)
                for frac in (1.0, 0.7, 0.4):           # rings down the bowl
                    rr = a * frac
                    zz = z - h + R - math.sqrt(max(R * R - rr * rr, 0.0))
                    self.polys.append((f.plate, f.net, _circle((x, y, zz), rr, (0, 0, 1), 24), "ring"))
            elif f.kind == "hole":
                x, y = d["at"]
                for z in (d["z0"], d["z1"]):
                    self.polys.append((f.plate, f.net, _circle((x, y, z), d["d"] / 2.0, (0, 0, 1), 16), "bolt"))
                self.bolt_axes.append((f.plate, f.net, (x, y), d["d"] / 2.0))
            elif f.kind == "nut":
                x, y = d["at"]
                cr = d["af"] / math.sqrt(3.0)
                hexa = [(x + cr * math.cos(math.radians(30 + 60 * k)),
                         y + cr * math.sin(math.radians(30 + 60 * k)), d["z"]) for k in range(6)]
                self.polys.append((f.plate, f.net, hexa, "nut"))
        for name, (x, y, _) in m.windows.items():
            self.labels.append(("top", name + ".window", (x, y, m.z0["top"] + m.thickness["top"] + 0.4), name,
                                np.array([0.0, 0.0, 1.0])))

    def _tube(self, plate, net, a, b, r, split=True):
        a, b = np.asarray(a, float), np.asarray(b, float)
        L = float(np.linalg.norm(b - a))
        if L < 1e-9:
            return
        n = max(1, int(L / 2.5)) if split else 1
        for i in range(n):
            self.tubes.append((plate, net, a + (b - a) * (i / n), a + (b - a) * ((i + 1) / n), r))

    # ------------------------------------------------------------------ UI
    def _ui(self):
        top = self.top
        side = ttk.Frame(top, padding=(14, 12), style="Side.TFrame", width=280)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        self.canvas = tk.Canvas(top, bg=BG, highlightthickness=0, cursor="fleur")
        self.canvas.pack(side="left", fill="both", expand=True)

        ttk.Label(side, text="View", style="Head.TLabel").pack(anchor="w")
        row = ttk.Frame(side, style="Side.TFrame")
        row.pack(fill="x", pady=(4, 2))
        ttk.Radiobutton(row, text="X-ray", value="xray", variable=self.mode, style="Seg.TRadiobutton",
                        command=self.redraw).pack(side="left", expand=True, fill="x")
        ttk.Radiobutton(row, text="Solid", value="solid", variable=self.mode, style="Seg.TRadiobutton",
                        command=self.redraw).pack(side="left", expand=True, fill="x")
        row = ttk.Frame(side, style="Side.TFrame")
        row.pack(fill="x", pady=(6, 2))
        for i, (label, yaw, pitch) in enumerate((("Iso", -32, 38), ("Top", 0, 90), ("Front", 0, 0),
                                                 ("Side", -90, 0), ("Below", 0, -90))):
            ttk.Button(row, text=label, style="Tiny.TButton",
                       command=lambda y=yaw, p=pitch: self.set_view(y, p)).grid(row=0, column=i, sticky="ew",
                                                                                 padx=1)
            row.columnconfigure(i, weight=1, uniform="v")
        ttk.Label(side, text="Explode (mm)", style="Side.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Scale(side, from_=0, to=30, variable=self.explode, command=lambda e: self.redraw()).pack(fill="x")

        ttk.Label(side, text="Show", style="Head.TLabel").pack(anchor="w", pady=(14, 2))
        grid = ttk.Frame(side, style="Side.TFrame")
        grid.pack(fill="x")
        items = [("Top plate", self.show["top"]), ("Middle plate", self.show["middle"]),
                 ("Bottom plate", self.show["bottom"]), ("Membranes", self.show_membranes),
                 ("Bolts", self.show_bolts), ("Names", self.show_names)]
        for i, (label, var) in enumerate(items):
            ttk.Checkbutton(grid, text=label, variable=var, style="Chip.TCheckbutton",
                            command=self.redraw).grid(row=i // 2, column=i % 2, sticky="ew", pady=2, padx=2)
        grid.columnconfigure((0, 1), weight=1)

        ttk.Label(side, text="Lines — click one to pick it out", style="Head.TLabel").pack(anchor="w", pady=(14, 4))
        lf = ttk.Frame(side, style="Side.TFrame")
        lf.pack(fill="both", expand=True)
        self.legend = tk.Canvas(lf, bg=theme.CARD, highlightthickness=1,
                                highlightbackground=theme.BORDER, height=150)
        self.legend.pack(fill="both", expand=True)
        self.legend.bind("<Button-1>", self._legend_click)
        self.legend.bind("<Configure>", lambda e: self._draw_legend())
        self.legend.bind("<MouseWheel>", lambda e: self.legend.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.legend.bind("<Button-4>", lambda e: self.legend.yview_scroll(-1, "units"))
        self.legend.bind("<Button-5>", lambda e: self.legend.yview_scroll(1, "units"))

        info = self.m.routing
        T = self.m.thickness
        ttk.Label(side, style="Muted.TLabel", wraplength=250, justify="left",
                  text=f"Plates {self.m.width:g} × {self.m.length:g} mm; bottom {T['bottom']:g}, "
                       f"middle {T['middle']:g}, top {T['top']:g} mm. "
                       f"{'Negative pressure (bowls). ' if self.m.actuation == 'vacuum' else ''}Lines on {info.levels} "
                       f"level{'s' if info.levels > 1 else ''}.").pack(anchor="w", pady=(10, 6))
        if self.on_export:
            ttk.Button(side, text="Export STL files…", style="Accent.TButton",
                       command=self.on_export).pack(fill="x", pady=(2, 0))

        c = self.canvas
        c.bind("<Configure>", lambda e: self.redraw())
        c.bind("<ButtonPress-1>", lambda e: self._start(e, "orbit"))
        c.bind("<B1-Motion>", self._move)
        for b in ("2", "3"):
            c.bind(f"<ButtonPress-{b}>", lambda e: self._start(e, "pan"))
            c.bind(f"<B{b}-Motion>", self._move)
        c.bind("<MouseWheel>", lambda e: self._zoom(e, 1 if e.delta > 0 else -1))
        c.bind("<Button-4>", lambda e: self._zoom(e, 1))
        c.bind("<Button-5>", lambda e: self._zoom(e, -1))
        self.top.bind("<KeyPress-f>", lambda e: self.fit())
        self.top.bind("<Escape>", lambda e: self._pick(None))

    def _legend_rows(self):
        rows = [(SUPPLY, "Supply (middle plate)")]
        for name, nr in self.m.routing.nets.items():
            if name != SUPPLY:
                rows.append((name, f"{name}  ·  {len(nr.members)} valve{'s' if len(nr.members) > 1 else ''}"))
        rows.append(("#mid", "Link between a cell's valves"))
        rows.append(("#out", "Valve outlet → dome"))
        return rows

    def _draw_legend(self):
        lg = self.legend
        lg.delete("all")
        for i, (key, text) in enumerate(self._legend_rows()):
            y = 8 + i * 22
            col = net_color("x.mid" if key == "#mid" else "x.out" if key == "#out" else key, self.pal)
            on = self.focus in (None, key)
            if self.focus == key:
                lg.create_rectangle(2, y - 3, 400, y + 17, fill=theme.SELECT_BG, outline="")
            lg.create_rectangle(10, y + 2, 24, y + 12, fill=col if on else mix(col, "#ffffff", 0.7),
                                outline="")
            lg.create_text(32, y + 7, text=text, anchor="w", font=theme.FONT,
                           fill=theme.TEXT if on else theme.MUTED)
        lg.config(scrollregion=(0, 0, 200, 16 + 22 * len(self._legend_rows())), yscrollincrement=22)

    def _legend_click(self, e):
        i = int((self.legend.canvasy(e.y) - 5) // 22)
        rows = self._legend_rows()
        if 0 <= i < len(rows):
            key = rows[i][0]
            self._pick(None if self.focus == key else key)

    def _pick(self, key):
        self.focus = key
        self._draw_legend()
        self.redraw()

    def _active(self, net):
        if self.focus is None:
            return True
        if self.focus == "#mid":
            return net.endswith(".mid")
        if self.focus == "#out":
            return net.endswith(".out") or net.endswith(".window")
        return net == self.focus

    # --------------------------------------------------------------- view
    def set_view(self, yaw, pitch):
        self.yaw, self.pitch = float(yaw), float(pitch)
        self.redraw()

    def fit(self):
        cw, ch = max(self.canvas.winfo_width(), 200), max(self.canvas.winfo_height(), 200)
        size = max(self.m.width, self.m.length) * 1.05 + 2 * self.explode.get()
        self.scale = min(cw, ch) / max(size, 1.0) * 0.95
        self.pan = [0.0, 0.0]
        self.redraw()

    def _start(self, e, kind):
        self._drag = (kind, e.x, e.y, self.yaw, self.pitch, list(self.pan))

    def _move(self, e):
        if not self._drag:
            return
        kind, x, y, yaw, pitch, pan = self._drag
        if kind == "orbit":
            self.yaw = yaw - (e.x - x) * 0.4
            self.pitch = max(-90.0, min(90.0, pitch + (e.y - y) * 0.4))
        else:
            self.pan = [pan[0] + e.x - x, pan[1] + e.y - y]
        self.redraw()

    def _zoom(self, e, d):
        self.scale *= 1.12 if d > 0 else 1 / 1.12
        self.redraw()

    def redraw(self):
        if not self._pending:
            self._pending = True
            self.top.after_idle(self._draw)

    # ------------------------------------------------------------ drawing
    def _dz(self):
        e = self.explode.get()
        return {"bottom": -e, "middle": 0.0, "top": e}

    def _project(self, P):
        """World points (N, 3) -> screen x, y and depth (bigger = nearer)."""
        m = self.m
        c = np.array([m.width / 2.0, m.length / 2.0, m.z0["middle"] + m.thickness["middle"] / 2.0])
        q = np.asarray(P, float) - c
        f, t = math.radians(self.yaw), math.radians(self.pitch)
        x1 = q[..., 0] * math.cos(f) + q[..., 1] * math.sin(f)
        y1 = -q[..., 0] * math.sin(f) + q[..., 1] * math.cos(f)
        z1 = q[..., 2]
        Y = z1 * math.cos(t) + y1 * math.sin(t)
        D = -y1 * math.cos(t) + z1 * math.sin(t)
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        sx = cw / 2.0 + self.pan[0] + x1 * self.scale
        sy = ch / 2.0 + self.pan[1] - Y * self.scale
        return sx, sy, D

    def _normal_view(self, n):
        f, t = math.radians(self.yaw), math.radians(self.pitch)
        x1 = n[0] * math.cos(f) + n[1] * math.sin(f)
        y1 = -n[0] * math.sin(f) + n[1] * math.cos(f)
        z1 = n[2]
        return np.array([x1, z1 * math.cos(t) + y1 * math.sin(t), -y1 * math.cos(t) + z1 * math.sin(t)])

    def _draw(self):
        self._pending = False
        c = self.canvas
        c.delete("all")
        m = self.m
        dz = self._dz()
        xray = self.mode.get() == "xray"
        W, L = m.width, m.length

        # plates and membranes, back to front
        layers = []
        for p in PLATES:
            if self.show[p].get():
                z0 = m.z0[p] + dz[p]
                layers.append(("plate", p, z0, z0 + m.thickness[p]))
        if self.show_membranes.get():
            layers.append(("membrane", "m1", (dz["bottom"] + dz["middle"]) / 2.0, None))
            layers.append(("membrane", "m2", m.thickness["middle"] + (dz["middle"] + dz["top"]) / 2.0, None))
        def depth(layer):
            z = layer[2] if layer[3] is None else (layer[2] + layer[3]) / 2.0
            return self._project(np.array([[W / 2, L / 2, z]]))[2][0]
        layers.sort(key=depth)
        if xray:
            for kind, p, z0, z1 in layers:
                if kind == "plate":
                    for pts, nv in self._box_faces(W, L, z0, z1):
                        if nv[2] <= 0:
                            self._poly(pts, fill=mix(PLATE_TINT[p], BG, 0.45),
                                       outline=mix(PLATE_EDGE[p], BG, 0.5))
        for kind, p, z0, z1 in layers:
            if kind == "membrane":
                self._membrane(z0)
                continue
            box = self._box_faces(W, L, z0, z1)
            back = [f for f in box if f[1][2] <= 0]
            front = [f for f in box if f[1][2] > 0]
            tint, edge = PLATE_TINT[p], PLATE_EDGE[p]
            if xray:
                self._bolt_axes(p, dz[p])
                self._contents(p, dz[p])
                for pts, nv in front:
                    self._poly(pts, fill="", outline=edge, width=1.4)
            else:
                for pts, nv in front:
                    shade = 0.72 + 0.28 * max(0.0, float(nv @ LIGHT))
                    self._poly(pts, fill=mix("#000000", tint, shade) if shade < 1 else tint,
                               outline=mix(edge, "#000000", 0.2))
                self._decorate(p, dz[p], z0, z1, front)
        if self.show_names.get():
            for plate, net, pt, text, out in self.labels:
                if not self.show[plate].get():
                    continue
                if not xray and self._normal_view(out)[2] <= 0:
                    continue
                sx, sy, _ = self._project(np.array([[pt[0], pt[1], pt[2] + dz[plate]]]))
                is_port = not net.endswith(".window")
                col = net_color(net, self.pal) if is_port else ("#495057" if xray else "#f1f3f5")
                if not self._active(net):
                    col = mix(col, BG, 0.65)
                c.create_text(sx[0], sy[0], text=text, fill=col,
                              font=theme.FONT_BOLD if is_port else theme.FONT_SMALL)
        self._triad()

    def _box_faces(self, W, L, z0, z1):
        v = np.array([[0, 0, z0], [W, 0, z0], [W, L, z0], [0, L, z0],
                      [0, 0, z1], [W, 0, z1], [W, L, z1], [0, L, z1]], float)
        faces = [((0, 3, 2, 1), (0, 0, -1)), ((4, 5, 6, 7), (0, 0, 1)), ((0, 1, 5, 4), (0, -1, 0)),
                 ((2, 3, 7, 6), (0, 1, 0)), ((1, 2, 6, 5), (1, 0, 0)), ((3, 0, 4, 7), (-1, 0, 0))]
        return [(v[list(idx)], self._normal_view(n)) for idx, n in faces]

    def _poly(self, pts, **kw):
        sx, sy, _ = self._project(np.asarray(pts))
        flat = [v for xy in zip(sx.tolist(), sy.tolist()) for v in xy]
        self.canvas.create_polygon(flat, **kw)

    def _membrane(self, z):
        W, L = self.m.width, self.m.length
        pts = np.array([[0, 0, z], [W, 0, z], [W, L, z], [0, L, z]], float)
        sx, sy, _ = self._project(pts)
        flat = [v for xy in zip(sx.tolist(), sy.tolist()) for v in xy]
        self.canvas.create_polygon(flat, fill="", outline=MEMBRANE, dash=(5, 3), width=1.2)

    def _contents(self, plate, dz):
        """Every cavity of one plate, painter-sorted."""
        items = []
        bolts = self.show_bolts.get()
        for p, net, a, b, r in self.tubes:
            if p != plate:
                continue
            is_bolt = net.startswith("bolt")
            if is_bolt and not bolts:
                continue
            items.append(("tube", net, a + (0, 0, dz), b + (0, 0, dz), r))
        for p, net, pts, kind in self.polys:
            if p != plate:
                continue
            if kind in ("nut", "bolt") and not bolts:
                continue
            items.append(("poly", net, np.asarray(pts) + (0, 0, dz), kind))
        if not items:
            return
        # depth of every item, one projection for all of them
        cents = np.array([(it[2] + it[3]) / 2.0 if it[0] == "tube" else it[2].mean(axis=0) for it in items])
        _, _, D = self._project(cents)
        order = np.argsort(D)
        c = self.canvas
        for idx in order:
            it = items[idx]
            net = it[1]
            col = "#adb5bd" if net.startswith("bolt") else net_color(net, self.pal)
            active = self._active(net)
            if not active:
                col = mix(col, BG, 0.78)
            if it[0] == "tube":
                _, _, a, b, r = it
                sx, sy, _ = self._project(np.array([a, b]))
                w = max(2 * r * self.scale, 1.5)
                x0, y0, x1, y1 = sx[0], sy[0], sx[1], sy[1]
                if net.startswith("bolt"):
                    c.create_line(x0, y0, x1, y1, fill=mix(col, BG, 0.5), width=w, capstyle="round")
                    continue
                c.create_line(x0, y0, x1, y1, fill=mix(col, "#000000", 0.35), width=w + 1.4, capstyle="round")
                c.create_line(x0, y0, x1, y1, fill=col, width=w, capstyle="round")
                dx, dy = x1 - x0, y1 - y0
                ln = math.hypot(dx, dy)
                if ln > 1e-6:
                    nx, ny = -dy / ln, dx / ln
                    if nx * -0.5 + ny * -0.8 < 0:
                        nx, ny = -nx, -ny
                else:
                    nx, ny = -0.53, -0.85
                o = 0.22 * w
                c.create_line(x0 + nx * o, y0 + ny * o, x1 + nx * o, y1 + ny * o,
                              fill=mix(col, "#ffffff", 0.5), width=max(w * 0.3, 1), capstyle="round")
            else:
                _, _, pts, kind = it
                sx, sy, _ = self._project(pts)
                flat = [v for xy in zip(sx.tolist(), sy.tolist()) for v in xy]
                if kind == "window":
                    c.create_polygon(flat, fill="", outline=col, width=2)
                elif kind == "ring":
                    c.create_polygon(flat, fill="", outline=col, width=1.4)
                elif kind == "nut":
                    c.create_polygon(flat, fill="", outline=mix(col, BG, 0.3), dash=(3, 2))
                elif kind == "bolt":
                    c.create_polygon(flat, fill="", outline=mix(col, BG, 0.15), width=1)
                elif kind == "mouth":
                    c.create_polygon(flat, fill=mix(col, "#000000", 0.25), outline="")
                elif kind == "cap":
                    c.create_polygon(flat, fill="", outline=mix(col, "#000000", 0.3), width=1)
                else:
                    v = pts[1] - pts[0]
                    w_ = pts[2] - pts[0]
                    n = np.cross(v, w_)
                    ln = np.linalg.norm(n)
                    shade = 0.8
                    if ln > 1e-12:
                        nv = self._normal_view(n / ln)
                        shade = 0.62 + 0.38 * abs(float(nv @ LIGHT))
                    c.create_polygon(flat, fill=mix("#000000", col, shade), outline=mix(col, "#000000", 0.3))

    def _bolt_axes(self, plate, dz):
        if not self.show_bolts.get():
            return
        m = self.m
        z0 = m.z0[plate] + dz
        z1 = z0 + m.thickness[plate]
        for p, net, (x, y), r in self.bolt_axes:
            if p != plate:
                continue
            for sgn in (-1, 1):
                # the two silhouette lines of the hole, across the view
                v = self._normal_view(np.array([1.0, 0, 0]))
                ang = math.atan2(v[1], v[0]) if abs(self.pitch) < 89 else 0.0
                dxw = r * math.cos(math.radians(self.yaw))
                dyw = r * math.sin(math.radians(self.yaw))
                pts = np.array([[x + sgn * dxw, y + sgn * dyw, z0], [x + sgn * dxw, y + sgn * dyw, z1]])
                sx, sy, _ = self._project(pts)
                self.canvas.create_line(sx[0], sy[0], sx[1], sy[1], fill="#ced4da")

    def _decorate(self, plate, dz, z0, z1, front):
        """Solid view: show the holes and inlets on the faces that face us."""
        for p, net, pts, kind in self.polys:
            if p != plate or kind != "mouth":
                continue
            pts = np.asarray(pts) + (0, 0, dz)
            inward = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            if self._normal_view(-inward / np.linalg.norm(inward))[2] > 0:
                self._poly(pts, fill=mix(net_color(net, self.pal), "#000000", 0.2), outline="")
        for p, net, (x, y), r in self.bolt_axes:
            if p != plate:
                continue
            z = (z1 if self._facing_up() else z0)
            self._poly(_circle((x, y, z), r, (0, 0, 1), 16), fill="#495057", outline="")
        for p, net, pts, kind in self.polys:
            if p != plate:
                continue
            pts = np.asarray(pts) + (0, 0, dz)
            if kind in ("window", "ring") and plate == "top":
                zz = z1 if self._facing_up() else z0
                ring = pts.copy()
                ring[:, 2] = zz
                self._poly(ring, fill="#343a40", outline="")
            if kind == "cap" and plate == "bottom" and self._facing_up():
                ring = pts.copy()
                ring[:, 2] = z1
                self._poly(ring, fill=mix(net_color(net, self.pal), "#000000", 0.3), outline="")
            if kind == "solid" and plate == "middle" and not self._facing_up() and len(pts) == 10:
                ring = pts.copy()
                ring[:, 2] = z0
                self._poly(ring, fill=mix(net_color(net, self.pal), "#000000", 0.3), outline="")

    def _facing_up(self):
        return self.pitch > 0

    def _triad(self):
        c = self.canvas
        ox, oy = 46, c.winfo_height() - 46
        for vec, label, col in (((1, 0, 0), "x", "#e03131"), ((0, 1, 0), "y", "#2f9e44"),
                                ((0, 0, 1), "z", "#1c7ed6")):
            v = self._normal_view(np.array(vec, float))
            c.create_line(ox, oy, ox + v[0] * 26, oy - v[1] * 26, fill=col, width=2, arrow="last")
            c.create_text(ox + v[0] * 34, oy - v[1] * 34, text=label, fill=col, font=theme.FONT_SMALL)
