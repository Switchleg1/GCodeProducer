"""Operation-specific strategy controls and real X/Y path directions."""
import os
from types import SimpleNamespace
import numpy as np
import pytest
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
            expected = (['Wall-parallel contours', 'Raster lines X', 'Raster lines Y', 'Trochoidal']
                        if kind in ('pocket', 'waterfall') else
                        ['Meander', 'Raster lines X', 'Raster lines Y'] if kind == 'contour3d' else [])
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
                strategy = 'trochoidal' if kind in ('pocket', 'waterfall') else 'raster_y'
                editor.strategy.setCurrentIndex(editor.strategy.findData(strategy))
                assert editor.operation().strategy == strategy
                restored = CAMSetup.from_dict(editor.setup.to_dict())
                assert restored.groups[0].operations[-1].strategy == strategy
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
def test_contour_raster_has_separate_single_direction_lines(strategy, axis):
    surface = SimpleNamespace(resolution=.1, heights=lambda xy, radius: np.full(len(xy), -2.))
    paths = surface_raster(box(0, 0, 10, 6), surface, 1, 1, -5, 0, strategy=strategy)
    assert len(paths) > 2
    for p in paths:
        assert np.ptp(p[:, 1-axis]) < 1e-9
        assert np.all(np.diff(p[:, axis]) >= -1e-9)
        assert np.ptp(p[:, axis]) > 1


def test_contour_meander_alternates_and_links():
    surface = SimpleNamespace(resolution=.1, heights=lambda xy, radius: np.full(len(xy), -2.))
    paths = surface_raster(box(0, 0, 10, 6), surface, 1, 1, -5, 0, strategy='meander')
    assert len(paths) == 1
    delta = np.diff(paths[0][:, :2], axis=0)
    assert delta[:, 0].min() < -1 and delta[:, 0].max() > 1
    assert np.ptp(paths[0][:, 1]) > 5


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
def test_trochoidal_strategy_emits_one_spiral_without_xy_rapids_at_depth(libset, kind):
    from gcodeproducer.core.cam import generate
    from gcodeproducer.stages.cam_emit import CAMEmit
    shape = ReferenceShape('rectangle', 'edge', (10, 8), (30, 22), 0)
    job, _ = surface_job(libset, kind=kind, refs=[Reference('drawing', [shape.id])],
                         end=Depth('absolute', -1), strategy='trochoidal')
    job.cam_setup.reference_shapes = [shape]
    generate(job, StageContext())
    assert len(job.layers) == 1 and len(job.layers[0].paths) == 1
    assert not job.layers[0].paths[0].closed and len(job.layers[0].paths[0].points) >= 16
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    from gcodeproducer.core.gcode.simulation import simulate
    sim = simulate(job.program)
    cut_z = job.layers[0].z
    at_depth = np.flatnonzero(sim.moved & np.isclose(sim.z, cut_z))
    assert len(at_depth) > 16
    assert all(job.program.lines[i].cmd == 'G1' for i in range(at_depth[0], at_depth[-1]+1) if sim.moved[i])
    assert not any('rapid motion contacts' in warning for warning in job.warnings)


def test_trochoidal_radius_grows_continuously_and_covers_the_corners():
    from shapely import union_all
    from shapely.geometry import LineString
    from gcodeproducer.core.cam.trochoidal import trochoidal_paths

    area = box(0, 0, 20, 20)
    paths = trochoidal_paths(area, 3., 0., 40, 'climb')
    assert not paths[0].closed
    seed = paths[0].points[:40] - [10., 10.]
    major = np.abs(seed[0]).argmax()
    axes = np.full(2, .9)
    axes[major] = 1.
    # Test the continuous pitch, not just the envelope of a whole turn.
    unit = seed/axes
    angle = np.unwrap(np.arctan2(unit[:, 1], unit[:, 0]))
    distance = np.linalg.norm(unit, axis=1)
    np.testing.assert_allclose(distance, .3 + 1.2*(angle-angle[0])/(2*np.pi), atol=1e-12)
    assert np.ptp(np.vstack([p.points for p in paths])[:, 0]) == pytest.approx(17.)
    sweeps = [LineString(np.vstack([p.points, p.points[0]]) if p.closed else p.points).buffer(1.49)
              for p in paths]
    assert area.buffer(-1.5).difference(union_all(sweeps)).area < 1e-6


def test_trochoidal_fronts_and_links_do_not_cross_islands_or_disconnected_areas():
    from shapely.geometry import LineString
    from gcodeproducer.core.cam.trochoidal import trochoidal_paths

    area = box(0, 0, 38, 20).difference(box(10, 3.5, 28, 14)).union(box(38.5, 0, 46, 10))
    paths = trochoidal_paths(area, 3., .1, 35, 'climb')
    allowed = area.buffer(-1.6).buffer(1e-7)
    assert len(paths) >= 2  # an unsafe connection remains a separate entry
    for path in paths:
        assert not path.closed
        assert allowed.covers(LineString(path.points))
    unlinked = trochoidal_paths(area, 3., .1, 35, 'climb', stay_down=False)
    assert len(unlinked) > len(paths)


def test_spiral_join_cannot_slot_across_uncut_stock():
    from shapely.geometry import LineString
    from shapely.prepared import prep
    from gcodeproducer.core.cam.trochoidal import _connector

    area = prep(box(0, 0, 20, 20))
    a, b = np.array([2., 5.]), np.array([16., 5.])
    # The straight join fits the pocket but not the swept stock.
    partial = prep(LineString([a, [8., 5.]]).buffer(1.5))
    assert _connector(a, b, area, [], [], partial, 1.5, 1.2) is None
    # Previously swept transit and a final, one-stepover approach are allowed.
    cleared = prep(LineString([a, [14.81, 5.]]).buffer(1.5))
    np.testing.assert_array_equal(_connector(a, b, area, [], [], cleared, 1.5, 1.2), [a, b])


def test_short_corner_arcs_are_replaced_by_local_spirals():
    from shapely.geometry import LineString
    from shapely.prepared import prep
    from gcodeproducer.core.cam.trochoidal import _corner_spirals, _pieces, _spiral

    area = box(1.5, 1.5, 18.5, 18.5)
    walls = [LineString(area.exterior.coords)]
    spiral, _ = _spiral(area, 1.2, 1, 100000)
    global_arcs = _pieces(spiral, area, prep(area.buffer(1e-7)))
    arcs, samples = _corner_spirals(area, global_arcs, walls, 1.5, 1.2, 1, 100000)
    assert samples > 0
    local = [arc for arc in arcs if not any(np.array_equal(arc, old) for old in global_arcs)]
    assert local and all(prep(area.buffer(1e-7)).covers(LineString(p)) for p in local)
    assert any(len(p) >= 16 and np.ptp(p[:, 0]) < 5 and np.ptp(p[:, 1]) < 5 for p in local)


def test_old_strategy_names_preserve_existing_behaviour():
    assert Operation(kind='pocket', strategy='raster').strategy == 'raster_y'
    assert Operation(kind='waterfall', strategy='raster').strategy == 'raster_y'
    assert Operation(kind='contour3d').strategy == 'meander'
    assert Operation(kind='contour3d', strategy='raster').strategy == 'meander'
    assert Operation(kind='pocket', protect_model=True, strategy='raster').strategy == 'raster_y'
