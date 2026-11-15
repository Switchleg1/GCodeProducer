import numpy as np
import pytest

from conftest import model_support, write_boxes
from gcodeproducer.core import workflow as wf
from gcodeproducer.core.pipeline import SlicePipeline
from gcodeproducer.core.placement import Placement
from gcodeproducer.core.session import build_job, load_mesh, slice_job

T_SHAPE = [(10, 10, 0, 20, 20, 15), (0, 0, 15, 30, 30, 18)]                       # plate on a pillar
SHELF = [(0, 0, 0, 30, 30, 4), (0, 0, 4, 10, 10, 20), (0, 0, 20, 30, 30, 22)]       # overhang above a base


def _support_lines(libset, path, enabled=True, placement="buildplate", pl=None):
    pipe = SlicePipeline.default(wf.FDM)
    ms, _ = model_support({"placement": placement}, enabled)
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path), placement=pl, support=ms)
    res = slice_job(job, pipe)
    lines = [ln for ln in res.program.lines
             if ln.feature in ("support", "support_interface") and ln.cmd == "G1" and "E" in ln.params]
    return lines, res


def test_support_off_by_default():
    from gcodeproducer.core.support import ModelSupport
    assert ModelSupport().mode == "none"                       # a model starts without support
    assert SlicePipeline.default(wf.FDM).step("fdm_support").enabled


def test_t_shape_gets_support_from_bed(libset, tmp_path):
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    lines, res = _support_lines(libset, path)
    assert lines
    assert any(ln.feature == "support_interface" for ln in lines)
    top = max(ln.layer for ln in lines)
    z = res.program.layer_z
    assert z[top] < 15.0                                   # stays under the plate (z gap)
    assert min(ln.layer for ln in lines) == 0              # reaches the bed


def test_disabled_and_flipped_have_no_support(libset, tmp_path):
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    assert not _support_lines(libset, path, enabled=False)[0]
    assert not _support_lines(libset, path, pl=Placement(rx=180))[0]


def test_buildplate_vs_everywhere(libset, tmp_path):
    path = write_boxes(tmp_path / "shelf.stl", SHELF)
    lines, res = _support_lines(libset, path, placement="buildplate")
    assert not lines
    assert "build plate" in [s.summary for s in res.steps if s.stage == "fdm_support"][0]
    lines, res = _support_lines(libset, path, placement="everywhere")
    assert lines
    z = res.program.layer_z
    assert z[min(ln.layer for ln in lines)] > 4.0          # stands on the base, not on the bed


def test_support_keeps_clear_of_model(libset, tmp_path):
    from gcodeproducer.core import sim
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    lines, res = _support_lines(libset, path)
    s = sim.simulate(res.program)
    sup = np.array([ln.feature.startswith("support") for ln in res.program.lines]) & s.extruding
    xy = np.concatenate([np.stack([s.x[sup], s.y[sup]], axis=1), np.stack([s.px[sup], s.py[sup]], axis=1)])
    # pillar is 10x10 centred on the bed (105..115): support stays >= xy_distance away
    inside = (np.abs(xy[:, 0] - 110) < 5 + 0.5) & (np.abs(xy[:, 1] - 110) < 5 + 0.5)
    assert not inside.any()


def test_cli_stage_param_enables_support(tmp_path, monkeypatch, capsys):
    from gcodeproducer.cli import main
    monkeypatch.setenv("GCODEPRODUCER_LIBRARY", str(tmp_path / "lib"))
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    out = tmp_path / "t.gcode"
    assert main(["slice", path, "-o", str(out), "-q", "--support", "buildplate",
                 "-m", "fdm_support:density=20"]) == 0
    assert ";TYPE:support" in out.read_text()
    assert main(["slice", path, "-o", str(out), "-q", "-m", "fdm_support:typo=1"]) == 2   # typo reported


# ------------------------------------------------------------------ holes & edges
def _hole_plate(tmp_path, hole=8):
    from conftest import box_tris, frame_tris, write_tris
    h0, h1 = 22 - hole / 2, 22 + hole / 2          # hole centred at (22, 22) -> (117, 117) on the bed
    return write_tris(tmp_path / "hp.stl", box_tris(10, 10, 0, 16, 16, 15) +
                      frame_tris(0, 0, 30, 30, h0, h0, h1, h1, 15, 18))


