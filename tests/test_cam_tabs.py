"""Model-owned holding rails, cutter-radius path splits, scheduling and exact travel guards."""
import numpy as np
import pytest
from shapely.geometry import LineString, box

from gcodeproducer.core.cam import CAMSetup, Depth, Operation, Reference, ToolGroup, Topology, generate
from gcodeproducer.core.cam_tabs import HoldingTab, tab_bounds, tab_pick, resolve_tabs, clip_paths, mask_at, contact
from gcodeproducer.core.cam_material import height_stock_for, simulate_material
from gcodeproducer.core.geometry import Mesh, load_stl
from gcodeproducer.core.job import Path
from gcodeproducer.core.placement import Placement
from gcodeproducer.core.session import build_job
from gcodeproducer.core.stock import Stock
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit


def cube_job(cube_stl, libset):
    mesh = Placement(z_anchor="top").apply(load_stl(cube_stl))
    tool = libset["tool"].get("3-mm-flat-endmill")
    machine = libset.machines.get("generic-300-router")
    tri = mesh.vertices[mesh.triangles]
    seed = int(np.flatnonzero(np.all(np.isclose(tri[:, :, 2], 0), axis=1))[0])
    op = Operation(kind="profile", name="Outside", geometry=[Reference("face", [seed])],
                   start=Depth("top"), end=Depth("bottom"), stepdown=1)
    setup = CAMSetup([ToolGroup(tool.id, [op])])
    setup.stock.auto(mesh)
    for origin, direction in (([30, 10, -10], [-1, 0, 0]), ([-10, 10, -10], [1, 0, 0])):
        result = tab_pick(mesh, setup, "tab", origin, direction)
        setup.tabs.append(HoldingTab(result["triangle"], result["barycentric"], 4, 4))
    return build_job("cam", machine, tools=[tool], mesh=mesh, cam_setup=setup), op


def test_tab_anchor_stock_edges_and_persistence(cube_stl, libset):
    job, _ = cube_job(cube_stl, libset)
    a, b = resolve_tabs(job.mesh, job.cam_setup)
    assert a[0] == pytest.approx([18, 8, -22]) and a[1] == pytest.approx([22, 12, -18])
    assert b[0] == pytest.approx([-2, 8, -22]) and b[1] == pytest.approx([2, 12, -18])
    loaded = CAMSetup.from_dict(job.cam_setup.to_dict())
    assert loaded.tabs == job.cam_setup.tabs
    assert CAMSetup.from_dict({"groups": []}).tabs == []
    # Translation re-evaluates a barycentric anchor, not a saved world point.
    moved = Mesh(job.mesh.vertices + [5, 3, 0], job.mesh.triangles)
    loaded.stock.x += 5; loaded.stock.y += 3
    lo, hi = tab_bounds(moved, loaded.stock, loaded.tabs[0])
    assert lo == pytest.approx(a[0]+[5, 3, 0]) and hi == pytest.approx(a[1]+[5, 3, 0])
    loaded.tabs[0].height = 100
    with pytest.raises(ValueError, match="thickness"):
        resolve_tabs(moved, loaded)


def test_tab_auto_direction_follows_rotation_and_rejects_tabs_below_part(cube_stl, libset):
    job, _ = cube_job(cube_stl, libset)
    r = np.array([[0,-1,0], [1,0,0], [0,0,1]])
    rotated = Mesh(job.mesh.vertices @ r.T, job.mesh.triangles)
    stock = Stock();stock.auto(rotated)
    lo, hi = tab_bounds(rotated, stock, job.cam_setup.tabs[0])
    assert lo == pytest.approx([-12,18,-22]) and hi == pytest.approx([-8,22,-18])
    job.cam_setup.tabs[0].height = 1
    with pytest.raises(ValueError, match="below the part"):
        resolve_tabs(job.mesh, job.cam_setup)
    job.cam_setup.tabs[0].height = 4
    job.cam_setup.stock.width = 0
    with pytest.raises(ValueError, match="allocated material"):
        resolve_tabs(job.mesh, job.cam_setup)


