"""Shared CAM motion planner: feed policy, phases, entries/exits and links for every operation."""
import copy
import numpy as np
import pytest
from gcodeproducer.core.cam import Operation, ToolGroup, generate
from gcodeproducer.core.cam.planner import FeedPolicy, EntryExitPlanner, LinkPlanner, MotionPlan
from gcodeproducer.core.cam.planner.planner_constants import PHASES, LEAD_BASE_PHASES, FACTOR_PHASES
from gcodeproducer.core.cam.height_stock import HeightStock
from gcodeproducer.core.cam.stock import Stock
from gcodeproducer.core.jobs.cut_condition import CutCondition
from gcodeproducer.core.gcode.simulation import simulate
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import stepped_part, floor_ref, job_for

SLOT = CutCondition(1., "slot", "neutral", .5)
HSM = CutCondition(.2, "hsm", "climb", 1.1)
AIR = CutCondition(0., "air", "air", 1.)


def test_feed_policy_phase_base_band_factor_and_cap():
    policy = FeedPolicy(0)
    assert set(LEAD_BASE_PHASES) | set(FACTOR_PHASES) <= set(PHASES)
    # A lead-in is a lead-base move AND (normally) slotting: both apply.
    assert policy.rate("lead_in", 1000, 300, SLOT) == 150
    assert policy.rate("lead_in", 1000, 300, AIR) == 300
    assert policy.rate("cut", 1000, 300, SLOT) == 500
    assert policy.rate("cut", 1000, 300, HSM) == 1100
    assert policy.rate("link", 1000, 300, SLOT) == 500
    # A vertical plunge keeps its plunge rate; a verified-air approach is unscaled.
    assert policy.rate("plunge", 1000, 300, SLOT) == 300
    assert policy.rate("approach", 1000, 300, AIR) == 300
    # Down into material steeper than the ramp is a plunge: plunge rate, unscaled, identified as one.
    assert policy.rate("cut", 1000, 300, SLOT, steep=True) == 300
    assert policy.rate("cut", 1000, 300, SLOT, steep=True, plunge_base=120) == 120
    assert policy.rate("lead_in", 1000, 300, SLOT, steep=True, plunge_base=120) == 120
    assert policy.rate("plunge", 1000, 300, SLOT, plunge_base=120) == 120
    assert policy.rate("lead_in", 1000, 300, AIR, plunge_base=120) == 300  # lead-ins keep their own rate
    assert policy.rate("cut", 100, 300, SLOT, steep=True) == 100           # never faster than cutting
    assert policy.feature("cut", SLOT, steep=True) == policy.feature("link", HSM, steep=True) == "plunge"
    assert policy.rate("cut", 1000, 300, AIR, steep=True) == 1000 and policy.feature("cut", AIR, steep=True) != "plunge"
    assert policy.feature("approach", SLOT, steep=True) == "air"
    capped = FeedPolicy(400)
    assert capped.rate("cut", 1000, 300, HSM) == 400 and capped.capped == {(1100, 400)}
    with pytest.raises(ValueError, match="nonnegative"):
        FeedPolicy(-1)
    with pytest.raises(ValueError, match="positive"):
        policy.rate("cut", 0, 300)


def test_descent_feed_blends_by_angle_from_level_to_lead_in_to_plunge():
    policy = FeedPolicy(0)
    rate = lambda angle, phase="cut", c=HSM: policy.rate(phase, 1000, 300, c, plunge_base=100, angle=angle, ramp=10)
    # Level: the cut rate (HSM 1100); at the lead-in angle: the lead-in rate (300 x 1.1); straight down: plunge.
    assert rate(0) == 1100 and rate(10) == pytest.approx(330) and rate(90) == 100
    assert rate(5) == pytest.approx((1100+330)/2) and rate(50) == pytest.approx((330+100)/2)
    rates = [rate(a) for a in range(0, 91)]
    assert all(b <= a + 1e-9 for a, b in zip(rates, rates[1:]))        # never faster as it gets steeper
    assert max(abs(b-a) for a, b in zip(rates, rates[1:])) < .1*1100    # no jumps
    assert rate(30, c=AIR) == 1000                                      # descending through air is not a descent into material
    assert rate(5, "lead_in", SLOT) == 150 and rate(50, "lead_in", SLOT) == pytest.approx(125)
    assert policy.rate("plunge", 1000, 300, SLOT, plunge_base=100, angle=0) == 100


def test_feed_policy_features_keep_phase_and_engagement_apart():
    policy = FeedPolicy(0)
    assert policy.feature("lead_in", SLOT) == "lead_in"
    assert policy.feature("plunge", SLOT) == "plunge"
    assert policy.feature("approach", AIR) == "air"
    assert policy.feature("cut", SLOT) == "slot"
    assert policy.feature("cut", HSM) == "hsm"
    conflict = CutCondition(.5, "cut", "conventional", 1., conflict=True)
    assert policy.feature("cut", conflict) == "conflict"
    assert FeedPolicy(0, highlight_conflicts=False).feature("cut", conflict) == "cut"


