"""Layer print order, print-time estimate and fast slicing helpers."""
import numpy as np
import pytest
from shapely.geometry import box

from gcodeproducer.core.fdm.layer_order import order_layer
from gcodeproducer.core.fdm.wall_regions import _nested_region, _symmetric_region, slice_region
from gcodeproducer.core.gcode.program import GCodeProgram
from gcodeproducer.core.gcode.simulation import simulate
from gcodeproducer.core.gcode.time_estimate import estimate_time, motion_comment, motion_settings
from gcodeproducer.core.geometry.kernel import _chain_general, _chain_manifold
from gcodeproducer.core.jobs.path import Path


def _program(text):
    program = GCodeProgram.from_text(text)
    program.machine = "fdm"
    return program


def test_trapezoid_time_of_a_single_move():
    program = _program("G1 X100 F6000\n")
    motion = {"print_acceleration": 1000., "travel_acceleration": 0., "junction_deviation": .013}
    # 0 -> 100 mm/s in 0.1 s (5 mm), cruise 90 mm, brake 0.1 s
    assert estimate_time(program, simulate(program), motion) == pytest.approx(1.1, rel=1e-6)


def test_m204_and_header_change_the_estimate():
    slow = _program("M204 S500\nG1 X100 F6000\n")
    fast = _program("M204 S5000\nG1 X100 F6000\n")
    assert estimate_time(slow, simulate(slow)) > estimate_time(fast, simulate(fast))
    motion = {"print_acceleration": 800., "travel_acceleration": 3000., "junction_deviation": .02}
    program = _program(f";{motion_comment(motion)}\nG1 X10 F600\n")
    assert motion_settings(program)["print_acceleration"] == 800.
    assert motion_settings(program)["travel_acceleration"] == 3000.


def test_corners_and_retracts_cost_time():
    straight = _program("M83\nG1 X10 E1 F3000\nG1 X20 E1\n")
    corner = _program("M83\nG1 X10 E1 F3000\nG1 X10 Y10 E1\n")
    retract = _program("M83\nG1 X10 E1 F3000\nG1 E-1 F1800\nG1 X20 E1 F3000\n")
    t = [estimate_time(p, simulate(p)) for p in (straight, corner, retract)]
    assert t[0] < t[1] and t[0] + 1 / 30 < t[2]


def _loop(x, y, size, feature):
    return Path(feature, np.array([[x, y], [x + size, y], [x + size, y + size], [x, y + size]], float), closed=True)


def test_layer_order_finishes_each_island_and_wall_group():
    left, right = box(0, 0, 10, 10), box(50, 0, 60, 10)
    paths = [_loop(1, 1, 8, "inner_perimeter"), _loop(51, 1, 8, "inner_perimeter"),
             _loop(.2, .2, 9.6, "outer_perimeter"), _loop(50.2, .2, 9.6, "outer_perimeter"),
             Path("infill", np.array([[52., 5.], [58., 5.]])), Path("infill", np.array([[2., 5.], [8., 5.]])),
             Path("skirt", np.array([[-5., -5.], [65., -5.]]))]
    out = order_layer(paths, (0., 0.), [left, right])
    assert out[0].feature == "skirt"
    xs = [float(np.asarray(p.points)[:, 0].mean()) for p in out[1:]]
    sides = [x > 30 for x in xs]
    assert sides == sorted(sides, reverse=True) or sides == sorted(sides)     # one island at a time
    for half in (out[1:4], out[4:]):
        assert [p.feature for p in half] == ["inner_perimeter", "outer_perimeter", "infill"]


def test_fast_slice_region_matches_even_odd():
    rings = [np.array(r, float) for r in (
        [[0, 0], [20, 0], [20, 20], [0, 20]], [[2, 2], [18, 2], [18, 18], [2, 18]],
        [[5, 5], [15, 5], [15, 15], [5, 15]], [[30, 0], [40, 0], [40, 10], [30, 10]])]
    fast = _nested_region(rings)
    assert fast is not None
    assert fast.symmetric_difference(_symmetric_region(rings)).area < 1e-9
    crossing = rings[:1] + [np.array([[10, 10], [30, 10], [30, 30], [10, 30]], float)]
    assert _nested_region(crossing) is None
    assert slice_region(crossing).area == pytest.approx(_symmetric_region(crossing).area)


def test_manifold_chain_matches_general_chain():
    square = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    segs = [(square[i], square[(i + 1) % 4]) for i in (2, 0, 3, 1)]
    fast, slow = _chain_manifold(segs, 1e-4), _chain_general(segs, 1e-4)
    assert len(fast) == len(slow) == 1 and len(fast[0]) == 4
    assert _chain_manifold([(square[0], square[1]), (square[1], square[2])], 1e-4) is None   # open
