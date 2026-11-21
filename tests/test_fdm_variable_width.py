"""Path decimation, variable-width walls and gap fill."""
import numpy as np
from shapely import union_all
from shapely.geometry import LineString, Point, Polygon, box

from gcodeproducer.core.fdm.gap_fill import gap_beads, gap_regions
from gcodeproducer.core.fdm.path_order import closed_loop
from gcodeproducer.core.fdm.variable_walls import variable_wall_levels
from gcodeproducer.core.geometry.decimate import decimate, decimate_rings

W = 0.4


def test_decimate_merges_tessellation_but_keeps_real_corners():
    t = np.linspace(0, 2*np.pi, 2000, endpoint=False)
    circle = np.c_[10*np.cos(t), 10*np.sin(t)]
    pts, _ = decimate(circle, True, 0.2, 0.02)
    assert len(pts) < 100
    assert np.hypot(*np.diff(pts, axis=0).T).min() >= 0.2
    # a 0.05 mm notch is larger than the deviation and must survive
    notch = np.array([[0, 0], [1, 0], [1, .05], [1.1, .05], [1.1, 0], [5, 0], [5, 5], [0, 5]], float)
    assert len(decimate(notch, True, 0.2, 0.02)[0]) == len(notch)
    assert decimate_rings([notch], 0, 0)[0] is notch


def test_decimate_keeps_width_changes_and_merges_linear_tapers():
    line = np.c_[np.linspace(0, 1, 11), np.zeros(11)]
    pts, widths = decimate(line, False, 0.2, 0.02, np.linspace(.4, .2, 11))
    assert len(pts) == 2 and np.allclose(widths, [.4, .2])
    step = np.r_[np.full(5, .4), np.full(6, .2)]
    pts, widths = decimate(line, False, 0.2, 0.02, step)
    assert len(pts) > 2 and set(np.round(widths, 3)) == {.4, .2}


def test_closed_loop_rotates_values_with_points():
    pts = np.array([[0, 0], [2, 0], [2, 2], [0, 2]], float)
    out, vals = closed_loop(pts, np.array([1., -1.]), np.array([1., 2., 3., 4.]))
    assert np.allclose(out[0], [1, 0]) and np.isclose(vals[0], 1.5)
    assert len(out) == len(vals) == 5


def _beads(levels):
    return [bead for level in levels for bead in level]


def test_wedge_tip_gets_tapering_centre_bead():
    wedge = Polygon([(0, -1), (10, 0), (0, 1)])          # 2 mm base tapering to a point
    levels, _ = variable_wall_levels(wedge, W, 2, .5*W, 1.5*W)
    open_beads = [b for b in _beads(levels) if not b[2]]
    assert open_beads, "the tip must get a centre bead"
    pts, widths, _ = max(open_beads, key=lambda b: len(b[0]))
    assert widths.min() >= .5*W - 1e-9 and widths.max() <= 1.5*W + 1e-9
    # the bead narrows towards the tip (x grows)
    order = np.argsort(pts[:, 0])
    assert widths[order[0]] > widths[order[-1]]
    assert pts[:, 0].max() > 8.5


def test_folded_strip_keeps_its_loop_and_only_thins_the_flow():
    strip = box(0, 0, 10, 1.7*W)                          # between 1 and 2 line widths
    levels, _ = variable_wall_levels(strip, W, 1, .5*W, 1.5*W)
    fixed = strip.buffer(-W/2, quad_segs=8)
    (pts, widths, closed), = levels[0]
    assert closed
    # same path as the fixed-width loop, just thinner where the sides overlap
    assert fixed.exterior.buffer(1e-6).covers(LineString(np.vstack((pts, pts[:1]))))
    middle = (pts[:, 0] > 2) & (pts[:, 0] < 8)
    assert np.allclose(widths[middle], .85*W, atol=.02)


def test_fixed_width_result_unchanged_for_wide_parts():
    square = box(0, 0, 20, 20)
    levels, rings = variable_wall_levels(square, W, 2, .5*W, 1.5*W)
    assert all(widths is None and closed for points, widths, closed in _beads(levels))
    assert len(rings) == 1


def test_gap_fill_only_thin_gaps():
    area = box(0, 0, 20, 20).union(box(20, 9.6, 30, 10.4))       # 0.8 mm wide tongue
    gaps = gap_regions(area, 2*W, W)
    assert gaps.intersects(box(25, 9.9, 26, 10.1)) and not gaps.contains(box(5, 5, 6, 6))
    assert gap_beads(gaps, area, W, .5*W, 1.5*W, .03)
    # a fan-hub-sized room joined by a narrow neck is left to the infill
    hub = Point(0, 0).buffer(2.5).union(box(-.25, 2.4, .25, 3.3)).union(box(-5, 3.2, 5, 8))
    gaps = gap_regions(hub, 2*W, W)
    assert not gaps.intersects(Point(0, 0).buffer(2.))
    assert gaps.intersects(box(-.1, 2.8, .1, 3.))


def test_stroke_near_max_width_stays_one_intact_loop():
    # lettering-like stroke whose width wobbles around 1.5 line widths
    xs = np.linspace(0, 8, 81)
    half = .3 + .03*np.sin(xs*7)
    stroke = Polygon(np.r_[np.c_[xs, half], np.c_[xs[::-1], -half[::-1]]])
    levels, _ = variable_wall_levels(stroke, W, 2, .5*W, 1.5*W)
    beads = _beads(levels)
    assert len(beads) == 1 and beads[0][2]
    assert beads[0][1].min() >= .5*W - 1e-9


def test_small_islands_are_filled_solid_only_below_the_area():
    from gcodeproducer.core.fdm.gap_fill import infill_area, small_islands
    from gcodeproducer.core.fdm.wall_regions import region_rings
    pillar, block = box(0, 0, 3, 3), box(10, 0, 30, 20)
    outline = list(region_rings(pillar.union(block)))
    inner = list(region_rings(pillar.union(block).buffer(-1.5*W)))
    area = infill_area(inner, W)
    solid, _ = small_islands(outline, area, 25.)
    assert solid.intersects(Point(1.5, 1.5)) and not solid.intersects(Point(20, 10))
    beads = gap_beads(solid, area, W, .5*W, 1.5*W, .03)
    covered = union_all([LineString(np.vstack((p, p[:1])) if c else p).buffer(max(w.max() if w is not None else W, W)/2)
                         for p, w, c in beads])
    assert covered.covers(Point(1.5, 1.5).buffer(.3))
