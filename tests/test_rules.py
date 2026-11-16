"""The rules against the matrices that were printed and worked."""

import math

from mfcad_layout import drc
from mfcad_layout.model import PROVEN, Actuator, Bolt, Layout, default_pitch, matrix


def grid_layout(rows, cols, rotation=0):
    """A matrix laid out like mfcad's build_matrix: plate edge 4.8 mm past
    the bolt grid."""
    px, py = default_pitch(PROVEN, rotation)
    probe = Actuator("p", 0, 0, rotation).footprint(PROVEN)
    origin = (PROVEN.act_edge - probe[0], PROVEN.act_edge - probe[1])
    acts, pts = matrix(rows, cols, PROVEN, rotation=rotation, origin=origin)
    lay = Layout(width=cols * px + 2 * PROVEN.act_edge, length=rows * py + 2 * PROVEN.act_edge,
                 actuators=acts, bolts=[Bolt(f"B{i + 1}", x, y) for i, (x, y) in enumerate(pts)])
    return lay


def test_printed_matrices_pass():
    for n in (2, 3, 4):
        lay = grid_layout(n, n)
        assert drc.check(lay) == []
        assert len(lay.bolts) == (n + 1) ** 2
    # same plate as mfcad's 3x3: 3 x 14 + 2 x 4.8 by 3 x 11.9 + 2 x 4.8
    lay = grid_layout(3, 3)
    assert math.isclose(lay.width, 51.6) and math.isclose(lay.length, 45.3)


def test_rotated_matrix_passes():
    assert drc.check(grid_layout(2, 3, rotation=90)) == []


def test_overlap_and_gap():
    lay = Layout(width=100, length=100)
    lay.actuators = [Actuator("A1", 30, 30), Actuator("A2", 43.9, 30)]
    assert [v.rule for v in drc.check(lay)] == ["actuator overlap"]
    lay.actuators[1].x = 44.0                    # footprints touch: allowed
    assert drc.check(lay) == []
    lay.rules = lay.rules.__class__(act_gap=1.0)
    assert [v.rule for v in drc.check(lay)] == ["actuator gap"]


def test_bolt_rules():
    lay = Layout(width=100, length=100, actuators=[Actuator("A1", 50, 50)])
    near_window = Bolt("B1", 50, 50 - 3.5 - 1.9 - 1.0)      # 1 mm wall to the window
    assert drc.placement(lay, [near_window])[0].rule == "bolt to window"
    on_chamber = Bolt("B1", 50 + 3 + 1.9 + 1.9 + 0.3, 54.0)  # 0.3 mm to the chamber
    assert drc.placement(lay, [on_chamber])[0].rule == "bolt to valve"
    corner = Bolt("B1", *lay.actuators[0].corners(PROVEN)[2])
    assert drc.placement(lay, [corner]) == []
    lay.bolts = [corner]
    assert drc.placement(lay, [Bolt("B2", corner.x + 5, corner.y)])[0].rule == "bolt spacing"


def test_edges():
    lay = Layout(width=40, length=40, actuators=[Actuator("A1", 20, 20)])
    assert drc.check(lay) == []
    lay.actuators[0].x = 10
    assert drc.check(lay)[0].rule == "edge"
    assert drc.placement(lay, [Bolt("B1", 2, 20)])[0].rule == "edge"


def test_file_round_trip(tmp_path):
    lay = grid_layout(2, 2)
    lay.actuators[0].rotation = 90
    p = tmp_path / "x.mfl"
    lay.save(p)
    back = Layout.load(p)
    assert back.to_dict() == lay.to_dict()