def cleared_state():
    stock = Stock(x=0, y=0, top=0, width=40, depth=40, height=10)
    state = HeightStock(stock, .1)
    state.heights[:] = 0
    state.heights[(state.y[:, None] > 10) & (state.y[:, None] < 30) & (state.x[None, :] > 10) & (state.x[None, :] < 30)] = -5
    return state


def test_entry_planner_ramps_only_into_material():
    state = cleared_state()
    planner = EntryExitPlanner(10, .5, 2)
    square = np.array([[15, 15], [25, 15], [25, 25], [15, 25.]])
    # Inside the cleared pocket the start column is clear down to Z-5: no lead.
    assert not planner.enters_material(state, (20, 20), -5)
    assert planner.planar(state, square, True, -5, 4) == (None, None)
    # Below the cleared floor the descent meets material: a ramp along the path.
    lead, kind = planner.planar(state, square, True, -6, 4)
    assert lead is not None and kind in ("linear", "helix")
    assert np.allclose(lead[-1], [15, 15, -6]) and lead[0, 2] == pytest.approx(-4.5)
    # Unknown material (no stock) is conservatively treated as entering material.
    assert planner.enters_material(None, (20, 20), -5)
    assert planner.planar(None, square, True, -5, 4) == (None, None)    # but no ramp without a state
    assert planner.planar(state, square[:1], True, -6, 4) == (None, "degenerate")


def test_link_planner_heights_and_stay_down():
    state = cleared_state()
    links = LinkPlanner(10, 1, .5, True, 2)
    position = np.array([20, 20, -5.])
    assert links.stay_at_depth(state, position, (22, 22), -6)
    assert links.stay_at_depth(state, position, (22, 22), -5)      # same cutting Z
    assert not links.stay_at_depth(state, position, (22, 22), -4)  # higher entry
    assert not links.stay_at_depth(state, position, (5, 5), -6)    # material at the target
    assert not links.stay_at_depth(None, position, (22, 22), -5)   # no verified stock
    state.heights[:, (state.x > 24) & (state.x < 25)] = 0
    assert not links.stay_at_depth(state, position, (28, 20), -5)  # clear endpoints, blocked route
    assert not LinkPlanner(10, 1, .5, False, 2).stay_at_depth(state, position, (22, 22), -6)
    assert links.travel_height(state, position, (22, 22), -5) == pytest.approx(-4)
    assert links.travel_height(state, position, (5, 5), -5) == pytest.approx(1)
    assert links.travel_height(None, position, (5, 5), -5) == 10
    assert links.descent_height(state, 1, (22, 22), -6, lead=True) == pytest.approx(-4.5)
    assert links.descent_height(state, 1, (22, 22), -6, lead=False) == pytest.approx(-4)


def test_inward_waypoint_routes_around_uncut_material():
    stock = Stock(x=0, y=0, top=0, width=40, depth=40, height=10)
    state = HeightStock(stock, .1)
    a = np.array([5., 5., -2.])
    b = np.array([15., 15., -2.])
    via = np.array([5., 15., -2.])
    state.cut(a, via, 3.)
    state.cut(via, b, 3.)
    links = LinkPlanner(10, 1, .5, True, 2.)
    assert not links.stay_at_depth(state, a, b[:2], b[2])
    candidates = np.array([[10., 10.], via[:2]])
    np.testing.assert_array_equal(links.inward_waypoint(state, a, b[:2], candidates), via[:2])
    assert links.inward_waypoint(state, a, b[:2], candidates[:1]) is None


def emitted(libset, **fields):
    mesh = stepped_part()
    job, op = job_for(mesh, [floor_ref(mesh)], libset)
    for key, value in fields.items():
        setattr(op, key, value)
    generate(job, StageContext())
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    return job, op


def test_every_feed_move_is_a_planned_segment_with_a_phase(libset):
    job, _ = emitted(libset)
    plan = job.motion_plan
    assert isinstance(plan, MotionPlan)
    feeds = [l for l in job.program.lines if l.cmd == "G1"]
    planned = [s for s in plan.segments if s.motion and s.phase != "rapid"]
    assert len(feeds) == len(planned)
    assert {s.phase for s in plan.segments if s.motion} <= set(PHASES)
    # Non-motion program lines (layer markers, spindle / tool change) are planned too.
    assert {s.phase for s in plan.segments if not s.motion} == {"comment", "command"}
    assert plan.of("lead_in") and plan.of("cut") and plan.of("link")
    # Lead-ins that contact material carry their measured band (normally slot).
    regimes = plan.regimes(("lead_in",))
    assert regimes["slot"] > 0


