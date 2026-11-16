"""mfcad Layout: place actuators and bolts on a plate, then generate the plates.

The window is a 2D view of the plate seen from the top (the finger / skin
side). Tools: Select (V), Actuator (A), Bolt (B), Matrix (M). Rules are
checked live: a ghost turns red where it may not go, and anything already on
the plate that breaks a rule (after the rules change, say) is drawn red and
listed under Checks.

Every actuator sits on two control lines, named automatically like a keyboard
matrix (rows and columns) or by hand. Generate 3D routes the lines and the
supply through the plates and opens a 3D view; Export writes the STL files.
"""

from __future__ import annotations

import math
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import asdict, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, drc, svgexport, theme
from .colors import mix, palette
from .model import (FACES, PROVEN, SUPPLY, Actuator, Bolt, Layout, Rules, default_pitch,
                    line_members, matrix, resolve_lines)

# ---- canvas colours ----
CANVAS = "#e6eaf0"
PLATE = "#ffffff"
PLATE_LINE = "#3d4752"
SHADOW = "#d3d9e1"
GRID_MINOR = "#f2f4f7"
GRID_MAJOR = "#e1e5eb"
AXIS_TEXT = "#8a94a0"
KEEP_IN = "#c5ccd5"
FOOT = "#b5bdc7"
FOOT_FILL = "#fafbfd"
SEAT = "#5c6773"
WINDOW = "#d0ebff"
WINDOW_LINE = "#1c7ed6"
BOLT_LINE = "#2b333b"
NUT = "#9aa3ad"
SELECT = theme.ACCENT
ERROR = theme.BAD
GHOST_OK = "#2f9e44"
GHOST_BAD = theme.BAD

TOOLS = (("select", "↖  Select", "V"), ("actuator", "◎  Actuator", "A"),
         ("bolt", "⊕  Bolt", "B"), ("matrix", "▦  Matrix", "M"))
HINTS = {
    "select": "Click to select, Shift+click to add, drag to move or box-select. "
              "Arrows nudge, R rotates, Del deletes.",
    "actuator": "Click to place an actuator (its dome centre). R rotates it. Esc to stop.",
    "bolt": "Click to place a bolt. Esc to stop.",
    "matrix": "Click to place the matrix (first dome at the cursor). R rotates. Esc to stop.",
}
FILETYPES = [("mfcad layout", "*.mfl"), ("JSON", "*.json"), ("All files", "*")]
LINE_NAME = re.compile(r"^[A-Za-z0-9_\-\.']{1,12}$")


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


