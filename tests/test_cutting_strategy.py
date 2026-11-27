"""Operation-specific strategy controls and real X/Y path directions."""
import os
from types import SimpleNamespace
import numpy as np
import pytest
from shapely.ops import unary_union
from shapely.geometry import box

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from gcodeproducer.core.cam import CAMSetup, Operation, Depth, Reference
from gcodeproducer.core.cam.reference_shape import ReferenceShape
from gcodeproducer.core.cam.surface_paths import surface_raster
from gcodeproducer.stages.base import StageContext
from tests.test_cam_surface import surface_job, assert_program_clear


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_operation_specific_choices_and_hidden_rows(app):
    from gcodeproducer.gui.editors.cam_editor import CAMEditor
    from gcodeproducer.core.libraries.profile import Profile
    editor = CAMEditor()
    editor.set_tools([Profile('tool', 'Cutter')])
    editor.add_tool()
    try:
        for kind in ('pocket', 'waterfall', 'contour3d', 'profile', 'slot', 'drill', 'engrave'):
            editor.kind.setCurrentIndex(editor.kind.findData(kind))
            editor.add_operation()
            labels = [editor.strategy.itemText(i) for i in range(editor.strategy.count())]
            expected = (['Wall-parallel contours', 'Raster lines X', 'Raster lines Y', 'Adaptive clearing']
                        if kind in ('pocket', 'waterfall') else
                        ['Raster lines X', 'Raster lines Y', 'Spiral from the centre'] if kind == 'contour3d' else [])
            assert labels == expected
            form = editor.operation_form
            assert form.labelForField(editor.strategy).text() == 'Cutting strategy'
            assert editor.strategy.isHidden() == (not expected)
            assert form.labelForField(editor.strategy).isHidden() == (not expected)
            assert editor.side.isHidden() == (kind != 'profile')
            assert form.labelForField(editor.side).isHidden() == (kind != 'profile')
            assert [editor.side.itemText(i) for i in range(editor.side.count())] == ['Outside', 'Inside']
            editor.lead_angle.setValue(4.5)
            assert editor.operation().lead_angle == 4.5
            assert CAMSetup.from_dict(editor.setup.to_dict()).groups[0].operations[-1].lead_angle == 4.5
            if kind == 'contour3d':
                assert editor.lead_in.isEnabled() and editor.lead_out.isEnabled()
                assert all(field.isEnabled() for field in editor.feed_controls.values())
                editor.feed_controls['slotting_feed'].setValue(42)
                assert editor.operation().slotting_feed == 42
            if expected:
                strategy = 'adaptive' if kind in ('pocket', 'waterfall') else 'raster_y'
                editor.strategy.setCurrentIndex(editor.strategy.findData(strategy))
                assert editor.operation().strategy == strategy
                restored = CAMSetup.from_dict(editor.setup.to_dict())
                assert restored.groups[0].operations[-1].strategy == strategy
                assert not hasattr(editor, 'adaptive_engagement')      # the stepover is Adaptive's limit
                assert 'engagement limit' in editor.stepover.toolTip()
                if strategy == 'adaptive':
                    editor.stepover.setValue(12.5)
                    assert CAMSetup.from_dict(editor.setup.to_dict()).groups[0].operations[-1].stepover == 12.5
    finally:
        editor.close()


def test_hidden_fields_and_legacy_on_are_not_silently_overwritten(app):
    from gcodeproducer.gui.editors.cam_editor import CAMEditor
    from gcodeproducer.core.libraries.profile import Profile
    editor = CAMEditor()
    editor.set_tools([Profile('tool', 'Cutter')])
    editor.add_tool()
    editor.kind.setCurrentIndex(editor.kind.findData('profile'))
    editor.add_operation()
    try:
        op = editor.operation()
        op.side = 'on'
        op.strategy = 'raster_y'
        editor.rebuild()
        assert editor.side.currentIndex() == -1
        editor.name.setText('Legacy centerline')
        editor._edit()
        assert op.side == 'on' and op.strategy == 'raster_y'
        editor.side.setCurrentIndex(editor.side.findData('inside'))
        assert op.side == 'inside'
    finally:
        editor.close()