def test_profile_can_cut_through_blank_bottom_except_at_tabs(cube_stl, libset):
    job, op = cube_job(cube_stl, libset)
    op.end = Depth("absolute", job.cam_setup.stock.bounds[0][2])
    job.tools[0].values["length"] = 30
    generate(job, StageContext())
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    assert min(job.program.layer_z) == pytest.approx(-22)
    assert not job.warnings
    state = job.material_results[-1]["heights"]
    assert np.count_nonzero(np.isclose(state, -18)) > 0  # tabs retain full 4 mm height
    assert state.min() == pytest.approx(-22)             # the rest of the kerf goes to stock bottom


def test_compute_result_contains_current_tab_overlays(cube_stl, libset):
    from gcodeproducer.core.compute import run_slice
    from gcodeproducer.core.pipeline import SlicePipeline
    job, _ = cube_job(cube_stl, libset)
    out = run_slice(job, SlicePipeline.default("cam"))
    assert len(out["tab_bounds"]) == 2 and out["toolpath"] is not None
    assert out["tab_bounds"][0][1][2] == pytest.approx(-18)


def test_tab_pick_side_only_and_ray_box_removal(cube_stl, libset):
    job, _ = cube_job(cube_stl, libset)
    assert "error" in tab_pick(job.mesh, job.cam_setup, "tab", [10, 10, 10], [0, 0, -1])
    assert tab_pick(job.mesh, job.cam_setup, "tab", [50, 50, 10], [0, 0, -1]) is None
    hit = tab_pick(job.mesh, job.cam_setup, "tab_remove", [30, 10, -20], [-1, 0, 0])
    assert hit == {"remove": 0}


def test_split_preserves_seam_and_expands_by_cutter_radius():
    bounds = [(np.array([-1, -1, -4]), np.array([1, 1, -2]))]
    path = Path("cut", np.array([[-5., 0.], [5., 0.]]))
    mask = mask_at(bounds, -3, .5)
    pieces = clip_paths([path], mask)
    assert len(pieces) == 2 and all(not p.closed for p in pieces)
    assert pieces[0].points[-1, 0] < -1.5 and pieces[1].points[0, 0] > 1.5
    for p in pieces:
        a, b = (np.r_[q, -3] for q in (p.points[0], p.points[-1]))
        assert not contact(bounds, a, b, .5)
    assert mask_at(bounds, -2, .5).is_empty   # cut the stock above the tab normally
    square = Path("cut", np.array([[-5., -5.], [5., -5.], [5., 5.], [-5., 5.]]), closed=True)
    strip = box(3, -10, 8, 10)
    q = clip_paths([square], strip)
    assert len(q) == 1 and not q[0].closed  # seam fragments become ONE surviving open path
    assert LineString(q[0].points).length == pytest.approx(26)


def test_distant_tabs_preserve_links_but_links_crossing_tabs_are_reset():
    p = Path("cut", np.array([[5.,0.], [6.,0.], [6.,1.]]), closed=True,
             stay_down=True, stay_down_from=(-5.,0.))
    far = clip_paths([p], box(100,100,110,110))
    assert far[0].stay_down and far[0].stay_down_from == (-5.,0.)
    cross = clip_paths([p], box(-1,-1,1,1))
    assert not cross[0].stay_down and cross[0].stay_down_from is None


@pytest.mark.parametrize("order", ["area", "depth"])
def test_tabs_split_lower_passes_and_preserve_leads(cube_stl, libset, order):
    job, op = cube_job(cube_stl, libset)
    op.area_order = order
    generate(job, StageContext())
    upper = [l for l in job.layers if l.z >= -18]
    lower = [l for l in job.layers if l.z < -18]
    assert len(upper) == 18 and all(p.closed for l in upper for p in l.paths)
    assert all(not p.closed for l in lower for p in l.paths)
    assert [l.z for l in lower] == ([-19, -20, -19, -20] if order == "area" else [-19, -19, -20, -20])
    bounds = resolve_tabs(job.mesh, job.cam_setup)
    for layer in lower:
        for p in layer.paths:
            for a, b in zip(p.points, p.points[1:]):
                assert not contact(bounds, np.r_[a, layer.z], np.r_[b, layer.z], 1.5)
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    for layer in lower:
        lines = [ln for ln in job.program.lines if ln.layer == layer.index]
        assert any(ln.feature == "lead_in" for ln in lines)
    # Lead-outs carry on only where that is clear; a section ending against a tab retracts straight out.
    assert not any("lead-out" in w for w in job.warnings)
    assert not [w for w in job.warnings if "holding tab" in w or "rapid motion" in w]
    assert len(job.material_results) == 2
    # Protected stock survives in the height field at each rail, not only in the overlay.
    heights = job.material_results[-1]["heights"]
    assert heights.min() < -18 and np.count_nonzero(np.isclose(heights, -18)) > 0


