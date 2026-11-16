"""The layout: a rectangular plate, actuators and bolts on it, and the rules.

Everything is in millimetres, in the plate's frame: origin at the plate's
bottom-left corner, x to the right, y up (the same frame mfcad's 3D builders
use, seen from the top plate).

An *actuator* is one cell of the row/column matrices that work on the rig: a
dome window in the top plate and, under it, two normally-open membrane valves
in series (an AND of a row line and a column line). Its position is the dome
centre. Its construction is fixed (`Cell`); what a user may change are the
distances between things (`Rules`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
import json
import math
from pathlib import Path

FORMAT = "mfcad-layout"
VERSION = 1
SUPPLY = "S"
FACES = ("auto", "left", "right", "front", "back")


@dataclass(frozen=True)
class Cell:
    """One actuator as built in the printed matrices (mfcad `build_matrix`
    with `proven_geom`), relative to the dome centre, unrotated. The valve
    row runs along x; the link row is +y of the dome row."""
    col: float = 6.0            # the two valve columns, centre to centre
    seat_gap: float = 3.2       # a valve's two seats (dome row -> link row)
    pocket_d: float = 2.4       # relief pocket round each seat
    chamber_l: float = 3.8      # control chamber, along x
    chamber_w: float = 7.0      # control chamber, along y
    chamber_dy: float = 1.6     # chamber centre, +y of the dome row
    footprint_dy: float = 0.7   # cell (bolt-grid) centre, +y of the dome row
    wall: float = 1.2           # minimum printed wall between two features


CELL = Cell()


@dataclass(frozen=True)
class Rules:
    """Distances a user may set. The defaults are the printed 2x2 / 3x3."""
    pitch_x: float = 14.0       # actuator footprint along x = matrix pitch
    pitch_y: float = 11.9       # actuator footprint along y = matrix pitch
    act_gap: float = 0.0        # extra gap between two footprints
    act_edge: float = 4.8       # footprint to the plate edge
    window_d: float = 7.0       # dome window in the top plate
    bolt_d: float = 3.8         # bolt clearance hole (M3)
    nut_af: float = 5.9         # nut pocket across flats (M3)
    bolt_edge: float = 4.8      # bolt centre to the plate edge
    bolt_spacing: float = 8.0   # bolt centre to bolt centre (two nut pockets + wall)
    bolt_window: float = 2.0    # bolt hole to a dome window (membrane clamped between)
    bolt_feature: float = 0.7   # bolt hole to a chamber or a valve seat
    needle_depth: float = 7.0   # needle bore into a line inlet (3D)
    supply_depth: float = 8.0   # needle bore into the supply inlet (3D)

    @staticmethod
    def describe() -> list[tuple[str, str, str]]:
        """(field, label, help) in the order the rules dialog shows them."""
        return [
            ("pitch_x", "Actuator footprint X",
             "Width of the area one actuator owns. Two actuators side by side "
             "sit at least this far apart (the matrix pitch)."),
            ("pitch_y", "Actuator footprint Y",
             "Height of the area one actuator owns (the matrix pitch)."),
            ("act_gap", "Extra gap between actuators",
             "Added between two footprints. 0 = packed like the matrices."),
            ("act_edge", "Actuator to plate edge",
             "From a footprint to the plate edge."),
            ("window_d", "Dome window diameter",
             "Hole in the top plate the membrane balloons through."),
            ("bolt_d", "Bolt hole diameter", "Clearance hole, through all plates."),
            ("nut_af", "Nut pocket across flats", "Hex pocket in the bottom plate."),
            ("bolt_edge", "Bolt to plate edge", "Bolt centre to the plate edge."),
            ("bolt_spacing", "Bolt to bolt", "Bolt centre to bolt centre."),
            ("bolt_window", "Bolt hole to dome window",
             "Wall between a bolt hole and a window: the membrane is clamped there."),
            ("bolt_feature", "Bolt hole to chamber / seat",
             "Wall between a bolt hole and a control chamber or a valve seat "
             "(0.7 on the printed matrices)."),
            ("needle_depth", "Needle bore, line inlets",
             "How far the dispensing needle goes into a row/column inlet before "
             "it lands on the stop (3D only)."),
            ("supply_depth", "Needle bore, supply inlet",
             "The same for the supply inlet in the middle plate (3D only)."),
        ]

    def floors(self) -> dict[str, float]:
        """Hard lower limits: below these the cell itself does not fit."""
        c = CELL
        span_x = c.col + c.chamber_l
        up = c.chamber_dy + c.chamber_w / 2.0 - c.footprint_dy
        down = self.window_d / 2.0 + c.footprint_dy
        return {
            "pitch_x": round(max(span_x, self.window_d) + c.wall, 2),
            "pitch_y": round(2.0 * max(up, down) + c.wall, 2),
            "window_d": 1.0,
            "bolt_d": 1.0,
            "nut_af": self.bolt_d,
            "needle_depth": 2.0,
            "supply_depth": 2.0,
        }


PROVEN = Rules()


def _rot(x: float, y: float, deg: int) -> tuple[float, float]:
    deg %= 360
    if deg == 0:
        return x, y
    if deg == 90:
        return -y, x
    if deg == 180:
        return -x, -y
    if deg == 270:
        return y, -x
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def _rect(cx, cy, w, h, ox, oy, deg):
    """Axis-aligned bounds of a local rect (centre cx, cy, size w x h) after
    rotating by deg (a multiple of 90) and moving to (ox, oy)."""
    pts = [_rot(cx + sx * w / 2.0, cy + sy * h / 2.0, deg) for sx in (-1, 1) for sy in (-1, 1)]
    xs = [ox + p[0] for p in pts]
    ys = [oy + p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class Actuator:
    name: str
    x: float
    y: float
    rotation: int = 0            # 0, 90, 180, 270 degrees, counter-clockwise
    row_line: str = ""           # line on the supply-side valve; "" = automatic
    col_line: str = ""           # line on the dome-side valve; "" = automatic

    kind = "actuator"

    def footprint(self, rules: Rules):
        return _rect(0.0, CELL.footprint_dy, rules.pitch_x, rules.pitch_y,
                     self.x, self.y, self.rotation)

    def window(self, rules: Rules):
        return (self.x, self.y, rules.window_d / 2.0)

    def seats(self):
        """Valve seats (relief pockets) as circles (x, y, r)."""
        out = []
        for lx in (-CELL.col / 2.0, CELL.col / 2.0):
            for ly in (0.0, CELL.seat_gap):
                dx, dy = _rot(lx, ly, self.rotation)
                out.append((self.x + dx, self.y + dy, CELL.pocket_d / 2.0))
        return out

    def chambers(self):
        """Control chambers as rects (x0, y0, x1, y1): column valve, row valve."""
        return [_rect(lx, CELL.chamber_dy, CELL.chamber_l, CELL.chamber_w,
                      self.x, self.y, self.rotation)
                for lx in (-CELL.col / 2.0, CELL.col / 2.0)]

    def corners(self, rules: Rules):
        x0, y0, x1, y1 = self.footprint(rules)
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def feeds(self):
        """Chamber feed points (x, y): column valve, row valve. The control
        line drops into each chamber at its centre."""
        out = []
        for lx in (-CELL.col / 2.0, CELL.col / 2.0):
            dx, dy = _rot(lx, CELL.chamber_dy, self.rotation)
            out.append((self.x + dx, self.y + dy))
        return out

    def local(self, lx: float, ly: float) -> tuple[float, float]:
        """A point of the unrotated cell (dome at 0, 0) in plate coordinates."""
        dx, dy = _rot(lx, ly, self.rotation)
        return self.x + dx, self.y + dy

    def to_dict(self):
        d = {"name": self.name, "x": round(self.x, 4), "y": round(self.y, 4),
             "rotation": self.rotation}
        if self.row_line:
            d["row_line"] = self.row_line
        if self.col_line:
            d["col_line"] = self.col_line
        return d


@dataclass
class Bolt:
    name: str
    x: float
    y: float

    kind = "bolt"

    def to_dict(self):
        return {"name": self.name, "x": round(self.x, 4), "y": round(self.y, 4)}


@dataclass
class Layout:
    width: float = 60.0
    length: float = 50.0
    rules: Rules = field(default_factory=Rules)
    actuators: list[Actuator] = field(default_factory=list)
    bolts: list[Bolt] = field(default_factory=list)
    grid: float = 0.5
    faces: dict[str, str] = field(default_factory=dict)   # line -> inlet face

    # ---- lookup and naming ----
    def items(self):
        return [*self.actuators, *self.bolts]

    def get(self, name: str):
        for it in self.items():
            if it.name == name:
                return it
        return None

    def next_name(self, prefix: str) -> str:
        used = {it.name for it in self.items()}
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        return f"{prefix}{n}"

    def remove(self, names) -> None:
        names = set(names)
        self.actuators = [a for a in self.actuators if a.name not in names]
        self.bolts = [b for b in self.bolts if b.name not in names]

    # ---- files ----
    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "version": VERSION,
            "units": "mm",
            "plate": {"width": round(self.width, 4), "length": round(self.length, 4)},
            "construction": "3 rigid plates (top, middle, bottom) + 2 membranes; "
                            "actuator = mfcad matrix cell (2 NO valves in series + dome)",
            "rules": asdict(self.rules),
            "editor": {"grid": self.grid},
            "actuators": [a.to_dict() for a in self.actuators],
            "bolts": [b.to_dict() for b in self.bolts],
            "lines": {k: {"face": v} for k, v in sorted(self.faces.items()) if v != "auto"},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Layout":
        if d.get("format") != FORMAT:
            raise ValueError("not an mfcad layout file")
        if int(d.get("version", 0)) > VERSION:
            raise ValueError(f"made by a newer version (file v{d['version']}, "
                             f"this program reads up to v{VERSION})")
        known = {f.name for f in fields(Rules)}
        rules = replace(PROVEN, **{k: float(v) for k, v in d.get("rules", {}).items() if k in known})
        acts = [Actuator(str(a["name"]), float(a["x"]), float(a["y"]), int(a.get("rotation", 0)) % 360,
                         str(a.get("row_line", "")).strip(), str(a.get("col_line", "")).strip())
                for a in d.get("actuators", [])]
        faces = {str(k): str(v.get("face", "auto")) for k, v in d.get("lines", {}).items()
                 if str(v.get("face", "auto")) in FACES}
        bolts = [Bolt(str(b["name"]), float(b["x"]), float(b["y"])) for b in d.get("bolts", [])]
        names = [it.name for it in (*acts, *bolts)]
        if len(names) != len(set(names)):
            raise ValueError("two items share a name")
        lay = cls(width=float(d["plate"]["width"]), length=float(d["plate"]["length"]),
                  rules=rules, actuators=acts, bolts=bolts,
                  grid=float(d.get("editor", {}).get("grid", 0.5)), faces=faces)
        return lay

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Layout":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def copy(self) -> "Layout":
        return Layout.from_dict(self.to_dict())


def default_pitch(rules: Rules, rotation: int = 0) -> tuple[float, float]:
    """Packed matrix pitch in plate x and y for actuators at this rotation."""
    fw, fh = rules.pitch_x + rules.act_gap, rules.pitch_y + rules.act_gap
    return (fh, fw) if rotation % 180 else (fw, fh)


def matrix(rows: int, cols: int, rules: Rules = PROVEN, pitch_x: float | None = None,
           pitch_y: float | None = None, rotation: int = 0, origin=(0.0, 0.0),
           corner_bolts: bool = True, start: int = 1):
    """A rows x cols block of actuators (and the bolts at their footprint
    corners), the first dome at `origin`. Returns (actuators, bolt points)."""
    fw, fh = default_pitch(rules, rotation)
    px = fw if pitch_x is None else pitch_x
    py = fh if pitch_y is None else pitch_y
    acts = []
    n = start
    for j in range(rows):
        for i in range(cols):
            acts.append(Actuator(f"A{n}", origin[0] + i * px, origin[1] + j * py, rotation % 360))
            n += 1
    pts = []
    if corner_bolts:
        for a in acts:
            for p in a.corners(rules):
                if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-6 for q in pts):
                    pts.append(p)
    return acts, pts


def resolve_lines(lay: Layout, tol: float = 1.0) -> dict[str, tuple[str, str]]:
    """(row line, column line) of every actuator.

    Automatic names work like a keyboard matrix: domes at the same height
    (within `tol` mm) share a row line, numbered R1, R2... from the top, and
    domes in the same vertical share a column line, C1, C2... from the left.
    A name typed on an actuator overrides its automatic one; actuators with
    the same name share that line.
    """
    def groups(vals, reverse):
        order = sorted(set(vals), reverse=reverse)
        names, n, last = {}, 0, None
        for v in order:
            if last is None or abs(v - last) > tol:
                n += 1
                last = v
            names[v] = n
        return names

    # number only the actuators left on automatic, so a renamed one leaves no gap
    rows = groups([a.y for a in lay.actuators if not a.row_line], True)
    cols = groups([a.x for a in lay.actuators if not a.col_line], False)
    return {a.name: (a.row_line or f"R{rows[a.y]}", a.col_line or f"C{cols[a.x]}")
            for a in lay.actuators}


def line_members(lay: Layout) -> dict[str, list[tuple[str, str]]]:
    """line -> [(actuator, 'row' | 'col')], rows first, in name order."""
    out: dict[str, list[tuple[str, str]]] = {}
    for name, (r, c) in resolve_lines(lay).items():
        out.setdefault(r, []).append((name, "row"))
        out.setdefault(c, []).append((name, "col"))
    return dict(sorted(out.items(), key=lambda kv: _line_key(kv[0])))


def _line_key(name: str):
    import re
    m = re.fullmatch(r"([A-Za-z]*)(\d*)(.*)", name)
    pre, num, rest = m.groups() if m else (name, "", "")
    rank = {"R": 0, "C": 1}.get(pre.upper(), 2)
    return (rank, pre, int(num) if num else -1, rest)