@pytest.mark.parametrize('kind', ['pocket', 'waterfall'])
@pytest.mark.parametrize('strategy,axis', [('raster_x', 0), ('raster_y', 1)])
def test_planar_clearing_raster_axis(libset, kind, strategy, axis):
    from gcodeproducer.core.cam import generate
    shape = ReferenceShape('rectangle', 'edge', (10, 8), (30, 22), 0)
    job, _ = surface_job(libset, kind=kind, refs=[Reference('drawing', [shape.id])],
                         end=Depth('absolute', -2), strategy=strategy)
    job.cam_setup.reference_shapes = [shape]
    generate(job, StageContext())
    paths = [np.asarray(p.points) for layer in job.layers for p in layer.paths if not p.closed]
    assert paths
    for p in paths:
        delta = np.diff(p[:, :2], axis=0)
        assert np.abs(delta[:, 1-axis]).max() < 1e-6
        assert np.abs(delta[:, axis]).max() > 1


@pytest.mark.parametrize('strategy,axis', [('raster_x', 0), ('raster_y', 1)])
@pytest.mark.parametrize('direction', ['climb', 'conventional'])
def test_contour_one_way_lines_cut_the_same_way_in_order_across_the_whole_width(strategy, axis, direction):
    """One path per line (the cutter lifts back to the start of the next), never reordered."""
    surface = SimpleNamespace(resolution=.1, heights=lambda xy, radius: np.full(len(xy), -2.))
    paths = surface_raster(box(0, 0, 10, 6), surface, 1, 1, -5, 0, strategy=strategy, direction=direction)
    assert len(paths) > 5
    across = [float(p[0, 1-axis]) for p in paths]
    assert np.all(np.diff(across) > 0)                                  # in order, stepping one way
    # Climb keeps the uncut lines on the right (M3): along X that is travelling -X, along Y +Y.
    climb_sign = -1 if axis == 0 else 1
    sign = climb_sign if direction == 'climb' else -climb_sign
    for p in paths:
        assert np.ptp(p[:, 1-axis]) < 1e-9                             # a straight line
        assert np.all(np.sign(np.diff(p[:, axis])) == sign)             # cut one way
        assert np.ptp(p[:, axis]) > (10 if axis == 0 else 6) - .01      # the whole width


@pytest.mark.parametrize('strategy,axis', [('raster_x', 0), ('raster_y', 1)])
def test_contour_one_way_staying_down_returns_over_the_cut_line_without_lifting(strategy, axis):
    """Stay down between contours: one path, each line cut one way and travelled back over exactly."""
    surface = SimpleNamespace(resolution=.1, heights=lambda xy, radius: np.full(len(xy), -2.))
    lifting = surface_raster(box(0, 0, 10, 6), surface, 1, 1, -5, 0, strategy=strategy, direction='climb')
    p, = surface_raster(box(0, 0, 10, 6), surface, 1, 1, -5, 0, strategy=strategy, direction='climb', stay_down=True)
    p = p[np.r_[True, np.any(np.abs(np.diff(p, axis=0)) > 1e-9, axis=1)]]
    across = p[:, 1-axis]
    assert np.all(np.diff(across) >= -1e-9)                             # same order, stepping one way
    assert len(np.unique(np.round(across, 6))) == len(lifting)
    sign = -1 if axis == 0 else 1
    for line in lifting[:-1]:
        on = p[np.isclose(across, line[0, 1-axis])]
        turn = np.flatnonzero(np.sign(np.diff(on[:, axis])) == -sign)[0]
        assert np.allclose(on[:turn+1][[0, -1]], line[[0, -1]])         # the same cut as when lifting
        assert np.allclose(on[:turn+1][::-1], on[turn:2*turn+1])        # and back over it exactly
    assert not Operation(kind='contour3d').stay_down_lines              # off unless chosen; old files too


