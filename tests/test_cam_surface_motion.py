"""Material-aware XYZ contour leads, engagement bands, rates and Preview metadata."""
import numpy as np
import pytest
from gcodeproducer.core.cam import Operation
from gcodeproducer.core.cam.stock import Stock
from gcodeproducer.core.cam.height_stock import HeightStock
from gcodeproducer.core.cam.surface_engagement import condition
from gcodeproducer.core.cam.surface_leads import surface_entry, surface_exit
from gcodeproducer.core.cam.cam_constants import RAMP_TAN
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.core.jobs.layer import Layer
from gcodeproducer.core.gcode.simulation import simulate
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_cam_surface import surface_job, assert_program_clear


def state_with_strip(width):
    stock = Stock(x=0, y=0, top=0, width=40, depth=20, height=10)
    state = HeightStock(stock, .05)
    state.heights[:] = -2
    state.heights[(state.y >= 10-width/2) & (state.y <= 10+width/2), :] = 0
    return state


@pytest.mark.parametrize('width,band,factor', [(4, 'slot', .35), (3.6, 'high', .6),
                                              (2.4, 'cut', .9), (.4, 'hsm', 1.1), (0, 'air', 1.)])
def test_xyz_engagement_bands_and_operation_overrides(width, band, factor):
    state = state_with_strip(width)
    op = Operation(kind='contour3d', slotting_feed=35, high_engagement_feed=60,
                   standard_engagement_feed=90, low_engagement_feed=110)
    cut = condition(state, [10, 10, -1], [14, 10, -1], 2, op, {}, {})
    assert cut.regime == band
    assert cut.feed_factor == factor
    if band == 'slot':
        assert cut.hand == 'neutral' and cut.engagement == 1
    # The same XY strip is air when the moving cutter is above it.
    assert condition(state, [10, 10, 1], [14, 10, 1], 2, op, {}, {}).regime == 'air'


def test_short_incremental_moves_do_not_misclassify_full_slot_as_hsm():
    state = state_with_strip(4)
    op = Operation(kind='contour3d')
    a = np.array([10., 10., -1.])
    state.cut(a, a, 2)
    for _ in range(12):
        b = a+np.array([.5, 0, 0])
        cut = condition(state, a, b, 2, op, {}, {})
        assert cut.regime == 'slot' and cut.hand == 'neutral'
        state.cut(a, b, 2)
        a = b


def test_engagement_uses_current_xyz_removal_and_machine_thresholds():
    state = state_with_strip(2.4)
    op = Operation(kind='contour3d')
    assert condition(state, [10, 10, -1], [14, 10, -1], 2, op, {}, {}).regime == 'cut'
    machine = {'hsm_engagement_threshold': 20, 'high_engagement_threshold': 50, 'slot_engagement_threshold': 90}
    assert condition(state, [10, 10, -1], [14, 10, -1], 2, op, {}, machine).regime == 'high'
    state.cut(np.array([8, 10, -1]), np.array([17, 10, -1]), 2)
    assert condition(state, [10, 10, -1], [14, 10, -1], 2, op, {}, machine).regime == 'air'


@pytest.mark.parametrize('points', [np.array([[0, 0, -1], [2, 0, -1.]]),
                                    np.array([[0, 0, -2], [20, 0, -10.]])])
def test_surface_entry_stays_on_the_path_above_floor_and_below_ten_degrees(points):
    lead, kind = surface_entry(points, .5, 3)
    assert np.allclose(lead[-1], points[0])
    assert lead[0, 2] == .5
    run = np.linalg.norm(np.diff(lead[:, :2], axis=0), axis=1)
    drop = -np.diff(lead[:, 2])
    assert np.all(run > 0) and np.all(drop <= RAMP_TAN*run+1e-9)
    floor = np.interp(lead[:, 0], points[:, 0], points[:, 2])
    assert np.all(lead[:, 2] >= floor-1e-9)
    assert np.all(lead[:, 1] == 0)
    if points[-1, 0] == 2:
        assert kind == 'zigzag'


def test_surface_ramp_up_a_steep_path_follows_the_path_and_never_goes_below_it():
    # Rising 4 mm in 5 mm from its start: no ramp at 10 degrees fits above it, so the
    # lead follows the path where the path is higher (never below it, never a failure).
    path = np.array([[0, 0, -4], [5, 0, 0.]])
    lead, kind = surface_entry(path, .5, 3)
    assert kind == 'zigzag' and np.allclose(lead[-1], path[0]) and lead[0, 2] == pytest.approx(.5)
    floor = np.interp(lead[:, 0], path[:, 0], path[:, 2])
    assert np.all(lead[:, 2] >= floor - 1e-9)
    ramp = .5 - RAMP_TAN*np.r_[0., np.cumsum(np.linalg.norm(np.diff(lead[:, :2], axis=0), axis=1))]
    assert np.allclose(lead[:-1, 2], np.maximum(ramp, floor)[:-1])
    with pytest.raises(ValueError, match='nonzero surface path'):
        surface_entry([[0, 0, -1]], .5, 3)


