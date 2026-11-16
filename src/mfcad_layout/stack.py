"""The fixed construction every actuator shares, in 3D.

These are the numbers mfcad's `build_matrix` uses with `proven_geom` and
`proven_bore` -- the matrices that were printed and worked on the rig. A test
compares them with mfcad itself when mfcad is importable.

World frame (the same as mfcad's): z = 0 is membrane 1. The bottom plate is
z in [-bottom_t, 0] with the control chambers opening upward at z = 0; the
middle plate z in [0, mid_t] with the valve seats on its underside; membrane 2
lies on it and the top plate is z in [mid_t, mid_t + top_t].
"""

from __future__ import annotations

from dataclasses import dataclass
import math

PROUD = 0.5          # how far a cut reaches past the face it opens on


@dataclass(frozen=True)
class Stack:
    d: float = 1.8                 # channel diameter
    seat_gap: float = 3.2          # a valve's two seats
    col: float = 6.0               # the two valve columns of a cell
    pocket_d: float = 2.4          # relief pocket round each seat
    relief_depth: float = 0.54
    chamber_l: float = 3.8         # control chamber across the valve column
    chamber_w: float = 7.0         # ... and along it
    chamber_depth: float = 1.35    # 45-degree tapered roof
    chamber_dy: float = 1.6        # chamber centre past the dome row
    bend: float = 1.35             # bend radius of the cell's own channels
    wall: float = 1.2              # side wall between two channels
    floor: float = 1.0             # solid layer between stacked channels
    edge_wall: float = 1.5         # channel to the plate's side faces
    ctrl_z: float = 3.25           # control level 0 below membrane 1
    level1: float = 3.0            # middle plate: link and outlet stubs
    level2: float = 5.8            # middle plate: the supply
    mid_t: float = 8.0
    top_t: float = 3.0
    bottom_t_min: float = 7.7      # level 0 over the nut pockets
    nut_depth: float = 2.5
    bore_d: float = 1.8            # needle bore (a 16G needle is 1.64)
    lead: float = 0.6              # funnel: +0.6 mm diameter at the face ...
    lead_len: float = 0.3 / math.tan(math.radians(5.0))   # ... over 3.4 mm
    needle_stop: float = 1.2       # neck the needle lands on
    neck_len: float = 1.0
    corner_key: float = 3.0        # chamfer on one corner of every plate

    @property
    def r(self) -> float:
        return self.d / 2.0

    @property
    def port_r(self) -> float:
        """Widest radius of a needle port (the funnel mouth)."""
        return (self.bore_d + self.lead) / 2.0

    @property
    def level_step(self) -> float:
        return self.d + self.floor

    def level_z(self, k: int) -> float:
        """Depth of bottom-plate control level k below membrane 1. Level 0
        passes under other chambers with a floor between; each next level
        passes under the one above it."""
        return self.ctrl_z + k * self.level_step

    def bottom_t(self, levels: int) -> float:
        t = max(self.bottom_t_min,
                self.level_z(levels - 1) + self.port_r + self.floor)
        return math.ceil(t * 10.0 - 1e-6) / 10.0

    def nut_level(self, k: int, levels: int, radius: float) -> bool:
        """Does a channel of `radius` on level k reach down into the nut
        pockets (so it must go round them in plan, not over them)?"""
        top_of_nut = self.bottom_t(levels) - self.nut_depth
        return self.level_z(k) + radius + self.floor > top_of_nut + 1e-9


STACK = Stack()
