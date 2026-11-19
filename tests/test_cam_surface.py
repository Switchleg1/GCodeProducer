"""Depth-limited 3D Waterfall clearing and 3D Contour surface passes."""
import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box

from gcodeproducer.core.cam import CAMSetup, Depth, Operation, Reference, Topology, generate
from gcodeproducer.core.cam.cam_constants import KINDS, KIND_LABELS, SURFACE_KINDS, SURFACE_TOLERANCE
from gcodeproducer.core.cam.drop_surface import DropSurface
from gcodeproducer.core.cam.model_shadow import ModelShadow, clip_band
from gcodeproducer.core.cam.reference_shape import ReferenceShape
from gcodeproducer.core.cam.surface_paths import selection_region, simplify3d, surface_raster, waterfall_paths
from gcodeproducer.core.geometry import Mesh
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import job_for

RADIUS = 1.5            # the library's 3 mm endmill
POCKET = box(10, 8, 30, 22)


def box_triangles(lo, hi, offset=0):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
         (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v, [tuple(i+offset for i in t) for t in f]


def wedge_pocket():
    """40 x 30 x 20 block (top Z0) with a pocket whose floor falls from Z-2 (x=10) to Z-10 (x=30)."""
    v = [(0, 0, -20), (40, 0, -20), (40, 30, -20), (0, 30, -20), (0, 0, 0), (40, 0, 0), (40, 30, 0), (0, 30, 0),
         (10, 8, 0), (30, 8, 0), (30, 22, 0), (10, 22, 0), (10, 8, -2), (30, 8, -10), (30, 22, -10), (10, 22, -2)]
    f = [(0, 2, 1), (0, 3, 2), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    for i in range(4):
        a, b, c, d = 4+i, 4+(i+1) % 4, 8+(i+1) % 4, 8+i
        f += [(a, b, c), (a, c, d)]
    f += [(8, 13, 12), (8, 9, 13), (9, 10, 14), (9, 14, 13), (10, 11, 15), (10, 15, 14), (11, 8, 12), (11, 12, 15),
          (12, 13, 14), (12, 14, 15)]
    return Mesh(np.asarray(v, float), np.asarray(f))


def floor_z(x):
    return -2-.4*(np.asarray(x, float)-10)


def sloped_floor_edges(mesh):
    """The four floor edges: two of them slope, which used to be rejected."""
    topo = Topology(mesh)
    refs = [Reference("edge", sorted(int(i) for i in chain[:2])) for chain in topo.feature_chains
            if set(int(i) for i in chain) <= {12, 13, 14, 15}]
    assert len(refs) == 4
    return refs


def surface_job(libset, kind="waterfall", refs=None, **fields):
    mesh = wedge_pocket()
    job, op = job_for(mesh, refs or sloped_floor_edges(mesh), libset)
    op.kind = kind
    op.start = Depth("selection", extreme="max")
    for key, value in fields.items():
        setattr(op, key, value)
    return job, op


def assert_clear_of_model(job, tolerance=.02):
    """Every cutter position stays inside the pocket walls and above the sloped floor under its footprint."""
    checked = 0
    for layer in job.layers:
        for path in layer.paths:
            p = np.asarray(path.points, float)
            z = p[:, 2] if p.shape[1] == 3 else np.full(len(p), layer.z)
            inside = (p[:, 0] > 10+RADIUS-tolerance) & (p[:, 0] < 30-RADIUS+tolerance) & \
                     (p[:, 1] > 8+RADIUS-tolerance) & (p[:, 1] < 22-RADIUS+tolerance)
            # Below the top face the cutter must be within the walls, and never below the
            # highest floor point under its footprint (the floor rises toward smaller x).
            assert np.all(inside | (z >= -1e-6)), "cutter left the pocket below the top surface"
            limit = floor_z(np.maximum(p[:, 0]-RADIUS, 10))
            assert np.all(z[inside] >= limit[inside]-tolerance)
            checked += len(p)
    assert checked


def assert_program_clear(program, tolerance=.02):
    """Every emitted position (rapids, plunges, leads and cuts) respects the walls and the sloped floor."""
    from gcodeproducer.core.sim import simulate
    state = simulate(program)
    x, y, z = np.asarray(state.x), np.asarray(state.y), np.asarray(state.z)
    below = z < -1e-6
    assert below.any()
    inside = (x > 10+RADIUS-tolerance) & (x < 30-RADIUS+tolerance) & (y > 8+RADIUS-tolerance) & (y < 22-RADIUS+tolerance)
    assert np.all(inside[below])
    assert np.all(z[below] >= floor_z(np.maximum(x[below]-RADIUS, 10))-tolerance)


def test_kind_tables_cover_the_new_operations():
    assert {"waterfall", "contour3d"} <= set(KINDS) and set(SURFACE_KINDS) == {"waterfall", "contour3d"}
    assert set(KIND_LABELS) == set(KINDS)
    assert KIND_LABELS["waterfall"] == "3D Waterfall" and KIND_LABELS["contour3d"] == "3D Contour"


def test_clip_band_and_shadow_levels():
    triangle = np.array([(0, 0, 0), (4, 0, -4), (0, 4, 0)], float)
    assert clip_band(triangle, -1, np.inf).area == pytest.approx(8-.5*3*3)
    assert clip_band(triangle, -10, -5) is None
    assert clip_band(triangle, -2, -1).area == pytest.approx(.5*3*3-.5*2*2)
    shadow = ModelShadow(wedge_pocket())
    assert shadow.at(1).is_empty
    # Just below the top face: everything except the pocket opening is blocked.
    top = shadow.at(-1)
    assert top.area == pytest.approx(40*30-POCKET.area, abs=.05)
    # At Z-6 the floor above that level (x < 20) is blocked as well; lower levels only grow.
    middle = shadow.at(-6)
    assert middle.contains(Point(15, 15)) and not middle.contains(Point(25, 15))
    assert shadow.at(-6.5).area > middle.area
    assert shadow.at(-1).area == pytest.approx(top.area)          # going back up restarts correctly
    assert shadow.at(-10-2*SURFACE_TOLERANCE).area == pytest.approx(40*30, abs=.05)


def test_shadow_protects_undercuts():
    v1, f1 = box_triangles((-2, -2, -10), (2, 2, -2))
    v2, f2 = box_triangles((-8, -8, -2), (8, 8, 0), 8)
    shadow = ModelShadow(Mesh(np.asarray(v1+v2, float), np.asarray(f1+f2)))
    # Beside the stem but under the cap: unreachable for a vertical cutter.
    assert shadow.at(-5).contains(Point(6, 6))
    assert shadow.at(-5).area == pytest.approx(16*16, abs=.01)


def test_drop_surface_is_conservative_and_close():
    surface = DropSurface(wedge_pocket(), (5, 5), (35, 25), .1, 2_000_000)
    xy = np.column_stack((np.linspace(12, 28, 60), np.full(60, 15.)))
    z = surface.heights(xy, RADIUS)
    exact = floor_z(xy[:, 0]-RADIUS)
    assert np.all(z >= exact-1e-9)
    assert np.all(z <= exact+.4*4*surface.resolution+1e-9)
    assert surface.heights([(10.5, 15)], RADIUS)[0] == pytest.approx(0)      # footprint overlaps the top face
    assert surface.heights([(100, 100)], RADIUS)[0] == -np.inf
    coarse = DropSurface(wedge_pocket(), (5, 5), (35, 25), .1, 100)
    assert coarse.resolution > .1 and np.all(coarse.heights(xy, RADIUS) >= exact-1e-9)
    with pytest.raises(ValueError):
        DropSurface(wedge_pocket(), (5, 5), (5, 25), .1, 100)


def test_surface_simplifier_reuses_unchanged_spans(monkeypatch):
    from gcodeproducer.core.cam.surface_simplifier import SurfaceSimplifier

    x = np.linspace(0, 16, 801)
    first = np.column_stack((x, np.zeros_like(x), np.cos(x)*.1))
    second = first.copy()
    second[360:400, 2] *= .98
    simplify = SurfaceSimplifier()
    np.testing.assert_array_equal(simplify([first])[0], simplify3d(first))
    expected = simplify3d(second)
    norm = np.linalg.norm
    calls = []

    def count(*args, **kwargs):
        calls.append(1)
        return norm(*args, **kwargs)

    monkeypatch.setattr(np.linalg, 'norm', count)
    reduced = simplify([second])[0]
    reused_calls = len(calls)
    np.testing.assert_array_equal(reduced, expected)
    assert simplify([second.copy()])[0] is reduced
    assert len(calls) == reused_calls
    simplify3d(second)
    assert reused_calls < len(calls) - reused_calls
    np.testing.assert_array_equal(simplify([second[10:]])[0], simplify3d(second[10:]))


def test_simplify3d_keeps_tolerance_and_ends():
    x = np.linspace(0, 10, 400)
    line = np.column_stack((x, np.zeros_like(x), np.where(x < 5, 0, -(x-5))))
    reduced = simplify3d(line, .005)
    assert len(reduced) <= 4 and np.array_equal(reduced[0], line[0]) and np.array_equal(reduced[-1], line[-1])
    # Every original sample stays within the tolerance of the reduced polyline.
    z = np.interp(line[:, 0], reduced[:, 0], reduced[:, 2])
    assert np.abs(z-line[:, 2]).max() <= .005+1e-9


def test_overlapping_selection_boundaries_merge_instead_of_failing():
    logged = []
    region = selection_region([np.array([(0, 0), (10, 0), (10, 10), (0, 10)]),
                               np.array([(5, 5), (15, 5), (15, 15), (5, 15)])], logged.append, "Op")
    assert region.area == pytest.approx(175) and "merged" in logged[0]
    nested = selection_region([np.array([(0, 0), (10, 0), (10, 10), (0, 10)]),
                               np.array([(4, 4), (6, 4), (6, 6), (4, 6)])])
    assert nested.area == pytest.approx(96)


def test_waterfall_with_sloped_boundary_follows_the_floor_in_terraces(libset):
    job, op = surface_job(libset)
    ctx = StageContext()
    generate(job, ctx)
    assert any("limited by the model surface" in message for message in ctx.messages)
    levels = sorted({layer.z for layer in job.layers}, reverse=True)
    # The selected Start is Z-2, but the stock ABOVE it must be cleared first.
    # Z-10 itself has no cutter-sized area.
    assert levels[0] == -1 and levels[-1] == -8
    assert_clear_of_model(job)
    # Deeper terraces begin further along the slope.
    reach = [min(float(np.asarray(p.points)[:, 0].min()) for p in layer.paths) for layer in job.layers]
    assert reach == sorted(reach) and reach[-1] > reach[0]+5
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    assert job.program is not None and any(line.cmd == "G1" for line in job.program.lines)
    assert_program_clear(job.program)


def test_flat_pocket_and_legacy_surface_stop_migration(libset):
    rim = ReferenceShape("rectangle", "edge", (10, 8), (30, 22), z=0)
    ref = [Reference("drawing", [rim.id])]
    legacy, op = surface_job(libset, kind="pocket", refs=ref, end=Depth("absolute", -6))
    legacy.cam_setup.reference_shapes = [rim]
    generate(legacy, StageContext())
    deepest = min(legacy.layers, key=lambda layer: layer.z)
    assert min(float(np.asarray(p.points)[:, 0].min()) for p in deepest.paths) < 12    # flat floor everywhere
    data = legacy.cam_setup.to_dict()
    data["groups"][0]["operations"][0]["protect_model"] = True
    job, op = surface_job(libset, refs=ref, end=Depth("absolute", -6))
    job.cam_setup = CAMSetup.from_dict(data)
    assert job.cam_setup.groups[0].operations[0].kind == "waterfall"
    generate(job, StageContext())
    assert_clear_of_model(job)
    assert min(layer.z for layer in job.layers) == -6
    restored = CAMSetup.from_dict(job.cam_setup.to_dict()).groups[0].operations[0]
    assert restored.kind == "waterfall" and not restored.protect_model
    assert Operation(kind="pocket", protect_model=True).kind == "waterfall"
    data["groups"][0]["operations"][0].pop("protect_model")
    assert CAMSetup.from_dict(data).groups[0].operations[0].kind == "pocket"


def test_waterfall_clears_the_interior_not_just_one_wall_contour(libset):
    job, op = surface_job(libset, kind="waterfall")
    generate(job, StageContext())
    assert_clear_of_model(job)
    levels = sorted({layer.z for layer in job.layers}, reverse=True)
    assert levels[0] == -1 and levels[-1] <= -8
    interior = []
    for layer in job.layers:
        blocked = ModelShadow(job.mesh).at(layer.z)
        for path in layer.paths:
            p = np.asarray(path.points)
            distances = np.array([blocked.distance(Point(q)) for q in p[::max(1, len(p)//25)]])
            assert np.all(distances >= RADIUS-.02)
            interior.extend(distances)
    assert max(interior) > 2*RADIUS   # multiple clearing tracks, not just a wall trace
    assert any(path.closed for layer in job.layers for path in layer.paths)
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    first = job.layers[0]
    sweeps = unary_union([LineString(np.vstack((p.points, p.points[0])) if p.closed else p.points).buffer(RADIUS)
                         for p in first.paths])
    assert POCKET.buffer(-RADIUS-.05).difference(sweeps).area < .01
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    assert job.program is not None
    assert_program_clear(job.program)


def test_waterfall_clips_to_the_selection_and_honours_stock_to_leave():
    blocked = box(0, 0, 10, 10)
    full = waterfall_paths(blocked, box(-20, -20, 30, 30), 1., .5, "climb")
    assert len(full) == 1 and full[0][1]
    assert np.allclose([blocked.distance(Point(q)) for q in full[0][0]], 1.5, atol=1e-3)
    half = waterfall_paths(blocked, box(-20, -20, 5, 30), 1., 0., "climb")
    assert half and all(not closed for _, closed in half)
    assert max(float(p[:, 0].max()) for p, _ in half) <= 5+1e-6
    assert waterfall_paths(Polygon(), box(0, 0, 1, 1), 1., 0., "climb") == []


def test_contour3d_clears_in_depth_limited_passes_then_follows_the_surface(libset):
    job, op = surface_job(libset, kind="contour3d")
    generate(job, StageContext())
    assert len(job.layers) == 10
    assert np.all(-np.diff([0] + [layer.z for layer in job.layers]) <= 1+1e-9)
    assert_clear_of_model(job)
    paths = [np.asarray(p.points) for p in job.layers[-1].paths]
    assert all(p.shape[1] == 3 for p in paths)
    points = np.vstack(paths)
    # A planar slope simplifies to a few vertices: check along the segments.
    dense = np.vstack([a+(b-a)*np.linspace(0, 1, 30)[:, None] for p in paths for a, b in zip(p, p[1:])])
    inside = (dense[:, 0] > 10+RADIUS+.3) & (dense[:, 0] < 30-RADIUS-.3) & \
             (dense[:, 1] > 8+RADIUS+.3) & (dense[:, 1] < 22-RADIUS-.3)
    exact = floor_z(dense[inside, 0]-RADIUS)
    assert inside.sum() > 100
    assert np.all(dense[inside, 2] >= exact-.01)              # never below the true floor
    assert np.all(dense[inside, 2] <= exact+.15)              # and close to it
    # The last pass follows the whole reachable floor, including its high end.
    assert points[:, 2].min() >= -10-1e-9 and points[:, 2].max() <= -2+1e-9
    assert points[:, 1].min() > 8+RADIUS-.3 and points[:, 1].max() < 22-RADIUS+.3
    # Passes are stepover apart across the short side of the area.
    ys = np.unique(np.round(points[:, 1], 3))
    assert np.diff(ys).max() <= 3*op.stepover/100+1e-6
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    cuts = [line for line in job.program.lines if line.cmd == "G1" and "Z" in line.raw and "X" in line.raw]
    assert len(cuts) > 10
    assert_program_clear(job.program)


def test_merged_feed_moves_keep_measurement_material_and_checks(libset):
    def emitted(merge, step=0.):
        job, _ = surface_job(libset, kind="contour3d")
        job.preferences.update(cam_merge_moves=merge, cam_engagement_step=step)
        generate(job, StageContext())
        CAMEmit().run(job, CAMEmit.defaults(), StageContext())
        return job

    from gcodeproducer.core.gcode.simulation import simulate
    plain, merged = emitted(False), emitted(True)
    feeds = [sum(line.cmd == "G1" for line in job.program.lines) for job in (plain, merged)]
    assert feeds[1] < feeds[0]
    assert plain.warnings == merged.warnings
    for a, b in zip(plain.material_results, merged.material_results, strict=True):
        np.testing.assert_allclose(a["heights"], b["heights"], atol=1e-3)
    sim_plain, sim_merged = simulate(plain.program), simulate(merged.program)
    assert sim_plain.dist.sum() == pytest.approx(sim_merged.dist.sum(), rel=1e-6)
    # Peak engagement is preserved on merged lines.
    assert max(l.engagement for l in merged.program.lines if l.note) == pytest.approx(
        max(l.engagement for l in plain.program.lines if l.note))
    assert_program_clear(merged.program)
    # A longer engagement step samples (and so writes) fewer unmerged moves.
    coarse = emitted(False, 4.)
    assert sum(line.cmd == "G1" for line in coarse.program.lines) < feeds[0]


def test_second_tool_skips_3d_moves_through_material_already_removed(libset):
    import copy
    from gcodeproducer.core.cam import ToolGroup
    from gcodeproducer.core.gcode.simulation import simulate

    def emitted(skip):
        job, op = surface_job(libset, kind="contour3d")
        finish = copy.deepcopy(op)
        finish.name = "Finish"
        job.cam_setup.groups.append(ToolGroup(job.tools[0].id, [finish]))
        job.preferences["skip_air_cuts"] = skip
        logs = []
        generate(job, StageContext())
        CAMEmit().run(job, CAMEmit.defaults(), StageContext(logs.append))
        second = {l.index for l in job.layers if l.cam_operation == "Finish"}
        feeds = [i for i, l in enumerate(job.program.lines) if l.cmd == "G1" and l.layer in second]
        return job, feeds, logs

    kept, kept_feeds, _ = emitted(False)
    skipped, skipped_feeds, logs = emitted(True)
    # The identical second pass only rubs air: almost every feed move disappears.
    assert len(skipped_feeds) < .1*len(kept_feeds)
    assert any("Remove air cutting: skipped" in line for line in logs)
    # The same material ends up removed and the output stays clear of the part.
    np.testing.assert_allclose(kept.material_results[-1]["heights"], skipped.material_results[-1]["heights"],
                               atol=1e-3)
    assert skipped.warnings == kept.warnings
    assert_program_clear(skipped.program)
    # Whatever the second pass still cuts actually meets material.
    sim = simulate(skipped.program)
    cuts = [i for i in skipped_feeds if skipped.program.lines[i].feature not in ("air", "lead_out", "approach")]
    assert all(sim.moved[i] for i in cuts)


def test_xyz_pieces_are_visited_nearest_first_without_reversing():
    from gcodeproducer.core.cam.planner.motion_planner import _nearest_order
    # Meander lines cut only at both ends: raster order would cross the middle every time.
    runs = []
    for i in range(6):
        pieces = ((0., 2.), (98., 100.)) if i % 2 == 0 else ((100., 98.), (2., 0.))
        runs += [np.array([[float(i), a, -1.], [float(i), b, -1.]]) for a, b in pieces]
    order = _nearest_order(runs, (0., 0.))
    assert sorted(order) == list(range(len(runs)))
    crossings = sum(abs(runs[a][-1, 1]-runs[b][0, 1]) > 50 for a, b in zip(order, order[1:]))
    raster = sum(abs(runs[a][-1, 1]-runs[a+1][0, 1]) > 50 for a in range(len(runs)-1))
    assert crossings == 1 and raster > 5


def test_partially_cleared_xyz_path_is_split_at_long_air_gaps():
    from types import SimpleNamespace
    from gcodeproducer.core.cam.height_stock import HeightStock
    from gcodeproducer.core.cam.planner.motion_planner import MotionPlanner
    from gcodeproducer.core.cam.stock import Stock

    state = HeightStock(Stock(width=60, depth=10, height=10), .1)
    state.heights[:, 100:450] = -10          # X10..X45 already cleared
    planner = SimpleNamespace(radius=1., sample_spacing=0., air_skipped=0.)
    path = np.array([[2., 5., -1.], [58., 5., -1.]])
    runs = MotionPlanner._material_runs(planner, state, path)
    assert len(runs) == 2
    # The cutter's edge (radius 1) still reaches material until its centre is 1 mm inside the gap.
    assert runs[0][0][0] == 2 and runs[0][-1][0] == pytest.approx(11, abs=.6)
    assert runs[1][0][0] == pytest.approx(44, abs=.6) and runs[1][-1][0] == 58
    assert planner.air_skipped == pytest.approx(33, abs=1.2)
    # Short gaps (under two diameters) are fed through instead of retracting.
    state.heights[:, 100:450] = 0
    state.heights[:, 300:320] = -10
    assert MotionPlanner._material_runs(planner, state, path) == [path]


def test_planner_resolution_preferences_reach_contour_geometry(libset):
    lines = []
    for tolerance, resolution in ((.005, 0.), (.2, 0.), (.005, .5)):
        job, _ = surface_job(libset, kind="contour3d")
        job.preferences.update(cam_surface_tolerance=tolerance, cam_surface_resolution=resolution)
        generate(job, StageContext())
        lines.append(sum(len(p.points) for layer in job.layers for p in layer.paths))
        assert_clear_of_model(job, tolerance=max(.02, tolerance+.01))
    assert lines[1] < lines[0] and lines[2] != lines[0]


def test_contour3d_raises_floor_over_retained_areas_and_leaves_stock():
    surface = DropSurface(wedge_pocket(), (5, 5), (35, 25), .1, 2_000_000)
    region = box(12, 10, 28, 20)
    plain = np.vstack(surface_raster(region, surface, RADIUS, 1.2, -10, 0.))
    stocked = np.vstack(surface_raster(region, surface, RADIUS, 1.2, -10, .5))
    assert stocked[:, 2].min() == pytest.approx(plain[:, 2].min()+.5, abs=.05)
    tab = box(18, 10, 22, 20)
    checked = 0
    for path in surface_raster(region, surface, RADIUS, 1.2, -10, 0., None, [(tab, -3.)]):
        # Simplified flat runs keep only their ends: check along the segments.
        dense = np.vstack([a+(b-a)*np.linspace(0, 1, 40)[:, None] for a, b in zip(path, path[1:])])
        over = (dense[:, 0] > 18.2) & (dense[:, 0] < 21.8)
        assert np.all(dense[over, 2] >= -3-.01)
        checked += int(over.sum())
    assert checked
    assert surface_raster(Polygon(), surface, RADIUS, 1.2, -10, 0.) == []
    trimmed = np.vstack(surface_raster(region, surface, RADIUS, 1.2, -10, 0., ceiling=-5))
    assert trimmed[:, 2].max() < -5 and trimmed[:, 0].min() > 17
    assert surface_raster(region, surface, RADIUS, 1.2, -10, 0., ceiling=-11) == []


def test_rough_then_finish_sequence_shares_one_setup(libset):
    job, op = surface_job(libset)
    refs = list(op.geometry)
    group = job.cam_setup.groups[0]
    for kind in ("contour3d",):
        group.operations.append(Operation(name=KIND_LABELS[kind], kind=kind, geometry=list(refs), stepdown=1,
                                          start=Depth("selection", extreme="max"), end=Depth("selection", extreme="min")))
    generate(job, StageContext())
    assert len({layer.cam_operation_key for layer in job.layers}) == 2
    assert_clear_of_model(job)
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    assert job.program is not None
    assert_program_clear(job.program)


@pytest.mark.parametrize("kind", ["profile", "slot", "engrave", "pocket"])
def test_planar_operations_still_reject_sloped_edges_clearly(libset, kind):
    job, op = surface_job(libset, kind=kind)
    with pytest.raises(ValueError, match="constant-Z edges; 3D Waterfall"):
        generate(job, StageContext())


@pytest.mark.parametrize("kind", ["waterfall", "contour3d"])
def test_3d_depth_of_cut_clears_stock_above_start_and_obeys_tool_cap(libset, kind):
    job, op = surface_job(libset, kind=kind, stepdown=.8)
    job.tools[0].values["max_doc"] = .5
    job.cam_setup.stock.top = 2
    op.end = Depth("absolute", -6)
    generate(job, StageContext())
    levels = [2.] + [layer.z for layer in job.layers]
    assert levels[1] == pytest.approx(1.5)
    assert min(levels) == pytest.approx(-6)
    assert np.all(-np.diff(levels) <= .5+1e-9)
    for i, layer in enumerate(job.layers):
        for path in layer.paths:
            points = np.asarray(path.points)
            if points.shape[1] == 3:
                assert points[:, 2].min() >= 2-(i+1)*.5-1e-9
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    assert not any("uncleared entry depth" in warning for warning in job.warnings)


def test_waterfall_removes_air_already_cleared_by_an_earlier_operation(libset):
    import copy
    job, op = surface_job(libset)
    duplicate = copy.deepcopy(op)
    duplicate.name = "Already cleared"
    job.cam_setup.groups[0].operations.append(duplicate)
    ctx = StageContext()
    generate(job, ctx)
    assert {layer.cam_operation_key for layer in job.layers} == {(0, 0)}
    assert any("already cleared by earlier operations" in message for message in ctx.messages)


def test_surface_operation_reports_when_nothing_is_reachable(libset):
    job, op = surface_job(libset, kind="waterfall", start=Depth("absolute", 5), end=Depth("absolute", 4))
    job.machine.values["safe_z"] = 30
    with pytest.raises(ValueError, match="End Z is below the surface"):
        generate(job, StageContext())