def test_surface_exit_follows_the_cleared_xyz_profile():
    points = np.array([[0, 0, -1], [5, 0, -3], [10, 0, -2.]])
    result = surface_exit(points, 8)
    assert np.array_equal(result[0], points[-1])
    assert np.allclose(result[-1], [2, 0, -1.8])
    assert np.allclose(result[:, 2], np.interp(result[:, 0], points[:, 0], points[:, 2]))


def motion_job(libset, lead_in=True, lead_out=True, repeat=False, parallel=False):
    job, op = surface_job(libset, kind='contour3d')
    op.lead_in, op.lead_out = lead_in, lead_out
    op.unlock_feed, op.feed = True, 1000
    op.unlock_lead_feed, op.lead_feed = True, 300
    op.slotting_feed, op.high_engagement_feed = 50, 70
    op.standard_engagement_feed, op.low_engagement_feed = 85, 110
    job.machine.values['max_feed'] = 5000
    job.preferences['stock_resolution'] = .1
    # slot, cut (33 %), cut (50 %), high (87 %), hsm (10 % of the 3 mm cutter)
    ys = [10, 11, 12.5, 15.1, 15.4] if parallel else [12]
    paths = [Path('cut', np.array([[13, y, -1], [27, y, -1.]]), width=3) for y in ys]
    for i in range(2 if repeat else 1):
        layer = Layer(i, -1, 1, paths=paths)
        layer.cam_tool_id = job.tools[0].id
        layer.cam_group = 0
        layer.cam_operation = op.name
        layer.cam_operation_key = (0, 0)
        layer.cam_operation_config = op
        job.layers.append(layer)
    return job, op


def test_xyz_leads_replace_only_contacting_entry_and_skip_cleared_repeat(libset):
    job, _ = motion_job(libset, repeat=True)
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    # Remove air cutting (default): the cleared repeat writes no feed moves at all.
    assert not any(l.cmd == 'G1' and l.layer == 1 for l in job.program.lines)
    job, _ = motion_job(libset, repeat=True)
    job.preferences['skip_air_cuts'] = False
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    lines = job.program.lines
    assert any(l.feature == 'lead_in' and l.layer == 0 for l in lines)
    # A slot ending short of the wall: carrying on would cut, so no lead-out (straight retract).
    assert not any(l.feature == 'lead_out' for l in lines)
    assert not any(l.feature == 'plunge' for l in lines)
    assert not any(l.cmd == 'G1' and l.feature in ('lead_in', 'lead_out') and l.layer == 1 for l in lines)
    assert any(l.feature == 'air' and l.layer == 1 for l in lines)
    sim = simulate(job.program)
    # Every contacting lead descends with actual XY motion, not a vertical plunge.
    for i, line in enumerate(lines):
        if line.feature == 'lead_in' and line.engagement > 0:
            assert sim.dist_xy[i] > 0
            assert sim.pz[i]-sim.z[i] <= RAMP_TAN*sim.dist_xy[i]+.002
        if line.cmd == 'G1' and line.feature == 'lead_out':
            assert line.engagement == 0
    assert_program_clear(job.program)
    assert not any('rapid contacts' in warning for warning in job.warnings)


def test_xyz_lead_toggles_are_independent_and_disabled_entry_plunges(libset):
    job, _ = motion_job(libset, lead_in=False, lead_out=False)
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    assert any(l.feature == 'plunge' for l in job.program.lines)
    assert not any(l.feature in ('lead_in', 'lead_out') for l in job.program.lines)
    job, op = motion_job(libset, lead_in=False, lead_out=True)
    ctx = StageContext()
    CAMEmit().run(job, CAMEmit.defaults(), ctx)
    assert not any(l.feature == 'lead_in' for l in job.program.lines)
    # A lone slot in uncut stock: carrying on would cut, so its lead-out is skipped for a straight retract.
    assert not any(l.feature == 'lead_out' for l in job.program.lines)
    assert any('lead-outs skipped' in m for m in ctx.messages)


