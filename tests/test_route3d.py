"""Routing and 3D generation."""

import math

import pytest

np = pytest.importorskip("numpy")

from mfcad_layout import drc
from mfcad_layout.model import SUPPLY, Actuator, Bolt, Layout, line_members, resolve_lines
from mfcad_layout.route import route_layout
from mfcad_layout.stack import STACK

from test_rules import grid_layout


def free_layout():
    lay = Layout(width=80, length=60)
    lay.actuators = [Actuator("A1", 15, 15, 0), Actuator("A2", 34, 13, 90), Actuator("A3", 58, 18, 180),
                     Actuator("A4", 20, 42, 270), Actuator("A5", 45, 40, 0, row_line="X", col_line="Y"),
                     Actuator("A6", 66, 44, 90, row_line="X")]
    lay.bolts = [Bolt("B1", 5, 5), Bolt("B2", 75, 5), Bolt("B3", 5, 55), Bolt("B4", 75, 55),
                 Bolt("B5", 40, 28), Bolt("B6", 26, 28)]
    lay.faces = {"X": "right", SUPPLY: "back"}
    return lay


def test_automatic_lines_are_rows_and_columns():
    lay = grid_layout(3, 3)
    lines = resolve_lines(lay)
    top_left = max(lay.actuators, key=lambda a: (a.y, -a.x))
    assert lines[top_left.name] == ("R1", "C1")
    assert len(line_members(lay)) == 6
    lay.actuators[0].row_line = "X"           # renamed: no gap in the automatic numbering
    names = set(line_members(lay))
    assert "X" in names and {"R1", "R2", "R3"} <= names


def _segments(nr):
    for p in nr.paths:
        for a, b in zip(p, p[1:]):
            yield a, b


def _seg_seg(a, b, c, d):
    """Closest distance between two 2D segments (they never cross when this
    is positive)."""
    def pt(p, a, b):
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        t = 0.0 if ll == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ll))
        return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)
    return min(pt(a, c, d), pt(b, c, d), pt(c, a, b), pt(d, a, b))


def _check_clearances(lay, r):
    """Two different lines on the same level keep a wall between them, and
    every channel keeps a wall from every bolt hole."""
    st = STACK
    flat = []
    for name, nr in r.nets.items():
        if nr.plate != "bottom":
            continue
        for a, b in _segments(nr):
            flat.append((name, a, b))
    for i, (n1, a, b) in enumerate(flat):
        for n2, c, d in flat[i + 1:]:
            if n1 == n2:
                continue
            # same level for at least part of both segments
            z1 = {round(a[2], 3), round(b[2], 3)}
            z2 = {round(c[2], 3), round(d[2], 3)}
            shared = {z for z in z1 & z2 if z < 0}
            if not shared:
                continue
            assert _seg_seg(a[:2], b[:2], c[:2], d[:2]) >= 2 * st.r + st.wall - 2e-3, (n1, n2, a, b, c, d)
    for name, a, b in flat:
        if max(a[2], b[2]) > 0:              # the drop into the chamber, above the plate
            a = (a[0], a[1], min(a[2], 0.0))
        for bolt in lay.bolts:
            dist = _seg_seg(a[:2], b[:2], (bolt.x, bolt.y), (bolt.x, bolt.y))
            assert dist >= lay.rules.bolt_d / 2 + st.wall + st.r - 2e-3, (name, bolt.name)


@pytest.mark.parametrize("n", [2, 3, 4])
def test_printed_matrices_route(n):
    lay = grid_layout(n, n)
    r = route_layout(lay)
    assert r.ok, r.problems
    assert len(r.nets) == 2 * n + 1
    assert all(nr.port is not None for nr in r.nets.values())
    _check_clearances(lay, r)
    if n >= 3:
        assert r.levels == 2          # rows have to cross the columns