class Tooltip:
    def __init__(self, widget, text):
        self.w, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, e):
        self._hide()
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        x = self.w.winfo_rootx() + 4
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#2b333b", fg="#ffffff", font=theme.FONT_SMALL,
                 padx=8, pady=4, justify="left").pack()

    def _hide(self, e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App:
    def __init__(self, root: tk.Tk, path: str | None = None):
        self.root = root
        self.lay = Layout()
        self.path: Path | None = None
        self.dirty = False
        self.undo: list[dict] = []
        self.redo: list[dict] = []
        self.sel: set[str] = set()
        self.tool = tk.StringVar(value="select")
        self.place_rot = 0
        self.mspec = None                 # matrix tool: (rows, cols, px, py, bolts)
        self.cursor = None                # world point under the mouse
        self.drag = None
        self.errors: list[drc.Violation] = []
        self.bad: set[str] = set()
        self.show_feet = tk.BooleanVar(value=True)
        self.show_grid = tk.BooleanVar(value=True)
        self.show_routes = tk.BooleanVar(value=True)
        self.scale = 8.0
        self.ox = self.oy = 0.0
        self.fitted = False
        self.routing = None               # last successful routing ...
        self.model = None
        self.routing_sig = None           # ... and the layout it belongs to
        self.viewer = None
        self._line_rows_key = None

        theme.init(root)
        root.title("mfcad Layout")
        root.geometry("1280x820")
        root.minsize(900, 600)

        self._menu()
        self._header()
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)
        self._side(body)
        tk.Frame(body, bg=theme.BORDER, width=1).pack(side="right", fill="y")
        self.canvas = tk.Canvas(body, bg=CANVAS, highlightthickness=0, cursor="arrow")
        self.canvas.pack(side="left", fill="both", expand=True)
        self._statusbar()
        self._bindings()
        self.tool.trace_add("write", lambda *_: self._tool_changed())
        root.protocol("WM_DELETE_WINDOW", self.quit)

        if path:
            self._open_path(Path(path))
        else:
            self._refresh()

    # ================================================================ UI build
    def _menu(self):
        m = tk.Menu(self.root, tearoff=False)
        f = tk.Menu(m, tearoff=False)
        f.add_command(label="New", accelerator="Ctrl+N", command=self.new)
        f.add_command(label="Open…", accelerator="Ctrl+O", command=self.open)
        f.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        f.add_command(label="Save as…", accelerator="Ctrl+Shift+S", command=self.save_as)
        f.add_separator()
        f.add_command(label="Generate 3D…", accelerator="Ctrl+G", command=self.generate)
        f.add_command(label="Export 3D (STL files)…", accelerator="Ctrl+E", command=self.export_3d)
        f.add_separator()
        f.add_command(label="Export drawing (SVG, 1:1)…", command=self.export_drawing)
        f.add_command(label="Export membrane template (SVG, 1:1)…", command=self.export_membrane)
        f.add_separator()
        f.add_command(label="Quit", accelerator="Ctrl+Q", command=self.quit)
        m.add_cascade(label="File", menu=f)
        e = tk.Menu(m, tearoff=False)
        e.add_command(label="Undo", accelerator="Ctrl+Z", command=self.do_undo)
        e.add_command(label="Redo", accelerator="Ctrl+Y", command=self.do_redo)
        e.add_separator()
        e.add_command(label="Select all", accelerator="Ctrl+A", command=self.select_all)
        e.add_command(label="Rotate 90°", accelerator="R", command=self.rotate)
        e.add_command(label="Delete", accelerator="Del", command=self.delete)
        m.add_cascade(label="Edit", menu=e)
        p = tk.Menu(m, tearoff=False)
        for key, label, acc in TOOLS:
            p.add_radiobutton(label=label.split("  ")[1], accelerator=acc, variable=self.tool, value=key)
        p.add_separator()
        p.add_command(label="Bolts at the corners of the selected actuators", command=self.corner_bolts)
        m.add_cascade(label="Place", menu=p)
        pl = tk.Menu(m, tearoff=False)
        pl.add_command(label="Fit plate to contents", command=self.fit_plate)
        pl.add_command(label="Rules (distances)…", command=self.rules_dialog)
        pl.add_command(label="Reset every line name to automatic", command=self.reset_lines)
        m.add_cascade(label="Plate", menu=pl)
        v = tk.Menu(m, tearoff=False)
        v.add_command(label="Fit to window", accelerator="F", command=self.fit_view)
        v.add_command(label="Zoom in", accelerator="+", command=lambda: self.zoom(1.25))
        v.add_command(label="Zoom out", accelerator="-", command=lambda: self.zoom(0.8))
        v.add_separator()
        v.add_checkbutton(label="Footprints and margins", variable=self.show_feet, command=self.redraw)
        v.add_checkbutton(label="Grid", variable=self.show_grid, command=self.redraw)
        v.add_checkbutton(label="Routed channels (after Generate 3D)", variable=self.show_routes,
                          command=self.redraw)
        m.add_cascade(label="View", menu=v)
        h = tk.Menu(m, tearoff=False)
        h.add_command(label="Shortcuts", command=self.help_keys)
        h.add_command(label="How the logic works", command=self.help_logic)
        h.add_command(label="About", command=self.about)
        m.add_cascade(label="Help", menu=h)
        self.root.config(menu=m)

    def _header(self):
        bar = ttk.Frame(self.root, style="Bar.TFrame", padding=(12, 8))
        bar.pack(side="top", fill="x")
        tk.Frame(self.root, bg=theme.BORDER, height=1).pack(side="top", fill="x")
        logo = tk.Canvas(bar, width=26, height=26, bg=theme.CARD, highlightthickness=0)
        logo.pack(side="left")
        logo.create_oval(3, 3, 23, 23, fill=theme.ACCENT, outline="")
        logo.create_oval(8, 8, 18, 18, fill="#ffffff", outline="")
        logo.create_oval(11, 11, 15, 15, fill=theme.ACCENT, outline="")
        ttk.Label(bar, text="mfcad Layout", style="Title.TLabel").pack(side="left", padx=(8, 14))

        grp = tk.Frame(bar, bg=theme.BORDER, padx=1, pady=1)
        grp.pack(side="left")
        inner = ttk.Frame(grp, style="Bar.TFrame")
        inner.pack()
        for key, label, acc in TOOLS:
            b = ttk.Radiobutton(inner, text=label, value=key, variable=self.tool, style="Tool.TRadiobutton")
            b.pack(side="left")
            Tooltip(b, f"{label.split('  ')[1]}  —  {acc}")
        ttk.Frame(bar, style="Bar.TFrame", width=10).pack(side="left")
        for text, fn, tip in (("↻  Rotate", self.rotate, "Rotate 90° — R"),
                              ("Corner bolts", self.corner_bolts,
                               "Bolts at the footprint corners of the selection (or of everything)"),
                              ("Fit plate", self.fit_plate, "Shrink or grow the plate around everything"),
                              ("Rules…", self.rules_dialog, "Every distance, in mm")):
            b = ttk.Button(bar, text=text, command=fn, style="Flat.TButton")
            b.pack(side="left", padx=1)
            Tooltip(b, tip)
        ttk.Frame(bar, style="Bar.TFrame", width=10).pack(side="left")
        ttk.Label(bar, text="Snap", style="Bar.TLabel").pack(side="left")
        self.grid_var = tk.StringVar(value=_fmt(self.lay.grid))
        sp = ttk.Combobox(bar, width=5, textvariable=self.grid_var,
                          values=("0.1", "0.25", "0.5", "1", "2", "5"))
        sp.pack(side="left", padx=(4, 2))
        ttk.Label(bar, text="mm", style="Bar.TLabel").pack(side="left")
        sp.bind("<<ComboboxSelected>>", lambda e: self._set_grid())
        sp.bind("<Return>", lambda e: self._set_grid())
        sp.bind("<FocusOut>", lambda e: self._set_grid())

        g = ttk.Button(bar, text="Generate 3D  ▸", style="Accent.TButton", command=self.generate)
        g.pack(side="right")
        Tooltip(g, "Route the lines and the supply, then show the plates in 3D — Ctrl+G")
        b = ttk.Button(bar, text="Export STL…", command=self.export_3d)
        b.pack(side="right", padx=6)
        Tooltip(b, "Write the three plates as STL files, ready to slice — Ctrl+E")

    def _side(self, parent):
        side = ttk.Frame(parent, style="Side.TFrame", width=330)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        nb = ttk.Notebook(side)
        nb.pack(fill="both", expand=True)
        self.nb = nb

        # ---- properties ----
        tab = ttk.Frame(nb, style="Side.TFrame", padding=10)
        nb.add(tab, text="Properties")
        outer, pf = theme.card(tab, "Plate")
        outer.pack(fill="x")
        self.w_var, self.l_var = tk.StringVar(), tk.StringVar()
        for row, (lab, var) in enumerate((("Width X", self.w_var), ("Length Y", self.l_var)), start=1):
            ttk.Label(pf, text=lab, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=2)
            en = ttk.Entry(pf, textvariable=var, width=9)
            en.grid(row=row, column=1, padx=6, pady=2, sticky="w")
            en.bind("<Return>", lambda e: self.apply_plate())
            ttk.Label(pf, text="mm", style="CardMuted.TLabel").grid(row=row, column=2, sticky="w")
        ttk.Button(pf, text="Apply", style="Small.TButton", command=self.apply_plate).grid(
            row=2, column=3, sticky="e", padx=(8, 0))
        pf.columnconfigure(3, weight=1)
        self.plate_info = ttk.Label(pf, style="CardMuted.TLabel", wraplength=270, justify="left")
        self.plate_info.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        outer, sf = theme.card(tab, "Selection")
        outer.pack(fill="x", pady=(10, 0))
        self.p_name, self.p_x, self.p_y = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.p_rot, self.p_row, self.p_col = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.p_entries = []
        for row, (lab, var, unit) in enumerate((("Name", self.p_name, ""), ("X", self.p_x, "mm"),
                                                ("Y", self.p_y, "mm")), start=1):
            ttk.Label(sf, text=lab, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=2)
            en = ttk.Entry(sf, textvariable=var, width=12)
            en.grid(row=row, column=1, padx=6, pady=2, sticky="w")
            en.bind("<Return>", lambda e: self.apply_props())
            ttk.Label(sf, text=unit, style="CardMuted.TLabel").grid(row=row, column=2, sticky="w")
            self.p_entries.append(en)
        ttk.Label(sf, text="Rotation", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=2)
        self.rot_box = ttk.Combobox(sf, textvariable=self.p_rot, width=10, state="readonly",
                                    values=("0", "90", "180", "270"))
        self.rot_box.grid(row=4, column=1, padx=6, pady=2, sticky="w")
        self.rot_box.bind("<<ComboboxSelected>>", lambda e: self.apply_props())
        ttk.Label(sf, text="°", style="CardMuted.TLabel").grid(row=4, column=2, sticky="w")
        self.line_boxes = []
        for row, (lab, var, tip) in enumerate((
                ("Row line", self.p_row, "Closes the valve on the supply side. Type a name to put "
                                         "this actuator on any line; 'auto' names it by its row."),
                ("Column line", self.p_col, "Closes the valve on the dome side. 'auto' names it by "
                                            "its column.")), start=5):
            l_ = ttk.Label(sf, text=lab, style="Card.TLabel")
            l_.grid(row=row, column=0, sticky="w", pady=2)
            cb = ttk.Combobox(sf, textvariable=var, width=10)
            cb.grid(row=row, column=1, padx=6, pady=2, sticky="w")
            cb.bind("<Return>", lambda e: self.apply_props())
            cb.bind("<<ComboboxSelected>>", lambda e: self.apply_props())
            Tooltip(l_, tip)
            self.line_boxes.append(cb)
        self.apply_btn = ttk.Button(sf, text="Apply", style="Small.TButton", command=self.apply_props)
        self.apply_btn.grid(row=6, column=3, sticky="e", padx=(8, 0))
        sf.columnconfigure(3, weight=1)
        self.sel_info = ttk.Label(sf, style="CardMuted.TLabel", wraplength=270, justify="left")
        self.sel_info.grid(row=7, column=0, columnspan=4, sticky="w", pady=(6, 0))

        outer, kf = theme.card(tab, "Key")
        outer.pack(fill="x", pady=(10, 0))
        key = tk.Canvas(kf, bg=theme.CARD, highlightthickness=0, height=88, width=280)
        key.grid(row=1, column=0, columnspan=4, sticky="w")
        self._draw_key(key)

        # ---- lines ----
        tab = ttk.Frame(nb, style="Side.TFrame", padding=10)
        nb.add(tab, text="Lines")
        ttk.Label(tab, style="Muted.TLabel", wraplength=300, justify="left",
                  text="Every actuator closes on two lines: its row line (supply-side valve) and "
                       "its column line (dome-side valve). Its dome rises while both are vented. "
                       "Names are automatic, like a keyboard matrix; select an actuator to put it "
                       "on another line. Pick the face each inlet comes out on.").pack(anchor="w")
        outer, spf = theme.card(tab, "Supply (middle plate)")
        outer.pack(fill="x", pady=(10, 0))
        ttk.Label(spf, text="Inlet face", style="Card.TLabel").grid(row=1, column=0, sticky="w")
        self.supply_face = tk.StringVar(value="front")
        cb = ttk.Combobox(spf, textvariable=self.supply_face, values=FACES, width=8, state="readonly")
        cb.grid(row=1, column=1, padx=8, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._set_face(SUPPLY, self.supply_face.get()))
        outer, lf = theme.card(tab, "Control lines (bottom plate)")
        outer.pack(fill="both", expand=True, pady=(10, 0))
        self.lines_frame = ttk.Frame(lf, style="Card.TFrame")
        self.lines_frame.grid(row=1, column=0, sticky="nsew")
        lf.rowconfigure(1, weight=1)
        lf.columnconfigure(0, weight=1)
        ttk.Button(tab, text="Reset names to automatic", style="Small.TButton",
                   command=self.reset_lines).pack(anchor="e", pady=(8, 0))

        # ---- checks ----
        tab = ttk.Frame(nb, style="Side.TFrame", padding=10)
        nb.add(tab, text="Checks")
        self.checks_tab = tab
        self.check_head = ttk.Label(tab, style="Good.TLabel")
        self.check_head.pack(anchor="w")
        lf = tk.Frame(tab, bg=theme.CARD, highlightthickness=1, highlightbackground=theme.BORDER)
        lf.pack(fill="both", expand=True, pady=(8, 0))
        self.check_list = tk.Listbox(lf, activestyle="none", borderwidth=0, highlightthickness=0,
                                     selectbackground=theme.SELECT_BG, selectforeground=theme.TEXT,
                                     bg=theme.CARD, fg=theme.TEXT, font=theme.FONT_SMALL)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.check_list.yview)
        self.check_list.config(yscrollcommand=sb.set)
        self.check_list.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb.pack(side="right", fill="y")
        self.check_list.bind("<<ListboxSelect>>", self._check_picked)
        ttk.Label(tab, style="Muted.TLabel", wraplength=300, justify="left",
                  text="Click a problem to select the parts involved.").pack(anchor="w", pady=(6, 0))

    def _draw_key(self, k):
        f = theme.FONT_SMALL
        k.create_oval(6, 6, 26, 26, fill=WINDOW, outline=WINDOW_LINE, width=1.5)
        k.create_text(34, 16, text="dome window (top plate)", anchor="w", font=f, fill=theme.MUTED)
        k.create_rectangle(8, 34, 16, 50, fill=mix("#e8590c", "#ffffff", 0.6), outline="#e8590c")
        k.create_rectangle(18, 34, 26, 50, fill=mix("#1c7ed6", "#ffffff", 0.6), outline="#1c7ed6")
        k.create_text(34, 42, text="chambers, coloured by their line", anchor="w", font=f, fill=theme.MUTED)
        k.create_oval(9, 60, 23, 74, fill="#ffffff", outline=BOLT_LINE, width=1.5)
        k.create_text(34, 67, text="M3 bolt (hex = nut pocket)", anchor="w", font=f, fill=theme.MUTED)

    def _statusbar(self):
        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.pack(side="bottom", fill="x")
        tk.Frame(self.root, bg=theme.BORDER, height=1).pack(side="bottom", fill="x")
        self.status = ttk.Label(bar, style="Status.TLabel")
        self.status.pack(side="left")
        self.coords = ttk.Label(bar, style="Status.TLabel", width=24, anchor="e")
        self.coords.pack(side="right")
        self.pill = ttk.Label(bar, style="GoodPill.TLabel", cursor="hand2")
        self.pill.pack(side="right", padx=8)
        self.pill.bind("<Button-1>", lambda e: self.nb.select(self.checks_tab))

    def _bindings(self):
        c, r = self.canvas, self.root
        c.bind("<Configure>", self._configure)
        c.bind("<Motion>", self._motion)
        c.bind("<Leave>", self._leave)
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._drag_move)
        c.bind("<ButtonRelease-1>", self._release)
        for b in ("2", "3"):
            c.bind(f"<ButtonPress-{b}>", self._pan_start)
            c.bind(f"<B{b}-Motion>", self._pan_move)
        c.bind("<MouseWheel>", lambda e: self._wheel(e, 1 if e.delta > 0 else -1))
        c.bind("<Button-4>", lambda e: self._wheel(e, 1))
        c.bind("<Button-5>", lambda e: self._wheel(e, -1))
        keys = {"v": "select", "a": "actuator", "b": "bolt", "m": "matrix"}
        for k, t in keys.items():
            c.bind(f"<KeyPress-{k}>", lambda e, t=t: self.tool.set(t))
        c.bind("<KeyPress-r>", lambda e: self.rotate())
        c.bind("<KeyPress-f>", lambda e: self.fit_view())
        c.bind("<KeyPress-plus>", lambda e: self.zoom(1.25))
        c.bind("<KeyPress-equal>", lambda e: self.zoom(1.25))
        c.bind("<KeyPress-minus>", lambda e: self.zoom(0.8))
        c.bind("<Delete>", lambda e: self.delete())
        c.bind("<BackSpace>", lambda e: self.delete())
        c.bind("<Escape>", lambda e: self._escape())
        for k, (dx, dy) in {"Left": (-1, 0), "Right": (1, 0), "Up": (0, 1), "Down": (0, -1)}.items():
            c.bind(f"<KeyPress-{k}>", lambda e, d=(dx, dy): self.nudge(*d, big=False))
            c.bind(f"<Shift-KeyPress-{k}>", lambda e, d=(dx, dy): self.nudge(*d, big=True))
        mod = "Command" if sys.platform == "darwin" else "Control"
        for key, fn in (("n", self.new), ("o", self.open), ("s", self.save),
                        ("S", self.save_as), ("q", self.quit), ("z", self.do_undo),
                        ("y", self.do_redo), ("Z", self.do_redo), ("g", self.generate),
                        ("e", self.export_3d)):
            r.bind(f"<{mod}-{key}>", lambda e, fn=fn: (fn(), "break")[1])
        c.bind(f"<{mod}-a>", lambda e: (self.select_all(), "break")[1])

    # ============================================================ coordinates
    def w2s(self, x, y):
        return self.ox + x * self.scale, self.oy - y * self.scale

    def s2w(self, sx, sy):
        return (sx - self.ox) / self.scale, (self.oy - sy) / self.scale

    def snap(self, v: float) -> float:
        g = self.lay.grid
        return round(round(v / g) * g, 6) if g > 0 else v

    def fit_view(self):
        cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        W, L = self.lay.width, self.lay.length
        self.scale = max(min((cw - 110) / W, (ch - 110) / L), 0.5)
        self.ox = (cw - W * self.scale) / 2.0 + 10
        self.oy = ch - (ch - L * self.scale) / 2.0 + 6
        self.redraw()

    def zoom(self, f, at=None):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        sx, sy = at if at else (cw / 2.0, ch / 2.0)
        wx, wy = self.s2w(sx, sy)
        self.scale = min(max(self.scale * f, 0.5), 400.0)
        self.ox, self.oy = sx - wx * self.scale, sy + wy * self.scale
        self.redraw()

    # ================================================================== state
    def _snapshot(self) -> dict:
        return self.lay.to_dict()

    def _sig(self) -> str:
        d = self.lay.to_dict()
        d.pop("editor", None)
        return repr(d)

    def _push(self, snap: dict | None = None):
        self.undo.append(snap if snap is not None else self._snapshot())
        del self.undo[:-300]
        self.redo.clear()

    def _changed(self, msg: str | None = None):
        self.dirty = True
        self._refresh()
        if msg:
            self.say(msg)

    def _routes_current(self) -> bool:
        return self.routing is not None and self.routing_sig == self._sig()

    def _refresh(self):
        self.errors = drc.check(self.lay)
        self.bad = {n for v in self.errors for n in v.items}
        self.sel = {n for n in self.sel if self.lay.get(n) is not None}
        self.lines = resolve_lines(self.lay)
        self.pal = palette([n for rc in self.lines.values() for n in rc])
        name = self.path.name if self.path else "untitled"
        self.root.title(f"{name}{' •' if self.dirty else ''} — mfcad Layout")
        self.w_var.set(_fmt(self.lay.width))
        self.l_var.set(_fmt(self.lay.length))
        self.grid_var.set(_fmt(self.lay.grid))
        nl = len({n for rc in self.lines.values() for n in rc})
        self.plate_info.config(text=f"{len(self.lay.actuators)} actuators on {nl} lines, "
                                    f"{len(self.lay.bolts)} bolts. Origin at the bottom-left "
                                    f"corner, seen from the top plate.")
        self.supply_face.set(self.lay.faces.get(SUPPLY, "front"))
        self._fill_checks()
        self._fill_props()
        self._fill_lines()
        self.redraw()

    def _restore(self, d: dict):
        self.lay = Layout.from_dict(d)
        self.dirty = True
        self._refresh()

    def do_undo(self):
        if not self.undo:
            return self.say("Nothing to undo.")
        self.redo.append(self._snapshot())
        self._restore(self.undo.pop())
        self.say("Undone.")

    def do_redo(self):
        if not self.redo:
            return self.say("Nothing to redo.")
        self.undo.append(self._snapshot())
        self._restore(self.redo.pop())
        self.say("Redone.")

    def say(self, msg: str, bad: bool = False):
        self.status.config(text=msg, foreground=ERROR if bad else theme.MUTED)

    # ================================================================ drawing
    def redraw(self):
        c = self.canvas
        c.delete("all")
        R = self.lay.rules
        W, L = self.lay.width, self.lay.length
        x0, y0 = self.w2s(0, L)
        x1, y1 = self.w2s(W, 0)
        for d, col in ((6, mix(SHADOW, CANVAS, 0.5)), (3, SHADOW)):
            c.create_rectangle(x0 + d, y0 + d, x1 + d, y1 + d, fill=col, outline="")
        c.create_rectangle(x0, y0, x1, y1, fill=PLATE, outline="")
        if self.show_grid.get():
            self._draw_grid(W, L)
        if self.show_feet.get():
            for e, dash in ((R.act_edge, (4, 3)), (R.bolt_edge, (1, 3))):
                if 2 * e < min(W, L):
                    a0, b0 = self.w2s(e, L - e)
                    a1, b1 = self.w2s(W - e, e)
                    c.create_rectangle(a0, b0, a1, b1, outline=KEEP_IN, dash=dash)
        c.create_rectangle(x0, y0, x1, y1, outline=PLATE_LINE, width=1.5)
        c.create_text(x0, y0 - 12, text=f"{_fmt(W)} × {_fmt(L)} mm", anchor="w",
                      fill=theme.MUTED, font=theme.FONT_BOLD)
        routes = self.show_routes.get() and self._routes_current()
        for a in self.lay.actuators:
            self._draw_act(a, self._state(a.name), under=True)
        if routes:
            self._draw_routes()
        for a in self.lay.actuators:
            self._draw_act(a, self._state(a.name))
        for b in self.lay.bolts:
            self._draw_bolt(b, self._state(b.name))
        self._draw_ghost()
        if self.drag and self.drag["kind"] == "band":
            bx, by = self.drag["start"]
            ex, ey = self.drag["now"]
            c.create_rectangle(bx, by, ex, ey, outline=SELECT, dash=(3, 2), width=1.5)
        if not self.lay.actuators and not self.lay.bolts and self.tool.get() == "select":
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            c.create_text(cx, cy - 10, text="An empty plate", fill=theme.MUTED, font=theme.FONT_TITLE)
            c.create_text(cx, cy + 14, text="Press A to place an actuator, M for a whole matrix, "
                                            "B for a bolt.", fill=theme.MUTED, font=theme.FONT)

    def _state(self, name):
        if name in self.bad:
            return "error"
        return "selected" if name in self.sel else "normal"

    def _draw_grid(self, W, L):
        c, s = self.canvas, self.scale
        step = next((v for v in (self.lay.grid, 0.5, 1, 2, 5, 10, 20, 50)
                     if v >= self.lay.grid and v * s >= 8), 50)
        major = next(v for v in (10, 20, 50, 100) if v * s >= 30)
        for i in range(int(W / step) + 1):
            x = i * step
            sx, sy0 = self.w2s(x, 0)
            _, sy1 = self.w2s(x, L)
            c.create_line(sx, sy0, sx, sy1, fill=GRID_MINOR)
        for j in range(int(L / step) + 1):
            sx0, sy = self.w2s(0, j * step)
            sx1, _ = self.w2s(W, j * step)
            c.create_line(sx0, sy, sx1, sy, fill=GRID_MINOR)
        k = 0
        while k * major <= W + 1e-9:
            sx, sy0 = self.w2s(k * major, 0)
            _, sy1 = self.w2s(k * major, L)
            c.create_line(sx, sy0, sx, sy1, fill=GRID_MAJOR)
            c.create_text(sx, sy0 + 11, text=_fmt(k * major), fill=AXIS_TEXT, font=theme.FONT_SMALL)
            k += 1
        k = 0
        while k * major <= L + 1e-9:
            sx0, sy = self.w2s(0, k * major)
            sx1, _ = self.w2s(W, k * major)
            c.create_line(sx0, sy, sx1, sy, fill=GRID_MAJOR)
            c.create_text(sx0 - 7, sy, text=_fmt(k * major), anchor="e", fill=AXIS_TEXT,
                          font=theme.FONT_SMALL)
            k += 1

    def _rect(self, r, **kw):
        a, b = self.w2s(r[0], r[3])
        cx, d = self.w2s(r[2], r[1])
        return self.canvas.create_rectangle(a, b, cx, d, **kw)

    def _rrect(self, r, rad, **kw):
        """Rounded rectangle (screen radius `rad` px)."""
        a, b = self.w2s(r[0], r[3])
        cx, d = self.w2s(r[2], r[1])
        rad = min(rad, (cx - a) / 2, (d - b) / 2)
        pts = [a + rad, b, cx - rad, b, cx, b, cx, b + rad, cx, d - rad, cx, d, cx - rad, d,
               a + rad, d, a, d, a, d - rad, a, b + rad, a, b]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _circle(self, x, y, r, **kw):
        sx, sy = self.w2s(x, y)
        rr = r * self.scale
        return self.canvas.create_oval(sx - rr, sy - rr, sx + rr, sy + rr, **kw)

    def _draw_act(self, a: Actuator, state: str, ghost_ok: bool | None = None, under: bool = False):
        """`under=True` draws the footprint and chambers (beneath the routed
        channels); the default draws the rest on top."""
        R, c = self.lay.rules, self.canvas
        ghost = ghost_ok is not None
        line = {"error": ERROR, "selected": SELECT}.get(state)
        if ghost:
            line = GHOST_OK if ghost_ok else GHOST_BAD
        row, col = self.lines.get(a.name, ("", ""))
        if under or ghost:
            if self.show_feet.get() or ghost or state != "normal":
                kw = {"dash": (4, 3)} if state == "normal" and not ghost else {}
                self._rrect(a.footprint(R), 6, fill="" if ghost else FOOT_FILL, outline=line or FOOT,
                            width=2 if state != "normal" or ghost else 1, **kw)
            for ch, ln in zip(a.chambers(), (col, row)):
                base = self.pal.get(ln, "#adb5bd")
                self._rrect(ch, 3, fill="" if ghost else mix(base, "#ffffff", 0.62),
                            outline=line or base, width=1.2)
            if not ghost:
                return
        for sx, sy, sr in a.seats():
            self._circle(sx, sy, sr, outline=line or SEAT, fill="" if ghost else "#ffffff")
        wx, wy, wr = a.window(R)
        self._circle(wx, wy, wr, fill="" if ghost else WINDOW, outline=line or WINDOW_LINE,
                     width=2.2 if state != "normal" or ghost else 1.4)
        self._circle(wx, wy, 0.9, fill=line or WINDOW_LINE, outline="")
        if self.scale >= 4 and not ghost:
            sx, sy = self.w2s(wx, wy - wr - 0.3)
            c.create_text(sx, sy, text=a.name, anchor="n", fill=line or "#1864ab", font=theme.FONT_BOLD)
            if self.scale >= 6:
                c.create_text(sx - 3, sy + 15, text=row, anchor="ne", fill=self.pal.get(row, theme.MUTED),
                              font=theme.FONT_SMALL)
                c.create_text(sx, sy + 15, text="·", anchor="n", fill=theme.MUTED, font=theme.FONT_SMALL)
                c.create_text(sx + 3, sy + 15, text=col, anchor="nw", fill=self.pal.get(col, theme.MUTED),
                              font=theme.FONT_SMALL)

    def _draw_bolt(self, b: Bolt, state: str, ghost_ok: bool | None = None):
        R = self.lay.rules
        ghost = ghost_ok is not None
        line = {"error": ERROR, "selected": SELECT}.get(state)
        if ghost:
            line = GHOST_OK if ghost_ok else GHOST_BAD
        if self.show_feet.get():
            cr = R.nut_af / math.sqrt(3.0)
            pts = []
            for k in range(6):
                ang = math.radians(30 + 60 * k)
                pts += self.w2s(b.x + cr * math.cos(ang), b.y + cr * math.sin(ang))
            self.canvas.create_polygon(pts, fill="", outline=line or NUT, dash=(2, 2))
        self._circle(b.x, b.y, R.bolt_d / 2.0, fill="" if ghost else "#ffffff",
                     outline=line or BOLT_LINE, width=2.2 if state != "normal" or ghost else 1.5)
        self._circle(b.x, b.y, 0.35, fill=line or BOLT_LINE, outline="")
        if self.scale >= 6 and not ghost:
            sx, sy = self.w2s(b.x, b.y - R.bolt_d / 2.0 - 0.3)
            self.canvas.create_text(sx, sy, text=b.name, anchor="n", fill=line or theme.MUTED,
                                    font=theme.FONT_SMALL)

    def _draw_routes(self):
        """The routed channels from the last Generate 3D, seen from the top."""
        c, st = self.canvas, self.model.stack
        pal = palette(self.routing.nets)
        for name, nr in self.routing.nets.items():
            col = pal.get(name, "#868e96")
            for p in nr.paths:
                for (x0, y0, z0), (x1, y1, z1) in zip(p, p[1:]):
                    if abs(x0 - x1) < 1e-9 and abs(y0 - y1) < 1e-9:
                        continue
                    deep = nr.plate == "bottom" and abs(z0) > st.ctrl_z + 0.1
                    w = max(st.d * self.scale * (0.85 if deep else 0.55), 2)
                    a, b = self.w2s(x0, y0), self.w2s(x1, y1)
                    kw = {"dash": (6, 4)} if nr.plate == "middle" else {}
                    c.create_line(*a, *b, fill=mix(col, "#ffffff", 0.55 if deep else 0.1), width=w,
                                  capstyle="round", **kw)
            if nr.port:
                a = self.w2s(*nr.port.start[:2])
                b = self.w2s(*nr.port.end[:2])
                c.create_line(*a, *b, fill=col, width=max(st.port_r * 1.2 * self.scale, 3))
                dx, dy = nr.port.direction[:2]
                c.create_text(a[0] - dx * 14, a[1] + dy * 14, text=name, fill=col, font=theme.FONT_BOLD)

    # ================================================================== ghost
    def _ghost_items(self):
        """Items the current place tool would add at the cursor."""
        if self.cursor is None:
            return [], []
        t = self.tool.get()
        x, y = self.snap(self.cursor[0]), self.snap(self.cursor[1])
        if t in ("actuator", "matrix"):
            # snap the footprint's corner, not the dome, so corner bolts land
            # on the grid too (the dome sits 0.7 mm off the footprint centre)
            fx, fy, _, _ = Actuator("p", 0.0, 0.0, self.place_rot).footprint(self.lay.rules)
            x = round(self.snap(self.cursor[0] + fx) - fx, 6)
            y = round(self.snap(self.cursor[1] + fy) - fy, 6)
        if t == "actuator":
            return [Actuator("new", x, y, self.place_rot)], []
        if t == "bolt":
            return [], [Bolt("new", x, y)]
        if t == "matrix" and self.mspec:
            rows, cols, px, py, cb = self.mspec
            acts, pts = matrix(rows, cols, self.lay.rules, px, py, self.place_rot, (x, y), cb)
            for k, a in enumerate(acts):
                a.name = f"new{k}"
            pts = [p for p in pts if not any(math.hypot(p[0] - b.x, p[1] - b.y) < 0.01
                                             for b in self.lay.bolts)]
            return acts, [Bolt(f"newb{k}", px_, py_) for k, (px_, py_) in enumerate(pts)]
        return [], []

    def _draw_ghost(self):
        acts, bolts = self._ghost_items()
        if not acts and not bolts:
            return
        if acts:
            ok = not drc.placement(self.lay, acts)
            for a in acts:
                self._draw_act(a, "normal", ghost_ok=ok)
            for b in bolts:
                good = ok and not drc.placement(self.lay, [b])
                self._draw_bolt(b, "normal", ghost_ok=good)
        else:
            errs = drc.placement(self.lay, bolts)
            self._draw_bolt(bolts[0], "normal", ghost_ok=not errs)
            if errs:
                self.say(errs[0].message, bad=True)

    # ================================================================= events
    def _configure(self, e):
        if not self.fitted:
            self.fitted = True
            self.fit_view()
        else:
            self.redraw()

    def _motion(self, e):
        self.cursor = self.s2w(e.x, e.y)
        self.coords.config(text=f"x {self.cursor[0]:7.2f}   y {self.cursor[1]:7.2f} mm")
        if self.tool.get() != "select":
            self.say(HINTS[self.tool.get()])
            self.redraw()

    def _leave(self, e):
        self.cursor = None
        if self.tool.get() != "select":
            self.redraw()

    def hit(self, wx, wy):
        R = self.lay.rules
        tol = 6.0 / self.scale
        for b in reversed(self.lay.bolts):
            if math.hypot(wx - b.x, wy - b.y) <= max(R.bolt_d / 2.0, tol):
                return b.name
        for a in reversed(self.lay.actuators):
            x0, y0, x1, y1 = a.footprint(R)
            if x0 <= wx <= x1 and y0 <= wy <= y1:
                return a.name
        return None

    def _press(self, e):
        self.canvas.focus_set()
        wx, wy = self.s2w(e.x, e.y)
        t = self.tool.get()
        if t != "select":
            return self._place(wx, wy)
        name = self.hit(wx, wy)
        shift = bool(e.state & 0x0001)
        if name is None:
            if not shift:
                self.sel.clear()
            self.drag = {"kind": "band", "start": (e.x, e.y), "now": (e.x, e.y), "shift": shift}
            self._fill_props()
            self.redraw()
            return
        if shift:
            self.sel ^= {name}
        elif name not in self.sel:
            self.sel = {name}
        orig = {n: (self.lay.get(n).x, self.lay.get(n).y) for n in self.sel}
        self.drag = {"kind": "move", "start": (wx, wy), "orig": orig, "snap": self._snapshot(),
                     "moved": False}
        self._fill_props()
        self.redraw()

    def _drag_move(self, e):
        d = self.drag
        if not d:
            return
        self._motion(e)
        if d["kind"] == "band":
            d["now"] = (e.x, e.y)
            return self.redraw()
        wx, wy = self.s2w(e.x, e.y)
        dx, dy = self.snap(wx - d["start"][0]), self.snap(wy - d["start"][1])
        for n, (x, y) in d["orig"].items():
            it = self.lay.get(n)
            it.x, it.y = round(x + dx, 6), round(y + dy, 6)
        d["moved"] = bool(dx or dy)
        moving = [self.lay.get(n) for n in d["orig"]]
        errs = drc.placement(self.lay, moving)
        self.bad = {n for v in errs for n in v.items} | {n for v in self.errors for n in v.items
                                                         if not set(v.items) & set(d["orig"])}
        self.say(errs[0].message if errs else f"Moving {len(moving)} item(s) by "
                 f"{_fmt(dx)}, {_fmt(dy)} mm", bad=bool(errs))
        self._fill_props()
        self.redraw()

    def _release(self, e):
        d, self.drag = self.drag, None
        if not d:
            return
        if d["kind"] == "band":
            x0, y0 = self.s2w(*d["start"])
            x1, y1 = self.s2w(e.x, e.y)
            lo_x, hi_x, lo_y, hi_y = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
            picked = {it.name for it in self.lay.items() if lo_x <= it.x <= hi_x and lo_y <= it.y <= hi_y}
            self.sel = (self.sel | picked) if d["shift"] else picked
            self._fill_props()
            return self.redraw()
        if not d["moved"]:
            return self._refresh()
        moving = [self.lay.get(n) for n in d["orig"]]
        errs = drc.placement(self.lay, moving)
        if errs:
            for n, (x, y) in d["orig"].items():
                it = self.lay.get(n)
                it.x, it.y = x, y
            self._refresh()
            return self.say(f"Can't go there: {errs[0].message}", bad=True)
        self._push(d["snap"])
        self._changed(f"Moved {len(moving)} item(s).")

    def _pan_start(self, e):
        self._pan = (e.x, e.y, self.ox, self.oy)

    def _pan_move(self, e):
        x, y, ox, oy = self._pan
        self.ox, self.oy = ox + e.x - x, oy + e.y - y
        self.redraw()

    def _wheel(self, e, direction):
        self.zoom(1.15 if direction > 0 else 1 / 1.15, at=(e.x, e.y))

    def _escape(self):
        if self.tool.get() != "select":
            self.tool.set("select")
        else:
            self.sel.clear()
            self._refresh()

    def _tool_changed(self):
        t = self.tool.get()
        if t == "matrix" and not self.matrix_dialog():
            self.tool.set("select")
            return
        self.canvas.config(cursor="arrow" if t == "select" else "crosshair")
        self.say(HINTS[t])
        self.canvas.focus_set()
        self.redraw()

    # ================================================================ editing
    def _place(self, wx, wy):
        self.cursor = (wx, wy)
        acts, bolts = self._ghost_items()
        if acts:
            errs = drc.placement(self.lay, acts)
            if errs:
                return self.say(f"Can't place there: {errs[0].message}", bad=True)
            self._push()
            for a in acts:
                a.name = self.lay.next_name("A")
                self.lay.actuators.append(a)
            added, skipped = self._add_bolts([(b.x, b.y) for b in bolts])
            msg = f"Placed {len(acts)} actuator(s)" + (f" and {added} bolt(s)" if bolts else "")
            if skipped:
                msg += f"; skipped {skipped} bolt(s) that broke a rule"
            self.sel = {a.name for a in acts}
            return self._changed(msg + ".")
        if bolts:
            errs = drc.placement(self.lay, bolts)
            if errs:
                return self.say(f"Can't place there: {errs[0].message}", bad=True)
            self._push()
            b = bolts[0]
            b.name = self.lay.next_name("B")
            self.lay.bolts.append(b)
            self.sel = {b.name}
            self._changed(f"Placed {b.name}.")

    def _add_bolts(self, points):
        added = skipped = 0
        for x, y in points:
            if any(math.hypot(x - b.x, y - b.y) < 0.01 for b in self.lay.bolts):
                continue
            b = Bolt(self.lay.next_name("B"), round(x, 6), round(y, 6))
            if drc.placement(self.lay, [b]):
                skipped += 1
                continue
            self.lay.bolts.append(b)
            added += 1
        return added, skipped

    def corner_bolts(self):
        acts = [a for a in self.lay.actuators if a.name in self.sel] or self.lay.actuators
        if not acts:
            return self.say("Place some actuators first.", bad=True)
        self._push()
        pts = [p for a in acts for p in a.corners(self.lay.rules)]
        added, skipped = self._add_bolts(pts)
        if not added:
            self.undo.pop()
        which = "selected" if any(a.name in self.sel for a in self.lay.actuators) else "all"
        self._changed(f"Corner bolts for {which} actuators: added {added}"
                      + (f", skipped {skipped} that broke a rule" if skipped else "") + ".")

    def rotate(self):
        if self.tool.get() in ("actuator", "matrix"):
            self.place_rot = (self.place_rot + 90) % 360
            self.say(f"Rotation {self.place_rot}°")
            return self.redraw()
        acts = [a for a in self.lay.actuators if a.name in self.sel]
        if not acts:
            return self.say("Select actuators to rotate (bolts don't rotate).")
        snap = self._snapshot()
        for a in acts:
            a.rotation = (a.rotation + 90) % 360
        errs = drc.placement(self.lay, acts)
        if errs:
            for a in acts:
                a.rotation = (a.rotation - 90) % 360
            return self.say(f"Can't rotate: {errs[0].message}", bad=True)
        self._push(snap)
        self._changed(f"Rotated {len(acts)} actuator(s).")

    def nudge(self, dx, dy, big):
        if not self.sel:
            return
        step = (10 if big else 1) * (self.lay.grid or 0.1)
        moving = [self.lay.get(n) for n in self.sel]
        snap = self._snapshot()
        for it in moving:
            it.x, it.y = round(it.x + dx * step, 6), round(it.y + dy * step, 6)
        errs = drc.placement(self.lay, moving)
        if errs:
            for it in moving:
                it.x, it.y = round(it.x - dx * step, 6), round(it.y - dy * step, 6)
            return self.say(f"Can't move there: {errs[0].message}", bad=True)
        self._push(snap)
        self._changed()

    def delete(self):
        if not self.sel:
            return
        self._push()
        n = len(self.sel)
        self.lay.remove(self.sel)
        self.sel.clear()
        self._changed(f"Deleted {n} item(s).")

    def select_all(self):
        self.sel = {it.name for it in self.lay.items()}
        self._fill_props()
        self.redraw()

    def apply_plate(self):
        try:
            w, l = float(self.w_var.get()), float(self.l_var.get())
            if w <= 0 or l <= 0:
                raise ValueError
        except ValueError:
            return self.say("Plate size must be two positive numbers.", bad=True)
        if (w, l) == (self.lay.width, self.lay.length):
            return
        self._push()
        self.lay.width, self.lay.length = w, l
        self._changed(f"Plate {_fmt(w)} × {_fmt(l)} mm.")
        self.fit_view()

    def fit_plate(self):
        R = self.lay.rules
        boxes = [a.footprint(R) for a in self.lay.actuators]
        boxes = [(b[0] - R.act_edge, b[1] - R.act_edge, b[2] + R.act_edge, b[3] + R.act_edge)
                 for b in boxes]
        boxes += [(b.x - R.bolt_edge, b.y - R.bolt_edge, b.x + R.bolt_edge, b.y + R.bolt_edge)
                  for b in self.lay.bolts]
        if not boxes:
            return self.say("Nothing on the plate to fit.", bad=True)
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        self._push()
        for it in self.lay.items():
            it.x, it.y = round(it.x - x0, 6), round(it.y - y0, 6)
        self.lay.width = math.ceil((x1 - x0) * 10 - 1e-6) / 10.0
        self.lay.length = math.ceil((y1 - y0) * 10 - 1e-6) / 10.0
        self._changed(f"Plate fitted: {_fmt(self.lay.width)} × {_fmt(self.lay.length)} mm.")
        self.fit_view()

    def _set_grid(self):
        try:
            g = float(self.grid_var.get())
            if g <= 0:
                raise ValueError
        except ValueError:
            self.grid_var.set(_fmt(self.lay.grid))
            return self.say("Snap must be a positive number.", bad=True)
        if g != self.lay.grid:
            self.lay.grid = g
            self.dirty = True
            self.say(f"Snap {_fmt(g)} mm.")
            self.redraw()
        self.canvas.focus_set()

    def _set_face(self, line, face):
        if self.lay.faces.get(line, "front" if line == SUPPLY else "auto") == face:
            return
        self._push()
        self.lay.faces[line] = face
        self._changed(f"{'Supply' if line == SUPPLY else line} inlet: {face} face.")

    def reset_lines(self):
        if not any(a.row_line or a.col_line for a in self.lay.actuators):
            return self.say("Every line name is already automatic.")
        self._push()
        for a in self.lay.actuators:
            a.row_line = a.col_line = ""
        self._changed("Line names reset to automatic.")

    # ============================================================ side panels
    def _fill_props(self):
        items = [self.lay.get(n) for n in sorted(self.sel)]
        items = [it for it in items if it is not None]
        one = items[0] if len(items) == 1 else None
        st = "normal" if one else "disabled"
        for en in self.p_entries:
            en.config(state=st)
        self.apply_btn.config(state=st)
        is_act = isinstance(one, Actuator)
        self.rot_box.config(state="readonly" if is_act else "disabled")
        names = sorted({n for rc in getattr(self, "lines", {}).values() for n in rc})
        for cb in self.line_boxes:
            cb.config(state="normal" if is_act else "disabled", values=["auto"] + names)
        if one:
            self.p_name.set(one.name)
            self.p_x.set(_fmt(one.x))
            self.p_y.set(_fmt(one.y))
            self.p_rot.set(str(one.rotation) if is_act else "")
            if is_act:
                row, col = self.lines.get(one.name, ("", ""))
                self.p_row.set(one.row_line or f"auto ({row})")
                self.p_col.set(one.col_line or f"auto ({col})")
            else:
                self.p_row.set("")
                self.p_col.set("")
            info = f"{one.kind.capitalize()}: " + drc.describe_clearance(self.lay, one)
            if is_act:
                x0, y0, x1, y1 = one.footprint(self.lay.rules)
                info += (f"\nFootprint {_fmt(x0)}…{_fmt(x1)} × {_fmt(y0)}…{_fmt(y1)} mm. "
                         f"X, Y is the dome centre.")
            self.sel_info.config(text=info)
        else:
            for v in (self.p_name, self.p_x, self.p_y, self.p_rot, self.p_row, self.p_col):
                v.set("")
            self.sel_info.config(text=f"{len(items)} items selected. Drag or use the arrows to move them."
                                 if items else "Nothing selected. Click a part on the plate.")

    def apply_props(self):
        if len(self.sel) != 1:
            return
        it = self.lay.get(next(iter(self.sel)))
        try:
            x, y = float(self.p_x.get()), float(self.p_y.get())
        except ValueError:
            return self.say("X and Y must be numbers.", bad=True)
        name = self.p_name.get().strip()
        if not name:
            return self.say("A name can't be empty.", bad=True)
        if name != it.name and self.lay.get(name) is not None:
            return self.say(f"{name} is already used.", bad=True)
        lines = None
        if isinstance(it, Actuator):
            lines = []
            for var in (self.p_row, self.p_col):
                v = var.get().strip()
                if not v or v.startswith("auto"):
                    lines.append("")
                elif v == SUPPLY:
                    return self.say(f"'{SUPPLY}' is the supply; pick another line name.", bad=True)
                elif not LINE_NAME.match(v):
                    return self.say("Line names: up to 12 letters, digits, _ - . or '", bad=True)
                else:
                    lines.append(v)
        rot = int(self.p_rot.get() or 0) if isinstance(it, Actuator) else None
        snap = self._snapshot()
        old = (it.name, it.x, it.y, getattr(it, "rotation", None))
        it.x, it.y = x, y
        if rot is not None:
            it.rotation = rot
        errs = drc.placement(self.lay, [it])
        if errs:
            it.x, it.y = old[1], old[2]
            if rot is not None:
                it.rotation = old[3]
            self._fill_props()
            return self.say(f"Can't: {errs[0].message}", bad=True)
        it.name = name
        if lines is not None:
            it.row_line, it.col_line = lines
        self.sel = {name}
        if snap != self._snapshot():
            self._push(snap)
            self._changed(f"{name} updated.")
        self.canvas.focus_set()

    def _fill_lines(self):
        members = line_members(self.lay)
        key = (tuple((n, len(m)) for n, m in members.items()),
               tuple(sorted(self.lay.faces.items())))
        if key == self._line_rows_key:
            return
        self._line_rows_key = key
        f = self.lines_frame
        for w in f.winfo_children():
            w.destroy()
        if not members:
            ttk.Label(f, text="No actuators yet.", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
            return
        ttk.Label(f, text="Line", style="CardMuted.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="Valves", style="CardMuted.TLabel").grid(row=0, column=2, sticky="w", padx=8)
        ttk.Label(f, text="Inlet face", style="CardMuted.TLabel").grid(row=0, column=3, sticky="w")
        for i, (name, mem) in enumerate(members.items(), start=1):
            sw = tk.Canvas(f, width=14, height=14, bg=theme.CARD, highlightthickness=0)
            sw.create_rectangle(1, 1, 13, 13, fill=self.pal.get(name, "#adb5bd"), outline="")
            sw.grid(row=i, column=0, padx=(0, 6), pady=2)
            ttk.Label(f, text=name, style="Card.TLabel", font=theme.FONT_BOLD).grid(row=i, column=1, sticky="w")
            acts = ", ".join(a for a, _ in mem)
            lab = ttk.Label(f, text=str(len(mem)), style="CardMuted.TLabel")
            lab.grid(row=i, column=2, sticky="w", padx=8)
            Tooltip(lab, acts)
            var = tk.StringVar(value=self.lay.faces.get(name, "auto"))
            cb = ttk.Combobox(f, textvariable=var, values=FACES, width=7, state="readonly")
            cb.grid(row=i, column=3, sticky="w", pady=2)
            cb.bind("<<ComboboxSelected>>", lambda e, n=name, v=var: self._set_face(n, v.get()))

    def _fill_checks(self):
        self.check_list.delete(0, "end")
        n = len(self.errors)
        if n:
            self.check_head.config(text=f"✗  {n} problem{'s' if n > 1 else ''}", style="Bad.TLabel")
            for v in self.errors:
                self.check_list.insert("end", "  " + v.message)
            self.pill.config(text=f"✗  {n} problem{'s' if n > 1 else ''}", style="BadPill.TLabel")
            self.nb.tab(2, text=f"Checks ({n})")
        else:
            self.check_head.config(text="✓  Every rule holds", style="Good.TLabel")
            self.pill.config(text="✓  Every rule holds", style="GoodPill.TLabel")
            self.nb.tab(2, text="Checks")

    def _check_picked(self, e):
        idx = self.check_list.curselection()
        if not idx:
            return
        self.sel = set(self.errors[idx[0]].items)
        self._fill_props()
        self.redraw()

    # ================================================================ dialogs
    def _dialog(self, title):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.transient(self.root)
        top.resizable(False, False)
        top.configure(bg=theme.SIDE)
        frm = ttk.Frame(top, padding=16, style="Side.TFrame")
        frm.pack(fill="both", expand=True)
        return top, frm

    def _modal(self, top):
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - top.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - top.winfo_height()) // 3
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        top.grab_set()
        top.wait_window()

    def matrix_dialog(self) -> bool:
        top, f = self._dialog("Place a matrix")
        rows, cols = tk.IntVar(value=3), tk.IntVar(value=3)
        rot = tk.StringVar(value=str(self.place_rot))
        packed = tk.BooleanVar(value=True)
        bolts = tk.BooleanVar(value=True)
        px, py = tk.StringVar(), tk.StringVar()

        def defaults(*_):
            if packed.get():
                a, b = default_pitch(self.lay.rules, int(rot.get()))
                px.set(_fmt(a))
                py.set(_fmt(b))
            st = "disabled" if packed.get() else "normal"
            ex.config(state=st)
            ey.config(state=st)

        ttk.Label(f, text="Place a matrix", style="Side.TLabel", font=theme.FONT_TITLE).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(f, text="Rows", style="Side.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(f, from_=1, to=50, textvariable=rows, width=6).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Columns", style="Side.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(f, from_=1, to=50, textvariable=cols, width=6).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Rotation", style="Side.TLabel").grid(row=3, column=0, sticky="w")
        cb = ttk.Combobox(f, textvariable=rot, values=("0", "90", "180", "270"), width=6, state="readonly")
        cb.grid(row=3, column=1, sticky="w", pady=3)
        cb.bind("<<ComboboxSelected>>", defaults)
        ttk.Checkbutton(f, text="Packed like the printed matrices (pitch = footprint + gap)",
                        variable=packed, command=defaults).grid(row=4, column=0, columnspan=3,
                                                                sticky="w", pady=(8, 3))
        ttk.Label(f, text="Pitch X (mm)", style="Side.TLabel").grid(row=5, column=0, sticky="w")
        ex = ttk.Entry(f, textvariable=px, width=8)
        ex.grid(row=5, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Pitch Y (mm)", style="Side.TLabel").grid(row=6, column=0, sticky="w")
        ey = ttk.Entry(f, textvariable=py, width=8)
        ey.grid(row=6, column=1, sticky="w", pady=3)
        ttk.Checkbutton(f, text="Bolts at the footprint corners", variable=bolts).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(8, 3))
        msg = ttk.Label(f, style="Bad.TLabel")
        msg.grid(row=8, column=0, columnspan=3, sticky="w")
        defaults()
        result = {}

        def ok(*_):
            try:
                r, c_ = int(rows.get()), int(cols.get())
                a, b = float(px.get()), float(py.get())
                if r < 1 or c_ < 1 or a <= 0 or b <= 0:
                    raise ValueError
            except (ValueError, tk.TclError):
                msg.config(text="Rows, columns and pitches must be positive numbers.")
                return
            result["spec"] = (r, c_, a, b, bolts.get())
            self.place_rot = int(rot.get())
            top.destroy()

        btns = ttk.Frame(f, style="Side.TFrame")
        btns.grid(row=9, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right")
        ttk.Button(btns, text="Place", style="Accent.TButton", command=ok).pack(side="right", padx=6)
        top.bind("<Return>", ok)
        top.bind("<Escape>", lambda e: top.destroy())
        self._modal(top)
        if "spec" in result:
            self.mspec = result["spec"]
            return True
        return False

    def rules_dialog(self):
        top, f = self._dialog("Rules — distances in mm")
        ttk.Label(f, text="Rules", style="Side.TLabel", font=theme.FONT_TITLE).grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(f, text="Every actuator has the construction of the printed matrices "
                          "(3 plates, 2 membranes, two NO valves in series under a dome). "
                          "These are the distances between things, in mm.",
                  wraplength=520, style="Muted.TLabel").grid(row=1, column=0, columnspan=4,
                                                             sticky="w", pady=(2, 10))
        ttk.Label(f, text="PROVEN", style="Head.TLabel").grid(row=2, column=2, sticky="w")
        cur = asdict(self.lay.rules)
        vars_, help_ = {}, ttk.Label(f, style="Muted.TLabel", wraplength=520, justify="left")
        for k, (name, label, hlp) in enumerate(Rules.describe()):
            ttk.Label(f, text=label, style="Side.TLabel").grid(row=k + 3, column=0, sticky="w")
            v = tk.StringVar(value=_fmt(cur[name]))
            en = ttk.Entry(f, textvariable=v, width=9)
            en.grid(row=k + 3, column=1, padx=8, pady=2, sticky="w")
            en.bind("<FocusIn>", lambda e, h=hlp: help_.config(text=h))
            ttk.Label(f, text=_fmt(getattr(PROVEN, name)), style="Muted.TLabel").grid(
                row=k + 3, column=2, sticky="w")
            vars_[name] = v
        n = len(vars_) + 3
        help_.grid(row=n, column=0, columnspan=4, sticky="w", pady=(10, 0))
        warn = ttk.Label(f, style="Bad.TLabel", wraplength=520, justify="left")
        warn.grid(row=n + 1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        def read():
            return {name: float(v.get()) for name, v in vars_.items()}

        def ok(*_):
            try:
                vals = read()
            except ValueError:
                warn.config(text="Every value must be a number.")
                return
            new = replace(self.lay.rules, **vals)
            floors = new.floors()
            bad = [f"{name} must be ≥ {floors.get(name, 0):g}" for name, val in vals.items()
                   if val < floors.get(name, 0) or (val <= 0 and name != "act_gap")]
            if vals["act_gap"] < 0:
                bad.append("act_gap can't be negative")
            if bad:
                warn.config(text="; ".join(bad))
                return
            below = [label for name, label, _ in Rules.describe()
                     if vals[name] < getattr(PROVEN, name) - 1e-9 and name not in ("bolt_d", "nut_af")]
            if below and not getattr(ok, "confirmed", False):
                warn.config(text="Below the printed matrices (untested): " + ", ".join(below)
                            + ". Press OK again to use them anyway.")
                ok.confirmed = True
                return
            if new != self.lay.rules:
                self._push()
                self.lay.rules = new
                self._changed("Rules changed." + (f" {len(drc.check(self.lay))} problem(s) now."
                                                  if drc.check(self.lay) else ""))
            top.destroy()

        def reset():
            for name, v in vars_.items():
                v.set(_fmt(getattr(PROVEN, name)))
            warn.config(text="")

        btns = ttk.Frame(f, style="Side.TFrame")
        btns.grid(row=n + 2, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Button(btns, text="Reset to proven", command=reset).pack(side="left")
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="right")
        ttk.Button(btns, text="OK", style="Accent.TButton", command=ok).pack(side="right", padx=6)
        top.bind("<Return>", ok)
        top.bind("<Escape>", lambda e: top.destroy())
        self._modal(top)

    def help_keys(self):
        messagebox.showinfo("Shortcuts", "\n".join([
            "V  select      A  actuator      B  bolt      M  matrix",
            "R  rotate 90° (the selection, or the piece you are placing)",
            "Arrows  nudge one snap step (Shift: ten)",
            "Del  delete      Esc  back to select / clear selection",
            "Wheel  zoom      Middle or right drag  pan      F  fit",
            "Ctrl+Z / Ctrl+Y  undo / redo      Ctrl+A  select all",
            "Ctrl+N / O / S  new / open / save",
            "Ctrl+G  generate 3D      Ctrl+E  export STL",
            "",
            "Shift+click adds to the selection; drag on empty space to box-select.",
            "",
            "3D view: drag to orbit, right/middle drag to pan, wheel to zoom.",
        ]), parent=self.root)

    def help_logic(self):
        messagebox.showinfo("How the logic works", "\n".join([
            "Each actuator is a dome over two normally-open membrane valves in series:",
            "",
            "  supply → valve 1 (row line) → valve 2 (column line) → dome",
            "",
            "Pressurising a line closes every valve it feeds. With the supply on, a dome "
            "rises only while both of its lines are vented — the way a keyboard matrix "
            "picks one key with a row and a column.",
            "",
            "Rows are named R1, R2… from the top, columns C1, C2… from the left. Give an "
            "actuator another line name to wire it however you like; actuators with the "
            "same name share that line and its inlet.",
            "",
            "Generate 3D routes every line through the bottom plate (crossing lines take "
            "different levels) and the supply through the middle plate.",
        ]), parent=self.root)

    def about(self):
        messagebox.showinfo("About", f"mfcad Layout {__version__}\n\n"
                            "Layout and 3D generation of membrane-valve actuator matrices: three "
                            "rigid plates and two membranes, each actuator a dome over two "
                            "normally-open valves in series.", parent=self.root)

    # ======================================================== 3D: generate
    def _need_3d(self) -> bool:
        try:
            import numpy  # noqa: F401
            import manifold3d  # noqa: F401
        except ImportError:
            messagebox.showerror(
                "3D needs two more packages",
                "Generating the plates needs numpy and manifold3d.\n\n"
                "Install them with:\n    pip install numpy manifold3d\n\n"
                "(The ready-made downloads already include them.)", parent=self.root)
            return False
        return True

    def _task(self, title, work, done):
        """Run work(progress) in a thread behind a small progress window,
        then done(result) back on the Tk thread."""
        top = tk.Toplevel(self.root)
        top.title(title)
        top.transient(self.root)
        top.resizable(False, False)
        top.configure(bg=theme.SIDE)
        f = ttk.Frame(top, padding=18, style="Side.TFrame")
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=title, style="Side.TLabel", font=theme.FONT_BOLD).pack(anchor="w")
        msg = ttk.Label(f, text="Starting…", style="Muted.TLabel", width=46)
        msg.pack(anchor="w", pady=(4, 8))
        bar = ttk.Progressbar(f, mode="indeterminate", length=320)
        bar.pack(fill="x")
        bar.start(12)
        top.protocol("WM_DELETE_WINDOW", lambda: None)
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - top.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - top.winfo_height()) // 3
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        top.grab_set()
        q = queue.Queue()

        def run():
            try:
                q.put(("done", work(lambda s: q.put(("msg", s)))))
            except Exception as ex:          # noqa: BLE001 -- reported in the GUI
                q.put(("error", ex))

        threading.Thread(target=run, daemon=True).start()

        def poll():
            try:
                while True:
                    kind, val = q.get_nowait()
                    if kind == "msg":
                        msg.config(text=val)
                        continue
                    top.grab_release()
                    top.destroy()
                    if kind == "error":
                        messagebox.showerror(title, f"{type(val).__name__}: {val}", parent=self.root)
                    else:
                        done(val)
                    return
            except queue.Empty:
                pass
            top.after(60, poll)

        top.after(60, poll)

    def generate(self, then=None):
        if not self.lay.actuators:
            return self.say("Place some actuators first.", bad=True)
        if self.errors:
            self.nb.select(self.checks_tab)
            messagebox.showwarning("Fix the problems first",
                                   f"The layout breaks {len(self.errors)} rule(s); see Checks. "
                                   "The plates can only be generated from a layout that passes.",
                                   parent=self.root)
            return
        try:
            import numpy  # noqa: F401
        except ImportError:
            return self._need_3d()
        from .build3d import build_model
        from .route import route_layout
        lay = self.lay.copy()
        sig = self._sig()

        def work(say):
            r = route_layout(lay, progress=say)
            if not r.ok:
                return r, None
            say("Building the plates…")
            return r, build_model(lay, r)

        def done(res):
            r, m = res
            if not r.ok:
                self.say("Couldn't route: " + "; ".join(r.problems), bad=True)
                messagebox.showwarning(
                    "Couldn't route the channels",
                    "\n".join(r.problems) + "\n\nThings that help: more space between actuators "
                    "(Rules → extra gap), fewer bolts in the way, or another inlet face for that "
                    "line (Lines tab; 'auto' tries every face).", parent=self.root)
                return
            self.routing, self.model, self.routing_sig = r, m, sig
            self.say(f"Generated: {'; '.join(r.notes)}. Drag in the 3D view to look around.")
            self.redraw()
            if then:
                then()
            else:
                self.open_viewer()

        self._task("Generating the plates", work, done)

    def open_viewer(self):
        from .viewer import Viewer3D
        if self.viewer is not None:
            try:
                self.viewer.top.destroy()
            except tk.TclError:
                pass
        name = self.path.stem if self.path else "untitled"
        self.viewer = Viewer3D(self.root, self.model, title=f"{name} — 3D view",
                               on_export=self.export_3d)

    def export_3d(self):
        if not self._routes_current():
            return self.generate(then=self.export_3d)
        if not self._need_3d():
            return
        stem = self.path.stem if self.path else "layout"
        parent = self.viewer.top if self.viewer and self.viewer.top.winfo_exists() else self.root
        folder = filedialog.askdirectory(parent=parent, title="Folder for the STL files",
                                         initialdir=str(self.path.parent) if self.path else None)
        if not folder:
            return
        from . import build3d
        lay, model = self.lay.copy(), self.model

        def work(say):
            return build3d.export(lay, model, folder, stem, progress=say)

        def done(res):
            written, problems = res
            self._export_done(folder, written, problems)

        self._task("Exporting the plates", work, done)

    def _export_done(self, folder, written, problems):
        top, f = self._dialog("Exported")
        ok = not problems
        ttk.Label(f, text="✓  Ready to print" if ok else "✗  Exported, but the checks found problems",
                  style="Good.TLabel" if ok else "Bad.TLabel", font=theme.FONT_TITLE).pack(anchor="w")
        ttk.Label(f, text=f"In {folder}:", style="Muted.TLabel").pack(anchor="w", pady=(6, 2))
        for p in written:
            ttk.Label(f, text="   " + Path(p).name, style="Side.TLabel", font=theme.FONT_MONO).pack(anchor="w")
        for q in problems:
            ttk.Label(f, text="! " + q, style="Bad.TLabel", wraplength=480).pack(anchor="w")
        ttk.Label(f, text="The STLs are already contact face down. The README says which inlet is "
                          "which and how to assemble.", style="Muted.TLabel", wraplength=480,
                  justify="left").pack(anchor="w", pady=(8, 0))
        btns = ttk.Frame(f, style="Side.TFrame")
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="OK", style="Accent.TButton", command=top.destroy).pack(side="right")
        ttk.Button(btns, text="Open folder", command=lambda: _open_folder(folder)).pack(side="right", padx=6)
        top.bind("<Return>", lambda e: top.destroy())
        top.bind("<Escape>", lambda e: top.destroy())
        self.say(f"Exported {len(written)} files to {folder}.")
        self._modal(top)

    # ================================================================== files
    def _ask_discard(self) -> bool:
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel("Unsaved changes", "Save the changes first?", parent=self.root)
        if ans is None:
            return False
        return self.save() if ans else True

    def _reset_state(self):
        self.undo.clear()
        self.redo.clear()
        self.sel.clear()
        self.routing = self.model = self.routing_sig = None
        self._line_rows_key = None

    def new(self):
        if not self._ask_discard():
            return
        self.lay, self.path, self.dirty = Layout(), None, False
        self._reset_state()
        self._refresh()
        self.fit_view()

    def open(self):
        if not self._ask_discard():
            return
        p = filedialog.askopenfilename(parent=self.root, filetypes=FILETYPES)
        if p:
            self._open_path(Path(p))

    def _open_path(self, p: Path):
        try:
            lay = Layout.load(p)
        except Exception as ex:          # noqa: BLE001 -- show any bad file as a message
            messagebox.showerror("Can't open", f"{p.name}: {ex}", parent=self.root)
            return self._refresh()
        self.lay, self.path, self.dirty = lay, p, False
        self._reset_state()
        self._refresh()
        self.fit_view()
        self.say(f"Opened {p.name}.")

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        try:
            self.lay.save(self.path)
        except OSError as ex:
            messagebox.showerror("Can't save", str(ex), parent=self.root)
            return False
        self.dirty = False
        self._refresh()
        self.say(f"Saved {self.path}.")
        return True

    def save_as(self) -> bool:
        p = filedialog.asksaveasfilename(parent=self.root, defaultextension=".mfl",
                                         filetypes=FILETYPES,
                                         initialfile=self.path.name if self.path else "layout.mfl")
        if not p:
            return False
        self.path = Path(p)
        return self.save()

    def _export(self, fn, what, suffix):
        stem = self.path.stem if self.path else "layout"
        p = filedialog.asksaveasfilename(parent=self.root, defaultextension=".svg",
                                         filetypes=[("SVG", "*.svg")],
                                         initialfile=f"{stem}_{suffix}.svg")
        if p:
            fn(self.lay, p)
            self.say(f"Exported the {what} to {p}.")

    def export_drawing(self):
        self._export(svgexport.drawing, "drawing", "drawing")

    def export_membrane(self):
        self._export(svgexport.membrane, "membrane template", "membrane")

    def quit(self):
        if self._ask_discard():
            self.root.destroy()