@pytest.mark.parametrize('strategy,axis', [('raster_x', 0), ('raster_y', 1)])
def test_contour_meander_alternates_and_links_without_lifting(strategy, axis):
    surface = SimpleNamespace(resolution=.1, heights=lambda xy, radius: np.full(len(xy), -2.))
    paths = surface_raster(box(0, 0, 10, 6), surface, 1, 1, -5, 0, strategy=strategy, direction='meander')
    assert len(paths) == 1
    delta = np.diff(paths[0][:, :2], axis=0)
    assert delta[:, axis].min() < -1 and delta[:, axis].max() > 1
    assert np.ptp(paths[0][:, 1-axis]) > 5
    assert np.ptp(paths[0][:, 2]) < 1e-9                                 # never lifts


def test_contour_lines_cross_cleared_ground_and_gaps_without_stopping():
    """A line traces the whole contour: over ground already at its floor, and over a gap in the selection
    at the top of the material (rising and descending vertically), never cutting outside the selection."""
    from shapely.geometry import Polygon
    surface = SimpleNamespace(resolution=.1, heights=lambda xy, radius: np.where(xy[:, 0] < 5, -6., 1.))
    region = box(0, 0, 4, 6).union(box(6, 0, 10, 6))            # a 2 mm gap in the selection at x 4..6
    paths = surface_raster(region, surface, 1, 1, -5, 0, strategy='raster_x', direction='meander', ceiling=0.)
    assert len(paths) == 1
    p = paths[0]
    gap = (p[:, 0] > 4 + 1e-6) & (p[:, 0] < 6 - 1e-6)
    assert gap.any() and np.all(p[gap, 2] >= 0.)                 # at or above the top in the gap
    inside = ~gap
    assert np.all(p[inside & (p[:, 0] < 4), 2] == -5.)          # down at the floor, model below it
    assert np.all(p[inside & (p[:, 0] > 6), 2] == 1.)           # on the model where it stands above
    moves = np.diff(p, axis=0)
    crossing = np.abs(moves[:, 2]) > 1e-9
    assert np.all((np.linalg.norm(moves[crossing][:, :2], axis=1) < 1e-9) | (np.abs(moves[crossing][:, 2]) < 1.5))


@pytest.mark.parametrize('strategy', ['raster_x', 'raster_y'])
def test_contour_axis_strategies_keep_depth_cap_and_model_clearance(libset, strategy):
    from gcodeproducer.core.cam import generate
    from gcodeproducer.stages.cam_emit import CAMEmit
    job, _ = surface_job(libset, kind='contour3d', strategy=strategy)
    generate(job, StageContext())
    assert len(job.layers) == 10
    assert np.all(-np.diff([0] + [layer.z for layer in job.layers]) <= 1+1e-9)
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    assert_program_clear(job.program)
    assert not any('uncleared entry depth' in w for w in job.warnings)


@pytest.mark.parametrize('kind', ['pocket', 'waterfall'])
def test_adaptive_incomplete_pass_exports_only_debug_prefix(libset, kind, monkeypatch):
    from copy import deepcopy
    from gcodeproducer.core.cam import generate
    from gcodeproducer.core.cam.wavefront import app_paths
    from gcodeproducer.stages.cam_emit import CAMEmit
    monkeypatch.setattr(app_paths, 'WAVEFRONT_LEFT_MM2', -1.)  # Treat any result as incomplete.
    shape = ReferenceShape('rectangle', 'edge', (10, 8), (30, 22), 0)
    job, op = surface_job(libset, kind=kind, refs=[Reference('drawing', [shape.id])],
                          end=Depth('absolute', -2), strategy='adaptive', lead_angle=4.)
    job.cam_setup.reference_shapes = [shape]
    following = deepcopy(op)
    following.name, following.strategy = 'Must not execute', 'contour'
    job.cam_setup.groups[0].operations.append(following)
    generate(job, StageContext())
    assert len(job.layers) == 1 and job.layers[0].paths  # Only the first depth: the run stops there.
    assert job.layers[0].paths[0].closed  # The helix orbit the lead planner ramps on.
    assert any(w.startswith('DEBUG ONLY') for w in job.warnings)
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    assert job.program.to_text().startswith(';DEBUG ONLY')
    assert 'Must not execute' not in job.program.to_text()


