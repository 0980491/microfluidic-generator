"""Design-rule checks: what may sit where.

* Actuators own their footprint (the matrix pitch). Two footprints may touch
  -- that is how the matrices tile -- but not overlap, and must keep
  `act_gap` between them.
* A bolt may go anywhere its hole keeps `bolt_window` from every dome window
  and `bolt_feature` from every chamber and valve seat: at the footprint
  corners as on the matrices, between actuators, or outside them.
* Bolts keep `bolt_spacing` from each other (the nut pockets) and everything
  keeps its margin from the plate edge.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .model import Actuator, Bolt, Layout, Rules

EPS = 1e-6


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str
    items: tuple[str, ...]


def _circle_rect(cx, cy, r, rect) -> float:
    """Gap from a circle to a rect; negative when they overlap."""
    x0, y0, x1, y1 = rect
    dx = max(x0 - cx, 0.0, cx - x1)
    dy = max(y0 - cy, 0.0, cy - y1)
    if dx == 0.0 and dy == 0.0:            # centre inside
        return -r - min(cx - x0, x1 - cx, cy - y0, y1 - cy)
    return math.hypot(dx, dy) - r


def footprint_gap(a: Actuator, b: Actuator, rules: Rules) -> float:
    """Separation of two footprints (negative: they overlap)."""
    fa, fb = a.footprint(rules), b.footprint(rules)
    sx = max(fa[0], fb[0]) - min(fa[2], fb[2])
    sy = max(fa[1], fb[1]) - min(fa[3], fb[3])
    return max(sx, sy)


def bolt_walls(bolt: Bolt, act: Actuator, rules: Rules) -> tuple[float, float]:
    """(wall to the window, wall to the nearest chamber or seat)."""
    r = rules.bolt_d / 2.0
    wx, wy, wr = act.window(rules)
    w = math.hypot(bolt.x - wx, bolt.y - wy) - r - wr
    f = min([math.hypot(bolt.x - sx, bolt.y - sy) - r - sr for sx, sy, sr in act.seats()]
            + [_circle_rect(bolt.x, bolt.y, r, ch) for ch in act.chambers()])
    return w, f


def _pair(a, b, rules: Rules) -> Violation | None:
    if isinstance(a, Bolt) and isinstance(b, Actuator):
        a, b = b, a
    if isinstance(a, Actuator) and isinstance(b, Actuator):
        g = footprint_gap(a, b, rules)
        if g < -EPS:
            return Violation("actuator overlap", f"{a.name} and {b.name} overlap", (a.name, b.name))
        if g < rules.act_gap - EPS:
            return Violation("actuator gap", f"{a.name}–{b.name}: {g:.2f} mm apart, "
                             f"the gap is {rules.act_gap:g}", (a.name, b.name))
        return None
    if isinstance(a, Actuator) and isinstance(b, Bolt):
        fx0, fy0, fx1, fy1 = a.footprint(rules)
        reach = rules.bolt_d / 2.0 + max(rules.bolt_window, rules.bolt_feature) + 0.1
        if not (fx0 - reach <= b.x <= fx1 + reach and fy0 - reach <= b.y <= fy1 + reach):
            return None
        w, f = bolt_walls(b, a, rules)
        if w < rules.bolt_window - EPS:
            what = "on" if w < 0 else f"{w:.2f} mm from"
            return Violation("bolt to window", f"{b.name} is {what} {a.name}'s dome window "
                             f"(needs {rules.bolt_window:g})", (a.name, b.name))
        if f < rules.bolt_feature - EPS:
            what = "cuts into" if f < 0 else f"is {f:.2f} mm from"
            return Violation("bolt to valve", f"{b.name} {what} {a.name}'s valves "
                             f"(needs {rules.bolt_feature:g})", (a.name, b.name))
        return None
    d = math.hypot(a.x - b.x, a.y - b.y)
    if d < rules.bolt_spacing - EPS:
        return Violation("bolt spacing", f"{a.name}–{b.name}: {d:.2f} mm apart "
                         f"(needs {rules.bolt_spacing:g})", (a.name, b.name))
    return None


def _edge(it, lay: Layout) -> Violation | None:
    R = lay.rules
    if isinstance(it, Actuator):
        x0, y0, x1, y1 = it.footprint(R)
        e = R.act_edge
        m = min(x0, y0, lay.width - x1, lay.length - y1)
    else:
        e = R.bolt_edge
        m = min(it.x, it.y, lay.width - it.x, lay.length - it.y)
    if m < e - EPS:
        where = "outside the plate" if m < 0 else f"{m:.2f} mm from the plate edge"
        return Violation("edge", f"{it.name} is {where} (needs {e:g})", (it.name,))
    return None


def check(lay: Layout) -> list[Violation]:
    """Every rule over the whole layout."""
    out = []
    items = lay.items()
    for i, a in enumerate(items):
        v = _edge(a, lay)
        if v:
            out.append(v)
        for b in items[i + 1:]:
            v = _pair(a, b, lay.rules)
            if v:
                out.append(v)
    return out


def placement(lay: Layout, moving: list, ignore=()) -> list[Violation]:
    """Rules broken by `moving` (items at their new positions, in or out of
    the layout) against the rest of the layout and each other. Items named
    in `ignore` (their old selves) are skipped."""
    skip = set(ignore) | {it.name for it in moving}
    others = [it for it in lay.items() if it.name not in skip]
    out = []
    for i, a in enumerate(moving):
        v = _edge(a, lay)
        if v:
            out.append(v)
        for b in others + moving[i + 1:]:
            v = _pair(a, b, lay.rules)
            if v:
                out.append(v)
    return out


def describe_clearance(lay: Layout, it) -> str:
    """One line on how close the item is to its neighbours."""
    R = lay.rules
    if isinstance(it, Actuator):
        gaps = [(footprint_gap(it, a, R), a.name) for a in lay.actuators if a.name != it.name]
        walls = [(min(bolt_walls(b, it, R)), b.name) for b in lay.bolts]
        parts = []
        if gaps:
            g, n = min(gaps)
            parts.append(f"nearest actuator {max(g, 0):.2f} mm ({n})")
        if walls:
            w, n = min(walls)
            parts.append(f"nearest bolt wall {w:.2f} mm ({n})")
        return "; ".join(parts) or "alone on the plate"
    near = [(bolt_walls(it, a, R), a.name) for a in lay.actuators]
    parts = []
    if near:
        (w, f), n = min(near, key=lambda t: min(t[0]))
        parts.append(f"to {n}: window wall {w:.2f}, valve wall {f:.2f} mm")
    bs = [(math.hypot(it.x - b.x, it.y - b.y), b.name) for b in lay.bolts if b.name != it.name]
    if bs:
        d, n = min(bs)
        parts.append(f"nearest bolt {d:.2f} mm ({n})")
    return "; ".join(parts) or "alone on the plate"
