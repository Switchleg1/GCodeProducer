"""FDM output ordering, seam placement and bounded detours."""
import math

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from gcodeproducer.core.fdm.path_order import closed_loop, ordered_paths
from gcodeproducer.core.fdm.travel_router import TravelRouter
from gcodeproducer.core.gcode.builder import GCodeBuilder
from gcodeproducer.core.gcode.simulation import simulate
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.stages.fdm.fdm_emit import FDMEmit


OUTER = [(0, 0), (12, 0), (12, 10), (0, 10)]
HOLE = [(5, 3), (7, 3), (7, 7), (5, 7)]


def test_mixed_fill_nearby_in_both_areas_without_moving_a_wall():
    def path(feature, x, y):
        return Path(feature, np.array([(x, y), (x+1, y)], float))

    wall = path('outer_perimeter', 0, 0)
    near_top, far_top = path('top_infill', 1, 1), path('top_infill', 80, 1)
    near_sparse, far_sparse = path('infill', 2, 2), path('infill', 81, 2)
    near_bottom = path('solid_infill', 4, 3)
    paths = [wall, near_top, far_top, near_bottom, near_sparse, far_sparse, wall]
    result = list(ordered_paths(paths, lambda: (1, 1)))
    assert [id(p) for p in result] == [id(p) for p in
        [wall, near_top, near_sparse, near_bottom, far_top, far_sparse, wall]]
    assert list(ordered_paths([far_top, near_top], lambda: (1, 1))) == [far_top, near_top]


def test_detour_around_hole_within_budget_and_fallback():
    a, b = (2, 5), (10, 5)
    router = TravelRouter([OUTER, HOLE, [(20, 0), (30, 0), (30, 10), (20, 10)]], 3)
    routed = router.route(a, b, 2.)
    assert len(routed) > 1 and routed[-1] == b
    line = LineString([a, *routed])
    assert Polygon(OUTER, [HOLE]).covers(line)
    assert math.dist(a, b) < line.length <= math.dist(a, b) + 2.
    assert router.route(a, b, 0.5) == [b]
    assert router.route(a, b, 0.) == [b]
    assert router.route(a, (22, 5), 50.) == [(22, 5)]
    assert router.route(a, (3, 5), 5.) == [(3, 5)]


def test_large_budget_does_not_disable_detours_on_dense_outlines():
    angles = np.linspace(0, 2*np.pi, 160, endpoint=False)
    remote_hole = [(3+np.cos(t), 8+np.sin(t)) for t in angles]
    a, b = (2, 5), (10, 5)
    router = TravelRouter([OUTER, HOLE, remote_hole], 3)
    small = router.route(a, b, 2.)
    large = router.route(a, b, 100*150.)
    assert len(small) > 1 and len(large) > 1
    assert LineString([a, *large]).length <= LineString([a, *small]).length
    assert Polygon(OUTER, [HOLE, remote_hole]).covers(LineString([a, *large]))
    assert router.detours == 2


def test_mixed_infill_setting_migrates_from_output():
    from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
    process = SlicePipeline.default('fdm').to_dict()
    next(s for s in process['steps'] if s['stage'] == 'fdm_emit')['params']['optimize_mixed_infill'] = False
    pipe = SlicePipeline.from_dict(process)
    assert 'optimize_mixed_infill' not in pipe.step('fdm_emit').params
    assert pipe.step('fdm_infill').params['optimize_mixed_infill'] is False


def test_detour_stays_inside_concave_island():
    outline = [(0, 0), (9, 0), (9, 9), (6, 9), (6, 3), (3, 3), (3, 9), (0, 9)]
    a, b = (1, 7), (8, 7)
    points = TravelRouter([outline], 3).route(a, b, 10.)
    assert len(points) > 1
    assert Polygon(outline).covers(LineString([a, *points]))


def test_emit_one_retract_for_detour_and_no_extrusion_in_waypoints():
    builder = GCodeBuilder()
    builder.travel(2, 5)
    path = Path('infill', np.array([(10, 5), (11, 5)], float))
    FDMEmit()._print_path(builder, path, path.points, .04, 1000, 5000,
                         {'retract': True, 'min_travel_retract': 8.5}, .4, 25, 0,
                         TravelRouter([OUTER, HOLE], builder.dx), 2.)
    program = builder.program()
    sim = simulate(program)
    travel_points = [(sim.x[i], sim.y[i]) for i, line in enumerate(program.lines) if line.cmd == 'G0']
    assert len(travel_points) > 2 and travel_points[-1] == (10, 5)
    assert Polygon(OUTER, [HOLE]).covers(LineString(travel_points))
    assert [line.params['E'] for line in program.lines if 'E' in line.params] == [-.4, .4, .04]


@pytest.mark.parametrize('mode, expected', [('xy', (7, 10)), ('nearest', (4, 0)), ('origin', (0, 0))])
def test_emitted_wall_seam_start_stop(mode, expected):
    builder = GCodeBuilder()
    builder.command('M83')
    builder.travel(4, -1)
    path = Path('outer_perimeter', np.asarray(OUTER, float), closed=True)
    params = {'seam': mode, 'seam_x': 7, 'seam_y': 25, 'retract': False}
    FDMEmit()._print_path(builder, path, path.points, .05, 1000, 5000, params, 0, 25, 0)
    program = builder.program()
    sim = simulate(program)
    first = next(i for i, line in enumerate(program.lines) if 'E' in line.params)
    assert (sim.px[first], sim.py[first]) == expected
    assert (sim.x[-1], sim.y[-1]) == expected
    assert sim.de.sum() == pytest.approx(44*.05)
    np.testing.assert_array_equal(path.points, OUTER)


def test_target_aligns_nested_walls_on_facing_edges():
    target = np.array([7, 20])
    inner = np.array([(1, 1), (11, 1), (11, 9), (1, 9)])
    assert tuple(closed_loop(np.array(OUTER), target)[0]) == (7, 10)
    assert tuple(closed_loop(inner, target)[0]) == (7, 9)