def test_move_estimate_counts_xyz_subdivision_and_closed_planar_edges():
    from types import SimpleNamespace
    from gcodeproducer.core.cam.planner.move_estimate import estimate_cut_segments
    from gcodeproducer.core.jobs.path import Path

    layer = SimpleNamespace(paths=[
        Path('cut', np.array([[0., 0., 0.], [2., 0., 0.], [2., 0., -1.]])),
        Path('cut', np.array([[0., 0.], [1., 0.], [0., 1.]]), closed=True),
    ])
    assert estimate_cut_segments([layer], {}, {'diameter': 3.}, SimpleNamespace(resolution=.05)) == 8


def test_chunked_planning_preserves_commands_feeds_and_checks(libset, monkeypatch):
    from gcodeproducer.core.cam.planner import motion_plan

    expected, _ = emitted(libset)
    monkeypatch.setattr(motion_plan, 'MOTION_CHUNK_SIZE', 7)
    streamed, _ = emitted(libset)
    assert not streamed.motion_plan.complete
    assert len(streamed.motion_plan.segments) == 7
    assert streamed.motion_plan.total == expected.motion_plan.total
    assert streamed.program.to_text() == expected.program.to_text()
    assert [line.engagement for line in streamed.program.lines if line.note] == [
        line.engagement for line in expected.program.lines if line.note]
    assert streamed.warnings == expected.warnings
    for a, b in zip(streamed.material_results, expected.material_results, strict=True):
        np.testing.assert_array_equal(a['heights'], b['heights'])


def test_planar_lead_in_uses_measured_band_and_operation_override(libset):
    job, op = emitted(libset, slotting_feed=30, unlock_lead_feed=True, lead_feed=300)
    sim = simulate(job.program)
    slot_leads = [s for s in job.motion_plan.of("lead_in") if s.condition.regime == "slot"]
    assert slot_leads and all(s.rate == pytest.approx(90) for s in slot_leads)      # 300 x operation 30 %
    air_leads = [s for s in job.motion_plan.of("lead_in") if s.condition.regime == "air"]
    assert all(s.rate == pytest.approx(300) for s in air_leads)
    rows = [i for i, l in enumerate(job.program.lines) if l.cmd == "G1" and l.feature == "lead_in"]
    assert set(np.round(sim.feed[rows], 6)) <= {90., 300.} | {s.rate for s in job.motion_plan.of("lead_in")}


def test_operation_lead_angle_reaches_emitted_planar_ramp(libset):
    job, _ = emitted(libset, lead_angle=4.)
    sim = simulate(job.program)
    ids = [i for i, line in enumerate(job.program.lines) if line.feature == 'lead_in' and sim.pz[i] > sim.z[i]]
    assert ids
    drops = sim.pz[ids] - sim.z[ids]
    xy = np.hypot(sim.x[ids]-sim.px[ids], sim.y[ids]-sim.py[ids])
    assert np.all(drops <= np.tan(np.deg2rad(4.))*xy + .0012)  # serialized XYZ precision
    assert drops.sum()/xy.sum() > np.tan(np.deg2rad(3.))


def test_surface_entry_uses_configured_angle():
    from gcodeproducer.core.cam.surface_leads import surface_entry

    path = np.array([[0., 0., -1.], [20., 0., -1.]])
    ramp, _ = surface_entry(path, 0., 0., angle=4.)
    assert np.linalg.norm(np.diff(ramp[:, :2], axis=0), axis=1).sum() == pytest.approx(1./np.tan(np.deg2rad(4.)))


def test_planar_reentry_into_cleared_material_skips_the_ramp(libset):
    job, op = emitted(libset)
    first = len(job.motion_plan.of("lead_in"))
    # Repeat the same operation: every entry now descends into material the first one removed.
    repeat = copy.deepcopy(op)
    repeat.name = "Repeat"
    job.cam_setup.groups.append(ToolGroup(job.tools[0].id, [repeat]))
    job.preferences["skip_air_cuts"] = False
    generate(job, StageContext())
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    second_layers = {l.index for l in job.layers if l.cam_operation == "Repeat"}
    lines = job.program.lines
    assert not any(l.cmd == "G1" and l.feature in ("lead_in", "plunge") and l.layer in second_layers for l in lines)
    assert any(l.cmd == "G1" and l.feature == "air" and l.layer in second_layers for l in lines)
    assert len(job.motion_plan.of("lead_in")) == first


def test_lead_out_follows_only_cleared_geometry(libset):
    job, _ = emitted(libset)
    outs = job.motion_plan.of("lead_out")
    assert outs and all(s.condition is not None and s.condition.regime == "air" for s in outs)