def _support_pts(libset, path, mode="buildplate", blocks=None, **params):
    from gcodeproducer.core import sim
    pipe = SlicePipeline.default(wf.FDM)
    ms, proc = model_support({"placement": mode, **params})
    pipe.step("fdm_support").params.update(proc)
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path), support_blocks=blocks,
                    support=ms)
    p = slice_job(job, pipe).program
    s = sim.simulate(p)
    sel = np.array([ln.feature.startswith("support") for ln in p.lines]) & s.extruding
    # sample every support line every 0.1 mm
    out = []
    for x0, y0, x1, y1, z in zip(s.px[sel], s.py[sel], s.x[sel], s.y[sel], s.z[sel]):
        t = np.linspace(0, 1, max(2, int(np.hypot(x1 - x0, y1 - y0) / 0.1)))
        out.append(np.stack([x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, np.full_like(t, z)], 1))
    return np.concatenate(out) if out else np.zeros((0, 3))


def _count(pts, x0, y0, x1, y1, z=14.8):
    m = (np.abs(pts[:, 2] - z) < 1e-3) & (pts[:, 0] > x0) & (pts[:, 0] < x1) & (pts[:, 1] > y0) & (pts[:, 1] < y1)
    return int(m.sum())


@pytest.mark.parametrize("mode", ["buildplate", "blocks"])
def test_small_hole_is_supported_underneath(libset, tmp_path, mode):
    from gcodeproducer.core.support import SupportBlock
    path = _hole_plate(tmp_path, hole=8)                     # 64 mm2 < 100 mm2
    blocks = [SupportBlock(95, 95, 0, 125, 125, 30)]
    pts = _support_pts(libset, path, mode, blocks, fill_holes=100)
    assert _count(pts, 115, 115, 119, 119) > 0              # under the hole centre
    assert not (pts[:, 2] > 15.0 + 1e-6).any()              # never climbs into the hole / plate
    off = _support_pts(libset, path, mode, blocks, fill_holes=0, edge_margin=0)
    assert _count(off, 115, 115, 119, 119) == 0             # the old behaviour: a hole in the support


def test_edge_margin_supports_hole_perimeters(libset, tmp_path):
    path = _hole_plate(tmp_path, hole=14)                   # 196 mm2: stays open
    pts = _support_pts(libset, path, fill_holes=100)
    off = _support_pts(libset, path, edge_margin=0)
    ring = lambda q: _count(q, 109.5, 109.5, 110.5, 124.5) + _count(q, 123.5, 109.5, 124.5, 124.5)
    hole_edge = lambda q: _count(q, 110.2, 112, 110.8, 122)     # just inside the hole's wall
    assert hole_edge(pts) > hole_edge(off)                   # margin reaches under the hole perimeter
    assert _count(pts, 114, 114, 120, 120) == 0              # but the large hole itself stays open
    assert not (pts[:, 2] > 15.0 + 1e-6).any()


def test_margin_keeps_z_gap(libset, tmp_path):
    from gcodeproducer.core.support import SupportBlock
    path = _hole_plate(tmp_path, hole=14)
    pts = _support_pts(libset, path, "blocks", [SupportBlock(95, 95, 0, 125, 125, 30)], edge_margin=1.0)
    assert pts[:, 2].max() == pytest.approx(14.8)            # plate starts at 15.0: one empty layer


def test_support_polys_fill_holes():
    from gcodeproducer.core.job import Layer
    from gcodeproducer.core.support import support_polys
    sq = lambda a, b: np.array([[a, a], [b, a], [b, b], [a, b]], float)
    layer = Layer(0, 0.2, 0.2, outline=[sq(0, 30), sq(5, 9), sq(10, 25), sq(12, 14)])   # hole 16, hole 225 with island
    assert len(support_polys(layer, 0)) == 4
    kept = support_polys(layer, 100)                         # small hole filled, big hole (and island) kept
    assert len(kept) == 3 and not any(abs(abs(float(np.ptp(k[:, 0]))) - 4) < 1e-9 for k in kept)
    kept = support_polys(layer, 1000)                        # both holes filled; the island goes with its hole
    assert len(kept) == 1