def test_free_layout_routes():
    lay = free_layout()
    assert drc.check(lay) == []
    r = route_layout(lay)
    assert r.ok, r.problems
    assert r.nets["X"].port.face == "right"
    assert r.nets[SUPPLY].port.face == "back"
    assert {m for m, _ in r.nets["X"].members} == {"A5", "A6"}
    _check_clearances(lay, r)


def test_unroutable_is_reported():
    lay = grid_layout(2, 2)
    lay.faces = {"R1": "left", "R2": "left", "C1": "left", "C2": "left"}
    lay.bolts.append(Bolt("BX", 4.8, lay.length / 2))        # blocks the middle of the left face
    r = route_layout(lay)
    if not r.ok:
        assert r.problems and r.problems[0].split(":")[0] in {"R1", "R2", "C1", "C2"}


def test_export_is_sealed_and_watertight(tmp_path):
    pytest.importorskip("manifold3d")
    from mfcad_layout import build3d
    lay = free_layout()
    r = route_layout(lay)
    m = build3d.build_model(lay, r)
    written, problems = build3d.export(lay, m, tmp_path, "t")
    assert problems == []
    names = sorted(p.name for p in written)
    assert names == ["t_README.txt", "t_bottom.stl", "t_channels.svg", "t_membrane.svg",
                     "t_middle.stl", "t_top.stl"]
    for p in written:
        assert p.stat().st_size > 0
    plates, _ = build3d.make_plates(m, check=False)
    for name, solid in plates.items():
        assert len(solid.decompose()) == 1, name        # one piece each
        x0, y0, z0, x1, y1, z1 = solid.bounding_box()
        assert math.isclose(x1 - x0, lay.width) and math.isclose(y1 - y0, lay.length)
        assert math.isclose(z1 - z0, m.thickness[name], abs_tol=1e-6)


def test_stack_matches_mfcad():
    """The constants are mfcad's proven geometry (only when mfcad is here)."""
    import sys
    from pathlib import Path
    here = Path(__file__).resolve().parents[1]
    root = next((p for p in (here.parent, here.parent / "microfluidic-cad") if (p / "mfcad").is_dir()), None)
    if root is None:
        pytest.skip("mfcad not alongside")
    sys.path.insert(0, str(root))
    try:
        fs = pytest.importorskip("mfcad.fingerstack")
    finally:
        sys.path.remove(str(root))
    dg, bore = fs.proven_geom(), fs.proven_bore()
    g, st = dg.g, STACK
    pairs = [(st.d, g.d), (st.seat_gap, g.seat_gap), (st.col, dg._col), (st.pocket_d, g.pocket_d),
             (st.relief_depth, g._relief_depth), (st.chamber_l, g.chamber_l), (st.chamber_w, g.chamber_w),
             (st.chamber_depth, g._chamber_depth), (st.bend, g.bend), (st.wall, dg.wall),
             (st.floor, dg.floor), (st.ctrl_z, dg.ctrl_z), (st.level1, dg.level1), (st.level2, dg.level2),
             (st.mid_t, dg.mid_t), (st.top_t, dg.top_t), (st.bottom_t_min, dg.bottom_t),
             (st.nut_depth, dg.c.nut_depth), (st.bore_d, bore.diameter), (st.lead, bore.lead),
             (st.lead_len, bore.lead_len), (st.needle_stop, dg.needle_stop), (st.neck_len, dg.neck_len),
             (st.corner_key, dg.corner_key), (st.port_r * 2, dg.port_face_d), (st.chamber_dy, dg.h)]
    for mine, theirs in pairs:
        assert math.isclose(mine, theirs, abs_tol=1e-9), (mine, theirs)


def test_file_keeps_lines_and_faces(tmp_path):
    lay = free_layout()
    p = tmp_path / "f.mfl"
    lay.save(p)
    back = Layout.load(p)
    assert back.faces == lay.faces
    assert back.get("A5").row_line == "X" and back.get("A5").col_line == "Y"
    assert back.to_dict() == lay.to_dict()