def test_adaptive_can_return_a_covered_cut_but_never_falls_back_for_tabs():
    from shapely.geometry import LineString, Point
    from gcodeproducer.core.cam.operations.pocket_generator import pocket_paths

    area = box(-3, -3, 3, 3)
    stock = Point(0, 0).buffer(1)
    op = Operation(kind='waterfall', strategy='adaptive')
    paths = pocket_paths(op, [], area, 3., 'climb', material=stock)
    assert paths and paths[0].closed and not any(p.closed for p in paths[1:])  # Orbit, then stay-down cuts.
    assert all(p.stay_down and p.stay_down_from == tuple(paths[i].points[-1 if not paths[i].closed else 0])
               for i, p in enumerate(paths[1:]) if p.stay_down)
    swept = unary_union([LineString(np.vstack((p.points, p.points[:1])) if p.closed else p.points).buffer(1.5)
                         for p in paths])
    assert stock.difference(swept).area < 1e-3
    with pytest.raises(ValueError, match='tab-protected.*No contour fallback'):
        pocket_paths(op, [], area, 3., 'climb', tabs=True)


def test_old_strategy_names_preserve_existing_behaviour():
    for kind in ('pocket', 'waterfall'):
        setup = CAMSetup.from_dict({'groups': [{'tool_id': 'tool', 'operations': [
            {'kind': kind, 'strategy': 'trochoidal', 'adaptive_peels': 8, 'start': {}, 'end': {}}]}]})
        assert setup.groups[0].operations[0].strategy == 'adaptive'
    assert Operation(kind='pocket', strategy='raster').strategy == 'raster_y'
    assert Operation(kind='waterfall', strategy='raster').strategy == 'raster_y'
    # Meander moved from the 3D Contour strategy to the cutting direction: saved files keep it.
    for old in ('meander', 'contour', 'raster'):
        op = Operation(kind='contour3d', strategy=old)
        assert (op.strategy, op.cut_direction) == ('raster_x', 'meander')
    assert Operation(kind='contour3d', strategy='meander', cut_direction='climb').cut_direction == 'climb'
    assert Operation(kind='contour3d', strategy='raster_y').cut_direction == 'machine'
    assert Operation(kind='pocket', protect_model=True, strategy='raster').strategy == 'raster_y'


def _hands(paths, area):
    from shapely.geometry import LineString
    from gcodeproducer.core.cam.engagement import measure_segments
    stock, left, right = area, 0., 0.
    for path in paths:
        q = np.asarray(path.points, float)
        if path.closed:
            q = np.vstack((q, q[:1]))
        for a, b in zip(q, q[1:]):
            l, r, e, lengths = measure_segments(np.array([a, b]), False, stock, 2.)
            if 1e-6 < e[0] < .9:                            # one-sided cuts only, not slots or air
                left += float(lengths[0])*(l[0] > r[0])
                right += float(lengths[0])*(r[0] > l[0])
            stock = stock.difference(LineString([a, b]).buffer(2.))
    return left, right


@pytest.mark.parametrize('direction', ['climb', 'conventional'])
def test_adaptive_follows_the_cutting_direction_and_its_orbit_turns_the_same_way(direction):
    """M3 spindle: climb keeps uncut stock on the right of the cutter's travel, like G41."""
    from shapely.geometry import LinearRing
    from gcodeproducer.core.cam.operations.pocket_generator import pocket_paths

    area = box(0, 0, 30, 20)
    op = Operation(kind='waterfall', strategy='adaptive')
    paths = pocket_paths(op, [], area, 4., direction, material=area)
    left, right = _hands(paths, area)
    assert (right > 5*left) if direction == 'climb' else (left > 5*right)
    ccw = direction == 'climb'
    assert paths[0].closed and LinearRing(paths[0].points).is_ccw == ccw   # the orbit the helix ramps down on
    centre = np.asarray(paths[0].points, float).mean(axis=0)
    spiral = np.asarray(paths[1].points, float)[:60] - centre
    turned = np.unwrap(np.arctan2(spiral[:, 1], spiral[:, 0]))
    assert (turned[-1] > turned[0]) == ccw                            # the spiral carries on the same way