@pytest.mark.parametrize("mode", ["buildplate", "blocks"])
@pytest.mark.parametrize("margin", [0.0, 1.0, 2.0, 3.0, 5.0])
def test_extend_past_model_edge(libset, tmp_path, mode, margin):
    """The support bead reaches the requested distance past the plate's edge (within the grid)."""
    from gcodeproducer.core import sim
    from gcodeproducer.core.support import SupportBlock
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)          # plate spans 95..125 on the bed
    pipe = SlicePipeline.default(wf.FDM)
    ms, _ = model_support({"placement": mode, "edge_margin": margin})
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path),
                    support_blocks=[SupportBlock(80, 80, 0, 140, 140, 15)], support=ms)
    p = slice_job(job, pipe).program
    s = sim.simulate(p)
    sel = np.array([ln.feature.startswith("support") for ln in p.lines]) & s.extruding
    xs = np.concatenate([s.x[sel], s.px[sel]])
    reach = max(xs.max() - 125, 95 - xs.min()) + 0.45 / 2        # bead edge past the model edge
    assert reach == pytest.approx(max(margin, 0.15), abs=0.3)


def test_extend_default_is_one_mm():
    from gcodeproducer.core.support import ModelSupport
    assert ModelSupport().extend == 1.0


def _ring_reach(libset, tmp_path, r_in, margin, fill):
    """Median / min / max bead reach past the outer and the inner circle of a lifted ring."""
    from conftest import ring_tris, write_tris
    from gcodeproducer.core import sim
    from gcodeproducer.core.placement import Placement
    path = write_tris(tmp_path / f"ring{r_in}.stl", ring_tris(0, 0, 20.0, r_in, 0, 3))
    pipe = SlicePipeline.default(wf.FDM)
    ms, _ = model_support({"placement": "buildplate", "edge_margin": margin, "fill_holes": fill})
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path), placement=Placement(z=5),
                    support=ms)
    p = slice_job(job, pipe).program
    s = sim.simulate(p)
    sel = np.array([ln.feature.startswith("support") for ln in p.lines]) & s.extruding
    pts = []
    for x0, y0, x1, y1 in zip(s.px[sel], s.py[sel], s.x[sel], s.y[sel]):
        t = np.linspace(0, 1, max(2, int(np.hypot(x1 - x0, y1 - y0) / 0.05)))
        pts.append(np.stack([x0 + (x1 - x0) * t, y0 + (y1 - y0) * t], 1))
    P = np.concatenate(pts) - 110.0
    r = np.hypot(P[:, 0], P[:, 1])
    b = (np.degrees(np.arctan2(P[:, 1], P[:, 0])) % 360 // 5).astype(int)
    outer = np.array([r[b == k].max() for k in range(72) if (b == k).any()]) + 0.225 - 20.0
    inner = r_in - (np.array([r[b == k].min() for k in range(72) if (b == k).any()]) - 0.225)
    return outer, inner


@pytest.mark.parametrize("margin", [0.5, 1.0, 2.0])
@pytest.mark.parametrize("r_in", [5.0, 8.0])
def test_round_hole_is_an_edge_like_the_outside(libset, tmp_path, margin, r_in):
    """The centre circle gets the same 'extend past edge' as the outer circle (holes are edges by default)."""
    outer, inner = _ring_reach(libset, tmp_path, r_in, margin, fill=0.0)
    assert np.median(outer) == pytest.approx(margin, abs=0.35)
    assert np.median(inner) == pytest.approx(margin, abs=0.35)
    assert abs(np.median(outer) - np.median(inner)) < 0.25          # same within the support grid
    assert inner.max() < margin + 0.6 and outer.max() < margin + 0.6     # round, not square, growth


def test_fill_holes_option_still_fills(libset, tmp_path):
    _outer, inner = _ring_reach(libset, tmp_path, 5.0, 1.0, fill=100.0)   # 78.5 mm2 hole -> filled
    assert inner.max() > 4.5                                               # support runs across the hole


def test_fill_holes_default_off():
    from gcodeproducer.core.support import ModelSupport
    assert ModelSupport().fill_holes == 0.0


# ------------------------------------------------------------------ gaps & interfaces
SHELF_EVERYWHERE = [(0, 0, 0, 30, 30, 4), (0, 0, 4, 10, 10, 20), (0, 0, 20, 30, 30, 22)]


def _layers(libset, tmp_path, boxes, mode, **params):
    from gcodeproducer.core import sim
    path = write_boxes(tmp_path / "m.stl", boxes)
    pipe = SlicePipeline.default(wf.FDM)
    ms, proc = model_support({"placement": mode, **params})
    pipe.step("fdm_support").params.update(proc)
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path), support=ms)
    p = slice_job(job, pipe).program
    s = sim.simulate(p)
    feat = np.array([ln.feature for ln in p.lines])
    lay = np.array([ln.layer for ln in p.lines])
    z = np.array(p.layer_z)
    sup = np.isin(feat, ["support", "support_interface"]) & s.extruding
    iface = (feat == "support_interface") & s.extruding
    return [round(float(v), 2) for v in z[np.unique(lay[sup])]], [round(float(v), 2) for v in z[np.unique(lay[iface])]]