def test_xyz_cutting_types_feed_modifiers_and_preview_metadata(libset):
    job, _ = motion_job(libset, parallel=True, repeat=True)
    job.preferences['skip_air_cuts'] = False    # keep the air repeat to check its feed
    job.preferences['cam_feed_smoothing'] = 0   # exact per-band feeds (smoothing only lowers them)
    ctx = StageContext()
    CAMEmit().run(job, CAMEmit.defaults(), ctx)
    sim = simulate(job.program)
    expected = {'slot': 500, 'high_engagement': 700, 'cut': 850, 'hsm': 1100, 'air': 1000}
    for feature, feed in expected.items():
        indices = [i for i, l in enumerate(job.program.lines) if l.cmd == 'G1' and l.feature == feature
                   and 'Z' not in l.params]   # vertical verified-air approaches use the lead base
        assert indices, feature
        assert np.allclose(sim.feed[indices], feed)
        assert all(job.program.lines[i].note and np.isfinite(job.program.lines[i].engagement) for i in indices)
    assert any('3D engagement moves' in message for message in ctx.messages)
    assert_program_clear(job.program)


def test_steep_air_only_surface_repeat_keeps_cut_base_instead_of_plunge_feed(libset):
    job, op = motion_job(libset, repeat=True)
    op.stepdown = 5
    job.tools[0].values['max_doc'] = 10
    for layer in job.layers:
        layer.z = -5
        layer.paths = [Path('cut', np.array([[13, 12, -1], [27, 12, -5.]]), width=3)]
    job.preferences['skip_air_cuts'] = False    # keep the air repeat to check its feed
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    sim = simulate(job.program)
    air = [i for i, l in enumerate(job.program.lines) if l.cmd == 'G1' and l.feature == 'air' and l.layer == 1
           and 'X' in l.params]   # vertical verified-air approaches use the lead base
    assert air and np.all(sim.feed[air] == 1000)


def test_xyz_cleared_entry_is_remembered_across_operations_and_tool_changes(libset):
    import copy
    from gcodeproducer.core.cam import ToolGroup
    job, op = motion_job(libset, repeat=True)
    other = copy.deepcopy(op)
    other.name = 'After tool change'
    job.cam_setup.groups.append(ToolGroup(job.tools[0].id, [other]))
    job.layers[1].cam_group = 1
    job.layers[1].cam_operation_key = (1, 0)
    job.layers[1].cam_operation = other.name
    job.layers[1].cam_operation_config = other
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    assert sum(l.cmd == 'T2' or 'M6' in l.raw for l in job.program.lines) >= 2
    assert not any(l.cmd == 'G1' and l.feature in ('lead_in', 'plunge') and l.layer == 1
                   for l in job.program.lines)


def test_xyz_without_stock_uses_a_logged_conservative_blank(libset):
    job, _ = motion_job(libset)
    job.cam_setup.stock.width = job.cam_setup.stock.depth = job.cam_setup.stock.height = 0
    ctx = StageContext()
    CAMEmit().run(job, CAMEmit.defaults(), ctx)
    assert any('conservative model-bounds blank' in m for m in ctx.messages)
    assert any(l.cmd == 'G1' and l.feature == 'lead_in' for l in job.program.lines)
    assert not job.material_results


def test_xyz_all_feeds_obey_machine_cap(libset):
    job, _ = motion_job(libset, parallel=True)
    job.machine.values['max_feed'] = 120
    CAMEmit().run(job, CAMEmit.defaults(), StageContext())
    sim = simulate(job.program)
    assert all(sim.feed[i] <= 120 for i, l in enumerate(job.program.lines) if l.cmd == 'G1')


def test_feed_smoothing_only_lowers_short_moves_and_merges_what_now_matches():
    from gcodeproducer.core.cam.planner.feed_smoother import FeedSmoother
    from gcodeproducer.core.cam.planner.motion_segment import MotionSegment

    def run(pattern):
        x, out = 0., []
        for length, rate in pattern:
            out.append(MotionSegment('cut', np.array([x, 0., 0.]), np.array([x+length, 0., 0.]), None, rate, 'cut'))
            x += length
        return out

    # Short fast flickers between slow moves are slowed; long moves keep their feed.
    pattern = [(10, 1000), (.2, 400), (.2, 1000), (.2, 400), (.2, 1000), (.2, 400), (10, 1000)]
    smoothed = FeedSmoother(2., merge=False)(run(pattern))
    rates = [s.rate for s in smoothed]
    assert rates[0] == rates[-1] == 1000 and rates[1:-1] == [400]*5
    assert all(s.rate <= r for s, (_, r) in zip(smoothed, pattern))
    merged = FeedSmoother(2.)(run(pattern))
    assert [s.rate for s in merged] == [1000, 400, 1000] and merged[1].end[0] - merged[1].start[0] == pytest.approx(1)
    assert FeedSmoother(0.)(run(pattern))[2].rate == 1000                       # off
    # A bend is never merged away.
    bent = run([(.2, 400), (.2, 400)])
    bent[1].start, bent[1].end = bent[0].end, bent[0].end + np.array([0., .2, 0.])
    assert len(FeedSmoother(2.)(bent)) == 2