def test_adaptive_meander_cuts_fronts_from_the_nearer_end_instead_of_travelling_back():
    from gcodeproducer.core.cam.operations.pocket_generator import pocket_paths
    area = box(0, 0, 60, 30)
    op = Operation(kind='waterfall', strategy='adaptive')
    travel = {}
    for direction in ('climb', 'meander'):
        paths = pocket_paths(op, [], area, 4., direction, material=area)
        left, right = _hands(paths, area)
        travel[direction] = (left, right)
    assert travel['meander'][0] > .05*sum(travel['meander'])          # both hands
    assert travel['climb'][0] < .02*sum(travel['climb'])              # climb stays climb
    from shapely import from_wkt
    from pathlib import Path
    from gcodeproducer.core.cam.wavefront.planner import clear_pocket
    pocket = from_wkt(Path('examples/hsm-shapes/l-shape.wkt').read_text())
    one, both = (clear_pocket(pocket, 2., wall_pull_back=False, wall_profile=False, leave_wall_crescents=True,
                              both_ways=b)[2] for b in (False, True))
    assert both['link_feed_mm'] < .5*one['link_feed_mm']              # far less travel back over cut ground
    assert both['reachable_residual_mm2'] < .05


def test_adaptive_walks_up_to_a_cutter_radius_from_the_area_edge_whatever_the_stock_to_leave():
    """The selected area (plus overcut) is a wall: the cutter's edge comes up to it, never past it.

    Stock to leave belongs to the part; the generator keeps it from the part's shadow and passes
    stock_applied, so the area's own edge is not pulled in by it.
    """
    from shapely import distance, points
    from gcodeproducer.core.cam.wavefront.app_paths import wavefront_paths
    area = box(0, 0, 40, 25)
    op = Operation(kind='waterfall', strategy='adaptive', stock=1.)
    paths = wavefront_paths(op, area, 4., 'climb', material=area, stock_applied=True)
    xy = np.vstack([np.asarray(p.points, float)[:, :2] for p in paths])
    gap = distance(area.exterior, points(xy))
    assert area.buffer(-2. + 1e-6).covers(points(xy)).all()     # never past a cutter radius from the edge
    assert gap.min() == pytest.approx(2., abs=.02)               # and right up to it
    shrunk = wavefront_paths(op, area, 4., 'climb', material=area)   # the old rule: stock from every wall
    assert distance(area.exterior, points(np.vstack([np.asarray(p.points)[:, :2] for p in shrunk]))).min() > 2.9


@pytest.mark.parametrize('direction', ['climb', 'conventional', 'meander'])
def test_contour_spiral_starts_at_the_centre_and_covers_the_area(direction):
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    from gcodeproducer.core.cam.surface_paths import surface_spiral
    surface = SimpleNamespace(resolution=.1, heights=lambda xy, radius: np.full(len(xy), -2.))
    region = box(0, 0, 10, 6)
    paths = surface_spiral(region, surface, 1, 1, -5, 0, direction=direction)
    *paths, edge = paths
    # The last pass goes round the edge of the area, the stock inside it on the climb side.
    from shapely.geometry import LinearRing
    assert region.exterior.buffer(1e-6).covers(LineString(edge[:, :2])) and LineString(edge[:, :2]).length == pytest.approx(32)
    assert LinearRing(edge[:-1, :2]).is_ccw == (direction == 'conventional')
    assert np.allclose(paths[0][0], (5, 3, -2))                           # the centre of the area
    first = paths[0][:, :2] - (5, 3)
    turned = np.unwrap(np.arctan2(first[5:, 1], first[5:, 0]))
    # Climb (M3) keeps the uncut turns outside on the right: counter-clockwise. Meander as climb.
    assert (turned[-1] > turned[0]) == (direction != 'conventional')
    assert np.all(np.diff(np.hypot(first[:, 0], first[:, 1])) > -1e-9)   # only ever outwards
    assert len(paths) > 3                                                 # cut off at the walls: lifts between
    for p in paths:
        assert region.buffer(1e-6).covers(LineString(p[:, :2])) and np.all(p[:, 2] == -2)
    swept = unary_union([LineString(p[:, :2]).buffer(.5 + .02) for p in paths])   # a turn apart: 1 mm
    assert region.difference(swept).area > .5                             # strips by the walls without the edge pass
    swept = swept.union(LineString(edge[:, :2]).buffer(.5 + .02))
    assert region.difference(swept).area < .01
    order = [float(np.hypot(*(p[0, :2] - (5, 3)))) for p in paths]
    assert order == sorted(order)                                         # from the centre outwards, in order