def test_non_aligned_tab_top_gets_a_roof_pass(cube_stl, libset):
    job, _ = cube_job(cube_stl, libset)
    for tab in job.cam_setup.tabs:tab.height = 3.7  # top Z-18.3, between ordinary 1 mm passes
    generate(job, StageContext())
    roof = [l for l in job.layers if abs(l.z+18.3) < 1e-6]
    assert len(roof) == 1 and all(p.closed for p in roof[0].paths)
    assert all(not p.closed for l in job.layers if l.z < -18.3-1e-6 for p in l.paths)


def test_fractional_tab_roof_and_emitted_z_rounding_never_cut_into_rail(cube_stl, libset):
    job, op = cube_job(cube_stl, libset)
    op.stepdown = .70027125
    for tab in job.cam_setup.tabs:tab.height = 5.1934  # top -16.8066
    generate(job, StageContext())
    assert any(abs(l.z+16.806) < 1e-6 for l in job.layers)  # roof rounded upward
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    assert not [w for w in job.warnings if "holding tab" in w]


@pytest.mark.parametrize("order", ["area", "depth"])
@pytest.mark.parametrize("strategy", ["contour", "raster"])
def test_tabs_split_pocket_sectors_not_individual_offset_fronts(libset, order, strategy):
    from tests.test_pocket_bounds import stepped_part, floor_ref, job_for
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    op.area_order, op.strategy = order, strategy
    for x, direction, outward in ((30, [-1,0,0], "+x"), (-30, [1,0,0], "-x")):
        hit = tab_pick(mesh, job.cam_setup, "tab", [x,0,-2], direction)
        job.cam_setup.tabs.append(HoldingTab(hit["triangle"], hit["barycentric"], 3,
                                           job.cam_setup.stock.height, outward))
    generate(job, StageContext())
    # Two radial rails split the annular region into north/south sectors.
    assert len(job.layers) == 8
    assert [l.z for l in job.layers] == ([-1,-2,-3,-4]*2 if order == "area" else [-1,-1,-2,-2,-3,-3,-4,-4])
    assert all(len(l.paths) > 1 for l in job.layers)  # every offset/raster segment in a sector stays grouped
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    assert not [w for w in job.warnings if "holding tab" in w or "rapid motion" in w]


def test_exact_tab_guard_survives_grid_coarsening(cube_stl, libset):
    job, _ = cube_job(cube_stl, libset)
    job.preferences = {"stock_resolution": 5.0}
    job.cam_setup.tabs[0].width = .1
    live = height_stock_for(job, job.cam_setup.stock)
    a = np.array([17, 10, -20]); b = np.array([24, 10, -20])
    assert live.tab_contact(a, b, .01)
    assert live.max_height_along(a[:2], b[:2], .01) >= -18
    live.cut(a, b, 1)
    assert live.tab_contact(a, b, .01)  # cannot erase a tab to make the check pass
    from gcodeproducer.core.builder import GCodeBuilder
    builder = GCodeBuilder()
    builder.raw("G0 Z10\nM3 S12000\nG0 X17 Y10\nG1 Z-20 F100")
    builder.op = "bad custom cut"
    builder.set_feature("cut")
    builder.command("G1 X24 F100")
    warnings, _ = simulate_material(job, builder.program())
    assert any("protected holding tab" in w for w in warnings)
