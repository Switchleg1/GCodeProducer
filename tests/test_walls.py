"""Walls around holes go into the material (regression: they were offset into the hole)."""
import numpy as np
import pytest

from conftest import box_tris, frame_tris, model_support, ring_tris, write_tris
from gcodeproducer.core import geometry, sim
from gcodeproducer.core import workflow as wf
from gcodeproducer.core.pipeline import SlicePipeline
from gcodeproducer.core.placement import Placement
from gcodeproducer.core.session import build_job, load_mesh, slice_job


def _square(a, b):
    return np.array([[a, a], [b, a], [b, b], [a, b]], float)


def test_hole_flags_and_offset_direction():
    outer, hole = _square(0, 30), _square(10, 20)
    assert geometry.hole_flags([outer, hole]) == [False, True]
    assert abs(geometry.area(geometry.offset_into_material(outer, 1, False)[0])) == pytest.approx(28 * 28)
    assert abs(geometry.area(geometry.offset_into_material(hole, 1, True)[0])) == pytest.approx(12 * 12)


def test_perimeter_loops_hole_walls_in_material():
    loops = geometry.perimeter_loops([_square(0, 30), _square(10, 20)], 0.5, 2)
    outer, hole = loops
    assert [abs(geometry.area(l)) for l in outer] == pytest.approx([29.5 ** 2, 28.5 ** 2])   # shrink
    assert [abs(geometry.area(l)) for l in hole] == pytest.approx([10.5 ** 2, 11.5 ** 2])    # grow


def test_thin_rim_limits_hole_walls():
    # 1 mm of material between the hole and the outside: room for one 0.45 mm wall around the hole
    loops = geometry.perimeter_loops([_square(0, 12), _square(1, 11)], 0.45, 4)
    hole_loops = loops[1]
    assert 1 <= len(hole_loops) < 4
    assert all(geometry.point_in_polygon(p, _square(0, 12)) for l in hole_loops for p in l)


def _slice(libset, path, walls=2, support=True, placement=None):
    pipe = SlicePipeline.default(wf.FDM)
    pipe.step("fdm_perimeters").params["perimeters"] = walls
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path), placement=placement,
                    support=model_support({}, support)[0])
    p = slice_job(job, pipe).program
    return p, sim.simulate(p)


def _sample(s, mask, step=0.05):
    out = []
    for x0, y0, x1, y1 in zip(s.px[mask], s.py[mask], s.x[mask], s.y[mask]):
        t = np.linspace(0, 1, max(2, int(np.hypot(x1 - x0, y1 - y0) / step)))
        out.append(np.stack([x0 + (x1 - x0) * t, y0 + (y1 - y0) * t], 1))
    return np.concatenate(out) if out else np.zeros((0, 2))


@pytest.mark.parametrize("walls", [1, 2, 4])
def test_round_hole_walls_and_infill_in_material(libset, tmp_path, walls):
    path = write_tris(tmp_path / "ring.stl", ring_tris(0, 0, 20.0, 8.0, 0, 3))
    p, s = _slice(libset, path, walls, support=False)
    feat = np.array([ln.feature for ln in p.lines])
    for f in ("outer_perimeter", "inner_perimeter", "infill", "solid_infill", "top_infill"):
        m = (feat == f) & s.extruding
        if m.any():
            r = np.hypot(*(_sample(s, m) - 110).T)
            assert r.min() > 8.0, f                       # nothing printed inside the hole
    m = np.isin(feat, ["outer_perimeter", "inner_perimeter"]) & s.extruding
    r = np.hypot(*(_sample(s, m) - 110).T)
    hole_walls = np.unique(np.round(r[r < 14], 1))
    assert hole_walls.min() == pytest.approx(8.0 + 0.225, abs=0.1)     # first wall half a width into material
    assert len(np.unique(np.round(hole_walls * 2) / 2)) == walls


def test_square_hole_walls_in_material(libset, tmp_path):
    path = write_tris(tmp_path / "frame.stl", frame_tris(0, 0, 30, 30, 10, 10, 20, 20, 0, 3))
    p, s = _slice(libset, path, 2, support=False)
    feat = np.array([ln.feature for ln in p.lines])
    pts = _sample(s, np.isin(feat, ["outer_perimeter", "inner_perimeter", "infill", "solid_infill",
                                    "top_infill"]) & s.extruding) - 95          # frame placed at 95..125
    in_hole = (pts[:, 0] > 10 + 1e-3) & (pts[:, 0] < 20 - 1e-3) & (pts[:, 1] > 10 + 1e-3) & (pts[:, 1] < 20 - 1e-3)
    assert not in_hole.any()


@pytest.mark.parametrize("r_in", [2.0, 5.0, 8.0])
def test_hole_walls_sit_on_support(libset, tmp_path, r_in):
    """Every wall around the hole of a lifted ring has support under it (sampled along the walls)."""
    path = write_tris(tmp_path / "ring.stl", ring_tris(0, 0, 20.0, r_in, 0, 3))
    p, s = _slice(libset, path, 3, placement=Placement(z=5))
    lay = np.array([ln.layer for ln in p.lines])
    feat = np.array([ln.feature for ln in p.lines]).astype(str)
    first = int(lay[feat == "outer_perimeter"].min())
    walls = _sample(s, np.isin(feat, ["outer_perimeter", "inner_perimeter"]) & s.extruding & (lay == first))
    walls = walls[np.hypot(*(walls - 110).T) < r_in + 3]                       # the hole's walls
    sup = _sample(s, np.char.startswith(feat, "support") & s.extruding & (lay == first - 2), 0.1)
    assert len(walls) and len(sup)
    wr = np.hypot(*(walls - 110).T)
    assert wr.min() > r_in                                  # walls in the material...
    sr = np.hypot(*(sup - 110).T)
    sa = np.degrees(np.arctan2(*(sup - 110).T[::-1])) % 360
    band = (wr.min() - 0.225, wr.max() + 0.225)              # radial band printed by the hole's walls
    for k in range(12):                                     # ...and on support all the way round
        m = (sa >= 30 * k) & (sa < 30 * (k + 1))
        assert m.any(), k
        assert sr[m].min() < r_in, k                        # support reaches past the hole edge
        in_band = sr[m][(sr[m] >= band[0]) & (sr[m] <= band[1])]
        assert len(in_band) > 0, k                          # and lies under the walls


def test_cam_profile_hole_offsets_away_from_material(libset, tmp_path):
    """CAM 'outside' profile: the outline grows by the tool radius, a hole shrinks (tool stays in the hole)."""
    path = write_tris(tmp_path / "frame.stl", frame_tris(0, 0, 30, 30, 10, 10, 20, 20, 0, 6))
    job = build_job(wf.CAM, libset.machines.get("generic-300-router"),
                    tools=[libset["tool"].get("3-mm-flat-endmill")], mesh=load_mesh(path))
    pipe = SlicePipeline.default(wf.CAM)
    slice_job(job, pipe)
    loops = job.layers[0].paths
    areas = sorted(abs(geometry.area(np.asarray(pth.points))) for pth in loops)
    assert areas[0] == pytest.approx((10 - 3) ** 2, rel=0.02)          # hole 10 mm, tool r 1.5 -> 7 mm
    assert areas[-1] == pytest.approx((30 + 3) ** 2, rel=0.02)         # outline 30 mm -> 33 mm