def test_contour_spiral_staying_down_walks_the_wall_instead_of_lifting():
    from shapely.geometry import LineString
    from gcodeproducer.core.cam.surface_paths import surface_spiral, _along_the_wall
    surface = SimpleNamespace(resolution=.1, heights=lambda xy, radius: np.where(xy[:, 0] > 8, -1., -2.))
    region = box(0, 0, 10, 6)
    lifting = surface_spiral(region, surface, 1, 1, -5, 0)[:-1]
    path, _ = surface_spiral(region, surface, 1, 1, -5, 0, stay_down=True)
    assert region.buffer(1e-6).covers(LineString(path[:, :2]))            # never outside the area
    assert LineString(path[:, :2]).length > sum(LineString(p[:, :2]).length for p in lifting)
    for piece in lifting:                                                  # the same cuts, joined along the edge
        assert LineString(path[:, :2]).distance(LineString(piece[:, :2])) < 1e-9
    on_wall = [k for k in range(len(path)-1) if region.exterior.distance(LineString(path[k:k+2, :2])) < 1e-9
               and region.exterior.buffer(1e-6).covers(LineString(path[k:k+2, :2]))]
    assert on_wall                                                         # stretches along the edge itself
    assert set(np.round(path[:, 2], 6)) <= {-2., -1.}                      # following the model there too
    # The shorter way round, and none where the points are on different edges of the area.
    way = _along_the_wall(region, (1, 0), (0, 1), .1)
    assert LineString(way).length == pytest.approx(2.)
    holed = region.difference(box(4, 2, 6, 4))
    assert _along_the_wall(holed, (1, 0), (4, 3), .1) is None


def test_saved_adaptive_engagement_becomes_the_stepover_only_for_adaptive():
    def load(strategy, **extra):
        return CAMSetup.from_dict({'groups': [{'tool_id': 't', 'operations': [
            dict({'kind': 'waterfall', 'strategy': strategy, 'stepover': 40., 'start': {}, 'end': {}}, **extra)]}]}
        ).groups[0].operations[0]
    assert load('adaptive', adaptive_engagement=10.).stepover == 10.
    assert load('trochoidal', adaptive_engagement=12.).stepover == 12.       # old name of Adaptive
    assert load('contour', adaptive_engagement=10.).stepover == 40.          # not Adaptive: kept
    assert load('adaptive').stepover == 40.
    assert not hasattr(load('adaptive', adaptive_engagement=10.), 'adaptive_engagement')


def test_tool_library_rates_the_machine_caps_are_reported():
    from gcodeproducer.core.cam.value_overrides import tool_overrides
    machine = {'spindle_max': 12000, 'max_feed': 1500}
    found = tool_overrides({'spindle_rpm': 18000, 'feed': 2000, 'plunge_feed': 300, 'max_spindle_rpm': 24000}, machine)
    assert set(found) == {'spindle_rpm', 'feed'} and '12000 rpm' in found['spindle_rpm']
    assert tool_overrides({'spindle_rpm': 18000, 'max_spindle_rpm': 16000}, {}) .keys() == {'spindle_rpm'}
    assert tool_overrides({'auto_cutting_data': True, 'spindle_rpm': 1e6}, machine) == {}