def _open_folder(folder):
    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)  # noqa: S606 -- the user's own export folder
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError:
        pass


def export_cli(src: str, folder: str | None) -> int:
    """mfcad-layout --export layout.mfl [folder]: the 3D files without the window."""
    from . import build3d
    from .route import route_layout
    p = Path(src)
    lay = Layout.load(p)
    errs = drc.check(lay)
    if errs:
        print(f"{p.name} breaks {len(errs)} rule(s):", *[f"  {e.message}" for e in errs], sep="\n")
        return 1
    r = route_layout(lay, progress=print)
    if not r.ok:
        print("couldn't route:", *r.problems, sep="\n  ")
        return 1
    out = Path(folder) if folder else p.with_suffix("")
    written, problems = build3d.export(lay, build3d.build_model(lay, r), out, p.stem, progress=print)
    print(*[f"wrote {w}" for w in written], sep="\n")
    for q in problems:
        print("PROBLEM:", q)
    return 1 if problems else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print("usage: mfcad-layout [layout.mfl]\n"
              "       mfcad-layout --export layout.mfl [folder]   (STL files, no window)")
        return 0
    if argv and argv[0] == "--export":
        if len(argv) < 2:
            print("usage: mfcad-layout --export layout.mfl [folder]")
            return 2
        return export_cli(argv[1], argv[2] if len(argv) > 2 else None)
    if argv and argv[0] in ("-V", "--version"):
        print(__version__)
        return 0
    root = tk.Tk()
    App(root, argv[0] if argv else None)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