@pytest.mark.parametrize("bgap,first", [(0, 4.2), (1, 4.4), (3, 4.8)])
def test_bottom_z_gap(libset, tmp_path, bgap, first):
    sup, _ = _layers(libset, tmp_path, SHELF_EVERYWHERE, "everywhere", bottom_z_gap_layers=bgap)
    assert sup[0] == pytest.approx(first)                   # base top is Z4.0
    assert sup[-1] == pytest.approx(19.8)                   # top gap unchanged


@pytest.mark.parametrize("tgap,last", [(0, 20.0), (1, 19.8), (3, 19.4)])
def test_top_z_gap_independent(libset, tmp_path, tgap, last):
    sup, _ = _layers(libset, tmp_path, SHELF_EVERYWHERE, "everywhere", z_gap_layers=tgap)
    assert sup[-1] == pytest.approx(last)                   # plate bottom is Z20.0
    assert sup[0] == pytest.approx(4.4)                     # bottom gap unchanged


def test_bottom_interface_layers(libset, tmp_path):
    _, iface = _layers(libset, tmp_path, SHELF_EVERYWHERE, "everywhere")
    assert iface == pytest.approx([4.4, 4.6, 19.6, 19.8])   # 2 floor + 2 roof by default
    _, iface = _layers(libset, tmp_path, SHELF_EVERYWHERE, "everywhere", bottom_interface_layers=4,
                       interface_layers=0)
    assert iface == pytest.approx([4.4, 4.6, 4.8, 5.0])
    _, iface = _layers(libset, tmp_path, SHELF_EVERYWHERE, "everywhere", bottom_interface_layers=0)
    assert iface == pytest.approx([19.6, 19.8])


def test_bottom_interface_on_the_bed(libset, tmp_path):
    _, iface = _layers(libset, tmp_path, T_SHAPE, "buildplate", bottom_interface_layers=3)
    assert iface == pytest.approx([0.2, 0.4, 0.6, 14.6, 14.8])     # floor on the bed + roof
    _, iface = _layers(libset, tmp_path, T_SHAPE, "buildplate", bottom_interface_layers=0)
    assert iface == pytest.approx([14.6, 14.8])                    # roof only


def test_bottom_gap_in_block_mode(libset, tmp_path):
    from gcodeproducer.core.support import SupportBlock
    path = write_boxes(tmp_path / "s.stl", SHELF_EVERYWHERE)
    pipe = SlicePipeline.default(wf.FDM)
    ms, proc = model_support({"placement": "blocks", "bottom_z_gap_layers": 2})
    pipe.step("fdm_support").params.update(proc)
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path),
                    support_blocks=[SupportBlock(110, 110, 0, 125, 125, 25)], support=ms)
    p = slice_job(job, pipe).program
    zs = [p.layer_z[ln.layer] for ln in p.lines if ln.feature.startswith("support") and ln.cmd == "G1"
          and ("X" in ln.params or "Y" in ln.params)]
    assert min(zs) == pytest.approx(4.6)                    # base top Z4.0 + 2 empty layers, also beside
                                                            # the base edge (within the XY distance)
